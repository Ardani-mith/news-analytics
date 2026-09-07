from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Literal


@dataclass(frozen=True)
class Article:
    source_url: str
    title: str
    body: str = ""
    published_at: str | None = None
    tickers: tuple[str, ...] = ()
    attachment_urls: tuple[str, ...] = ()
    source: str = "IDX"

    def key(self) -> str:
        return f"{self.source_url}|{self.title}".lower().strip()


@dataclass(frozen=True)
class NewsScore:
    sentiment: int
    materiality: int
    event_type: Literal["earnings", "contract", "corporate_action", "legal", "regulation", "governance", "operational", "other"]
    horizon: Literal["immediate", "short_term", "long_term"]
    confidence: float
    rationale: str
    evidence: tuple[str, ...]
    provider: str
    model: str | None = None

    def to_dict(self) -> dict:
        result = asdict(self)
        result["evidence"] = list(self.evidence)
        return result


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
