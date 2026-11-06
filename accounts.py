"""Accounts: email sign-in, sessions and the activity log.

Same approach as YachtPlan's email sign-in. A user types an email address; KEvidence emails a one-time link
(15 minutes, usable once). Opening the link shows a confirmation button (so mail scanners that prefetch
links cannot spend it); confirming starts a session whose random token lives only in an HttpOnly cookie.
The database stores SHA-256 digests of login and session tokens, never the tokens, so a copied database
cannot be replayed as signed-in browsers. Signing out deletes the session row server-side.

Any verified email can sign in: the point is to keep out anonymous and casual browsing, and to know who
did what (activity log), not to restrict testers.

State lives in SQLite at $KEVIDENCE_STATE_DIR/accounts.db (default <KEVIDENCE_HOME>/data/state/).
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import threading
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx

SESSION_TTL = timedelta(days=14)
LOGIN_TOKEN_TTL = timedelta(minutes=15)
LOGIN_TOKENS_PER_EMAIL_PER_HOUR = 5
AUTH_REQUESTS_PER_IP = (20, 15 * 60)  # 20 per 15 minutes
EMAIL_RE = re.compile(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[A-Za-z]{2,}$")

CURRENT_USER: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar("kevidence_user", default=None)
CURRENT_IP: contextvars.ContextVar[str] = contextvars.ContextVar("kevidence_ip", default="")


class ConfigurationError(RuntimeError):
    """The deployment is missing something it needs to run safely."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def production() -> bool:
    return os.getenv("KEVIDENCE_ENV", "").lower() == "production"


def app_url() -> str:
    """Public base URL links and redirects are built from (may include a path prefix). Never derived from
    the Host header, which the client controls."""
    return (os.getenv("APP_URL") or f"http://127.0.0.1:{os.getenv('PORT', '3457')}").rstrip("/")


def app_origin() -> str:
    parts = urlsplit(app_url())
    return f"{parts.scheme}://{parts.netloc}"


def secure_cookies() -> bool:
    return app_url().startswith("https://")


def session_cookie_name() -> str:
    # __Host- cookies must be Secure, host-only and Path=/, so a sibling subdomain cannot plant them.
    return "__Host-kevidence_session" if secure_cookies() else "kevidence_session"


def state_dir() -> Path:
    home = Path(os.getenv("KEVIDENCE_HOME", "/var/www/kevidence"))
    d = Path(os.getenv("KEVIDENCE_STATE_DIR") or home / "data" / "state")
    d.mkdir(parents=True, exist_ok=True)
    return d


def admin_emails() -> set[str]:
    return {e.strip().lower() for e in os.getenv("KEVIDENCE_ADMIN_EMAILS", "").split(",") if e.strip()}


def mail_transport() -> str:
    if os.getenv("RESEND_API_KEY"):
        return "resend"
    if os.getenv("SMTP_HOST"):
        return "smtp"
    return "console"


def check_configuration() -> list[str]:
    """Problems that make the deployment unsafe. In production they stop the server from starting."""
    problems = []
    if production():
        if not app_url().startswith("https://"):
            problems.append("APP_URL must be the public https:// URL in production")
        if not os.getenv("KEVIDENCE_SECRET_KEY"):
            problems.append("KEVIDENCE_SECRET_KEY must be set in production (encrypts stored AI keys)")
        if mail_transport() == "console":
            problems.append("set RESEND_API_KEY or SMTP_HOST in production: sign-in links must be emailed")
    return problems


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS login_tokens (
    token_digest TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);
