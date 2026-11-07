"""Authentication, rate limiting and browser-side protections for the gateway (docs/security/threat-model.md).

API keys are 256-bit random strings shown once at creation; only their SHA-256 is stored in config
(`EA_API_KEYS="name:sha256hex,name2:sha256hex"`). Comparison is constant-time. Rate limiting is in process
memory: per instance, reset on restart (a stated residual risk). Auth failures are logged without the key.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from fastapi import HTTPException, Request

log = structlog.get_logger()
KEY_PREFIX = "ea_"


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_key() -> tuple[str, str]:
    """(the key to hand to the user once, the hash to put in config)."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    return key, hash_key(key)


def parse_keys(config: str) -> dict[str, str]:
    """'alice:ab12...,bob:cd34...' -> {sha256hex: name}. Bad entries fail loudly at startup."""
    keys: dict[str, str] = {}
    for part in filter(None, (p.strip() for p in config.split(","))):
        name, sep, digest = part.partition(":")
        if (
            not sep
            or not name
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError(
                f"EA_API_KEYS entry {name or part[:8]!r} must look like name:<64 hex chars>"
            )
        keys[digest] = name
    return keys


class KeyStore:
    def __init__(self, keys: dict[str, str]) -> None:
        self._keys = keys

    def __len__(self) -> int:
        return len(self._keys)

    def authenticate(self, presented: str) -> str | None:
        digest = hash_key(presented)
        found: str | None = None
        for (
            stored,
            name,
        ) in self._keys.items():  # no early exit: time does not reveal which entry matched
            if hmac.compare_digest(stored, digest):
                found = name
        return found


@dataclass
class RateLimiter:
    """Sliding window per caller, plus a per-UTC-day cap for expensive calls."""

    per_minute: int
    daily_cap: int
    _hits: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    _daily: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def check(self, caller: str, now: float | None = None) -> float:
        """0.0 if allowed (and counted); otherwise seconds until the next call is allowed."""
        now = time.monotonic() if now is None else now
        with self._lock:
            window = self._hits[caller]
            while window and now - window[0] >= 60.0:
                window.popleft()
            if len(window) >= self.per_minute:
                return max(0.1, 60.0 - (now - window[0]))
            window.append(now)
            return 0.0

    def take_daily(self, caller: str, today: str | None = None) -> bool:
        today = today or datetime.now(UTC).strftime("%Y-%m-%d")
        with self._lock:
            if self._daily[(caller, today)] >= self.daily_cap:
                return False
            self._daily[(caller, today)] += 1
            return True


@dataclass
class Security:
    keys: KeyStore
    limiter: RateLimiter
    auth_required: bool = True
    # failed-auth throttle per client address: 10 failures per 5 minutes
    _failures: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def open(cls) -> Security:
        """No auth, generous limits. For tests and EA_AUTH=off in dev only."""
        return cls(
            KeyStore({}), RateLimiter(per_minute=10_000, daily_cap=10_000), auth_required=False
        )

    def note_failure(self, client: str, now: float | None = None) -> bool:
        """Record a failed attempt; True if this client is now throttled."""
        now = time.monotonic() if now is None else now
        with self._lock:
            window = self._failures[client]
            while window and now - window[0] >= 300.0:
                window.popleft()
            window.append(now)
            return len(window) > 10

    def throttled(self, client: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            window = self._failures[client]
            while window and now - window[0] >= 300.0:
                window.popleft()
            return len(window) > 10


def _presented_key(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.headers.get("x-api-key") or None


def _security(request: Request) -> Security:
    sec: Security | None = getattr(request.app.state, "security", None)
    if sec is None:  # fail closed: a startup bug must not silently disable auth
        raise HTTPException(status_code=500, detail="security is not configured")
    return sec


def authenticated(request: Request) -> str:
    """FastAPI dependency: identify the caller and apply the per-minute limit. Returns the caller's name."""
    sec = _security(request)
    client = request.client.host if request.client else "unknown"
    if not sec.auth_required:
        caller = "dev"
    else:
        if sec.throttled(client):
            log.warning("auth_throttled", client=client)
            raise HTTPException(
                status_code=429, detail="too many failed attempts", headers={"retry-after": "300"}
            )
        presented = _presented_key(request)
        name = sec.keys.authenticate(presented) if presented else None
        if name is None:
            sec.note_failure(client)
            log.warning(
                "auth_failed", client=client, reason="missing" if presented is None else "invalid"
            )
            raise HTTPException(
                status_code=401,
                detail="invalid or missing API key",
                headers={"www-authenticate": "Bearer"},
            )
        caller = name
    wait = sec.limiter.check(caller)
    if wait:
        log.warning("rate_limited", caller=caller)
        raise HTTPException(
            status_code=429,
            detail="rate limit exceeded",
            headers={"retry-after": str(int(wait) + 1)},
        )
    return caller


def apply_daily_cap(request: Request, caller: str) -> None:
    if not _security(request).limiter.take_daily(caller):
        log.warning("daily_cap", caller=caller)
        raise HTTPException(
            status_code=429, detail="daily agent-run cap reached", headers={"retry-after": "3600"}
        )


SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
}
UI_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
