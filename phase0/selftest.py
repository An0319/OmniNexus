# -*- coding: utf-8 -*-
"""管线自检：用合成数据验证索引对齐+xcorr逻辑（不消耗任何API额度）"""
import sys
sys.path.insert(0, r"c:\Users\24063\Desktop\Trae-CN-Project\OmniNexus\phase0")
import numpy as np
import pandas as pd
from lead_lag_check import to_weekly, roll_z, xcorr, LAG_RANGE

rng = np.random.default_rng(42)
idx = pd.date_range("2021-10-04", periods=200, freq="W-MON")  # 周一标签

# 合成：lead 是一个热信号，lag = lead 滞后2周的响应+噪声 -> 应在超前2周出峰值
lead_raw = pd.Series(rng.poisson(50, 200).astype(float), index=idx)
lag_resp = lead_raw.shift(2).bfill() * 0.5 + rng.normal(0, 5, 200)
# 模拟"板块日线"（日频）以便测 to_weekly 的对齐逻辑
daily_idx = pd.date_range("2021-10-01", periods=200 * 5, freq="B")
daily = pd.DataFrame({
    "close": np.repeat(lag_resp.values, 5) + rng.normal(0, 1, 1000).cumsum() * 0.1,
    "amount": np.repeat(np.abs(lag_resp.values), 5) * 1000 + rng.normal(0, 100, 1000),
}, index=daily_idx)

wk = to_weekly(daily)
print("weekly index sample:", wk.index[:3].tolist(), "(应为周一)")

lead_z = roll_z(lead_raw)
lag_z = roll_z(wk["amount"].reindex(lead_raw.index, method="nearest"))
tbl = pd.DataFrame({k: v for k, v in {"lag": lag_z}.items()}).pipe(
    lambda _: xcorr(lead_z, lag_z, LAG_RANGE))
print("\n合成数据 xcorr（预期峰值在超前2周）:")
print(tbl.round(3))
peak = tbl.abs().idxmax()
print(f"\n峰值 @ 超前{peak}周 -> {'PASS' if peak == 2 else 'FAIL'}")
sys.exit(0 if peak == 2 else 1)
