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
