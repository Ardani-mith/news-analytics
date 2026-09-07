from __future__ import annotations

import time
from datetime import date
from typing import Any

from curl_cffi import requests

from .models import Article

IDX_ANNOUNCEMENT_API = "https://www.idx.co.id/primary/ListedCompany/GetAnnouncement"
IDX_DISCLOSURE_PAGE = "https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi/"


class IDXAnnouncementScraper:
    """Client for IDX's public Keterbukaan Informasi JSON listing endpoint using curl_cffi."""

    def __init__(
        self,
        url: str = IDX_ANNOUNCEMENT_API,
        request_delay_seconds: float = 1.0,
        transport: str = "curl_cffi",
    ) -> None:
        self.url = url
        self.request_delay_seconds = request_delay_seconds
        self.transport = transport

    def fetch(
        self,
        *,
        keyword: str = "",
        ticker: str = "",
        date_from: str = "19010101",
        date_to: str | None = None,
        page_size: int = 100,
        max_pages: int = 1,
    ) -> list[Article]:
        """Fetch at most ``max_pages`` pages, using IDX's zero-based offset."""
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100")
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")

        date_to = date_to or date.today().strftime("%Y%m%d")

        articles: list[Article] = []
        seen: set[str] = set()

        # Menggunakan Session dari curl_cffi dengan impersonasi Chrome
        with requests.Session(impersonate="chrome120") as session:
            # Lakukan request awal ke halaman Keterbukaan Informasi untuk mendapatkan cookie/session jika ada
            try:
                session.get(IDX_DISCLOSURE_PAGE, timeout=10)
            except Exception:
                pass

            for page in range(max_pages):
                payload = self._get_page_curl(session, keyword, ticker, date_from, date_to, page * page_size, page_size)
                page_articles = self._add_unique_articles(articles, seen, payload)
                if len(page_articles) < page_size:
                    break
                if page < max_pages - 1:
                    time.sleep(self.request_delay_seconds)

        return articles

    def _get_page_curl(
        self,
        session: requests.Session,
        keyword: str,
        ticker: str,
        date_from: str,
        date_to: str,
        index_from: int,
        page_size: int,
    ) -> dict[str, Any]:
        params = self._params(keyword, ticker, date_from, date_to, index_from, page_size)
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": IDX_DISCLOSURE_PAGE,
            "Origin": "https://www.idx.co.id",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        response = session.get(
            self.url,
            params=params,
            headers=headers,
            timeout=20,
        )
        return self._decode_response(response.status_code, response.text)

    @staticmethod
    def _params(
        keyword: str,
        ticker: str,
        date_from: str,
        date_to: str,
        index_from: int,
        page_size: int,
    ) -> dict[str, str | int]:
        return {
            "kodeEmiten": ticker.strip().upper(),
            "emitenType": "*",
            "indexFrom": index_from,
            "pageSize": page_size,
            "dateFrom": date_from,
            "dateTo": date_to,
            "lang": "id",
            "keyword": keyword,
        }

    @staticmethod
    def _decode_response(status: int, text: str) -> dict[str, Any]:
        if status == 403:
            raise PermissionError(
                "IDX returned HTTP 403. Check your TLS configuration or headers."
            )
        if status < 200 or status >= 300:
            raise RuntimeError(f"IDX returned HTTP {status}")
        import json
        payload = json.loads(text)
        if not isinstance(payload, dict) or not isinstance(payload.get("Replies", []), list):
            raise ValueError("Unexpected IDX announcement API response: expected a Replies list")
        return payload

    def _add_unique_articles(self, articles: list[Article], seen: set[str], payload: dict[str, Any]) -> list[Article]:
        page_articles = self.parse(payload)
        for article in page_articles:
            if article.key() not in seen:
                seen.add(article.key())
                articles.append(article)
        return page_articles

    def parse(self, payload: dict[str, Any]) -> list[Article]:
        """Map IDX API records to the internal, model-ready article shape."""
        articles: list[Article] = []
        for reply in payload.get("Replies", []):
            if not isinstance(reply, dict):
                continue
            announcement = reply.get("pengumuman") or {}
            if not isinstance(announcement, dict):
                continue
            title = str(announcement.get("JudulPengumuman") or "").strip()
            announcement_id = str(announcement.get("Id2") or announcement.get("NoPengumuman") or "").strip()
            if not title or not announcement_id:
                continue
            attachments = reply.get("attachments") or []
            primary_url, attachment_names = self._attachment_details(attachments)
            source_url = primary_url or f"{self.url}#announcement={announcement_id}"
            ticker = str(announcement.get("Kode_Emiten") or "").strip().upper()
            subject = str(announcement.get("PerihalPengumuman") or "").strip()
            announcement_type = str(announcement.get("JenisPengumuman") or "").strip()
            body_parts = [part for part in (
                subject,
                f"Announcement number: {announcement.get('NoPengumuman', '')}".strip(),
                f"Announcement type: {announcement_type}" if announcement_type else "",
                f"Attachments: {', '.join(attachment_names)}" if attachment_names else "",
            ) if part]
            articles.append(Article(
                source_url=source_url,
                title=title,
                body="\n".join(body_parts),
                published_at=str(announcement.get("TglPengumuman") or "").strip() or None,
                tickers=(ticker,) if ticker else (),
            ))
        return articles

    @staticmethod
    def _attachment_details(attachments: Any) -> tuple[str | None, list[str]]:
        if not isinstance(attachments, list):
            return None, []
        valid = [attachment for attachment in attachments if isinstance(attachment, dict)]
        primary = next((item for item in valid if not item.get("IsAttachment")), valid[0] if valid else None)
        primary_url = str(primary.get("FullSavePath") or "").strip() if primary else None
        names = [str(item.get("OriginalFilename") or item.get("PDFFilename") or "").strip() for item in valid]
        return primary_url or None, [name for name in names if name]