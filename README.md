# IDX News Intelligence MVP

A local Python MVP for collecting public IDX announcements, extracting IDX stock
codes, scoring their likely market relevance, and reviewing the results in a
small dashboard. It is a research tool, **not** investment advice or an
automated trading system.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Load reproducible sample announcements and score them without an API key
python -m idx_news.cli seed-demo
python -m idx_news.cli score --provider rules
python -m idx_news.cli collect --keyword bumi --page-size 100
python -m idx_news.cli score --provider rules
streamlit run app.py
```

## Collect public IDX announcements

The default source is the public IDX Keterbukaan Informasi JSON endpoint. It
keeps the official announcement title, ticker, date, subject, and primary PDF
URL. The endpoint is configurable in `.env` in case IDX changes it.

```bash
python -m idx_news.cli collect --keyword bumi --page-size 100
# Or request a specific issuer and a bounded date range
python -m idx_news.cli collect --ticker BUMI --date-from 20260101 --max-pages 3
python -m idx_news.cli score --provider rules
python -m idx_news.cli report --limit 20
```

Only collect content you are permitted to access and respect IDX terms, robots
rules, rate limits, and copyright. The collector does not bypass controls.
If IDX returns HTTP 403, use an authorised IDX export/feed or an approved
browser-based integration; do not work around the restriction.

## Optional DeepSeek scorer

Set `DEEPSEEK_API_KEY` in your untracked `.env` file, then use:

```bash
python -m idx_news.cli score --provider deepseek
```

The DeepSeek scorer uses JSON Output mode and validates its response against the
local rubric before it is stored. Treat it as an analyst-assist signal: review
the source document and rationale before acting.

## Near-real-time monitoring and cost controls

The dashboard refreshes its local SQLite view every 60 seconds by default; this
does **not** call IDX or DeepSeek. Configure `DASHBOARD_REFRESH_SECONDS` in
`.env` if needed.

Run the monitor only for the period you intend to watch. It polls IDX every 15
minutes by default, rules-scores only new records, and runs until you stop it:

```bash
# Collection and free rules scoring only
python -m idx_news.cli monitor --keyword bumi

# DeepSeek only for rules materiality >= 60, capped at 50 scores/day by default
python -m idx_news.cli monitor --keyword bumi --with-deepseek
```

Use `--cycles 1` for a one-off monitoring cycle, or set `--interval-minutes`
to a value no lower than 1. `DEEPSEEK_MIN_MATERIALITY` and
`DEEPSEEK_DAILY_LIMIT` in `.env` control the default AI threshold and daily
budget. Each article receives at most one DeepSeek score, preventing duplicate
spend on repeated dashboard refreshes or polling cycles.

## Scoring rubric

Each article receives transparent fields instead of a hidden buy/sell signal:

- `sentiment`: -100 (adverse) to +100 (favourable)
- `materiality`: 0 to 100, based on likely importance to a reasonable investor
- `event_type`: e.g. earnings, contract, corporate_action, legal, regulation
- `horizon`: immediate, short_term, or long_term
- `confidence`: 0 to 1, reflecting classification confidence, not return odds
- `rationale` and `evidence`: reviewable reasons grounded in the input title

Validate the rubric before relying on it: label a sample, compare scores with
subsequent price/volume reactions, and monitor false positives by event type.

## Layout

```text
idx_news/         collection, storage, and scoring modules
app.py            Streamlit review dashboard
data/             local SQLite database (created at runtime)
tests/            deterministic scorer and storage tests
```
