"""Per-user AI configuration: encrypted keys bound to their owner, endpoint safety, provider calls,
and that every feature uses the signed-in user's own configuration."""

import json

import httpx
import pytest

import accounts
import ai
from conftest import sign_in


@pytest.fixture()
def user(request):
    # A fresh user per test, so saved models never carry over between tests.
    accounts.init_db()
    return accounts.find_or_create_user(f"{request.node.name[:40].replace('[', '-').replace(']', '')}@example.org".lower())


def test_key_is_encrypted_bound_to_its_owner_and_never_returned(user):
    cfg = ai.add_config(user["id"], "openai", "gpt-4o-mini", api_key="sk-secret-value-1234")
    assert cfg["api_key_hint"] == "****1234" and "api_key" not in cfg
    with accounts.connect() as conn:
        blob = conn.execute("SELECT api_key_ciphertext FROM ai_models WHERE id = ?", (cfg["id"],)).fetchone()[0]
    assert "sk-secret" not in blob
    assert ai.load_config(user["id"])["api_key"] == "sk-secret-value-1234"
    other = accounts.find_or_create_user("other@example.org")
    with pytest.raises(ai.AIError):  # a row copied to another account does not decrypt
        ai.decrypt_secret(blob, f"user:{other['id']}")


def test_several_models_one_in_use_and_key_reuse(user):
    a = ai.add_config(user["id"], "mistral", "mistral-large-latest", api_key="key-aaaaaaaa")
    b = ai.add_config(user["id"], "mistral", "mistral-small-latest")  # blank key reuses the saved Mistral key
    assert b["api_key_hint"] == "****aaaa" and b["active"] and ai.load_config(user["id"])["api_key"] == "key-aaaaaaaa"
    assert [c["active"] for c in ai.list_configs(user["id"])] == [False, True]
    ai.select_config(user["id"], a["id"])
    assert ai.public_config(user["id"])["model"] == "mistral-large-latest"
    again = ai.add_config(user["id"], "mistral", "mistral-large-latest", api_key="key-bbbbbbbb")  # same model: key updated, no duplicate
    assert again["id"] == a["id"] and again["api_key_hint"] == "****bbbb" and len(ai.list_configs(user["id"])) == 2
    with pytest.raises(ai.AIError, match="requires an API key"):
        ai.add_config(user["id"], "anthropic", "claude", api_key="")  # no saved Anthropic key to reuse
    with pytest.raises(ai.AIError, match="provider"):
        ai.add_config(user["id"], "nope", "m", api_key="x" * 10)
    gone = ai.delete_config(user["id"], a["id"])
    assert gone["was_active"] and ai.public_config(user["id"]) is None and len(ai.list_configs(user["id"])) == 1


def test_models_are_private_to_their_owner(user):
    mine = ai.add_config(user["id"], "openrouter", "mistralai/mistral-large", api_key="or-key-12345678")
    other = accounts.find_or_create_user(f"other-{user['id']}@example.org")
    for action in (ai.select_config, ai.delete_config, lambda u, i: ai.load_config(u, i)):
        with pytest.raises(ai.AIError, match="does not exist"):
            action(other["id"], mine["id"])
    assert ai.list_configs(other["id"]) == []


def test_fireworks_and_openrouter_are_openai_compatible():
    seen = []

    def handler(req):
        seen.append((str(req.url), req.headers.get("x-title")))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    for provider, model in (("fireworks", "accounts/fireworks/models/llama-v3p3-70b-instruct"), ("openrouter", "mistralai/mistral-large")):
        assert ai.complete({"provider": provider, "model": model, "api_key": "k" * 12}, [{"role": "user", "content": "x"}],
                           client=_transport(handler))[0] == "ok"
    assert seen == [("https://api.fireworks.ai/inference/v1/chat/completions", None),
                    ("https://openrouter.ai/api/v1/chat/completions", "KEvidence")]


def test_single_configuration_from_before_is_migrated(user):
    with accounts.connect() as conn:
        conn.execute("DELETE FROM ai_models WHERE user_id = ?", (user["id"],))
        conn.execute("INSERT OR REPLACE INTO ai_configs (user_id, provider, model, endpoint, api_key_ciphertext, api_key_hint, updated_at) "
                     "VALUES (?, 'deepseek', 'deepseek-chat', '', ?, '****9999', '2026-11-01T00:00:00+00:00')",
                     (user["id"], ai.encrypt_secret("sk-old-99999999", f"user:{user['id']}")))
    accounts.init_db()
    cfg = ai.public_config(user["id"])
    assert cfg["model"] == "deepseek-chat" and cfg["active"] and ai.load_config(user["id"])["api_key"] == "sk-old-99999999"


@pytest.mark.parametrize("url", ["http://169.254.169.254/v1", "https://localhost/v1", "https://127.0.0.1/v1",
                                 "https://user:pw@example.org/v1", "ftp://example.org"])
def test_endpoint_ssrf_guard(url):
    ok, _ = ai.validate_endpoint(url)
    assert not ok


