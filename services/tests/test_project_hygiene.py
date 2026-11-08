"""Guards against silent project rot: things that broke quietly during development."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_every_tests_folder_is_collected_by_pytest() -> None:
    """A test folder missing from `testpaths` is silently skipped: new tests 'pass' by never running."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    collected = set(config["tool"]["pytest"]["ini_options"]["testpaths"])
    on_disk = {
        str(p.relative_to(ROOT))
        for base in ("services", "evals")
        for p in (ROOT / base).rglob("tests")
        if p.is_dir() and any(p.glob("test_*.py"))
    }
    assert on_disk == collected, f"tests on disk but not collected: {sorted(on_disk - collected)}"


def test_mypy_covers_every_service_package() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    typed = set(config["tool"]["mypy"]["files"])
    packages = {
        f"services/{p.name}"
        for p in (ROOT / "services").iterdir()
        if p.is_dir() and (p / "__init__.py").exists() and p.name not in {"web", "tests"}
    }
    assert packages <= typed, f"packages not type-checked: {sorted(packages - typed)}"


def test_dockerfile_copies_every_module_the_gateway_imports() -> None:
    dockerfile = (ROOT / "services/gateway/Dockerfile").read_text()
    for needed in (
        "services/embeddings.py",
        "services/genai_client.py",
        "services/db.py",
        "services/agent",
        "services/tools",
    ):
        assert needed in dockerfile, f"Dockerfile does not copy {needed}"
