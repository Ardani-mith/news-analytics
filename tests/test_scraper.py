from idx_news.scraper import IDXAnnouncementScraper


def test_maps_idx_json_to_an_article_with_the_primary_pdf():
    payload = {
        "ResultCount": 1,
        "Replies": [{
            "pengumuman": {
                "Id2": "20260907070704-658/BR-BOD/IX/26_id-id",
                "NoPengumuman": "658/BR-BOD/IX/26",
                "TglPengumuman": "2026-09-07T07:07:04",
                "JudulPengumuman": "Pengambilalihan Loyal Metals Ltd",
                "JenisPengumuman": "STOCK",
                "Kode_Emiten": "BUMI                                ",
                "PerihalPengumuman": "Pengambilalihan Loyal Metals L",
            },
            "attachments": [
                {"FullSavePath": "https://www.idx.co.id/main.pdf", "OriginalFilename": "main.pdf", "IsAttachment": False},
                {"FullSavePath": "https://www.idx.co.id/appendix.pdf", "OriginalFilename": "appendix.pdf", "IsAttachment": True},
            ],
        }],
    }
    article = IDXAnnouncementScraper().parse(payload)[0]
    assert article.title == "Pengambilalihan Loyal Metals Ltd"
    assert article.tickers == ("BUMI",)
    assert article.source_url == "https://www.idx.co.id/main.pdf"
    assert article.attachment_urls == ("https://www.idx.co.id/appendix.pdf",)
    assert article.published_at == "2026-09-07T07:07:04"
    assert "Pengambilalihan Loyal Metals L" in article.body
    assert "appendix.pdf" in article.body


def test_uses_api_fallback_url_when_no_pdf_is_available():
    payload = {"Replies": [{"pengumuman": {"Id2": "record-1", "JudulPengumuman": "A valid announcement"}, "attachments": []}]}
    article = IDXAnnouncementScraper("https://example.test/api").parse(payload)[0]
    assert article.source_url == "https://example.test/api#announcement=record-1"
