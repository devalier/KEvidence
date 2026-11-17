"""Per-user AI configuration and the one function every LLM call goes through.

Same approach as ICDT_AISH's model configuration: each user brings their own provider, model and key.
The key is encrypted with AES-256-GCM under a key derived from KEVIDENCE_SECRET_KEY, bound to the user
(associated data "user:<id>"), so a row copied to another account fails to decrypt. The UI only ever
sees a hint ("****abcd"). Nobody's key is used for anyone else, and without a configuration the AI
features are simply off for that user; everything that runs locally keeps working.

Each user can save several models (to compare them) and picks the one in use. Providers are called over plain
HTTPS with httpx (no vendor SDKs): OpenAI, Anthropic, Mistral AI (EU), DeepSeek, Fireworks AI, OpenRouter, or any
OpenAI-compatible endpoint (on-premises vLLM, Ollama, TGI, an institution's gateway).
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import accounts
import netguard

PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {"label": "OpenAI", "base": "https://api.openai.com/v1", "requires_key": True, "requires_endpoint": False,
               "hint": "Cloud (US). Model id such as gpt-4o-mini."},
    "anthropic": {"label": "Anthropic (Claude)", "base": "https://api.anthropic.com/v1", "requires_key": True, "requires_endpoint": False,
                  "hint": "Cloud. Model id such as claude-sonnet-5-5."},
    "mistral": {"label": "Mistral AI (EU)", "base": "https://api.mistral.ai/v1", "requires_key": True, "requires_endpoint": False,
                "hint": "Cloud, EU-based provider. Model id such as mistral-large-latest."},
    "deepseek": {"label": "DeepSeek", "base": "https://api.deepseek.com", "requires_key": True, "requires_endpoint": False,
                 "hint": "Cloud. Model id such as deepseek-chat."},
    "fireworks": {"label": "Fireworks AI", "base": "https://api.fireworks.ai/inference/v1", "requires_key": True, "requires_endpoint": False,
                  "hint": "Cloud (US), open-weight models. Model id such as accounts/fireworks/models/llama-v3p3-70b-instruct."},
    "openrouter": {"label": "OpenRouter", "base": "https://openrouter.ai/api/v1", "requires_key": True, "requires_endpoint": False,
                   "hint": "Routes to many providers with one key; the provider that receives your text depends on the model. "
                           "Model id such as mistralai/mistral-large."},
    "openai_compatible": {"label": "On-premises / OpenAI-compatible endpoint", "base": "", "requires_key": False, "requires_endpoint": True,
                          "hint": "vLLM, Ollama, TGI, llama.cpp or an institutional gateway serving /v1/chat/completions."},
}
TIMEOUT_S = float(os.getenv("KEVIDENCE_AI_TIMEOUT", "90"))
# A provider (custom endpoints are user-chosen) must not be able to hold a worker or its memory: responses are read
# as a stream up to a byte cap and a total deadline, and only a few calls run at once.
MAX_RESPONSE_BYTES = int(os.getenv("KEVIDENCE_AI_MAX_RESPONSE_BYTES", str(8 * 1024 * 1024)))
MAX_MODELS = 2000
AI_CONCURRENCY = int(os.getenv("KEVIDENCE_AI_CONCURRENCY", "8"))
AI_CONCURRENCY_PER_USER = int(os.getenv("KEVIDENCE_AI_CONCURRENCY_PER_USER", "2"))


class AIError(RuntimeError):
    """Transport, authentication or protocol failure, with a message safe to show the user."""


class AINotConfigured(AIError):
    """The signed-in user has no AI configuration."""


# ---------------------------------------------------------------------------
# Secret encryption (AES-256-GCM, key derived with HKDF)
# ---------------------------------------------------------------------------

def _master_key() -> bytes:
    raw = os.getenv("KEVIDENCE_SECRET_KEY")
    if not raw:
        if accounts.production():
            raise accounts.ConfigurationError("KEVIDENCE_SECRET_KEY is not set")
        # Development: a random key kept next to the accounts database (never committed).
        path: Path = accounts.state_dir() / ".secret_key"
        if not path.exists():
            try:  # created 0600 from the start, and never overwritten if another worker got there first
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(secrets.token_urlsafe(48))
            except FileExistsError:
                pass
        raw = path.read_text().strip()
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"kevidence.ai-credentials.v1", info=b"aes-256-gcm").derive(raw.encode())


def encrypt_secret(plaintext: str, aad: str) -> str:
    nonce = secrets.token_bytes(12)
    ct = AESGCM(_master_key()).encrypt(nonce, plaintext.encode(), aad.encode())
    return base64.urlsafe_b64encode(nonce + ct).decode()


def decrypt_secret(blob: str, aad: str) -> str:
    try:
        raw = base64.urlsafe_b64decode(blob.encode())
        return AESGCM(_master_key()).decrypt(raw[:12], raw[12:], aad.encode()).decode()
    except Exception:
        raise AIError("The stored API key could not be decrypted. Enter it again in AI configuration.") from None


def secret_hint(key: str) -> str:
    return f"****{key[-4:]}" if len(key) >= 8 else "****"


def redact(text: str, *secrets_to_hide: Optional[str]) -> str:
    for s in secrets_to_hide:
        if s and len(s) >= 8:
            text = text.replace(s, "****")
    return text


# ---------------------------------------------------------------------------
# Outbound request safety (SSRF): a user-supplied endpoint must not reach internal services
# ---------------------------------------------------------------------------

def _allow_private() -> bool:
    return os.getenv("KEVIDENCE_ALLOW_PRIVATE_ENDPOINTS", "").lower() in ("1", "true", "yes")


def validate_endpoint(url: str) -> tuple[bool, str]:
    """Checks shared with dossier URLs (netguard.py). Private networks and plain http are for on-premises
    models only (KEVIDENCE_ALLOW_PRIVATE_ENDPOINTS=1); loopback and link-local stay refused even then."""
    allow_private = _allow_private()
    try:
        netguard.check_url(url, allow_private=allow_private, allow_http=allow_private)
    except netguard.BlockedURL as exc:
        reason = str(exc)
        if "private address" in reason:
            reason += " (set KEVIDENCE_ALLOW_PRIVATE_ENDPOINTS=1 for on-premises models)"
        return False, "endpoint rejected: " + reason
    return True, ""


def _client(endpoint: str, timeout: float) -> httpx.Client:
    """Fixed provider URLs use a plain client. A user-supplied endpoint gets one that connects only to the
    address that passed validate_endpoint (no DNS rebinding) and never follows redirects."""
    if endpoint:
        return netguard.client(allow_private=_allow_private(), timeout=timeout)
    return httpx.Client(timeout=timeout, follow_redirects=False)


class AIBusy(AIError):
    """Too many AI calls in progress (overall or for this user); the caller should retry shortly."""


_slots_lock = threading.Lock()
_slots_total = 0
_slots_user: dict[Any, int] = {}


@contextmanager
def _slot():
    """Admission control for outbound AI calls: refuse rather than queue, so waiting calls never pile up threads."""
    global _slots_total
    user = accounts.CURRENT_USER.get()
    who = user["id"] if user else None
    with _slots_lock:
        if _slots_total >= AI_CONCURRENCY or _slots_user.get(who, 0) >= AI_CONCURRENCY_PER_USER:
            raise AIBusy("Too many AI requests are running; try again in a moment.")
        _slots_total += 1
        _slots_user[who] = _slots_user.get(who, 0) + 1
    try:
        yield
    finally:
        with _slots_lock:
            _slots_total -= 1
            _slots_user[who] -= 1
            if not _slots_user[who]:
                del _slots_user[who]


def _bounded(c: httpx.Client, method: str, url: str, total_s: float, **kw) -> tuple[int, bytes]:
    """Send a request and read the (decompressed) body up to MAX_RESPONSE_BYTES within total_s seconds overall."""
    deadline = time.monotonic() + total_s
    with c.stream(method, url, **kw) as r:
        declared = r.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
            raise AIError("The AI provider's response is too large.")
        body = bytearray()
        for chunk in r.iter_bytes():
            body += chunk
            if len(body) > MAX_RESPONSE_BYTES:
                raise AIError("The AI provider's response is too large.")
            if time.monotonic() > deadline:
                raise AIError("The AI provider took too long to answer.")
        return r.status_code, bytes(body)


def _call(method: str, url: str, endpoint: str, timeout: float, client: Optional[httpx.Client], **kw) -> tuple[int, Any]:
    """One bounded provider call. Returns (status, parsed JSON or None when the body is not JSON)."""
    try:
        with _slot():
            if client is not None:
                status, raw = _bounded(client, method, url, timeout, **kw)
            else:
                with _client(endpoint, timeout) as c:
                    status, raw = _bounded(c, method, url, timeout, **kw)
    except httpx.RequestError as exc:
        raise AIError(f"Could not reach the AI provider ({type(exc).__name__}).") from None
    try:
        return status, json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return status, None


def _base(provider: str, endpoint: str) -> str:
    if provider not in PROVIDERS:
        raise AIError(f"Unknown provider '{provider}'.")
    base = (endpoint or PROVIDERS[provider]["base"]).rstrip("/")
    if not base:
        raise AIError("This provider needs an endpoint URL.")
    if endpoint:
        ok, reason = validate_endpoint(base)
        if not ok:
            raise AIError(f"{reason[0].upper()}{reason[1:]}.")
    return base[: -len("/chat/completions")] if base.endswith("/chat/completions") else base


# ---------------------------------------------------------------------------
# Provider calls
# ---------------------------------------------------------------------------

def _post(url: str, headers: dict, payload: dict, key: str, client: Optional[httpx.Client] = None, endpoint: str = "") -> dict:
    status, body = _call("POST", url, endpoint, TIMEOUT_S, client, headers=headers, json=payload)
    if status in (401, 403):
        raise AIError("The AI provider rejected the API key.")
    if status >= 400:
        msg = ""
        if isinstance(body, dict):
            err = body.get("error")
            msg = str((err.get("message") if isinstance(err, dict) else err) or "")
        raise AIError(redact(f"The AI provider returned {status}{': ' + msg[:200] if msg else ''}.", key))
    if not isinstance(body, dict):
        raise AIError("The AI provider returned an unreadable response.")
    return body


def complete(config: dict, messages: list[dict], *, temperature: float = 0.1, max_tokens: int = 1200,
             json_mode: bool = False, client: Optional[httpx.Client] = None) -> tuple[str, dict]:
    """One chat completion with a stored configuration. Returns (text, usage)."""
    provider, model, key = config["provider"], config["model"], config.get("api_key") or ""
    endpoint = config.get("endpoint") or ""
    base = _base(provider, endpoint)
    if provider == "anthropic":
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        if json_mode:
            system += "\n\nRespond with a single JSON object and nothing else."
        payload = {"model": model, "max_tokens": max_tokens, "temperature": temperature,
                   "messages": [m for m in messages if m["role"] != "system"]}
        if system:
            payload["system"] = system
        data = _post(f"{base}/messages", {"x-api-key": key, "anthropic-version": "2023-06-01"}, payload, key, client, endpoint)
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        if json_mode:
            m = re.search(r"\{.*\}", text, re.S)
            text = m.group(0) if m else text
        usage = data.get("usage") or {}
        return text, {"in": usage.get("input_tokens", 0), "out": usage.get("output_tokens", 0)}
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    if provider == "openrouter":
        headers["X-Title"] = "KEvidence"
    payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        data = _post(f"{base}/chat/completions", headers, payload, key, client, endpoint)
    except AIError as exc:
        if json_mode and provider == "openai_compatible" and "returned 4" in str(exc):
            payload.pop("response_format")  # some on-premises servers do not support JSON mode
            data = _post(f"{base}/chat/completions", headers, payload, key, client, endpoint)
        else:
            raise
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise AIError("The AI provider returned an unexpected response.") from None
    usage = data.get("usage") or {}
    return text, {"in": usage.get("prompt_tokens", 0), "out": usage.get("completion_tokens", 0)}


def list_models(provider: str, api_key: str, endpoint: str, client: Optional[httpx.Client] = None) -> list[str]:
    """Models the entered key can use. The key is used for this one call and not stored."""
    base = _base(provider, endpoint)
    if PROVIDERS[provider]["requires_key"] and not api_key:
        raise AIError("Enter the API key first.")
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"} if provider == "anthropic" else (
        {"Authorization": f"Bearer {api_key}"} if api_key else {})
    status, body = _call("GET", f"{base}/models", endpoint, 15, client, headers=headers,
                         params={"limit": 1000} if provider == "anthropic" else None)
    if status in (401, 403):
        raise AIError("The AI provider rejected the API key.")
    if status >= 400:
        raise AIError(f"The AI provider returned {status}.")
    try:
        ids = {str(m["id"])[:200] for m in body["data"][:MAX_MODELS]}
    except (KeyError, TypeError):
        raise AIError("The AI provider returned an unrecognised model list.") from None
    return sorted(ids)


# ---------------------------------------------------------------------------
# Saved models (several per user, one in use)
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Columns the UI may see (never the key ciphertext). Queries below are literal strings: nothing is ever
# formatted into SQL.
_SELECT_PUBLIC_BY_ID = ("SELECT id, provider, model, endpoint, api_key_hint, active, created_at, updated_at, last_checked_at, "
    "last_check_ok, last_check_message FROM ai_models WHERE id = ?")
_SELECT_PUBLIC_BY_USER = ("SELECT id, provider, model, endpoint, api_key_hint, active, created_at, updated_at, last_checked_at, "
    "last_check_ok, last_check_message FROM ai_models WHERE user_id = ? ORDER BY id")
_SELECT_PUBLIC_ACTIVE = ("SELECT id, provider, model, endpoint, api_key_hint, active, created_at, updated_at, last_checked_at, "
    "last_check_ok, last_check_message FROM ai_models WHERE user_id = ? AND active = 1")


def _public(row) -> dict:
    """A saved model as the UI may see it: never the key, only its hint."""
    out = dict(row)
    spec = PROVIDERS.get(out["provider"], {})
    out["provider_label"] = spec.get("label", out["provider"])
    out["url"] = (out["endpoint"] or spec.get("base", "")).rstrip("/")
    out["active"] = bool(out["active"])
    out["last_check_ok"] = None if out["last_check_ok"] is None else bool(out["last_check_ok"])
    return out


def list_configs(user_id: int) -> list[dict]:
    with accounts.connect() as conn:
        rows = conn.execute(_SELECT_PUBLIC_BY_USER, (user_id,)).fetchall()
    return [_public(r) for r in rows]


def public_config(user_id: int) -> Optional[dict]:
    """The model in use, as the UI may see it, or None."""
    with accounts.connect() as conn:
        row = conn.execute(_SELECT_PUBLIC_ACTIVE, (user_id,)).fetchone()
    return _public(row) if row else None


def _owned(conn, user_id: int, config_id: int):
    row = conn.execute("SELECT * FROM ai_models WHERE id = ? AND user_id = ?", (config_id, user_id)).fetchone()
    if not row:
        raise AIError("That model does not exist.")  # also for another user's id: no existence leak
    return row


def load_config(user_id: int, config_id: Optional[int] = None) -> Optional[dict]:
    """The model in use (or the given one) with the decrypted key, for a call. Never returned to the browser."""
    with accounts.connect() as conn:
        if config_id is None:
            row = conn.execute("SELECT * FROM ai_models WHERE user_id = ? AND active = 1", (user_id,)).fetchone()
            if not row:
                return None
        else:
            row = _owned(conn, user_id, config_id)
    key = decrypt_secret(row["api_key_ciphertext"], f"user:{user_id}") if row["api_key_ciphertext"] else ""
    return {"id": row["id"], "provider": row["provider"], "model": row["model"], "endpoint": row["endpoint"], "api_key": key}


def add_config(user_id: int, provider: str, model: str, endpoint: str = "", api_key: str = "", activate: bool = True) -> dict:
    """Save a model (or update the key of an identical one) and, by default, put it in use.
    Without a key, the key already saved for the same provider and endpoint is reused, so comparing several
    models of one provider needs the key only once."""
    provider, model, endpoint, api_key = provider.strip(), model.strip()[:160], endpoint.strip()[:400], (api_key or "").strip()
    if provider not in PROVIDERS:
        raise AIError("Choose a provider from the list.")
    spec = PROVIDERS[provider]
    if not model:
        raise AIError("Enter the model identifier.")
    if spec["requires_endpoint"] and not endpoint:
        raise AIError("An on-premises / OpenAI-compatible model needs its endpoint URL.")
    if endpoint:
        ok, reason = validate_endpoint(endpoint)
        if not ok:
            raise AIError(f"{reason[0].upper()}{reason[1:]}.")
    now = _now()
    with accounts.connect() as conn:
        same = conn.execute("SELECT id, api_key_ciphertext, api_key_hint FROM ai_models WHERE user_id = ? AND provider = ? AND model = ? "
                            "AND endpoint = ?", (user_id, provider, model, endpoint)).fetchone()
        if api_key:
            ct, hint = encrypt_secret(api_key, f"user:{user_id}"), secret_hint(api_key)
        else:
            donor = same if same and same["api_key_ciphertext"] else conn.execute(
                "SELECT api_key_ciphertext, api_key_hint FROM ai_models WHERE user_id = ? AND provider = ? AND endpoint = ? "
                "AND api_key_ciphertext IS NOT NULL ORDER BY updated_at DESC LIMIT 1", (user_id, provider, endpoint)).fetchone()
            ct, hint = (donor["api_key_ciphertext"], donor["api_key_hint"]) if donor else (None, "")
        if spec["requires_key"] and not ct:
            raise AIError("This provider requires an API key.")
        if same:
            conn.execute("UPDATE ai_models SET api_key_ciphertext = ?, api_key_hint = ?, updated_at = ? WHERE id = ?",
                         (ct, hint, now, same["id"]))
            config_id = same["id"]
        else:
            config_id = conn.execute("INSERT INTO ai_models (user_id, provider, model, endpoint, api_key_ciphertext, api_key_hint, "
                                     "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                     (user_id, provider, model, endpoint, ct, hint, now, now)).lastrowid
        if activate:
            conn.execute("UPDATE ai_models SET active = (id = ?) WHERE user_id = ?", (config_id, user_id))
        row = conn.execute(_SELECT_PUBLIC_BY_ID, (config_id,)).fetchone()
    return _public(row)


def select_config(user_id: int, config_id: int) -> dict:
    """Put one saved model in use; every AI feature uses it from the next call."""
    with accounts.connect() as conn:
        _owned(conn, user_id, config_id)
        conn.execute("UPDATE ai_models SET active = (id = ?) WHERE user_id = ?", (config_id, user_id))
        row = conn.execute(_SELECT_PUBLIC_BY_ID, (config_id,)).fetchone()
    return _public(row)


def delete_config(user_id: int, config_id: int) -> dict:
    """Remove a saved model and its key. Deleting the model in use leaves AI off until another is selected.
    Returns what was deleted (provider, model, whether it was in use) for the activity log."""
    with accounts.connect() as conn:
        row = _owned(conn, user_id, config_id)
        conn.execute("DELETE FROM ai_models WHERE id = ?", (config_id,))
    return {"provider": row["provider"], "model": row["model"], "was_active": bool(row["active"])}


def check_config(user_id: int, config_id: Optional[int] = None, client: Optional[httpx.Client] = None) -> dict:
    """One minimal live call, so the user finds out here rather than mid-assessment."""
    cfg = load_config(user_id, config_id)
    if not cfg:
        raise AINotConfigured("No model is in use.")
    started = time.monotonic()
    try:
        complete(cfg, [{"role": "user", "content": "Reply with the single word: ready"}], max_tokens=16, client=client)
        ok, msg = True, f"Responded in {int((time.monotonic() - started) * 1000)} ms."
    except AIError as exc:
        ok, msg = False, redact(str(exc), cfg.get("api_key"))
    with accounts.connect() as conn:
        conn.execute("UPDATE ai_models SET last_checked_at = ?, last_check_ok = ?, last_check_message = ? WHERE id = ?",
                     (_now(), int(ok), msg[:400], cfg["id"]))
        row = conn.execute(_SELECT_PUBLIC_BY_ID, (cfg["id"],)).fetchone()
    return _public(row)


# ---------------------------------------------------------------------------
# The entry point used by every feature
# ---------------------------------------------------------------------------

NOT_CONFIGURED = ("No AI model is in use for your account. Open AI configuration (left menu) and add your own provider, "
                  "model and key, or select one of your saved models. Everything that runs locally keeps working without it.")


def user_has_ai() -> bool:
    user = accounts.CURRENT_USER.get()
    return bool(user) and public_config(user["id"]) is not None


def llm_chat(messages: list[dict], *, feature: str, temperature: float = 0.1, max_tokens: int = 1200,
             json_mode: bool = False) -> str:
    """Run a completion with the signed-in user's own configuration and log it (feature, provider, model,
    token counts — never the content). Raises AINotConfigured when the user has none."""
    user = accounts.CURRENT_USER.get()
    if not user:
        raise AINotConfigured(NOT_CONFIGURED)
    cfg = load_config(user["id"])
    if not cfg:
        raise AINotConfigured(NOT_CONFIGURED)
    try:
        text, usage = complete(cfg, messages, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode)
    except AIError as exc:
        accounts.log("ai.call_failed", {"feature": feature, "provider": cfg["provider"], "model": cfg["model"]}, user)
        raise AIError(redact(str(exc), cfg.get("api_key"))) from None
    accounts.log("ai.call", {"feature": feature, "provider": cfg["provider"], "model": cfg["model"],
                             "tokens_in": usage.get("in", 0), "tokens_out": usage.get("out", 0)}, user)
    return text


def json_completer(feature: str, max_tokens: int = 2500):
    """A (system, user) -> JSON text callable for modules that take one (narratives, sanitisation review)."""
    def call(system: str, user: str) -> str:
        return llm_chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                        feature=feature, temperature=0, max_tokens=max_tokens, json_mode=True)
    return call
