from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from idx_news.repository import NewsRepository

st.set_page_config(page_title="IDX News Intelligence", layout="wide")
st.title("IDX News Intelligence")
st.caption("Research support only — scores are not investment recommendations.")


def refresh_seconds() -> int:
    try:
        return max(5, int(os.getenv("DASHBOARD_REFRESH_SECONDS", "60")))
    except ValueError:
        return 60


def lookback_days() -> int:
    try:
        return max(1, int(os.getenv("NEWS_LOOKBACK_DAYS", "30")))
    except ValueError:
        return 30


def display_rules_score(score: dict | None) -> None:
    """Render the deterministic Rules score without making it a recommendation."""
    st.markdown("#### Rules score")
    if not score:
        st.caption("No score available yet.")
        return
    cols = st.columns(4)
    cols[0].metric("Sentiment", score["sentiment"])
    cols[1].metric("Materiality", score["materiality"])
    cols[2].metric("Confidence", f"{score['confidence']:.0%}")
    cols[3].metric("Horizon", score["horizon"])
    st.caption(f"Event type: {score['event_type']}")
    st.write(score["rationale"])
    st.write("**Evidence:** " + "; ".join(score["evidence"]))


@st.fragment(run_every=refresh_seconds())
def review_dashboard() -> None:
    """Refreshes the local database view only; it does not call IDX or DeepSeek."""
    repo = NewsRepository.from_environment()
    rows = repo.list_scored_articles(limit=500)
    if not rows:
        st.info("No scored announcements yet. Run `seed-demo` and `score --provider rules`.")
        return

    frame = pd.DataFrame(rows)
    frame["published_at"] = pd.to_datetime(frame["published_at"], errors="coerce", utc=True)
    frame["rules_materiality"] = frame["rules_materiality"].fillna(frame["materiality"])
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=lookback_days())
    frame = frame[frame["published_at"] >= cutoff].copy()
    if frame.empty:
        st.info(f"No scored announcements in the last {lookback_days()} days.")
        return
    with st.sidebar:
        st.header("Filters")
        tickers = sorted({ticker for value in frame["tickers"].fillna("") for ticker in value.split(",") if ticker})
        selected_tickers = st.multiselect("Ticker", tickers, key="ticker_filter")
        min_materiality = st.slider("Minimum Rules materiality", 0, 100, 50, key="materiality_filter")
        event_types = st.multiselect("Event type", sorted(frame["event_type"].dropna().unique()), key="event_type_filter")

    filtered = frame[frame["rules_materiality"] >= min_materiality]
    if selected_tickers:
        filtered = filtered[filtered["tickers"].fillna("").apply(lambda value: any(ticker in value.split(",") for ticker in selected_tickers))]
    if event_types:
        filtered = filtered[filtered["event_type"].isin(event_types)]

    st.caption(f"Showing the last {lookback_days()} days. Database view refreshes every {refresh_seconds()} seconds; refreshing does not call IDX or DeepSeek.")
    first, second, third = st.columns(3)
    first.metric("Scored items", len(filtered))
    second.metric("Average Rules materiality", f"{filtered['rules_materiality'].mean():.0f}" if not filtered.empty else "—")
    third.metric("High Rules materiality", int((filtered["rules_materiality"] >= 75).sum()))

    st.subheader("Review queue")
    if filtered.empty:
        st.info("No articles match the current filters.")
        return
    st.dataframe(
        filtered[[
            "published_at", "tickers", "title", "rules_sentiment", "rules_materiality", "event_type", "horizon",
        ]],
        use_container_width=True,
        hide_index=True,
        column_config={
            "title": st.column_config.TextColumn("Title", width="large"),
            "rules_sentiment": "Rules sentiment",
            "rules_materiality": "Rules materiality",
        },
    )

    st.subheader("Article detail")
    selected_id = st.selectbox(
        "Select an announcement",
        filtered["id"].tolist(),
        format_func=lambda value: next(row["title"] for row in rows if row["id"] == value),
        key="article_selector",
    )
    article = repo.get_article(selected_id)
    rules_score = repo.get_latest_score(selected_id, "rules")
    if article:
        st.markdown(f"### {article['title']}")
        st.caption(f"Source: {article['source_url']}")
        display_rules_score(rules_score)
        if article["body"]:
            st.text_area("Extracted text", article["body"], height=180, disabled=True)
        if article.get("pdf_text"):
            with st.expander("Extracted IDX PDF text"):
                st.text(article["pdf_text"])
        elif article.get("pdf_extraction_error"):
            st.caption(f"PDF extraction unavailable: {article['pdf_extraction_error']}")


review_dashboard()
