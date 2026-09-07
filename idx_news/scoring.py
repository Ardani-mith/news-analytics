from __future__ import annotations

import json
import os
from typing import Protocol

import httpx

from .models import Article, NewsScore


class Scorer(Protocol):
    def score(self, article: Article) -> NewsScore: ...


class RuleScorer:
    """A reproducible baseline; a useful comparator for any LLM implementation."""

    RULES = (
        ("legal", ("pkpu", "pailit", "gugatan", "sanksi", "suspensi", "fraud", "penyelidikan"), -55, 85, "immediate"),
        ("earnings", ("laporan keuangan", "laba", "pendapatan", "dividen"), 10, 70, "short_term"),
        ("corporate_action", ("rights issue", "hm et d", "hmetd", "stock split", "buyback", "saham tambahan", "konversi"), 0, 80, "short_term"),
        ("contract", ("kontrak", "kerja sama", "akuisisi", "merger", "pengambilalihan"), 25, 75, "long_term"),
        ("governance", ("rupst", "rups", "direksi", "komisaris", "audit"), 0, 50, "short_term"),
        ("operational", ("produksi", "operasional", "ekspansi", "pabrik"), 10, 60, "long_term"),
    )
    POSITIVE = ("meningkat", "laba", "dividen", "kontrak", "ekspansi", "persetujuan")
    NEGATIVE = ("rugi", "turun", "sanksi", "suspensi", "gugatan", "pkpu", "pailit")

    def score(self, article: Article) -> NewsScore:
        text = f"{article.title} {article.body}".lower()
        event_type, keywords, base_sentiment, materiality, horizon = "other", (), 0, 30, "short_term"
        for candidate, candidate_keywords, candidate_sentiment, candidate_materiality, candidate_horizon in self.RULES:
            if any(keyword in text for keyword in candidate_keywords):
                event_type, keywords, base_sentiment, materiality, horizon = candidate, candidate_keywords, candidate_sentiment, candidate_materiality, candidate_horizon
                break
        positive_hits = sum(word in text for word in self.POSITIVE)
        negative_hits = sum(word in text for word in self.NEGATIVE)
        sentiment = max(-100, min(100, base_sentiment + 15 * (positive_hits - negative_hits)))
        evidence = tuple(word for word in keywords if word in text)[:3] or ("No specific event keyword matched",)
        return NewsScore(
            sentiment=sentiment,
            materiality=materiality,
            event_type=event_type,  # type: ignore[arg-type]
            horizon=horizon,  # type: ignore[arg-type]
            confidence=0.72 if event_type != "other" else 0.35,
            rationale=f"Rules baseline classified the announcement as {event_type}; review the source document before use.",
            evidence=evidence,
            provider="rules",
        )


class DeepSeekScorer:
    """DeepSeek Chat Completions scorer using JSON Output mode."""

    def __init__(self, model: str | None = None) -> None:
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is required for `score --provider deepseek`.")
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")

    def score(self, article: Article) -> NewsScore:
        system_prompt = """You classify public IDX announcements for research. Do not issue a buy, sell, or price prediction.
Use only the supplied article. Materiality means likely importance to a reasonable investor, not expected return.
Output valid JSON only, using exactly this shape:
{"sentiment": 0, "materiality": 0, "event_type": "other", "horizon": "short_term", "confidence": 0.0, "rationale": "", "evidence": [""]}
Rules: sentiment is an integer from -100 to 100; materiality is an integer from 0 to 100; confidence is 0 to 1.
event_type must be one of earnings, contract, corporate_action, legal, regulation, governance, operational, other.
horizon must be one of immediate, short_term, long_term. Evidence must contain at most 3 short, source-grounded points."""
        response = httpx.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": self._article_prompt(article)},
                ],
                "response_format": {"type": "json_object"},
                "thinking": {"type": "disabled"},
                "temperature": 0.1,
                "max_tokens": 600,
            },
            timeout=45,
        )
        response.raise_for_status()
        body = response.json()
        try:
            content = body["choices"][0]["message"]["content"]
            payload = json.loads(content)
            return self._to_score(payload)
        except (IndexError, KeyError, TypeError, json.JSONDecodeError, ValueError) as error:
            raise RuntimeError("DeepSeek returned an invalid news-score JSON response.") from error

    def _to_score(self, payload: dict) -> NewsScore:
        event_type = str(payload["event_type"])
        horizon = str(payload["horizon"])
        allowed_event_types = {"earnings", "contract", "corporate_action", "legal", "regulation", "governance", "operational", "other"}
        allowed_horizons = {"immediate", "short_term", "long_term"}
        sentiment, materiality, confidence = int(payload["sentiment"]), int(payload["materiality"]), float(payload["confidence"])
        if event_type not in allowed_event_types or horizon not in allowed_horizons:
            raise ValueError("DeepSeek returned an unknown event type or horizon.")
        if not -100 <= sentiment <= 100 or not 0 <= materiality <= 100 or not 0 <= confidence <= 1:
            raise ValueError("DeepSeek returned values outside the scoring rubric.")
        evidence = payload["evidence"]
        if not isinstance(evidence, list) or len(evidence) > 3:
            raise ValueError("DeepSeek evidence must be a list with at most 3 items.")
        return NewsScore(
            sentiment=sentiment,
            materiality=materiality,
            event_type=event_type,  # type: ignore[arg-type]
            horizon=horizon,  # type: ignore[arg-type]
            confidence=confidence,
            rationale=str(payload["rationale"]),
            evidence=tuple(str(item) for item in evidence),
            provider="deepseek",
            model=self.model,
        )

    @staticmethod
    def _article_prompt(article: Article) -> str:
        return f"TITLE: {article.title}\nTICKERS: {', '.join(article.tickers) or 'unknown'}\nTEXT: {article.body[:7000]}"


def article_from_row(row: dict) -> Article:
    return Article(
        source_url=row["source_url"], title=row["title"], body=row["body"],
        published_at=row["published_at"], tickers=tuple(filter(None, row["tickers"].split(","))), source=row["source"],
    )
