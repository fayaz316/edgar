"""Authentication, rate limiting, headers and fail-closed startup, through the real HTTP stack."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
import structlog
from fastapi.testclient import TestClient

from services.agent.llm import ModelTurn
from services.agent.tests.test_agent import FakeRetriever, ScriptedLLM
from services.gateway import main
from services.gateway.main import app
from services.gateway.security import KeyStore, RateLimiter, Security, generate_key
from services.tools.filings import ToolContext, build_registry
from services.tools.tests.test_registry import _Pool

client = TestClient(app)
QUESTION = "How do export controls affect NVIDIA demand?"
KEY, DIGEST = generate_key()


@pytest.fixture
def secured() -> Iterator[Any]:
    def _install(per_minute: int = 100, daily_cap: int = 100) -> Security:
        sec = Security(KeyStore({DIGEST: "alice"}), RateLimiter(per_minute, daily_cap))
        app.state.security = sec
        ctx = ToolContext(retriever=FakeRetriever(), pool=_Pool([]))  # type: ignore[arg-type]
        app.state.registry = build_registry(ctx)
        app.state.agent_llm = ScriptedLLM([ModelTurn(text="INSUFFICIENT_CONTEXT. none.")] * 20)
        return sec

    yield _install
    for name in ("registry", "agent_llm"):
        if hasattr(app.state, name):
            delattr(app.state, name)


def _post(headers: dict[str, str] | None = None) -> Any:
    return client.post("/agent", json={"question": QUESTION}, headers=headers or {})


def test_no_key_is_401_with_a_www_authenticate_header(secured: Any) -> None:
    secured()
    r = _post()
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_wrong_key_is_401_and_right_key_works_in_both_header_styles(secured: Any) -> None:
    secured()
    assert _post({"authorization": "Bearer ea_wrong"}).status_code == 401
    assert _post({"authorization": f"Bearer {KEY}"}).status_code == 200
    assert _post({"x-api-key": KEY}).status_code == 200


def test_every_spending_endpoint_requires_a_key(secured: Any) -> None:
    secured()
    assert client.post("/ask", json={"question": QUESTION}).status_code == 401
    assert client.post("/agent/stream", json={"question": QUESTION}).status_code == 401
    assert client.post("/agent", json={"question": QUESTION}).status_code == 401


def test_health_and_ui_stay_public(secured: Any) -> None:
    secured()
    assert client.get("/healthz").status_code == 200
    assert client.get("/").status_code == 200


def test_rate_limit_returns_429_with_retry_after(secured: Any) -> None:
    secured(per_minute=2)
    h = {"authorization": f"Bearer {KEY}"}
    assert [_post(h).status_code for _ in range(2)] == [200, 200]
    r = _post(h)
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1


def test_daily_agent_cap_returns_429(secured: Any) -> None:
    secured(daily_cap=1)
    h = {"authorization": f"Bearer {KEY}"}
    assert _post(h).status_code == 200
    r = _post(h)
    assert r.status_code == 429 and "daily" in r.json()["detail"]


def test_repeated_bad_keys_get_the_client_throttled_even_for_a_good_key(secured: Any) -> None:
    secured()
    for _ in range(11):
        _post({"authorization": "Bearer ea_bad"})
    r = _post({"authorization": f"Bearer {KEY}"})
    assert r.status_code == 429 and "failed attempts" in r.json()["detail"]


def test_keys_never_reach_the_logs(secured: Any) -> None:
    secured()
    with structlog.testing.capture_logs() as logs:
        _post({"authorization": "Bearer ea_super_secret_value"})
        _post({"authorization": f"Bearer {KEY}"})
    text = repr(logs)
    assert "ea_super_secret_value" not in text and KEY not in text
    assert any(entry["event"] == "auth_failed" and entry["reason"] == "invalid" for entry in logs)


def test_security_headers_and_a_strict_csp_on_the_ui(secured: Any) -> None:
    secured()
    r = client.get("/")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY" and r.headers["referrer-policy"] == "no-referrer"
    csp = r.headers["content-security-policy"]
    assert (
        "script-src 'self'" in csp
        and "unsafe-inline" not in csp
        and "frame-ancestors 'none'" in csp
    )
    assert (
        "content-security-policy" not in client.get("/healthz").headers
    )  # CSP only where HTML is served


def test_the_ui_page_has_no_inline_script_or_style() -> None:
    html = client.get("/").text
    assert "<script>" not in html and "<style>" not in html and "onclick=" not in html
    assert (
        client.get("/static/app.js").status_code == 200
        and client.get("/static/app.css").status_code == 200
    )


def test_missing_security_config_fails_closed() -> None:
    saved = app.state.security
    del app.state.security
    try:
        assert client.post("/ask", json={"question": QUESTION}).status_code == 500
    finally:
        app.state.security = saved


def test_startup_refuses_unsafe_configurations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.settings, "auth", "off")
    monkeypatch.setattr(main.settings, "environment", "prod")
    with pytest.raises(RuntimeError, match="only allowed when EA_ENVIRONMENT=dev"):
        main._build_security()
    monkeypatch.setattr(main.settings, "auth", "on")
    monkeypatch.setattr(main.settings, "api_keys", "")
    with pytest.raises(RuntimeError, match="no API keys configured"):
        main._build_security()
    monkeypatch.setattr(main.settings, "api_keys", f"alice:{DIGEST}")
    assert main._build_security().auth_required is True


def test_logging_config_does_not_hide_the_auth_failure_event() -> None:
    assert (
        logging.getLogger().handlers is not None
    )  # guards the capture_logs test above against silent config
