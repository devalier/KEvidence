"""Email sign-in, sessions, CSRF origin check and the activity log."""

import contextlib
import io
import re

import pytest

import accounts
from conftest import sign_in


def _request_link(client, email):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        r = client.post("/auth/email", data={"email": email})
    m = re.search(r"token=([\w-]+)", out.getvalue())
    return r, (m.group(1) if m else None)


def test_everything_but_sign_in_requires_a_session(anon_client):
    r = anon_client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("/auth/signin")
    assert anon_client.get("/samples/characterisation_demo_dossier.md", follow_redirects=False).status_code == 303
    r = anon_client.get("/api/domains")
    assert r.status_code == 401 and r.json()["signin"].endswith("/auth/signin")
    assert anon_client.get("/api/health").status_code == 200
    assert anon_client.get("/auth/signin").status_code == 200
    assert "Disallow: /" in anon_client.get("/robots.txt").text


def test_sign_in_page_introduces_the_project(anon_client):
    page = anon_client.get("/auth/signin").text
    assert 'action="http://127.0.0.1:3457/auth/email"' in page and 'name="email"' in page
    for text in ("Sign in to try it", "Contribute", "Grounded, not generative", "GNU AGPL v3", "github.com/devalier/KEvidence"):
        assert text in page
    assert "&lt;x&gt;" in accounts.sign_in_page("<x>")  # error text is escaped


def test_email_link_signs_in_once(anon_client):
    r, token = _request_link(anon_client, "Officer@Agency.EU")
    assert r.status_code == 200 and "Check your email" in r.text and token
    # Opening the link only shows a confirmation; scanners prefetching it do not spend it.
    assert "Sign in as officer@agency.eu" in anon_client.get(f"/auth/verify?token={token}").text
    r = anon_client.post("/auth/verify", data={"token": token}, follow_redirects=False)
    assert r.status_code == 303 and "HttpOnly" in r.headers["set-cookie"] and "SameSite=Lax" in r.headers["set-cookie"]
    assert anon_client.get("/api/me").json()["email"] == "officer@agency.eu"
    assert anon_client.post("/auth/verify", data={"token": token}).status_code == 400  # used up
    events = [e["event"] for e in anon_client.get("/api/activity").json()["events"]]
    assert "signin" in events


def test_invalid_email_and_hourly_limit(anon_client):
    assert anon_client.post("/auth/email", data={"email": "not-an-email"}).status_code == 400
    tokens = [_request_link(anon_client, "limit@example.org")[1] for _ in range(accounts.LOGIN_TOKENS_PER_EMAIL_PER_HOUR + 1)]
    assert all(tokens[:-1]) and tokens[-1] is None  # same page, no link: the form cannot probe the limit


def test_tokens_and_sessions_are_stored_as_digests(anon_client):
    _, token = _request_link(anon_client, "digest@example.org")
    with accounts.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM login_tokens WHERE token_digest = ?", (token,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM login_tokens WHERE token_digest = ?", (accounts.digest(token),)).fetchone()[0] == 1


def test_logout_kills_the_session_server_side(client):
    cookie = client.cookies.get(accounts.session_cookie_name())
    assert client.get("/api/me").status_code == 200
    r = client.post("/auth/logout", follow_redirects=False)
    assert r.status_code == 303 and "Max-Age=0" in r.headers["set-cookie"]
    assert accounts.authenticate(cookie) is None


def test_cross_site_writes_are_refused(client):
    r = client.post("/api/ai/config", json={"provider": "openai"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert client.post("/api/ai/config", json={"provider": "x"}, headers={"Origin": "http://testserver"}).status_code == 400


def test_activity_is_private_unless_admin(client, monkeypatch):
    accounts.log("test.event", {"n": 1})
    assert client.get("/api/activity?scope=all").status_code == 403
    monkeypatch.setenv("KEVIDENCE_ADMIN_EMAILS", "tester@example.org")
    from fastapi.testclient import TestClient
    import server
    admin = TestClient(server.app)
    sign_in(admin, "tester@example.org")
    assert admin.get("/api/activity?scope=all").json()["scope"] == "all"


def test_production_refuses_unsafe_configuration(monkeypatch):
    monkeypatch.setenv("KEVIDENCE_ENV", "production")
    monkeypatch.setenv("APP_URL", "http://kevidence.example")
    problems = accounts.check_configuration()
    assert any("APP_URL" in p for p in problems) and any("SECRET_KEY" in p for p in problems) and any("RESEND" in p for p in problems)
    monkeypatch.setenv("APP_URL", "https://kevidence.example")
    monkeypatch.setenv("KEVIDENCE_SECRET_KEY", "x" * 40)
    monkeypatch.setenv("SMTP_HOST", "smtp.example")
    assert accounts.check_configuration() == []
    assert accounts.session_cookie_name() == "__Host-kevidence_session"
    assert "Secure" in accounts.session_cookie("t")
