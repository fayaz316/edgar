"""Liveness/readiness contract. No DB: readiness is tested with fake pools."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from services.gateway.main import app

client = TestClient(app)  # no `with` -> lifespan (and its DB requirement) is skipped


class _Conn:
    def __init__(self, fail: bool) -> None:
        self._fail = fail

    def execute(self, sql: str) -> None:
        if self._fail:
            raise psycopg.OperationalError("connection refused")


class _Pool:
    def __init__(self, fail: bool = False) -> None:
        self._fail = fail

    @contextmanager
    def connection(self) -> Iterator[_Conn]:
        yield _Conn(self._fail)


@pytest.fixture(autouse=True)
def _reset_pool() -> Iterator[None]:
    yield
    if hasattr(app.state, "pool"):
        del app.state.pool


def _set_pool(pool: Any) -> None:
    app.state.pool = pool


def test_healthz() -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readyz_ready_when_db_answers() -> None:
    _set_pool(_Pool())
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_readyz_503_when_db_down() -> None:
    _set_pool(_Pool(fail=True))
    r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json()["reason"] == "database unavailable"


def test_readyz_503_before_startup() -> None:
    assert client.get("/readyz").status_code == 503


def test_healthz_never_checks_dependencies() -> None:
    _set_pool(_Pool(fail=True))
    assert client.get("/healthz").status_code == 200


def test_request_id_echoed() -> None:
    r = client.get("/healthz", headers={"x-request-id": "test-123"})
    assert r.headers["x-request-id"] == "test-123"
