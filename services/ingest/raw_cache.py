"""On-disk cache of raw filing HTML + metadata (data/raw/<TICKER>/<accession>.{htm,json}).

Why: the SEC is the slowest, politest-rate-limited dependency we have. Parser and
chunking changes are the most frequent thing we iterate on. Caching the raw HTML makes
that loop offline, instant and reproducible (same bytes in, same chunks out), and it
means a re-ingest never re-downloads. data/ is gitignored — it is a cache, not source.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path

from services.ingest.edgar_client import EdgarClient, Filing

RAW_DIR = Path("data/raw")


def _paths(filing: Filing, root: Path = RAW_DIR) -> tuple[Path, Path]:
    base = root / filing.ticker / filing.accession
    return base.with_suffix(".htm"), base.with_suffix(".json")


def save(filing: Filing, html: str, root: Path = RAW_DIR) -> Path:
    html_path, meta_path = _paths(filing, root)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")
    meta_path.write_text(json.dumps(asdict(filing), indent=2), encoding="utf-8")
    return html_path


def load(filing: Filing, root: Path = RAW_DIR) -> str | None:
    html_path, _ = _paths(filing, root)
    return html_path.read_text(encoding="utf-8") if html_path.exists() else None


def get_html(
    client: EdgarClient, filing: Filing, *, refresh: bool = False, root: Path = RAW_DIR
) -> str:
    """Cache-first fetch. refresh=True re-downloads and overwrites."""
    if not refresh:
        cached = load(filing, root)
        if cached is not None:
            return cached
    html = client.filing_document(filing)
    save(filing, html, root)
    return html


def iter_cached(
    tickers: list[str] | None = None, root: Path = RAW_DIR
) -> Iterator[tuple[Filing, str]]:
    """Every cached filing (optionally for some tickers), newest first per ticker.
    Fully offline: metadata comes from the sidecar JSON, not the SEC."""
    wanted = {t.upper() for t in tickers} if tickers else None
    for meta_path in sorted(root.glob("*/*.json"), reverse=True):
        filing = Filing(**json.loads(meta_path.read_text(encoding="utf-8")))
        if wanted and filing.ticker not in wanted:
            continue
        html = load(filing, root)
        if html is not None:
            yield filing, html
