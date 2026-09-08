from idx_news.models import Article
from idx_news.scoring import DeepSeekScorer, RuleScorer


def test_legal_disclosure_is_high_materiality_and_negative():
    score = RuleScorer().score(Article("https://example.test/1", "Perkara PKPU [ASDF]", ""))
    assert score.event_type == "legal"
    assert score.materiality >= 80
    assert score.sentiment < 0


def test_contract_is_long_term_event():
    score = RuleScorer().score(Article("https://example.test/2", "Kontrak baru [ADRO]", ""))
    assert score.event_type == "contract"
    assert score.horizon == "long_term"


def test_deepseek_payload_is_validated_before_storage():
    scorer = object.__new__(DeepSeekScorer)
    scorer.model = "deepseek-v4-flash"
    score = scorer._to_score({
        "sentiment": 20,
        "materiality": 75,
        "event_type": "contract",
        "horizon": "long_term",
        "confidence": 0.8,
        "rationale": "A material contract was announced.",
        "evidence": ["contract", "announced"],
    })
    assert score.provider == "deepseek"
    assert score.model == "deepseek-v4-flash"


def test_deepseek_prompt_keeps_attachment_text_by_default(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_MAX_INPUT_CHARS", raising=False)
    text = "x" * 8_000
    prompt = DeepSeekScorer._article_prompt(Article("https://example.test/1", "Disclosure", text))
    assert text in prompt
