"""SEC EDGAR client — polite, typed, retrying.

SEC rules of the road (https://www.sec.gov/os/accessing-edgar-data):
  * a descriptive User-Agent identifying you (name + email), and
  * max 10 requests/second.
We go politer (0.15s floor between calls) and retry with backoff on
403/429/5xx — the rate-limit dance that any partner-API integration teaches.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

BASE_URL = "https://data.sec.gov"          # JSON APIs (submissions, xbrl)
ARCHIVE_URL = "https://www.sec.gov"        # filing documents (/Archives/...)
DEFAULT_USER_AGENT = "edgar-analyst dev (contact: you@example.com)"
THROTTLE_SECONDS = 0.15


class EdgarError(RuntimeError):
    pass


@dataclass(frozen=True)
class Filing:
    cik: str
    ticker: str
    accession: str  # e.g. 0001045810-25-000023
    form: str  # 10-K | 10-Q | 8-K
    filed_at: str  # ISO date
    period_end: str | None
    primary_doc: str  # filename within the accession folder

    @property
    def accession_dashes(self) -> str:
        return self.accession.replace("-", "")

    @property
    def document_url(self) -> str:
        return (
            f"{ARCHIVE_URL}/Archives/edgar/data/{int(self.cik)}/"
            f"{self.accession_dashes}/{self.primary_doc}"
        )


class EdgarClient:
    def __init__(self, user_agent: str = DEFAULT_USER_AGENT) -> None:
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={"User-Agent": user_agent},
            timeout=30.0,
            follow_redirects=True,
        )
        self._last_request = 0.0
        self._cik_map: dict[str, str] | None = None

    def _throttle(self) -> None:
        wait = THROTTLE_SECONDS - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _get(self, url: str) -> httpx.Response:
        last_error: EdgarError | None = None
        for attempt in range(3):
            self._throttle()
            resp = self._client.get(url)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (403, 429) or resp.status_code >= 500:
                last_error = EdgarError(f"GET {url} -> {resp.status_code} (attempt {attempt + 1})")
                time.sleep(2.0**attempt)
                continue
            raise EdgarError(f"GET {url} -> {resp.status_code}: {resp.text[:200]}")
        raise last_error if last_error else EdgarError(f"GET {url} failed")

    def _ticker_map(self) -> dict[str, str]:
        """ticker -> zero-padded CIK, from SEC's canonical mapping file (cached)."""
        if self._cik_map is None:
            resp = self._get("https://www.sec.gov/files/company_tickers.json")
            self._cik_map = {
                entry["ticker"].upper(): str(entry["cik_str"]).zfill(10)
                for entry in resp.json().values()
            }
        return self._cik_map

    def cik_for_ticker(self, ticker: str) -> str:
        cik = self._ticker_map().get(ticker.upper())
        if not cik:
            raise EdgarError(f"unknown ticker: {ticker}")
        return cik

    def recent_filings(
        self, ticker: str, forms: frozenset[str], limit_per_form: int = 2
    ) -> list[Filing]:
        """Most recent filings per form type for a ticker."""
        cik = self.cik_for_ticker(ticker)
        resp = self._get(f"/submissions/CIK{cik}.json")
        data = resp.json()
        recent = data.get("filings", {}).get("recent", {})

        picked: dict[str, int] = {}
        filings: list[Filing] = []
        for acc, form, filed, period, doc in zip(
            recent["accessionNumber"],
            recent["form"],
            recent["filingDate"],
            recent["reportDate"],
            recent["primaryDocument"],
            strict=False,
        ):
            if form not in forms or not doc.lower().endswith((".htm", ".html")):
                continue
            if picked.get(form, 0) >= limit_per_form:
                continue
            picked[form] = picked.get(form, 0) + 1
            filings.append(
                Filing(
                    cik=cik,
                    ticker=ticker.upper(),
                    accession=acc,
                    form=form,
                    filed_at=filed,
                    period_end=period or None,
                    primary_doc=doc,
                )
            )
        return filings

    def filing_document(self, filing: Filing) -> str:
        """Raw HTML of the filing's primary document."""
        return self._get(filing.document_url.removeprefix(BASE_URL)).text

    def close(self) -> None:
        self._client.close()
