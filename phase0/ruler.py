"""Ruler: segment-wise circular-shift calibration for one lead/lag pair.

可复用的「尺子」。输入一对周频序列、分段方案、滞后范围与窗口，输出：
窗口内峰值（值、落点 k、n）、分段循环平移零分布（全平移 / 远平移）、
块自助 95% 区间、有效独立平移量估计、以及按段重标的等效阈值（p70 与 p95）。

实现不复制处理链：周频对齐 / 滚动 z / 段内配对 / 交叉相关直接复用
`phase0/run_batch1.py`，零分布与块自助复用 `phase0/run_null_calibration.py`
的同名函数（`null_curve` / `describe` / `mbb` / `acf_tau`）。本文件只做参数化
编排，不另写第二份统计逻辑。

接口纪律：
  1. `segments` 必填，不提供「不传就整段一个阈值」的默认路径。
  2. 阈值是段的函数：每段各自给 p70 / p95，不返回跨段共用的常数。
  3. 比例一律以「分数 + 区间」返回（`(hit, total)` 与 `(lo, hi)`），
     不在返回值里给两位小数的点估计。

本模块不属预注册，不参与任何已发布判定，也不写入过程账本。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

PHASE0 = Path(__file__).resolve().parent
if str(PHASE0) not in sys.path:
    sys.path.insert(0, str(PHASE0))

import run_batch1 as rb  # noqa: E402  处理链的唯一实现
import run_null_calibration as rnc  # noqa: E402  零分布与块自助的唯一实现

FAR_MIN = rnc.FAR_MIN
N_BOOT = rnc.N_BOOT
SEED = rnc.SEED


# ---------------------------------------------------------------- helpers


def _as_series(s, name: str) -> pd.Series:
    s = pd.Series(s).astype(float)
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index)
    s = s[~s.index.duplicated(keep="last")].sort_index().dropna()
    s.name = name
    return s


def _pair(lead_z: pd.Series, lag_z: pd.Series, k: int, span) -> pd.DataFrame:
    """段内配对：t 与 t+k 都落在段内（与 run_batch1.seg_xcorr 同一口径）。"""
    start, end = span
    shifted = lag_z.shift(-k)
    pair = pd.concat([lead_z.rename("lead"), shifted.rename("lag")], axis=1)
    last_t = end - pd.Timedelta(weeks=k)
    return pair.loc[(pair.index >= start) & (pair.index <= last_t)].dropna()


def corr_ci(lead_z: pd.Series, lag_z: pd.Series, k: int, span, block: int,
            nrep: int = N_BOOT, seed: int = SEED):
    """Peak correlation 的循环块自助 95% 区间（段内成对重采样，块长 block 周）。"""
    pair = _pair(lead_z, lag_z, k, span)
    x = pair["lead"].to_numpy(float)
    y = pair["lag"].to_numpy(float)
    n = len(x)
    if n < 4 or block < 1:
        return None
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(n / block))
    st = rng.integers(0, n, size=(nrep, nb))
    idx = ((st[:, :, None] + np.arange(block)[None, None, :]) % n).reshape(nrep, nb * block)[:, :n]
    xb, yb = x[idx], y[idx]
    xm, ym = xb.mean(axis=1), yb.mean(axis=1)
    num = (xb * yb).mean(axis=1) - xm * ym
    den = np.sqrt((xb * xb).mean(axis=1) - xm ** 2) * np.sqrt((yb * yb).mean(axis=1) - ym ** 2)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = num / den
    r = r[np.isfinite(r)]
    if len(r) < 10:
        return None
    return float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _cell(hit: int, total: int, band) -> str:
    if hit == 0 or band is None:
        return f"{hit}/{total}"
    return f"{hit}/{total}（{_pct(band[1])}–{_pct(band[2])}）"


# ---------------------------------------------------------------- results


@dataclass
class NullView:
    """某一版零（全平移或远平移）的分布、阈值与命中。"""

    version: str
    values: np.ndarray
    p70: float
    p95: float
    max: float
    median: float
    rho1: float
    tau: float
    neff: float
    block: int
    hit_p70: tuple
    hit_p95: tuple
    hit_peak: tuple
    band_p70: tuple | None
    band_p95: tuple | None
    band_peak: tuple | None

    @property
    def n(self) -> int:
        return len(self.values)


@dataclass
class SegmentResult:
    name: str
    start: pd.Timestamp
    end: pd.Timestamp
    peak_k: int
    peak_corr: float
    peak_n: int
    corr_ci: tuple | None
    all_shifts: NullView
    far_shifts: NullView


@dataclass
class RulerReport:
    lag_range: tuple
    window: tuple
    far_min: int
    n_boot: int
    seed: int
    segments: list[SegmentResult] = field(default_factory=list)

    def to_markdown(self) -> str:
        out = [
            f"| 段 | 窗口峰值 | n | P(≥峰值) 全 | P(≥峰值) 远 | P(≥p70) 全 | P(≥p95) 全 "
            f"| p70 全 | p95 全 | p95 远 | N_eff 全 | 峰值 95% 区间 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for s in self.segments:
            a, f = s.all_shifts, s.far_shifts
            ci = "—" if s.corr_ci is None else f"{s.corr_ci[0]:+.2f}–{s.corr_ci[1]:+.2f}"
            out.append(
                f"| {s.name} | {s.peak_corr:+.4f} @ k={s.peak_k} | {s.peak_n} "
                f"| {_cell(*a.hit_peak, a.band_peak)} | {_cell(*f.hit_peak, f.band_peak)} "
                f"| {_cell(*a.hit_p70, a.band_p70)} | {_cell(*a.hit_p95, a.band_p95)} "
                f"| {a.p70:.2f} | {a.p95:.2f} | {f.p95:.2f} | {a.neff:.1f} | {ci} |")
        return "\n".join(out)


# ---------------------------------------------------------------- core


def _null_view(values: np.ndarray, peak: float, version: str) -> NullView:
    d = rnc.describe(values, peak)
    block = 2 * d["b"]
    hit_p70 = int(np.sum(values >= d["p70"]))
    hit_p95 = int(np.sum(values >= d["p95"]))
    hit_peak = int(np.sum(values >= peak))
    return NullView(
        version=version,
        values=values,
        p70=d["p70"], p95=d["p95"], max=d["max"], median=d["median"],
        rho1=d["rho1"], tau=d["tau"], neff=d["neff"], block=block,
        hit_p70=(hit_p70, len(values)), hit_p95=(hit_p95, len(values)),
        hit_peak=(hit_peak, len(values)),
        band_p70=rnc.mbb(values, d["p70"], block) if hit_p70 else None,
        band_p95=rnc.mbb(values, d["p95"], block) if hit_p95 else None,
        band_peak=rnc.mbb(values, peak, block) if hit_peak else None,
    )


def measure(lead, lag, segments, lag_range, window, *, far_min: int = FAR_MIN,
            n_boot: int = N_BOOT, seed: int = SEED) -> RulerReport:
    """对一对序列逐段校准。

    lead / lag : 周频序列（index 为周标签，通常是周五）；本函数按已发布处理链
                 做 52 周滚动 z（`run_batch1.roll_z`），调用方不要预先 z 化。
    segments   : [(name, start, end), ...]，必填；每段独立零分布、独立阈值。
    lag_range  : (k_min, k_max)，含端点。
    window     : (w_min, w_max)，含端点，须落在 lag_range 内。
    """
    if segments is None:
        raise TypeError("segments 必填：阈值是段的函数，不提供整段共用的默认阈值")
    segments = list(segments)
    if not segments:
        raise ValueError("segments 不能为空")
    k0, k1 = int(lag_range[0]), int(lag_range[1])
    w0, w1 = int(window[0]), int(window[1])
    if w1 < w0:
        raise ValueError(f"window 上界 {w1} 小于下界 {w0}")
    if w0 < k0 or w1 > k1:
        raise ValueError(f"window {window} 必须落在 lag_range {lag_range} 内")
    lags = list(range(k0, k1 + 1))

    lead = _as_series(lead, "lead")
    lag = _as_series(lag, "lag")
    lz = rb.roll_z(lead)
    gz = rb.roll_z(lag)

    report = RulerReport(lag_range=(k0, k1), window=(w0, w1),
                         far_min=far_min, n_boot=n_boot, seed=seed)
    for name, start, end in segments:
        span = (pd.Timestamp(start), pd.Timestamp(end))
        pub = rb.seg_xcorr(lz, gz, *span, lags=lags)
        k, obs, n = rnc.peak_in_window(pub, window=(w0, w1))
        pos, _abs, dist, _shifts, _single = rnc.null_curve(
            lz, gz, span, lags=lags, window=(w0, w1))
        mask = dist >= far_min
        all_view = _null_view(pos, obs, "all")
        far_view = _null_view(pos[mask], obs, "far")
        ci = corr_ci(lz, gz, k, span, block=all_view.block, nrep=n_boot, seed=seed)
        report.segments.append(SegmentResult(
            name=str(name), start=span[0], end=span[1], peak_k=k, peak_corr=obs,
            peak_n=n, corr_ci=ci, all_shifts=all_view, far_shifts=far_view))
    return report
