# IDX stock summary collector

Jalankan dashboard ringkasan perdagangan saham harian dari endpoint publik IDX:

```bash
cd market-data-collector
python -m streamlit run dashboard.py
```

Dashboard memanggil `https://www.idx.co.id/primary/TradingSummary/GetStockSummary?length=9999&start=0`, lalu menampilkan ticker, nama, tanggal, OHLC, perubahan, volume, nilai, frekuensi, bid/offer, serta beli/jual asing. Gunakan tombol **Refresh data** untuk mengambil data terbaru; cache lima menit membatasi permintaan berulang ke IDX.

Gunakan filter ticker pada dashboard untuk mempersempit tabel tanpa mengunduh CSV.

Jalankan test setelah memasang dependensi:

```bash
python -m pytest -q tests/test_stock_summary.py
```

Jika IDX mengembalikan HTTP 403, collector berhenti dengan pesan jelas. Gunakan export/feed IDX yang sah; program ini tidak mencoba melewati kontrol akses atau pembatasan layanan IDX.
