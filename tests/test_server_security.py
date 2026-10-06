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
