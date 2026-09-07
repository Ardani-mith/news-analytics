from __future__ import annotations

import argparse
import os
import time
from datetime import date, timedelta

from dotenv import load_dotenv
import httpx

from .models import Article
from .pdf_extract import IDXPDFTextExtractor
from .repository import NewsRepository
from .scraper import IDXAnnouncementScraper, IDX_ANNOUNCEMENT_API
from .scoring import DeepSeekScorer, RuleScorer, article_from_row


DEMO_ARTICLES = (
    ("Laporan Keuangan dan Pembagian Dividen [BBCA]", "BBCA reports profit growth and proposes a cash dividend."),
    ("Perkara PKPU [ASDF]", "Disclosure regarding a PKPU legal proceeding."),
    ("Penandatanganan Kontrak Baru [ADRO]", "The company announces a material new contract."),
)


def add_collection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--keyword", default="", help="IDX keyword query, e.g. bumi")
    parser.add_argument("--ticker", default="", help="IDX issuer code, e.g. BUMI")
    parser.add_argument("--date-from", default=None, help="Start date (YYYYMMDD); defaults to the lookback window")
    parser.add_argument("--date-to", default=None, help="End date (YYYYMMDD); defaults to today")
    parser.add_argument("--page-size", type=int, default=100, help="Records per request (1-100)")
    parser.add_argument("--max-pages", type=int, default=1, help="Maximum API pages to request")
    parser.add_argument("--transport", choices=("httpx", "playwright"), default=None, help="HTTP client or Chromium browser context")


def collect(repo: NewsRepository, args: argparse.Namespace) -> int:
    scraper = IDXAnnouncementScraper(
        os.getenv("IDX_ANNOUNCEMENT_API", IDX_ANNOUNCEMENT_API),
        float(os.getenv("IDX_REQUEST_DELAY_SECONDS", "1")),
        args.transport or os.getenv("IDX_TRANSPORT", "playwright"),
    )
    articles = scraper.fetch(
        keyword=args.keyword, ticker=args.ticker, date_from=args.date_from or default_date_from(),
        date_to=args.date_to, page_size=args.page_size, max_pages=args.max_pages,
    )
    for article in articles:
        repo.upsert_article(article)
    return len(articles)


def default_date_from() -> str:
    """Return the configured rolling collection window, defaulting to 30 days."""
    lookback_days = int(os.getenv("NEWS_LOOKBACK_DAYS", "30"))
    if lookback_days < 1:
        raise ValueError("NEWS_LOOKBACK_DAYS must be at least 1")
    return (date.today() - timedelta(days=lookback_days)).strftime("%Y%m%d")


def score_rules(repo: NewsRepository, limit: int | None = None) -> int:
    rows = repo.unscored_articles()
    if limit is not None:
        rows = rows[:limit]
    scorer = RuleScorer()
    for row in rows:
        repo.save_score(row["id"], scorer.score(article_from_row(row)))
    return len(rows)


def score_deepseek(repo: NewsRepository, min_materiality: int, daily_limit: int, limit: int | None = None) -> tuple[int, int]:
    if not 0 <= min_materiality <= 100:
        raise ValueError("min_materiality must be between 0 and 100")
    if daily_limit < 0:
        raise ValueError("daily_limit cannot be negative")
    remaining = max(0, daily_limit - repo.scores_today("deepseek"))
    if limit is not None:
        remaining = min(remaining, limit)
    if remaining == 0:
        return 0, 0
    rows = repo.articles_for_deepseek(min_materiality, remaining)
    if not rows:
        return 0, remaining
    scorer = DeepSeekScorer()
    for row in rows:
        repo.save_score(row["id"], scorer.score(article_from_row(row)))
    return len(rows), remaining


def enrich_pdfs(
    repo: NewsRepository, min_materiality: int, limit: int, retry_failed: bool = False, ticker: str | None = None
) -> tuple[int, int]:
    if limit < 1:
        raise ValueError("PDF enrichment limit must be at least 1")
    rows = repo.articles_for_pdf_enrichment(min_materiality, limit, retry_failed, ticker)
    if not rows:
        return 0, 0
    extractor = IDXPDFTextExtractor()
    max_documents = int(os.getenv("PDF_MAX_DOCUMENTS", "3"))
    if max_documents < 1:
        raise ValueError("PDF_MAX_DOCUMENTS must be at least 1")
    extracted = failed = 0
    for row in rows:
        texts: list[str] = []
        errors: list[str] = []
        for document_number, url in enumerate(repo.pdf_urls(row, max_documents), 1):
            try:
                result = extractor.extract(url)
                label = "Primary IDX document" if document_number == 1 else f"IDX attachment {document_number - 1}"
                texts.append(f"{label}:\n{result.text}")
            except (httpx.HTTPError, ValueError) as error:
                errors.append(f"{url}: {error}")
        if texts:
            error_message = "Partial PDF extraction; unavailable document(s): " + " | ".join(errors) if errors else None
            repo.save_pdf_extraction(row["id"], text="\n\n".join(texts), error=error_message)
            extracted += 1
        else:
            repo.save_pdf_extraction(row["id"], error=(" | ".join(errors) or "No PDF URLs were available.")[:500])
            failed += 1
    return extracted, failed


def configured_min_materiality(value: int | None) -> int:
    return value if value is not None else int(os.getenv("DEEPSEEK_MIN_MATERIALITY", "60"))


def configured_daily_limit(value: int | None) -> int:
    return value if value is not None else int(os.getenv("DEEPSEEK_DAILY_LIMIT", "50"))