CREATE INDEX IF NOT EXISTS login_tokens_email ON login_tokens (email, created_at);
CREATE TABLE IF NOT EXISTS sessions (
    token_digest TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ip_hash TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    user_id INTEGER,
    email TEXT,
    event TEXT NOT NULL,
    detail TEXT,
    ip_hash TEXT
);
CREATE INDEX IF NOT EXISTS activity_user ON activity (user_id, id);
CREATE TABLE IF NOT EXISTS rate_buckets (
    key TEXT PRIMARY KEY,
    window_start TEXT NOT NULL,
    count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_configs (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    endpoint TEXT NOT NULL DEFAULT '',
    api_key_ciphertext TEXT,
    api_key_hint TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    last_checked_at TEXT,
    last_check_ok INTEGER,
    last_check_message TEXT
);
"""

_lock = threading.Lock()


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(state_dir() / "accounts.db"), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextlib.contextmanager
def connect():
    """A connection that commits on success and is always closed."""
    conn = db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with _lock, connect() as conn:
        conn.executescript(_SCHEMA)
    try:
        os.chmod(state_dir() / "accounts.db", 0o600)
    except OSError:
        pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def ip_hash(ip: str) -> str:
    """Activity rows keep a keyed hash of the IP, enough to spot patterns without storing addresses."""
    key = (os.getenv("KEVIDENCE_SECRET_KEY") or "kevidence-dev").encode()
    return hmac.new(key, (ip or "").encode(), hashlib.sha256).hexdigest()[:16]


def normalise_email(email: str) -> str:
    email = (email or "").strip().lower()
    return email if EMAIL_RE.match(email) and len(email) <= 254 else ""


# ---------------------------------------------------------------------------
# Rate limiting (persisted, so a restart does not reset an attacker's budget)
# ---------------------------------------------------------------------------

def rate_limited(key: str, limit: int, window_s: int) -> bool:
    now = _now()
    with _lock, connect() as conn:
        row = conn.execute("SELECT window_start, count FROM rate_buckets WHERE key = ?", (key[:180],)).fetchone()
        if not row or datetime.fromisoformat(row["window_start"]) + timedelta(seconds=window_s) <= now:
            conn.execute("INSERT OR REPLACE INTO rate_buckets (key, window_start, count) VALUES (?, ?, 1)", (key[:180], _iso(now)))
            return False
        conn.execute("UPDATE rate_buckets SET count = count + 1 WHERE key = ?", (key[:180],))
        return row["count"] + 1 > limit


# ---------------------------------------------------------------------------
# Login tokens, users, sessions
# ---------------------------------------------------------------------------

def issue_login_token(email: str) -> Optional[str]:
    """A fresh one-time token, or None when the address asked for too many links in the past hour."""
    now = _now()
    with _lock, connect() as conn:
        conn.execute("DELETE FROM login_tokens WHERE expires_at < ?", (_iso(now - timedelta(hours=1)),))
        recent = conn.execute("SELECT COUNT(*) FROM login_tokens WHERE email = ? AND created_at > ?",
                              (email, _iso(now - timedelta(hours=1)))).fetchone()[0]
        if recent >= LOGIN_TOKENS_PER_EMAIL_PER_HOUR:
            return None
        token = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO login_tokens (token_digest, email, created_at, expires_at) VALUES (?, ?, ?, ?)",
                     (digest(token), email, _iso(now), _iso(now + LOGIN_TOKEN_TTL)))
    return token


def login_token_email(token: str) -> Optional[str]:
    """The email a still-valid token signs in, without using it up."""
    if not token:
        return None
    with connect() as conn:
        row = conn.execute("SELECT email FROM login_tokens WHERE token_digest = ? AND used_at IS NULL AND expires_at > ?",
                           (digest(token), _iso(_now()))).fetchone()
    return row["email"] if row else None


def redeem_login_token(token: str) -> Optional[str]:
    """Use the token up, atomically, so it signs in exactly once."""
    if not token:
        return None
    with _lock, connect() as conn:
        row = conn.execute("UPDATE login_tokens SET used_at = ? WHERE token_digest = ? AND used_at IS NULL AND expires_at > ? RETURNING email",
                           (_iso(_now()), digest(token), _iso(_now()))).fetchone()
    return row["email"] if row else None


def find_or_create_user(email: str) -> dict:
    with _lock, connect() as conn:
        conn.execute("INSERT OR IGNORE INTO users (email, created_at) VALUES (?, ?)", (email, _iso(_now())))
        conn.execute("UPDATE users SET last_login_at = ? WHERE email = ?", (_iso(_now()), email))
        row = conn.execute("SELECT id, email FROM users WHERE email = ?", (email,)).fetchone()
    return {"id": row["id"], "email": row["email"]}


def start_session(user_id: int, ip: str = "", user_agent: str = "") -> str:
    """Create a session; returns the raw token for the cookie (only its digest is stored)."""
    token = secrets.token_urlsafe(32)
    now = _now()
    with _lock, connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_iso(now),))
        conn.execute("INSERT INTO sessions (token_digest, user_id, ip_hash, user_agent, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (digest(token), user_id, ip_hash(ip), (user_agent or "")[:300], _iso(now), _iso(now + SESSION_TTL)))
    return token


def authenticate(token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    with connect() as conn:
        row = conn.execute("SELECT users.id, users.email FROM sessions JOIN users ON users.id = sessions.user_id "
                           "WHERE sessions.token_digest = ? AND sessions.expires_at > ?", (digest(token), _iso(_now()))).fetchone()
    if not row:
        return None
    return {"id": row["id"], "email": row["email"], "admin": row["email"] in admin_emails()}


def end_session(token: Optional[str]) -> None:
    if token:
        with _lock, connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_digest = ?", (digest(token),))


def session_cookie(token: str, *, clear: bool = False) -> str:
    max_age = 0 if clear else int(SESSION_TTL.total_seconds())
    # SameSite=Lax, not Strict: sign-in finishes on a top-level navigation from an email client, where a
    # Strict cookie would be withheld. Cross-site writes are refused by the Origin check instead.
    return (f"{session_cookie_name()}={'' if clear else token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={max_age}"
            + ("; Secure" if secure_cookies() else ""))


# ---------------------------------------------------------------------------
# Activity log
# ---------------------------------------------------------------------------

def log(event: str, detail: Any = "", user: Optional[dict] = None) -> None:
    """Record what a user did. Never store document content, questions or keys: names of features,
    counts and settings only."""
    user = user or CURRENT_USER.get()
    if not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False, separators=(",", ":"))
    with _lock, connect() as conn:
        conn.execute("INSERT INTO activity (at, user_id, email, event, detail, ip_hash) VALUES (?, ?, ?, ?, ?, ?)",
                     (_iso(_now()), user["id"] if user else None, user["email"] if user else None, event[:60],
                      (detail or "")[:600], ip_hash(CURRENT_IP.get())))


def activity(user: dict, everyone: bool = False, limit: int = 200) -> list[dict]:
    with connect() as conn:
        if everyone:
            rows = conn.execute("SELECT at, email, event, detail FROM activity ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = conn.execute("SELECT at, email, event, detail FROM activity WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                                (user["id"], limit)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_sign_in_link(email: str, link: str) -> None:
    subject = "Your KEvidence sign-in link"
    text = (f"Sign in to KEvidence:\n\n{link}\n\nThe link works once and expires in 15 minutes. "
            "If you did not ask for it, ignore this email.")
    body_html = (f"<p>Sign in to KEvidence:</p><p><a href=\"{html.escape(link)}\">Sign in</a></p>"
                 "<p>The link works once and expires in 15 minutes. If you did not ask for it, ignore this email.</p>")
    sender = os.getenv("MAIL_FROM", "KEvidence <onboarding@resend.dev>")
    transport = mail_transport()
    if transport == "resend":
        r = httpx.post("https://api.resend.com/emails", timeout=10,
                       headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
                       json={"from": sender, "to": [email], "subject": subject, "text": text, "html": body_html})
        if r.status_code >= 400:
            raise RuntimeError(f"Email provider returned {r.status_code}")
    elif transport == "smtp":
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = sender, email, subject
        msg.set_content(text)
        msg.add_alternative(body_html, subtype="html")
        host, port = os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587"))
        mode = os.getenv("SMTP_TLS", "starttls").lower()
        context = ssl.create_default_context()
        if mode == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=15, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            if mode == "starttls":
                server.starttls(context=context)
        with server:
            if os.getenv("SMTP_USER"):
                server.login(os.environ["SMTP_USER"], os.getenv("SMTP_PASSWORD", ""))
            server.send_message(msg)
    else:
        if production():
            raise ConfigurationError("No mail transport configured")
        print(f"[KEvidence] (development, not emailed) Sign-in link for {email}: {link}", flush=True)


# ---------------------------------------------------------------------------
# Pages (server-rendered, no script)
# ---------------------------------------------------------------------------

_PAGE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>KEvidence — sign in</title><style>
body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0f172a;color:#f1f5f9;
font-family:Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:16px}}
.card{{background:#1e293b;border:1px solid #334155;border-radius:14px;padding:28px;max-width:440px;width:100%}}
h1{{font-size:20px;margin:0 0 4px}}.sub{{color:#94a3b8;font-size:14px;margin:0 0 18px}}
label{{display:block;font-size:12px;color:#94a3b8;text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px}}
input{{width:100%;box-sizing:border-box;padding:11px 12px;border-radius:10px;border:1px solid #475569;background:#0f172a;color:#f1f5f9;font-size:15px}}
button{{margin-top:14px;width:100%;padding:11px;border:0;border-radius:10px;font-weight:700;font-size:15px;cursor:pointer;
background:linear-gradient(135deg,#38bdf8,#818cf8);color:#0f172a}}
.err{{color:#f87171;margin:0 0 12px}}.muted{{color:#94a3b8;font-size:13px;line-height:1.5}}a{{color:#38bdf8}}
.logo{{width:38px;height:38px;border-radius:10px;background:linear-gradient(135deg,#38bdf8,#818cf8);display:flex;align-items:center;
justify-content:center;font-weight:800;margin-bottom:14px;color:#0f172a}}
</style></head><body><main class="card"><div class="logo">K</div>{body}</main></body></html>"""


def page(body: str) -> str:
    return _PAGE.format(body=body)


def sign_in_page(error: str = "", email: str = "") -> str:
    err = f'<p class="err" role="alert">{html.escape(error)}</p>' if error else ""
    return page(f"""<h1>Sign in to KEvidence</h1>
<p class="sub">Open-source prototype for food and feed safety risk assessment.</p>{err}
<form method="post" action="{html.escape(app_url())}/auth/email">
<label for="email">Your email</label>
<input id="email" name="email" type="email" required autocomplete="email" value="{html.escape(email)}" autofocus>
<button type="submit">Email me a sign-in link</button></form>
<p class="muted">No password: we email you a link that works once for 15 minutes. Any email address can sign in.
Your actions are recorded in an activity log you can see. <a href="https://github.com/devalier/KEvidence">Source code</a> (AGPL-3.0).</p>""")


def check_email_page(email: str) -> str:
    return page(f"""<h1>Check your email</h1>
<p class="sub">If {html.escape(email)} can receive mail, a sign-in link is on its way.</p>
<p class="muted">The link works once and expires in 15 minutes. Nothing arrived? Check spam, or
<a href="{html.escape(app_url())}/auth/signin">ask for another link</a>.</p>""")


def confirm_page(email: str, token: str) -> str:
    return page(f"""<h1>Sign in as {html.escape(email)}?</h1>
<form method="post" action="{html.escape(app_url())}/auth/verify">
<input type="hidden" name="token" value="{html.escape(token)}">
<button type="submit">Sign in</button></form>
<p class="muted">This extra click stops email scanners from using up your link.</p>""")


def message_page(title: str, text: str) -> str:
    return page(f"""<h1>{html.escape(title)}</h1><p class="muted">{html.escape(text)}</p>
<p class="muted"><a href="{html.escape(app_url())}/auth/signin">Back to sign in</a></p>""")
