"""Per-user AI configuration: encrypted keys bound to their owner, endpoint safety, provider calls,
and that every feature uses the signed-in user's own configuration."""

import json

import httpx
import pytest

import accounts
import ai
from conftest import sign_in


@pytest.fixture()
def user():
    return accounts.find_or_create_user("ai-user@example.org")


def test_key_is_encrypted_bound_to_its_owner_and_never_returned(user):
    cfg = ai.save_config(user["id"], "openai", "gpt-4o-mini", api_key="sk-secret-value-1234")
    assert cfg["api_key_hint"] == "****1234" and "api_key" not in cfg
    with accounts.connect() as conn:
        blob = conn.execute("SELECT api_key_ciphertext FROM ai_configs WHERE user_id = ?", (user["id"],)).fetchone()[0]
    assert "sk-secret" not in blob
    assert ai.load_config(user["id"])["api_key"] == "sk-secret-value-1234"
    other = accounts.find_or_create_user("other@example.org")
    with pytest.raises(ai.AIError):  # a row copied to another account does not decrypt
        ai.decrypt_secret(blob, f"user:{other['id']}")


def test_keep_replace_and_require_key(user):
    ai.save_config(user["id"], "mistral", "mistral-large-latest", api_key="key-aaaaaaaa")
    assert ai.save_config(user["id"], "mistral", "mistral-small-latest")["api_key_hint"] == "****aaaa"  # None keeps it
    with pytest.raises(ai.AIError, match="requires an API key"):
        ai.save_config(user["id"], "anthropic", "claude", api_key="")
    with pytest.raises(ai.AIError, match="provider"):
        ai.save_config(user["id"], "nope", "m", api_key="x" * 10)


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
    ai.save_config(user["id"], "openai", "gpt-test", api_key="sk-user-own-key-0001")
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


def test_config_api_never_returns_the_key(client):
    r = client.post("/api/ai/config", json={"provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-deep-0123456789"})
    assert r.status_code == 200 and "sk-deep" not in r.text and r.json()["config"]["api_key_hint"] == "****6789"
    assert "sk-deep" not in client.get("/api/ai/config").text
    events = [e["event"] for e in client.get("/api/activity").json()["events"]]
    assert "ai.config_saved" in events
    assert client.delete("/api/ai/config").json()["config"] is None
    assert client.post("/api/ai/config", json={"provider": "openai_compatible", "model": "llama"}).status_code == 400  # needs endpoint