def main() -> None:
    parser = argparse.ArgumentParser(description="IDX News Intelligence MVP")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser("collect", help="Collect permitted public IDX disclosures")
    add_collection_arguments(collect_parser)

    score_parser = subparsers.add_parser("score", help="Score new articles or qualifying rules candidates")
    score_parser.add_argument("--provider", choices=("rules", "deepseek"), default="rules")
    score_parser.add_argument("--min-materiality", type=int, default=None, help="Rules threshold before DeepSeek scoring")
    score_parser.add_argument("--daily-limit", type=int, default=None, help="Maximum DeepSeek scores per UTC day")
    score_parser.add_argument("--limit", type=int, default=None, help="Maximum articles scored in this run")

    pdf_parser = subparsers.add_parser("extract-pdfs", help="Extract text from qualifying official IDX PDFs")
    pdf_parser.add_argument("--min-materiality", type=int, default=None, help="Rules threshold for PDF extraction")
    pdf_parser.add_argument("--limit", type=int, default=None, help="Maximum PDFs extracted in this run")
    pdf_parser.add_argument("--retry-failed", action="store_true", help="Retry PDFs with a prior extraction error")
    pdf_parser.add_argument("--ticker", default=None, help="Extract only one IDX issuer code, e.g. BUMI")
    pdf_parser.add_argument("--with-deepseek", action="store_true", help="Rescore enriched candidates with DeepSeek")
    pdf_parser.add_argument("--daily-limit", type=int, default=None, help="Maximum DeepSeek scores per UTC day")

    monitor_parser = subparsers.add_parser("monitor", help="Poll IDX at a bounded interval; run until interrupted by default")
    add_collection_arguments(monitor_parser)
    monitor_parser.add_argument("--interval-minutes", type=int, default=None, help="Time between polling cycles")
    monitor_parser.add_argument("--cycles", type=int, default=0, help="Number of cycles; 0 means run until interrupted")
    monitor_parser.add_argument("--with-deepseek", action="store_true", help="Also score qualifying articles with DeepSeek")
    monitor_parser.add_argument("--min-materiality", type=int, default=None, help="Rules threshold before DeepSeek scoring")
    monitor_parser.add_argument("--daily-limit", type=int, default=None, help="Maximum DeepSeek scores per UTC day")

    report_parser = subparsers.add_parser("report", help="Print the latest review queue")
    report_parser.add_argument("--limit", type=int, default=20)
    subparsers.add_parser("seed-demo", help="Insert reproducible demo announcements")
    args = parser.parse_args()

    load_dotenv()
    repo = NewsRepository.from_environment()
    if args.command == "collect":
        print(f"Collected {collect(repo, args)} announcement record(s).")
    elif args.command == "seed-demo":
        for index, (title, body) in enumerate(DEMO_ARTICLES, 1):
            ticker = title.split("[")[-1].rstrip("]")
            repo.upsert_article(Article(f"https://example.test/idx-demo/{index}", title, body, tickers=(ticker,)))
        print(f"Stored {len(DEMO_ARTICLES)} demo announcements.")
    elif args.command == "score":
        if args.provider == "rules":
            print(f"Scored {score_rules(repo, args.limit)} announcement(s) with rules.")
        else:
            scored, remaining = score_deepseek(repo, configured_min_materiality(args.min_materiality), configured_daily_limit(args.daily_limit), args.limit)
            print(f"Scored {scored} qualifying announcement(s) with DeepSeek (daily budget available: {remaining}).")
    elif args.command == "extract-pdfs":
        min_materiality = configured_min_materiality(args.min_materiality)
        limit = args.limit or int(os.getenv("PDF_ENRICHMENT_LIMIT", "20"))
        extracted, failed = enrich_pdfs(repo, min_materiality, limit, args.retry_failed, args.ticker)
        message = f"Enriched {extracted} announcement(s) with PDF text; {failed} announcement(s) could not be enriched."
        if args.with_deepseek:
            deepseek_scored, _ = score_deepseek(repo, min_materiality, configured_daily_limit(args.daily_limit))
            message += f" DeepSeek rescored {deepseek_scored} enriched candidate(s)."
        print(message)
    elif args.command == "monitor":
        interval_seconds = 60 * (args.interval_minutes or int(os.getenv("MONITOR_INTERVAL_MINUTES", "15")))
        if interval_seconds < 60 or args.cycles < 0:
            raise ValueError("interval-minutes must be at least 1 and cycles cannot be negative")
        cycle = 0
        while args.cycles == 0 or cycle < args.cycles:
            cycle += 1
            collected = collect(repo, args)
            rules_scored = score_rules(repo)
            message = f"Cycle {cycle}: collected {collected}, rules-scored {rules_scored}."
            if args.with_deepseek:
                extracted, failed = enrich_pdfs(
                    repo, configured_min_materiality(args.min_materiality), int(os.getenv("PDF_ENRICHMENT_LIMIT", "20"))
                )
                deepseek_scored, _ = score_deepseek(repo, configured_min_materiality(args.min_materiality), configured_daily_limit(args.daily_limit))
                message += f" Announcements enriched {extracted}, failed {failed}; DeepSeek-scored {deepseek_scored}."
            print(message, flush=True)
            if args.cycles == 0 or cycle < args.cycles:
                time.sleep(interval_seconds)
    else:
        for row in repo.list_scored_articles(args.limit):
            print(f"[{row['materiality']:>3}] {row['tickers'] or '----'} {row['event_type']:<17} {row['title']}")


if __name__ == "__main__":
    main()
