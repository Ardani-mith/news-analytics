"""Interactive Streamlit view of the daily IDX stock trading summary."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from idx_market.scraper import IDXStockSummaryClient


st.set_page_config(page_title="IDX Stock Summary", page_icon="📈", layout="wide")
st.title("IDX Stock Summary")
st.caption("Ringkasan perdagangan saham harian dari endpoint publik IDX. Bukan rekomendasi investasi.")


@st.cache_data(ttl=300, show_spinner="Mengambil data perdagangan dari IDX…")
def load_stock_summary() -> pd.DataFrame:
    """Return a cached tabular representation; refresh clears this cache."""
    rows = IDXStockSummaryClient().fetch()
    return pd.DataFrame([row.to_dict() for row in rows])


with st.sidebar:
    st.header("Kontrol")
    if st.button("Refresh data", type="primary", use_container_width=True):
        load_stock_summary.clear()
    st.caption("Data disimpan sementara selama 5 menit untuk mengurangi permintaan ke IDX.")

try:
    data = load_stock_summary()
except PermissionError as error:
    st.error("IDX menolak permintaan ini (HTTP 403). Gunakan export/feed IDX yang sah bila Anda memiliki akses.")
    st.caption(str(error))
    st.stop()
except Exception as error:
    st.error("Data IDX belum dapat dimuat.")
    st.exception(error)
    st.stop()

if data.empty:
    st.info("IDX tidak mengembalikan data saham.")
    st.stop()

data["date"] = pd.to_datetime(data["date"], errors="coerce")
tickers = sorted(data["ticker"].dropna().unique())
selected_tickers = st.multiselect("Filter ticker", tickers, placeholder="Semua saham")
visible = data[data["ticker"].isin(selected_tickers)].copy() if selected_tickers else data.copy()

latest_date = visible["date"].max()
total_value = visible["value"].sum(min_count=1)
positive = (visible["change"] > 0).sum()
negative = (visible["change"] < 0).sum()
metrics = st.columns(4)
metrics[0].metric("Saham ditampilkan", f"{len(visible):,}")
metrics[1].metric("Tanggal perdagangan", latest_date.strftime("%d %b %Y") if pd.notna(latest_date) else "–")
metrics[2].metric("Naik / turun", f"{positive:,} / {negative:,}")
metrics[3].metric("Total nilai transaksi", f"Rp{total_value:,.0f}" if pd.notna(total_value) else "–")

table_columns = [
    "ticker", "name", "previous", "open", "high", "low", "close", "change", "volume", "value",
    "frequency", "bid", "bid_volume", "offer", "offer_volume", "foreign_buy", "foreign_sell",
]
st.dataframe(
    visible[table_columns],
    hide_index=True,
    use_container_width=True,
    column_config={
        "ticker": "Kode", "name": "Nama emiten", "previous": st.column_config.NumberColumn("Sebelumnya", format="%.0f"),
        "open": st.column_config.NumberColumn("Buka", format="%.0f"), "high": st.column_config.NumberColumn("Tertinggi", format="%.0f"),
        "low": st.column_config.NumberColumn("Terendah", format="%.0f"), "close": st.column_config.NumberColumn("Penutupan", format="%.0f"),
        "change": st.column_config.NumberColumn("Perubahan", format="%+.0f"), "volume": st.column_config.NumberColumn("Volume", format="%,.0f"),
        "value": st.column_config.NumberColumn("Nilai", format="Rp%,.0f"), "frequency": st.column_config.NumberColumn("Frekuensi", format="%,.0f"),
        "bid": st.column_config.NumberColumn("Bid", format="%.0f"), "bid_volume": st.column_config.NumberColumn("Vol. bid", format="%,.0f"),
        "offer": st.column_config.NumberColumn("Offer", format="%.0f"), "offer_volume": st.column_config.NumberColumn("Vol. offer", format="%,.0f"),
        "foreign_buy": st.column_config.NumberColumn("Beli asing", format="%,.0f"), "foreign_sell": st.column_config.NumberColumn("Jual asing", format="%,.0f"),
    },
)
