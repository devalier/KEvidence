"""HTTP-level security tests: static file confinement, CORS, headers, optional auth."""

import base64
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("KEVIDENCE_HOME", str(ROOT))
os.environ.setdefault("OPENAI_API_KEY", "sk-test-not-used")
os.environ.pop("KEVIDENCE_CORS_ORIGINS", None)

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402

INDEX_MARKER = "KEvidence Risk Assessment Workbench"


@pytest.fixture()
def client():
    return TestClient(server.app)


@pytest.mark.parametrize("path", [
    "//etc/passwd",
    "/%2Fetc%2Fpasswd",
    "/../server.py",
    "/%2e%2e/server.py",
    "/..%2f..%2f..%2fetc%2fpasswd",
    "/samples/..%2f..%2fserver.py",
    "/%2e%2e%2f.env",
    "/..%5cserver.py",
    "/.git/config",
])
def test_static_route_cannot_read_outside_static_dir(client, path):
    # httpx normalises "..", so send the raw path as an attacker would
    response = client.request("GET", "http://testserver" + path)
    assert "root:x:0:0" not in response.text
    assert "import characterisation" not in response.text
    assert "[core]" not in response.text
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        assert INDEX_MARKER in response.text


def test_static_files_still_served(client):
    response = client.get("/samples/characterisation_demo_dossier.md")
    assert response.status_code == 200 and "FICTIONAL DEMO DOSSIER" in response.text
    assert INDEX_MARKER in client.get("/").text


def test_unknown_api_path_is_404_not_index(client):
    assert client.get("/api/does-not-exist").status_code == 404


def test_no_wildcard_cors(client):
    response = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}


def test_security_headers(client):
    headers = client.get("/").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in headers["content-security-policy"]


def test_openapi_docs_disabled(client):
    assert INDEX_MARKER in client.get("/docs").text
    assert client.get("/openapi.json").status_code in (200, 404)
    assert '"openapi"' not in client.get("/openapi.json").text


def test_basic_auth_when_configured(client, monkeypatch):
    monkeypatch.setattr(server, "AUTH_USER", "officer")
    monkeypatch.setattr(server, "AUTH_PASSWORD", "s3cret")
    assert client.get("/api/health").status_code == 401
    bad = base64.b64encode(b"officer:wrong").decode()
    assert client.get("/api/health", headers={"Authorization": f"Basic {bad}"}).status_code == 401
    good = base64.b64encode(b"officer:s3cret").decode()
    ok = client.get("/api/health", headers={"Authorization": f"Basic {good}"})
    assert ok.status_code == 200 and ok.headers["x-frame-options"] == "DENY"


# --- Domain routing for step 0 grounding ---------------------------------------------------

def test_domains_endpoint_lists_feed_only(client):
    data = client.get("/api/domains").json()
    assert data["default"] == "feed"
    assert [d["id"] for d in data["domains"]] == ["feed"]


def test_guidance_status_reports_every_source_of_the_domain(client):
    data = client.get("/api/characterisation/guidance?domain=feed").json()
    assert data["domain"]["id"] == "feed"
    assert [s["role"] for s in data["sources"]] == ["primary"] + ["supporting"] * 9
    assert {d["key"] for d in data["datasets"]} == {"qps", "mic", "vich"}
    assert next(d for d in data["datasets"] if d["key"] == "qps")["partial"] is True
    assert all(s["guidance_text_loaded"] and not s["broken"] for s in data["sources"])


@pytest.mark.parametrize("path", [
    "/api/characterisation/guidance?domain=food",
    "/api/characterisation/guidance.pdf?domain=food",
    "/api/characterisation/guidance.pdf?domain=../feed",
])
def test_unknown_domain_is_rejected_not_defaulted(client, path):
    assert client.get(path).status_code == 400


def test_unknown_source_pdf_is_404_and_known_sources_serve_pdf(client):
    assert client.get("/api/characterisation/guidance.pdf?domain=feed&source=nope").status_code == 404
    for source in ("", "efsa-2024-8912-wgs"):
        r = client.get(f"/api/characterisation/guidance.pdf?domain=feed&source={source}")
        assert r.status_code == 200 and r.content.startswith(b"%PDF")


def test_analyse_rejects_unknown_domain(client):
    r = client.post("/api/characterisation/analyse", data={"urls": "x", "domain": "food"})
    assert r.status_code == 400


def test_chat_in_an_unloaded_domain_refuses_instead_of_answering_from_feed(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("LLM must not be called without grounding")
    monkeypatch.setattr(server.llm.chat.completions, "create", boom)
    r = client.post("/api/chat", json={"message": "What are the batch requirements?",
                                       "context": {"workflow_step": "characterisation", "domain": "food"}})
    body = r.json()
    assert body["no_data"] is True and "food" in body["answer"]


def test_qps_endpoint_is_partial_and_domain_scoped(client):
    r = client.get("/api/qps?domain=feed&q=Is Bacillus sonorensis QPS?").json()
    assert r["partial"] is True and r["matches"][0]["qps"] == "yes"
    assert client.get("/api/qps?domain=feed&q=Bacillus subtilis").json()["matches"] == []
    assert client.get("/api/qps?domain=food&q=x").status_code == 400


class _FakeLLM:
    def __init__(self):
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        class _M: content = "stub answer"
        class _C: message = _M()
        class _R: choices = [_C()]
        return _R()


@pytest.mark.parametrize("step,question,entry", [
    ("exposure", "Which age classes are used for the consumer exposure?", "C4.3.1-CONSUMPTION"),
    ("risk-char", "When is an MRL needed?", "C5-MRL"),
    ("hazard-char", "Which uncertainty factor is applied to the NOAEL?", "C4.2-HBGV"),
])
def test_later_steps_answer_from_their_own_guidance_entries(client, monkeypatch, step, question, entry):
    fake = _FakeLLM()
    monkeypatch.setattr(server.llm.chat.completions, "create", fake.create)
    r = client.post("/api/chat", json={"message": question, "context": {"workflow_step": step, "domain": "feed"}}).json()
    assert entry in r["guidance_requirements"] and r["answer"] == "stub answer"
    system = fake.calls[0]["messages"][0]["content"]
    assert "FEEDAP 2017 consumer safety (5022)" in system or "consumer" in system.lower()
    assert f"Workflow step: " in fake.calls[0]["messages"][1]["content"]


def test_characterisation_tab_points_to_the_step_that_holds_the_answer(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("LLM must not be called")
    monkeypatch.setattr(server.llm.chat.completions, "create", boom)
    r = client.post("/api/chat", json={"message": "95th percentile consumption of honey and offals",
                                       "context": {"workflow_step": "characterisation", "domain": "feed"}}).json()
    assert r["no_data"] is True and "3. Exposure assessment" in r["answer"]


def test_dataset_only_question_is_answered_with_the_partial_qps_block(client, monkeypatch):
    fake = _FakeLLM()
    monkeypatch.setattr(server.llm.chat.completions, "create", fake.create)
    r = client.post("/api/chat", json={"message": "Is Bacillus sonorensis QPS?",
                                       "context": {"workflow_step": "characterisation", "domain": "feed"}}).json()
    assert r["answer"] == "stub answer"
    assert "PARTIAL dataset" in fake.calls[0]["messages"][1]["content"]
