"""Collect daily IDX stock trading-summary data."""

from .scraper import IDXStockSummaryClient, StockSummary

__all__ = ("IDXStockSummaryClient", "StockSummary")
