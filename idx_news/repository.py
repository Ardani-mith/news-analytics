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
        self.connection.commit()

    def upsert_article(self, article: Article) -> int:
        self.connection.execute("""
            INSERT INTO articles (source_url, source, title, body, published_at, tickers, article_key, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(article_key) DO UPDATE SET
                body=excluded.body, published_at=COALESCE(excluded.published_at, articles.published_at),
                tickers=excluded.tickers
        """, (article.source_url, article.source, article.title, article.body, article.published_at,
              ",".join(article.tickers), article.key(), utc_now()))
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
        """Return high-materiality rules scores that have not used DeepSeek yet."""
        query = """
            SELECT a.*
            FROM articles a
            JOIN scores rules_score ON rules_score.id = (
                SELECT id FROM scores
                WHERE article_id = a.id AND provider = 'rules'
                ORDER BY created_at DESC, id DESC LIMIT 1
            )
            WHERE rules_score.materiality >= ?
              AND NOT EXISTS (
                  SELECT 1 FROM scores deepseek_score
                  WHERE deepseek_score.article_id = a.id AND deepseek_score.provider = 'deepseek'
              )
            ORDER BY rules_score.materiality DESC, a.published_at DESC, a.id DESC
            LIMIT ?
        """
        return [dict(row) for row in self.connection.execute(query, (min_materiality, limit))]

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
            SELECT a.*, s.sentiment, s.materiality, s.event_type, s.horizon, s.confidence,
                   s.rationale, s.evidence, s.provider, s.model, s.created_at AS scored_at
            FROM articles a JOIN scores s ON s.id = (
                SELECT id FROM scores WHERE article_id = a.id ORDER BY created_at DESC, id DESC LIMIT 1
            ) ORDER BY s.materiality DESC, a.published_at DESC LIMIT ?
        """
        return [dict(row) for row in self.connection.execute(query, (limit,))]

    def get_article(self, article_id: int) -> dict | None:
        row = self.connection.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        return dict(row) if row else None

    def get_latest_score(self, article_id: int) -> dict | None:
        row = self.connection.execute("SELECT * FROM scores WHERE article_id = ? ORDER BY created_at DESC, id DESC LIMIT 1", (article_id,)).fetchone()
        if not row:
            return None
        score = dict(row)
        score["evidence"] = json.loads(score["evidence"])
        return score
