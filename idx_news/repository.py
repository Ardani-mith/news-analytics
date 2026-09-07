from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

from .models import Article, NewsScore, utc_now


class NewsRepository:
    def __init__(self, database_path: str = "data/idx_news.db") -> None:
        path = Path(database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self._migrate()

    @classmethod
    def from_environment(cls) -> "NewsRepository":
        load_dotenv()
        return cls(os.getenv("IDX_NEWS_DB", "data/idx_news.db"))

    def _migrate(self) -> None:
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY,
                source_url TEXT NOT NULL,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                published_at TEXT,
                tickers TEXT NOT NULL DEFAULT '',
                attachment_urls TEXT NOT NULL DEFAULT '[]',
                article_key TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY,
                article_id INTEGER NOT NULL REFERENCES articles(id),
                provider TEXT NOT NULL,
                model TEXT,
                sentiment INTEGER NOT NULL,
                materiality INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                horizon TEXT NOT NULL,
                confidence REAL NOT NULL,
                rationale TEXT NOT NULL,
                evidence TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_scores_article_created ON scores(article_id, created_at DESC);
        """)
        self._add_column_if_missing("articles", "pdf_text", "TEXT NOT NULL DEFAULT ''")
        self._add_column_if_missing("articles", "pdf_extracted_at", "TEXT")
        self._add_column_if_missing("articles", "pdf_extraction_error", "TEXT")
        self._add_column_if_missing("articles", "attachment_urls", "TEXT NOT NULL DEFAULT '[]'")
        self.connection.commit()

    def _add_column_if_missing(self, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in self.connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            self.connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def upsert_article(self, article: Article) -> int:
        self.connection.execute("""
            INSERT INTO articles (source_url, source, title, body, published_at, tickers, attachment_urls, article_key, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(article_key) DO UPDATE SET
                body=excluded.body, published_at=COALESCE(excluded.published_at, articles.published_at),
                tickers=excluded.tickers,
                pdf_text=CASE WHEN articles.attachment_urls <> excluded.attachment_urls THEN '' ELSE articles.pdf_text END,
                pdf_extracted_at=CASE WHEN articles.attachment_urls <> excluded.attachment_urls THEN NULL ELSE articles.pdf_extracted_at END,
                pdf_extraction_error=CASE WHEN articles.attachment_urls <> excluded.attachment_urls THEN NULL ELSE articles.pdf_extraction_error END,
                attachment_urls=excluded.attachment_urls
        """, (article.source_url, article.source, article.title, article.body, article.published_at,
              ",".join(article.tickers), json.dumps(article.attachment_urls), article.key(), utc_now()))
        row = self.connection.execute("SELECT id FROM articles WHERE article_key = ?", (article.key(),)).fetchone()
        self.connection.commit()
        return int(row["id"])

    def unscored_articles(self) -> list[dict]:
        return [dict(row) for row in self.connection.execute("""
            SELECT a.* FROM articles a
            WHERE NOT EXISTS (SELECT 1 FROM scores s WHERE s.article_id = a.id)
            ORDER BY a.published_at DESC, a.id DESC
        """)]

    def articles_for_deepseek(self, min_materiality: int, limit: int) -> list[dict]:
        """Return high-materiality rules scores missing AI analysis or with newer PDF text."""
        query = """
            SELECT a.*
            FROM articles a
            JOIN scores rules_score ON rules_score.id = (
                SELECT id FROM scores
                WHERE article_id = a.id AND provider = 'rules'
                ORDER BY created_at DESC, id DESC LIMIT 1
            )
            WHERE rules_score.materiality >= ?
              AND (
                  NOT EXISTS (
                      SELECT 1 FROM scores deepseek_score
                      WHERE deepseek_score.article_id = a.id AND deepseek_score.provider = 'deepseek'
                  )
                  OR (
                      a.pdf_extracted_at IS NOT NULL
                      AND COALESCE((
                          SELECT MAX(deepseek_score.created_at) FROM scores deepseek_score
                          WHERE deepseek_score.article_id = a.id AND deepseek_score.provider = 'deepseek'
                      ), '') < a.pdf_extracted_at
                  )
              )
            ORDER BY rules_score.materiality DESC, a.published_at DESC, a.id DESC
            LIMIT ?
        """
        return [dict(row) for row in self.connection.execute(query, (min_materiality, limit))]

    def articles_for_pdf_enrichment(
        self, min_materiality: int, limit: int, retry_failed: bool = False, ticker: str | None = None
    ) -> list[dict]:
        error_condition = "" if retry_failed else "AND a.pdf_extraction_error IS NULL"
        ticker_condition = "AND a.tickers LIKE ?" if ticker else ""
        query = f"""
            SELECT a.*
            FROM articles a
            JOIN scores rules_score ON rules_score.id = (
                SELECT id FROM scores
                WHERE article_id = a.id AND provider = 'rules'
                ORDER BY created_at DESC, id DESC LIMIT 1
            )
            WHERE rules_score.materiality >= ?
              AND a.source_url LIKE 'https://www.idx.co.id/%'
              AND lower(a.source_url) LIKE '%.pdf'
              AND a.pdf_extracted_at IS NULL
              {error_condition}
              {ticker_condition}
            ORDER BY rules_score.materiality DESC, a.published_at DESC, a.id DESC
            LIMIT ?
        """
        parameters = (min_materiality, f"%{ticker.strip().upper()}%", limit) if ticker else (min_materiality, limit)
        return [dict(row) for row in self.connection.execute(query, parameters)]

    def save_pdf_extraction(self, article_id: int, text: str | None = None, error: str | None = None) -> None:
        if not text and not error:
            raise ValueError("Provide extracted text, an error, or both for a PDF extraction.")
        self.connection.execute(
            "UPDATE articles SET pdf_text = ?, pdf_extracted_at = ?, pdf_extraction_error = ? WHERE id = ?",
            (text or "", utc_now() if text else None, error, article_id),
        )
        self.connection.commit()

    @staticmethod
    def pdf_urls(article: dict, max_documents: int) -> tuple[str, ...]:
        """Return the primary document and bounded, de-duplicated IDX attachments."""
        try:
            attachment_urls = json.loads(article.get("attachment_urls") or "[]")
        except json.JSONDecodeError:
            attachment_urls = []
        urls = [article["source_url"], *(url for url in attachment_urls if isinstance(url, str))]
        return tuple(dict.fromkeys(url for url in urls if url))[:max_documents]

    def scores_today(self, provider: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS total FROM scores WHERE provider = ? AND date(created_at) = date('now')",
            (provider,),
        ).fetchone()
        return int(row["total"])

    def save_score(self, article_id: int, score: NewsScore) -> None:
        self.connection.execute("""
            INSERT INTO scores (article_id, provider, model, sentiment, materiality, event_type, horizon, confidence, rationale, evidence, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (article_id, score.provider, score.model, score.sentiment, score.materiality,
              score.event_type, score.horizon, score.confidence, score.rationale,
              json.dumps(score.evidence), utc_now()))
        self.connection.commit()

    def list_scored_articles(self, limit: int = 100) -> list[dict]:
        query = """
            SELECT a.*, rules_score.sentiment, rules_score.materiality, rules_score.event_type,
                   rules_score.horizon, rules_score.confidence, rules_score.rationale,
                   rules_score.evidence, rules_score.provider, rules_score.model,
                   rules_score.created_at AS scored_at,
                   rules_score.sentiment AS rules_sentiment,
                   rules_score.materiality AS rules_materiality
            FROM articles a JOIN scores rules_score ON rules_score.id = (
                SELECT id FROM scores
                WHERE article_id = a.id AND provider = 'rules'
                ORDER BY created_at DESC, id DESC LIMIT 1
            )
            ORDER BY rules_score.materiality DESC, a.published_at DESC LIMIT ?
        """
        return [dict(row) for row in self.connection.execute(query, (limit,))]

    def get_article(self, article_id: int) -> dict | None:
        row = self.connection.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        return dict(row) if row else None

    def get_latest_score(self, article_id: int, provider: str | None = None) -> dict | None:
        query = "SELECT * FROM scores WHERE article_id = ?"
        parameters: tuple[int, ...] | tuple[int, str] = (article_id,)
        if provider is not None:
            query += " AND provider = ?"
            parameters = (article_id, provider)
        row = self.connection.execute(query + " ORDER BY created_at DESC, id DESC LIMIT 1", parameters).fetchone()
        if not row:
            return None
        score = dict(row)
        score["evidence"] = json.loads(score["evidence"])
        return score
