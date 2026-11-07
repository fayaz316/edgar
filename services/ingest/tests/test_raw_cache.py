"""Raw-HTML cache: round-trip, cache-first fetch, offline iteration. No network, no DB."""

from __future__ import annotations

from pathlib import Path

from services.ingest import raw_cache
from services.ingest.edgar_client import Filing


def _filing(acc: str = "0001045810-26-000075", ticker: str = "NVDA") -> Filing:
    return Filing(
        cik="0001045810",
        ticker=ticker,
        accession=acc,
        form="10-Q",
        filed_at="2026-08-26",
        period_end="2026-07-26",
        primary_doc="nvda-20260726.htm",
    )


class _FakeClient:
    def __init__(self) -> None:
        self.downloads = 0

    def filing_document(self, filing: Filing) -> str:
        self.downloads += 1
        return f"<html>{filing.accession}</html>"


def test_round_trip(tmp_path: Path) -> None:
    f = _filing()
    assert raw_cache.load(f, tmp_path) is None
    raw_cache.save(f, "<html>hi</html>", tmp_path)
    assert raw_cache.load(f, tmp_path) == "<html>hi</html>"


def test_get_html_is_cache_first(tmp_path: Path) -> None:
    client = _FakeClient()
    f = _filing()
    first = raw_cache.get_html(client, f, root=tmp_path)  # type: ignore[arg-type]
    second = raw_cache.get_html(client, f, root=tmp_path)  # type: ignore[arg-type]
    assert first == second
    assert client.downloads == 1
    raw_cache.get_html(client, f, refresh=True, root=tmp_path)  # type: ignore[arg-type]
    assert client.downloads == 2


def test_iter_cached_filters_by_ticker_and_restores_metadata(tmp_path: Path) -> None:
    raw_cache.save(_filing("0001045810-26-000075", "NVDA"), "<html>a</html>", tmp_path)
    raw_cache.save(_filing("0000320193-26-000026", "AAPL"), "<html>b</html>", tmp_path)
    everything = list(raw_cache.iter_cached(root=tmp_path))
    assert {f.ticker for f, _ in everything} == {"NVDA", "AAPL"}
    only_aapl = list(raw_cache.iter_cached(["aapl"], root=tmp_path))
    assert [f.accession for f, _ in only_aapl] == ["0000320193-26-000026"]
    assert only_aapl[0][0].document_url.endswith("nvda-20260726.htm")  # metadata round-tripped
