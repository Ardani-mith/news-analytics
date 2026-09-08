"""Small, bounded client for IDX's public stock-summary JSON endpoint."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from curl_cffi import requests

IDX_STOCK_SUMMARY_API = "https://www.idx.co.id/primary/TradingSummary/GetStockSummary"
IDX_STOCK_SUMMARY_PAGE = "https://www.idx.co.id/id/data-pasar/ringkasan-perdagangan/ringkasan-saham"


@dataclass(frozen=True, slots=True)
class StockSummary:
    """One regular-market row returned by IDX."""

    date: str
    ticker: str
    name: str
    previous: float | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    change: float | None
    volume: float | None
    value: float | None
    frequency: float | None
    offer: float | None
    offer_volume: float | None
    bid: float | None
    bid_volume: float | None
    foreign_buy: float | None
    foreign_sell: float | None

    @classmethod
    def from_idx(cls, row: Mapping[str, Any]) -> "StockSummary":
        ticker = str(row.get("StockCode") or "").strip().upper()
        if not ticker:
            raise ValueError("IDX stock-summary row is missing StockCode")
        return cls(
            date=str(row.get("Date") or "").strip(),
            ticker=ticker,
            name=str(row.get("StockName") or "").strip(),
            previous=_number(row.get("Previous")),
            open=_number(row.get("OpenPrice")),
            high=_number(row.get("High")),
            low=_number(row.get("Low")),
            close=_number(row.get("Close")),
            change=_number(row.get("Change")),
            volume=_number(row.get("Volume")),
            value=_number(row.get("Value")),
            frequency=_number(row.get("Frequency")),
            offer=_number(row.get("Offer")),
            offer_volume=_number(row.get("OfferVolume")),
            bid=_number(row.get("Bid")),
            bid_volume=_number(row.get("BidVolume")),
            foreign_buy=_number(row.get("ForeignBuy")),
            foreign_sell=_number(row.get("ForeignSell")),
        )

    def to_dict(self) -> dict[str, str | float | None]:
        return asdict(self)


class IDXStockSummaryClient:
    """Fetch the daily stock summary using curl_cffi for TLS impersonation."""

    def __init__(self, url: str = IDX_STOCK_SUMMARY_API, *, timeout_seconds: float = 30.0) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds

    def fetch(self, *, length: int = 9999, start: int = 0) -> list[StockSummary]:
        if not 1 <= length <= 9999:
            raise ValueError("length must be between 1 and 9999")
        if start < 0:
            raise ValueError("start cannot be negative")

        # Menggunakan impersonate chrome124/120
        with requests.Session(impersonate="chrome120") as session:
            headers = _headers()
            
            # Step 1: Lakukan warmup request ke halaman UI resmi agar Cloudflare menetapkan cookie/session
            try:
                session.get(IDX_STOCK_SUMMARY_PAGE, headers=headers, timeout=15)
            except Exception:
                pass

            # Step 2: Lakukan request API utama
            params = {
                "length": length,
                "start": start,
            }

            response = session.get(
                self.url,
                params=params,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            
            _raise_for_idx_error(response.status_code)
            payload = response.json()

        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("Unexpected IDX stock-summary response: expected an object with a data list")
            
        return [StockSummary.from_idx(row) for row in payload["data"] if isinstance(row, dict)]


def _headers() -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": IDX_STOCK_SUMMARY_PAGE,
        "Origin": "https://www.idx.co.id",
        "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }


def _raise_for_idx_error(status_code: int) -> None:
    if status_code == 403:
        raise PermissionError("IDX returned HTTP 403. Check TLS fingerprint / headers configuration.")
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(f"IDX returned HTTP status code: {status_code}")


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"IDX returned a non-numeric value: {value!r}") from error