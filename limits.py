"""Resource limits that keep one client from exhausting the server: request size, request rate and the
number of heavy jobs (document parsing, PDF rendering) running at once.

Anyone with an email address can sign in, so a session is not a reason to trust the load a client sends.
State is in memory, per process: enough to stop a single abusive client. Front the service with a reverse
proxy or WAF for volumetric attacks.
"""

from __future__ import annotations

import ipaddress
import os
import re
import threading
import time
from collections import deque
from typing import Optional


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def enabled() -> bool:
    return os.getenv("KEVIDENCE_RATE_LIMIT", "on").lower() not in ("0", "off", "false", "no")


# ---------------------------------------------------------------------------
# Request size
# ---------------------------------------------------------------------------

MB = 1024 * 1024
DEFAULT_BODY_LIMIT = _int("KEVIDENCE_MAX_BODY_MB", 16) * MB
AUTH_BODY_LIMIT = 16 * 1024


class BodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    """Refuses request bodies over the limit of their route, before they are buffered or spooled to disk.

    The declared Content-Length is checked first; the bytes actually received are counted too, so a
    chunked upload (or a lying Content-Length) cannot get past it."""

    def __init__(self, app, limit_for):
        self.app = app
        self.limit_for = limit_for  # (method, path) -> max bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self.limit_for(scope.get("method", "GET"), scope.get("path", ""))
        declared = next((v for k, v in scope.get("headers", []) if k == b"content-length"), None)
        if declared is not None:
            try:
                too_large = int(declared) > limit
            except ValueError:
                too_large = True
            if too_large:
                return await self._refuse(send, limit)
        seen = 0
        exceeded = False
        answered = False

        async def counting_receive():
            nonlocal seen, exceeded
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    exceeded = True
                    raise BodyTooLarge()  # stops the read; whatever the app makes of it, the answer is 413
            return message

        refused = False

        async def guarded_send(message):
            nonlocal answered, refused
            if exceeded and not answered:
                # The app turned the aborted read into some error of its own: answer 413 instead.
                answered = refused = True
                return await self._refuse(send, limit)
            if refused:
                return
            if message["type"] == "http.response.start":
                answered = True
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except Exception:
            if not exceeded:
                raise
        if exceeded and not answered:
            await self._refuse(send, limit)

    @staticmethod
    async def _refuse(send, limit: int) -> None:
        body = b'{"detail":"Request too large (limit %d MB)."}' % max(1, limit // MB)
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                (b"connection", b"close"), (b"cache-control", b"no-store"),
                                (b"x-content-type-options", b"nosniff")]})
        await send({"type": "http.response.body", "body": body})


# ---------------------------------------------------------------------------
# Request rate (sliding window, per user or per client address)
# ---------------------------------------------------------------------------

# class: (requests, seconds). Override one with e.g. KEVIDENCE_RATE_HEAVY="120/600".
_DEFAULT_RATES = {
    "general": (600, 60),     # every request
    "heavy": (60, 600),       # document analysis, sanitisation, completeness, Word export
    "ai": (120, 600),         # assistant questions
    "outbound": (30, 600),    # requests that make the server call a user-supplied endpoint
}


def _rate(cls: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", os.getenv(f"KEVIDENCE_RATE_{cls.upper()}", ""))
    return (int(m.group(1)), int(m.group(2))) if m else _DEFAULT_RATES[cls]


_HEAVY = re.compile(r"/api/(characterisation/(analyse|export\.docx)|sanitisation/(analyse|locate|apply)|completeness/(check|file))$")
_OUTBOUND = re.compile(r"/api/ai/(models|configs|configs/\d+/test)$")


def classify(method: str, path: str) -> Optional[str]:
    """The extra rate class of a request, besides 'general'."""
    if method != "POST":
        return None
    if _HEAVY.search(path):
        return "heavy"
    if _OUTBOUND.search(path):
        return "outbound"
    if path.endswith("/api/chat"):
        return "ai"
    return None


def client_key(ip: str) -> str:
    """Rate-limit key for an address. An IPv6 client owns a whole /64, so the key is the network: rotating
    through its addresses does not reset the budget."""
    try:
        addr = ipaddress.ip_address((ip or "").split("%", 1)[0])
    except ValueError:
        return ip or "unknown"
    if addr.version == 6:
        if addr.ipv4_mapped:
            return str(addr.ipv4_mapped)
        return str(ipaddress.ip_network(f"{addr}/64", strict=False).network_address) + "/64"
    return str(addr)


class SlidingWindow:
    def __init__(self):
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()
        self._swept = time.monotonic()

    def hit(self, key: str, limit: int, window_s: int) -> float:
        """Record a request. Returns 0 when allowed, else the seconds to wait."""
        now = time.monotonic()
        with self._lock:
            if now - self._swept > 300:
                self._sweep(now)
            q = self._hits.setdefault(key, deque())
            while q and q[0] <= now - window_s:
                q.popleft()
            if len(q) >= limit:
                return max(1.0, q[0] + window_s - now)
            q.append(now)
            return 0.0

    def _sweep(self, now: float) -> None:
        horizon = now - max(w for _, w in _DEFAULT_RATES.values()) - 3600
        for key in [k for k, q in self._hits.items() if not q or q[-1] < horizon]:
            del self._hits[key]
        self._swept = now

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


WINDOW = SlidingWindow()


def check(who: str, method: str, path: str) -> float:
    """0 when the request may proceed, else the seconds after which to retry."""
    if not enabled():
        return 0.0
    limit, window = _rate("general")
    wait = WINDOW.hit(f"general:{who}", limit, window)
    cls = classify(method, path)
    if not wait and cls:
        limit, window = _rate(cls)
        wait = WINDOW.hit(f"{cls}:{who}", limit, window)
    return wait


# ---------------------------------------------------------------------------
# Heavy jobs running at once
# ---------------------------------------------------------------------------

class HeavySlots:
    """Document jobs hold their input (up to hundreds of MB) and a worker thread. A few per user and a few
    overall, so parallel uploads cannot run the server out of memory."""

    def __init__(self):
        self._lock = threading.Lock()
        self._per_user: dict[str, int] = {}
        self._total = 0

    def acquire(self, who: str) -> bool:
        per_user, total = _int("KEVIDENCE_HEAVY_PER_USER", 2), _int("KEVIDENCE_HEAVY_TOTAL", 6)
        with self._lock:
            if self._total >= total or self._per_user.get(who, 0) >= per_user:
                return False
            self._total += 1
            self._per_user[who] = self._per_user.get(who, 0) + 1
            return True

    def release(self, who: str) -> None:
        with self._lock:
            self._total = max(0, self._total - 1)
            left = self._per_user.get(who, 0) - 1
            if left > 0:
                self._per_user[who] = left
            else:
                self._per_user.pop(who, None)


SLOTS = HeavySlots()
