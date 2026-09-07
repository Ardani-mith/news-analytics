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


@st.fragment(run_every=refresh_seconds())
def review_dashboard() -> None:
    """Refreshes the local database view only; it does not call IDX or DeepSeek."""
    repo = NewsRepository.from_environment()
    rows = repo.list_scored_articles(limit=500)
    if not rows:
        st.info("No scored announcements yet. Run `seed-demo` and `score --provider rules`.")
        return

    frame = pd.DataFrame(rows)
    frame["published_at"] = pd.to_datetime(frame["published_at"], errors="coerce")
    with st.sidebar:
        st.header("Filters")
        tickers = sorted({ticker for value in frame["tickers"].fillna("") for ticker in value.split(",") if ticker})
        selected_tickers = st.multiselect("Ticker", tickers, key="ticker_filter")
        min_materiality = st.slider("Minimum materiality", 0, 100, 50, key="materiality_filter")
        event_types = st.multiselect("Event type", sorted(frame["event_type"].dropna().unique()), key="event_type_filter")

    filtered = frame[frame["materiality"] >= min_materiality]
    if selected_tickers:
        filtered = filtered[filtered["tickers"].fillna("").apply(lambda value: any(ticker in value.split(",") for ticker in selected_tickers))]
    if event_types:
        filtered = filtered[filtered["event_type"].isin(event_types)]

    st.caption(f"Database view refreshes every {refresh_seconds()} seconds. Refreshing this page does not call IDX or DeepSeek.")
    first, second, third = st.columns(3)
    first.metric("Scored items", len(filtered))
    second.metric("Average materiality", f"{filtered['materiality'].mean():.0f}" if not filtered.empty else "—")
    third.metric("High materiality", int((filtered["materiality"] >= 75).sum()))

    st.subheader("Review queue")
    if filtered.empty:
        st.info("No articles match the current filters.")
        return
    st.dataframe(
        filtered[["published_at", "tickers", "title", "event_type", "sentiment", "materiality", "horizon", "confidence"]],
        use_container_width=True,
        hide_index=True,
        column_config={"title": st.column_config.TextColumn("Title", width="large")},
    )

    st.subheader("Article detail")
    selected_id = st.selectbox(
        "Select an announcement",
        filtered["id"].tolist(),
        format_func=lambda value: next(row["title"] for row in rows if row["id"] == value),
        key="article_selector",
    )
    article = repo.get_article(selected_id)
    score = repo.get_latest_score(selected_id)
    if article and score:
        st.markdown(f"### {article['title']}")
        st.caption(f"Source: {article['source_url']}")
        cols = st.columns(4)
        cols[0].metric("Sentiment", score["sentiment"])
        cols[1].metric("Materiality", score["materiality"])
        cols[2].metric("Confidence", f"{score['confidence']:.0%}")
        cols[3].metric("Horizon", score["horizon"])
        st.write(score["rationale"])
        st.write("**Evidence:** " + "; ".join(score["evidence"]))
        if article["body"]:
            st.text_area("Extracted text", article["body"], height=180, disabled=True)


review_dashboard()
