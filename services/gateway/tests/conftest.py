"""Gateway tests run with auth switched OFF unless a test installs real security (see test_auth_api.py).

The gateway itself fails closed when `app.state.security` is missing; this fixture is the explicit, test-only opt-out.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from services.gateway.main import app
from services.gateway.security import Security


@pytest.fixture(autouse=True)
def _open_security() -> Iterator[None]:
    app.state.security = Security.open()
    yield
    app.state.security = Security.open()
