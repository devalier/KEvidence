"""Shared test set-up: an isolated accounts database and a signed-in client."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("KEVIDENCE_HOME", str(ROOT))
os.environ["KEVIDENCE_STATE_DIR"] = tempfile.mkdtemp(prefix="kevidence-test-state-")
os.environ.pop("KEVIDENCE_ENV", None)
os.environ.pop("APP_URL", None)
os.environ.pop("RESEND_API_KEY", None)
os.environ.pop("SMTP_HOST", None)
# The suite sends hundreds of requests as one user; rate limits are tested on their own (test_hardening.py).
os.environ["KEVIDENCE_RATE_LIMIT"] = "off"


def sign_in(client, email="tester@example.org"):
    """Give a TestClient a real session for `email` (bypasses only the email delivery)."""
    import accounts
    accounts.init_db()
    user = accounts.find_or_create_user(email)
    client.cookies.set(accounts.session_cookie_name(), accounts.start_session(user["id"]))
    return user


@pytest.fixture()
def anon_client():
    from fastapi.testclient import TestClient
    import server
    return TestClient(server.app)


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    import server
    c = TestClient(server.app)
    sign_in(c)
    return c
