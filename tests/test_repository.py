from idx_news.models import Article, NewsScore
from idx_news.repository import NewsRepository
from idx_news.scoring import RuleScorer


def test_upsert_and_score(tmp_path):
    repo = NewsRepository(str(tmp_path / "news.db"))
    article = Article("https://example.test/a", "Laporan Keuangan [BBCA]", tickers=("BBCA",))
    article_id = repo.upsert_article(article)
    repo.upsert_article(article)
    assert len(repo.unscored_articles()) == 1
    repo.save_score(article_id, RuleScorer().score(article))
    assert len(repo.unscored_articles()) == 0
    assert repo.list_scored_articles()[0]["tickers"] == "BBCA"


def test_recollection_with_attachment_urls_marks_pdf_for_reenrichment(tmp_path):
    repo = NewsRepository(str(tmp_path / "news.db"))
    article = Article("https://www.idx.co.id/main.pdf", "Material fact [ADRO]", attachment_urls=())
    article_id = repo.upsert_article(article)
    repo.save_pdf_extraction(article_id, text="Primary document only")

    repo.upsert_article(Article(
        "https://www.idx.co.id/main.pdf", "Material fact [ADRO]",
        attachment_urls=("https://www.idx.co.id/attachment.pdf",),
    ))
    stored = repo.get_article(article_id)
    assert stored["pdf_text"] == ""
    assert stored["pdf_extracted_at"] is None
    assert repo.pdf_urls(stored, max_documents=3) == (
        "https://www.idx.co.id/main.pdf", "https://www.idx.co.id/attachment.pdf",
    )


def test_deepseek_candidates_require_high_rules_score_and_are_not_rescored(tmp_path):
    repo = NewsRepository(str(tmp_path / "news.db"))
    article = Article("https://example.test/material", "Material contract [ADRO]", tickers=("ADRO",))
    article_id = repo.upsert_article(article)
    rules_score = NewsScore(20, 75, "contract", "long_term", 0.8, "Rules match", ("contract",), "rules")
    deepseek_score = NewsScore(25, 76, "contract", "long_term", 0.9, "AI confirms", ("contract",), "deepseek", "deepseek-v4-flash")
    repo.save_score(article_id, rules_score)

    assert [row["id"] for row in repo.articles_for_deepseek(60, 10)] == [article_id]
    assert repo.scores_today("deepseek") == 0

    repo.save_score(article_id, deepseek_score)
    assert repo.articles_for_deepseek(60, 10) == []
    assert repo.scores_today("deepseek") == 1
    assert repo.get_latest_score(article_id, "rules")["materiality"] == 75
    assert repo.get_latest_score(article_id, "deepseek")["materiality"] == 76

    row = repo.list_scored_articles()[0]
    assert row["rules_materiality"] == 75
    assert row["materiality"] == 75
    assert row["provider"] == "rules"


def test_new_pdf_text_makes_a_previously_scored_article_eligible_for_rescore(tmp_path):
    repo = NewsRepository(str(tmp_path / "news.db"))
    article = Article("https://www.idx.co.id/StaticData/example.pdf", "Material contract [ADRO]", tickers=("ADRO",))
    article_id = repo.upsert_article(article)
    repo.save_score(article_id, NewsScore(20, 75, "contract", "long_term", 0.8, "Rules match", ("contract",), "rules"))
    repo.save_score(article_id, NewsScore(20, 70, "contract", "long_term", 0.8, "Initial AI score", ("contract",), "deepseek"))

    assert repo.articles_for_pdf_enrichment(60, 10)[0]["id"] == article_id
    assert repo.articles_for_deepseek(60, 10) == []

    repo.save_pdf_extraction(article_id, text="A material contract value is IDR 1 trillion.")
    assert repo.articles_for_deepseek(60, 10)[0]["id"] == article_id
