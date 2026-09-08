import pytest

from idx_news.pdf_extract import IDXPDFTextExtractor


def test_rejects_non_idx_pdf_urls():
    extractor = IDXPDFTextExtractor()
    with pytest.raises(ValueError, match="idx.co.id"):
        extractor._validate_url("https://example.com/file.pdf")


def test_rejects_non_pdf_paths():
    extractor = IDXPDFTextExtractor()
    with pytest.raises(ValueError, match="HTTPS document"):
        extractor._validate_url("https://www.idx.co.id/announcement")
