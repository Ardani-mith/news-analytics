from __future__ import annotations

import io
import os
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from pypdf import PdfReader


@dataclass(frozen=True)
class PDFText:
    text: str
    page_count: int


class IDXPDFTextExtractor:
    """Extract bounded text from an official IDX PDF without retaining the file."""

    ALLOWED_HOSTS = {"www.idx.co.id", "idx.co.id"}

    def __init__(self, max_bytes: int | None = None, max_pages: int | None = None, max_chars: int | None = None) -> None:
        self.max_bytes = max_bytes or int(os.getenv("PDF_MAX_BYTES", "15728640"))
        self.max_pages = max_pages or int(os.getenv("PDF_MAX_PAGES", "20"))
        self.max_chars = max_chars or int(os.getenv("PDF_MAX_CHARS", "30000"))

    def extract(self, url: str) -> PDFText:
        self._validate_url(url)
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/pdf,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi/",
        }

        # 1. Coba menggunakan curl_cffi terlebih dahulu
        try:
            from curl_cffi import requests
            response = requests.get(
                url,
                headers=headers,
                impersonate="chrome120",
                timeout=30,
                stream=True,
            )
            if response.status_code == 200:
                content = self._read_bounded_curl(response)
                if content.startswith(b"%PDF"):
                    return self.extract_bytes(content)
        except Exception:
            pass  # Jika libcurl gagal karena DNS error, lewati ke fallback httpx

        # 2. Fallback menggunakan httpx dengan Header Spoofing Browser Lengkap
        with httpx.stream("GET", url, headers=headers, timeout=30, follow_redirects=True) as response:
            response.raise_for_status()
            content = self._read_bounded(response)

        if not content.startswith(b"%PDF"):
            raise ValueError("IDX response was not a PDF document.")

        return self.extract_bytes(content)

    def extract_bytes(self, content: bytes) -> PDFText:
        try:
            reader = PdfReader(io.BytesIO(content), strict=False)
            page_count = len(reader.pages)
            pages = [page.extract_text() or "" for page in reader.pages[:self.max_pages]]
        except Exception as error:
            raise ValueError(f"PDF text extraction failed: {error}") from error
        text = "\n\n".join(pages).strip()
        if not text:
            raise ValueError("PDF contains no extractable text; OCR is required.")
        return PDFText(text=text[:self.max_chars], page_count=page_count)

    def _read_bounded(self, response: httpx.Response) -> bytes:
        declared_length = response.headers.get("content-length")
        if declared_length and int(declared_length) > self.max_bytes:
            raise ValueError(f"PDF exceeds the {self.max_bytes:,}-byte download limit.")
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > self.max_bytes:
                raise ValueError(f"PDF exceeds the {self.max_bytes:,}-byte download limit.")
            chunks.append(chunk)
        return b"".join(chunks)

    def _read_bounded_curl(self, response: Any) -> bytes:
        declared_length = response.headers.get("content-length")
        if declared_length and int(declared_length) > self.max_bytes:
            raise ValueError(f"PDF exceeds the {self.max_bytes:,}-byte download limit.")
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=8192):
            total += len(chunk)
            if total > self.max_bytes:
                raise ValueError(f"PDF exceeds the {self.max_bytes:,}-byte download limit.")
            chunks.append(chunk)
        return b"".join(chunks)

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in self.ALLOWED_HOSTS or not parsed.path.lower().endswith(".pdf"):
            raise ValueError("PDF URL must be an HTTPS document hosted on idx.co.id.")