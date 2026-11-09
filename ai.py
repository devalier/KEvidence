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
import ipaddress
import json
import os
import re
import secrets
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

import accounts

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
            path.write_text(secrets.token_urlsafe(48))
            os.chmod(path, 0o600)
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

def validate_endpoint(url: str) -> tuple[bool, str]:
    allow_private = os.getenv("KEVIDENCE_ALLOW_PRIVATE_ENDPOINTS", "").lower() in ("1", "true", "yes")
    try:
        parts = urlsplit(url)
    except ValueError:
        return False, "endpoint is not a valid URL"
    if parts.scheme not in ("https", "http"):
        return False, "endpoint must use https"
    if parts.scheme == "http" and not allow_private:
        return False, "plain http endpoints are not permitted"
    if not parts.hostname:
        return False, "endpoint has no host"
    if parts.username or parts.password:
        return False, "credentials must not be embedded in the endpoint URL"
    host = parts.hostname.lower()
    if host in ("localhost", "metadata.google.internal") or host.endswith(".localhost"):
        return False, "endpoint host is not permitted"
    try:
        infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror:
        return False, "endpoint host does not resolve from this server"
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved or addr.is_unspecified:
            return False, "endpoint resolves to a blocked address range"
        if addr.is_private and not allow_private:
            return False, "endpoint resolves to a private address (set KEVIDENCE_ALLOW_PRIVATE_ENDPOINTS=1 for on-premises models)"
    return True, ""


def _base(provider: str, endpoint: str) -> str:
    if provider not in PROVIDERS:
        raise AIError(f"Unknown provider '{provider}'.")
    base = (endpoint or PROVIDERS[provider]["base"]).rstrip("/")
    if not base:
        raise AIError("This provider needs an endpoint URL.")
    if endpoint:
        ok, reason = validate_endpoint(base)
        if not ok:
            raise AIError(f"Endpoint rejected: {reason}.")
    return base[: -len("/chat/completions")] if base.endswith("/chat/completions") else base


# ---------------------------------------------------------------------------
# Provider calls
# ---------------------------------------------------------------------------

def _post(url: str, headers: dict, payload: dict, key: str, client: Optional[httpx.Client] = None) -> dict:
    try:
        if client is not None:
            r = client.post(url, headers=headers, json=payload)
        else:
            with httpx.Client(timeout=TIMEOUT_S, follow_redirects=False) as c:
                r = c.post(url, headers=headers, json=payload)
    except httpx.RequestError as exc:
        raise AIError(f"Could not reach the AI provider ({type(exc).__name__}).") from None
    if r.status_code in (401, 403):
        raise AIError("The AI provider rejected the API key.")
    if r.status_code >= 400:
        msg = ""
        try:
            body = r.json()
            msg = (body.get("error") or {}).get("message", "") if isinstance(body.get("error"), dict) else str(body.get("error") or "")
        except ValueError:
            pass
        raise AIError(redact(f"The AI provider returned {r.status_code}{': ' + msg[:200] if msg else ''}.", key))
    try:
        return r.json()
    except ValueError:
        raise AIError("The AI provider returned an unreadable response.") from None


def complete(config: dict, messages: list[dict], *, temperature: float = 0.1, max_tokens: int = 1200,
             json_mode: bool = False, client: Optional[httpx.Client] = None) -> tuple[str, dict]:
    """One chat completion with a stored configuration. Returns (text, usage)."""
    provider, model, key = config["provider"], config["model"], config.get("api_key") or ""
    base = _base(provider, config.get("endpoint") or "")
    if provider == "anthropic":
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        if json_mode:
            system += "\n\nRespond with a single JSON object and nothing else."
        payload = {"model": model, "max_tokens": max_tokens, "temperature": temperature,
                   "messages": [m for m in messages if m["role"] != "system"]}
        if system:
            payload["system"] = system
        data = _post(f"{base}/messages", {"x-api-key": key, "anthropic-version": "2023-06-01"}, payload, key, client)
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
        data = _post(f"{base}/chat/completions", headers, payload, key, client)
    except AIError as exc:
        if json_mode and provider == "openai_compatible" and "returned 4" in str(exc):
            payload.pop("response_format")  # some on-premises servers do not support JSON mode
            data = _post(f"{base}/chat/completions", headers, payload, key, client)
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
    try:
        if client is not None:
            r = client.get(f"{base}/models", headers=headers)
        else:
            with httpx.Client(timeout=15, follow_redirects=False) as c:
                r = c.get(f"{base}/models", headers=headers, params={"limit": 1000} if provider == "anthropic" else None)
    except httpx.RequestError as exc:
        raise AIError(f"Could not reach the AI provider ({type(exc).__name__}).") from None
    if r.status_code in (401, 403):
        raise AIError("The AI provider rejected the API key.")
    if r.status_code >= 400:
        raise AIError(f"The AI provider returned {r.status_code}.")
    try:
        return sorted({str(m["id"]) for m in r.json()["data"]})
    except (ValueError, KeyError, TypeError):
        raise AIError("The AI provider returned an unrecognised model list.") from None


# ---------------------------------------------------------------------------
# Saved models (several per user, one in use)
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_PUBLIC_COLS = ("id, provider, model, endpoint, api_key_hint, active, created_at, updated_at, last_checked_at, "
                "last_check_ok, last_check_message")


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
        rows = conn.execute(f"SELECT {_PUBLIC_COLS} FROM ai_models WHERE user_id = ? ORDER BY id", (user_id,)).fetchall()
    return [_public(r) for r in rows]


def public_config(user_id: int) -> Optional[dict]:
    """The model in use, as the UI may see it, or None."""
    with accounts.connect() as conn:
        row = conn.execute(f"SELECT {_PUBLIC_COLS} FROM ai_models WHERE user_id = ? AND active = 1", (user_id,)).fetchone()
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
            raise AIError(f"Endpoint rejected: {reason}.")
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
        row = conn.execute(f"SELECT {_PUBLIC_COLS} FROM ai_models WHERE id = ?", (config_id,)).fetchone()
    return _public(row)


def select_config(user_id: int, config_id: int) -> dict:
    """Put one saved model in use; every AI feature uses it from the next call."""
    with accounts.connect() as conn:
        _owned(conn, user_id, config_id)
        conn.execute("UPDATE ai_models SET active = (id = ?) WHERE user_id = ?", (config_id, user_id))
        row = conn.execute(f"SELECT {_PUBLIC_COLS} FROM ai_models WHERE id = ?", (config_id,)).fetchone()
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
        row = conn.execute(f"SELECT {_PUBLIC_COLS} FROM ai_models WHERE id = ?", (cfg["id"],)).fetchone()
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
