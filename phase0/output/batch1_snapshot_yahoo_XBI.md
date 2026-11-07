# Snapshot note: Yahoo XBI

- endpoint: https://query1.finance.yahoo.com/v8/finance/chart/XBI
- params: range=10y interval=1d events=div,splits
- fetched_at_utc: 2026-11-07T06:52:56Z
- symbol: XBI
- long_name: State Street SPDR S&P Biotech ETF
- currency: USD
- exchange_timezone: America/New_York
- rows_daily: 2514
- coverage: 2016-11-07 .. 2026-11-06
- null_adjclose_dropped: 0
- base_close: `batch1_yahoo_XBI_base.csv` (2026-11-07 fetch, period 2016-10-24..2016-11-06); last row 2016-11-04 = 54.112389, used only to compute the first weekly return at 2016-11-11; sample window unchanged
- holdout: rows for 2025-01-03 .. 2026-10-30 exist on disk in this raw file, but no computation or inspection has been performed on them; the batch-1 runner hard-clips every series at 2024-12-27 unless `--open-holdout` is passed
