from datetime import date, timedelta

from idx_news.cli import default_date_from, enrich_pdfs
from idx_news.models import Article, NewsScore
from idx_news.pdf_extract import PDFText
from idx_news.repository import NewsRepository


def test_default_collection_window_uses_configured_lookback(monkeypatch):
    monkeypatch.setenv("NEWS_LOOKBACK_DAYS", "30")
    assert default_date_from() == (date.today() - timedelta(days=30)).strftime("%Y%m%d")


def test_pdf_enrichment_combines_primary_document_and_attachments(tmp_path, monkeypatch):
    repo = NewsRepository(str(tmp_path / "news.db"))
    article_id = repo.upsert_article(Article(
        "https://www.idx.co.id/main.pdf", "Acquisition [BUMI]", tickers=("BUMI",),
        attachment_urls=("https://www.idx.co.id/attachment.pdf",),
    ))
    repo.save_score(article_id, NewsScore(25, 75, "contract", "long_term", 0.72, "Rules match", ("acquisition",), "rules"))

    class FakeExtractor:
        def extract(self, url: str) -> PDFText:
            return PDFText(text=f"text from {url}", page_count=1)

    monkeypatch.setattr("idx_news.cli.IDXPDFTextExtractor", FakeExtractor)
    assert enrich_pdfs(repo, min_materiality=60, limit=1) == (1, 0)

    stored = repo.get_article(article_id)
    assert "Primary IDX document:\ntext from https://www.idx.co.id/main.pdf" in stored["pdf_text"]
    assert "IDX attachment 1:\ntext from https://www.idx.co.id/attachment.pdf" in stored["pdf_text"]


def test_pdf_enrichment_keeps_primary_text_when_attachment_fails(tmp_path, monkeypatch):
    repo = NewsRepository(str(tmp_path / "news.db"))
    article_id = repo.upsert_article(Article(
        "https://www.idx.co.id/main.pdf", "Acquisition [BUMI]", tickers=("BUMI",),
        attachment_urls=("https://www.idx.co.id/attachment.pdf",),
    ))
    repo.save_score(article_id, NewsScore(25, 75, "contract", "long_term", 0.72, "Rules match", ("acquisition",), "rules"))

    class PartialExtractor:
        def extract(self, url: str) -> PDFText:
            if url.endswith("attachment.pdf"):
                raise ValueError("HTTP 403")
            return PDFText(text="primary text", page_count=1)

    monkeypatch.setattr("idx_news.cli.IDXPDFTextExtractor", PartialExtractor)
    assert enrich_pdfs(repo, min_materiality=60, limit=1) == (1, 0)

    stored = repo.get_article(article_id)
    assert "primary text" in stored["pdf_text"]
    assert "Partial PDF extraction" in stored["pdf_extraction_error"]
    assert stored["pdf_extracted_at"] is not None
