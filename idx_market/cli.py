"""Command line entry point for IDX stock-summary downloads."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from dotenv import load_dotenv

from .scraper import IDXStockSummaryClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download IDX daily stock trading summaries.")
    parser.add_argument("--length", type=int, default=9999, help="Maximum records to request (1-9999).")
    parser.add_argument("--start", type=int, default=0, help="Zero-based record offset.")
    parser.add_argument("--ticker", action="append", default=[], help="Filter one ticker; may be supplied repeatedly.")
    parser.add_argument("--format", choices=("csv", "json"), default="csv")
    parser.add_argument("--output", type=Path, required=True, help="Destination CSV or JSON file.")
    return parser


def main() -> None:
    load_dotenv()
    args = build_parser().parse_args()
    requested = {ticker.strip().upper() for ticker in args.ticker if ticker.strip()}
    rows = [row.to_dict() for row in IDXStockSummaryClient().fetch(length=args.length, start=args.start)]
    if requested:
        rows = [row for row in rows if row["ticker"] in requested]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "json":
        args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        with args.output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["date", "ticker", "name"])
            writer.writeheader()
            writer.writerows(rows)
    print(f"Saved {len(rows)} stock summary row(s) to {args.output}")


if __name__ == "__main__":
    main()