def _transport(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openai_compatible_call_and_json_mode():
    seen = {}

    def handler(req):
        seen["url"], seen["auth"], seen["body"] = str(req.url), req.headers.get("authorization"), json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{\"ok\": true}"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}})
    text, usage = ai.complete({"provider": "mistral", "model": "m", "api_key": "k" * 10}, [{"role": "user", "content": "hi"}],
                              json_mode=True, client=_transport(handler))
    assert text == '{"ok": true}' and usage == {"in": 5, "out": 2}
    assert seen["url"] == "https://api.mistral.ai/v1/chat/completions" and seen["auth"] == "Bearer " + "k" * 10
    assert seen["body"]["response_format"] == {"type": "json_object"}


def test_anthropic_call_shape():
    seen = {}

    def handler(req):
        seen["body"], seen["key"] = json.loads(req.content), req.headers.get("x-api-key")
        return httpx.Response(200, json={"content": [{"type": "text", "text": "Sure: {\"a\": 1}"}], "usage": {"input_tokens": 3, "output_tokens": 4}})
    text, usage = ai.complete({"provider": "anthropic", "model": "claude-x", "api_key": "a" * 12},
                              [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}], json_mode=True, client=_transport(handler))
    assert text == '{"a": 1}' and usage == {"in": 3, "out": 4}
    assert seen["body"]["system"].startswith("S") and seen["body"]["messages"] == [{"role": "user", "content": "U"}]
    assert seen["key"] == "a" * 12


def test_provider_errors_are_redacted():
    def handler(req):
        return httpx.Response(400, json={"error": {"message": "bad key sk-leaky-secret-999"}})
    with pytest.raises(ai.AIError) as exc:
        ai.complete({"provider": "openai", "model": "m", "api_key": "sk-leaky-secret-999"}, [{"role": "user", "content": "x"}],
                    client=_transport(handler))
    assert "sk-leaky" not in str(exc.value)
    def denied(req):
        return httpx.Response(401, json={})
    with pytest.raises(ai.AIError, match="rejected the API key"):
        ai.complete({"provider": "openai", "model": "m", "api_key": "k" * 10}, [{"role": "user", "content": "x"}], client=_transport(denied))


def test_llm_chat_uses_the_signed_in_users_config_and_logs_without_content(user, monkeypatch):
    ai.add_config(user["id"], "openai", "gpt-test", api_key="sk-user-own-key-0001")
    calls = []
    monkeypatch.setattr(ai, "complete", lambda cfg, messages, **kw: (calls.append(cfg) or ("answer", {"in": 7, "out": 3})))
    token = accounts.CURRENT_USER.set(user)
    try:
        assert ai.llm_chat([{"role": "user", "content": "CONFIDENTIAL QUESTION"}], feature="assistant.test") == "answer"
    finally:
        accounts.CURRENT_USER.reset(token)
    assert calls[0]["api_key"] == "sk-user-own-key-0001" and calls[0]["model"] == "gpt-test"
    last = accounts.activity(user, limit=1)[0]
    assert last["event"] == "ai.call" and "CONFIDENTIAL" not in last["detail"] and '"tokens_in":7' in last["detail"]


def test_without_config_ai_is_off_and_local_features_still_work(client):
    body = client.post("/api/chat", json={"message": "rotenone", "context": {}}).json()
    assert body.get("no_ai") or body.get("no_data")
    assert client.get("/api/me").json()["ai"] is None


def test_config_api_lists_switches_and_never_returns_keys(client):
    r = client.post("/api/ai/configs", json={"provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-deep-0123456789"})
    assert r.status_code == 200 and "sk-deep" not in r.text and r.json()["active"]["api_key_hint"] == "****6789"
    d = client.post("/api/ai/configs", json={"provider": "fireworks", "model": "accounts/fireworks/models/x", "api_key": "fw-0000aaaa"}).json()
    assert [c["model"] for c in d["configs"]] == ["deepseek-chat", "accounts/fireworks/models/x"] and d["active"]["provider"] == "fireworks"
    assert d["configs"][1]["url"] == "https://api.fireworks.ai/inference/v1"
    first = d["configs"][0]["id"]
    assert client.post(f"/api/ai/configs/{first}/select").json()["active"]["model"] == "deepseek-chat"
    assert client.get("/api/me").json()["ai"]["model"] == "deepseek-chat"
    assert "sk-deep" not in client.get("/api/ai/configs").text
    assert client.post("/api/ai/configs/999999/select").status_code == 404
    left = client.delete(f"/api/ai/configs/{first}").json()
    assert left["active"] is None and len(left["configs"]) == 1
    events = [e["event"] for e in client.get("/api/activity").json()["events"]]
    assert {"ai.model_saved", "ai.model_selected", "ai.model_deleted"} <= set(events)
    assert client.post("/api/ai/configs", json={"provider": "openai_compatible", "model": "llama"}).status_code == 400  # needs endpoint
