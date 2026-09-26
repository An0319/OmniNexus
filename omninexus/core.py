# -*- coding: utf-8 -*-
"""omninexus.core —— 计算分析层：对齐、标准化、交叉相关、预注册判定。

M0 泛化说明：全部函数从 phase0/lead_lag_check.py 原样搬移，仅做参数化，
判定逻辑与旧脚本逐位一致（回归校验见 tests/run_m0_regression.py）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_Z_ROLL = 52
DEFAULT_MIN_PERIODS = 26


def align_weekday(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """任意日历标签统一对齐到该周的周一（修复周五/周日标签错位问题）。"""
    return index - pd.to_timedelta(index.dayofweek, unit="D")


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """日线 -> 周线：close 取周末最后值，amount 求和，ret 为周收益率；索引对齐周一。

    amount 为可选列：新浪美股/新浪指数接口只返回 OHLC+volume，**没有成交额**
    （接口限制，非主动取舍——见协议第9.3节）。缺列时只产出 close/ret，
    判定指标随之只剩周收益率，而非把无成交额当成缺失值处理。
    """
    wk = pd.DataFrame()
    wk["close"] = daily["close"].resample("W").last()
    if "amount" in daily.columns:
        wk["amount"] = daily["amount"].resample("W").sum()
    wk["ret"] = wk["close"].pct_change()
    wk.index = align_weekday(wk.index)
    return wk


def roll_z(s: pd.Series, window: int = DEFAULT_Z_ROLL,
           min_periods: int = DEFAULT_MIN_PERIODS) -> pd.Series:
    """滚动 z-score 标准化（phase0 口径：window=52, min_periods=26）。"""
    m = s.rolling(window, min_periods=min_periods).mean()
    sd = s.rolling(window, min_periods=min_periods).std()
    return (s - m) / sd


def xcorr(lead: pd.Series, lag: pd.Series, lag_range) -> pd.Series:
    """交叉相关：lead 超前 k 周。有效对少于 30 返回 NaN。"""
    out = {}
    for k in lag_range:
        pair = pd.concat([lead.shift(k).rename("lead"), lag.rename("lag")], axis=1).dropna()
        out[k] = pair["lead"].corr(pair["lag"]) if len(pair) > 30 else np.nan
    return pd.Series(out).rename("corr")


def judge(corr_tbl: pd.DataFrame, pass_window: tuple[int, int],
          pass_corr: float, noise_band: float,
          null_median: float | None = None) -> list[dict]:
    """预注册判定（协议口径，判定线在跑数据前写死）。

    - PASS：峰值 corr > pass_corr 且峰值位置位于 pass_window 内
    - NO_TRANSMISSION：|corr| 峰值 < 判据线（默认 noise_band）
    - GREY：其余（登记评估，不调参）

    null_median（协议第9.1节表述修订）：给了就用"零分布中位数"作「无传导」判据，
    此时 noise_band 降级为描述"弱信号"的带，不再决定判定。不传则行为与 M0 逐位一致
    （回归校验依赖这一点）。
    """
    verdicts = []
    lo, hi = pass_window
    no_trans_line = noise_band if null_median is None else null_median
    for name in corr_tbl.columns:
        c = corr_tbl[name].dropna()
        if c.empty:
            verdicts.append({"metric": name, "status": "NO_DATA"})
            continue
        k_best = c.abs().idxmax()
        c_best = float(c.loc[k_best])
        if lo <= k_best <= hi and c_best > pass_corr:
            status = "PASS"
        elif abs(c_best) < no_trans_line:
            status = "NO_TRANSMISSION"
        else:
            status = "GREY"
        verdicts.append({"metric": name, "status": status,
                         "k_best": int(k_best), "corr": round(c_best, 3)})
    return verdicts


STATUS_CN = {"PASS": "✅ 传导迹象成立",
             "NO_TRANSMISSION": "❌ 无传导迹象",
             "GREY": "⚠️ 信号弱/滞后位置不对，需换链评估",
             "NO_DATA": "⚠️ 样本不足，无法判定"}
