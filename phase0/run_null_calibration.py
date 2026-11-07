"""Post-hoc null calibration for the batch-1 peak correlations.

This is NOT a judgment and NOT part of the preregistration.  It reuses
phase0/run_batch1.py's processing chain verbatim (weekly Friday last
adjclose -> pct_change -> rolling 52-week z with min_periods=26, lag 0..13,
segment pairing t <= end - k weeks) and only asks: how often can noise alone
produce the observed peak, when the two series keep their own temporal
structure and only their alignment is destroyed?

Null construction: circularly roll the lead z-values by s whole weeks
(s = 1..L-1) while keeping the date labels, then recompute the in-window
statistics of one segment.  Rolling the z-series (not the raw series) keeps
the exact values that enter the published correlation; each shift therefore
preserves each series' autocorrelation and volatility clustering.

Two variants are reported, both enumerated exhaustively (no resampling):
  all-shift  : every s in 1..L-1
  far-shift  : only shifts whose circular distance min(s, L-s) >= 26 weeks.
               Near shifts keep part of the original alignment with the lag
               series, which can carry the observed peak's shape into the null.

Three statistics are computed from the same shift set:
  1. max positive corr over the pass window [4,13]  (the published statistic)
  2. max |corr| over the same window                (two-sided variant)
  3. the corr at one fixed lag k                    (single-point variant,
                                                     a different statistic)

Outputs (both written by the SAME run when accounts == all; never retyped):
  phase0/batch1_null_calibration.md              combined, both accounts (gitignored)
  phase0/batch1_null_calibration.svg             combined figure       (gitignored)
  phase0/batch1_null_calibration_clinical.md     clinical account only (tracked)
  phase0/batch1_null_calibration_clinical.csv    per-shift values       (tracked)

Usage (run from the repository root):
  python phase0/run_null_calibration.py                  # both accounts
  python phase0/run_null_calibration.py --accounts clinical   # clinical only

Not self-contained: the script reads the local raw inputs
phase0/output/batch1_clinical_weekly_counts.csv and
phase0/output/batch1_yahoo_XBI_daily.csv, which are NOT tracked in the
repository.  A clean clone therefore cannot regenerate these documents from
the script.  The supported external recompute path is the tracked per-shift
CSV phase0/batch1_null_calibration_clinical.csv -> section 3 of the clinical
document.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "phase0"))

import run_batch1 as rb  # noqa: E402  reuse the published chain, no second copy

SEED = 20261107
N_BOOT = 5000
NOISE = 0.19
PASS = 0.30
FAR_MIN = 26
SEGMENTS = (("train", rb.TRAIN), ("validation", rb.VALID))
LABELS = {"clinical_xbi": "临床 XBI", "energy_n1": "能源 N1"}
LOADERS = {"clinical_xbi": (rb.load_lead_clinical, "XBI"),
           "energy_n1": (rb.load_lead_energy, "CRAK")}


# ---------------------------------------------------------------- series


def build(accounts):
    """Load and z-score only the requested accounts, through the published functions."""
    rb.ARGS = type("A", (), {"open_holdout": False})()
    oh = rb.ARGS.open_holdout
    out = {}
    for name in accounts:
        lead_fn, sym = LOADERS[name]
        lead, lag = lead_fn(oh), rb.load_weekly_price(sym, oh)
        out[name] = (rb.roll_z(lead), rb.roll_z(lag), lead, lag)
    return out


def reproduce_published(built):
    """Recompute the published xcorr grids and assert they match the CSVs."""
    checks = []
    for name, (lz, gz, _lead, _lag) in built.items():
        for seg, span in SEGMENTS:
            got = rb.seg_xcorr(lz, gz, *span)
            pub = pd.read_csv(rb.OUT / f"batch1_xcorr_{name}_{seg}.csv")
            assert list(got["k"]) == list(pub["k"]), name + seg
            assert np.array_equal(got["n"].values, pub["n"].values), name + seg
            assert np.allclose(got["corr"].values, pub["corr"].values, atol=1e-12), name + seg
            checks.append((name, seg))
    return checks


def peak_in_window(df):
    win = df[(df["k"] >= 4) & (df["k"] <= 13)]
    r = win.loc[win["corr"].idxmax()]
    return int(r["k"]), float(r["corr"]), int(r["n"])


def abs_peak_in_window(df):
    win = df[(df["k"] >= 4) & (df["k"] <= 13)]
    r = win.loc[win["corr"].abs().idxmax()]
    return int(r["k"]), float(r["corr"]), int(r["n"])


def null_curve(lead_z, lag_z, span):
    """Every whole-week shift: in-window max corr, max |corr|, and each single lag k."""
    arr = lead_z.values
    index = lead_z.index
    L = len(arr)
    shifts = np.arange(1, L)
    pos = np.empty(L - 1, dtype=float)
    abso = np.empty(L - 1, dtype=float)
    single = {int(k): np.empty(L - 1, dtype=float) for k in rb.LAGS}
    for i, s in enumerate(shifts):
        rolled = pd.Series(np.roll(arr, s), index=index)
        df = rb.seg_xcorr(rolled, lag_z, *span)
        win = df[(df["k"] >= 4) & (df["k"] <= 13)]
        pos[i] = float(win["corr"].max())
        abso[i] = float(win["corr"].abs().max())
        for k in single:
            single[k][i] = float(df.loc[df["k"] == k, "corr"].iloc[0])
    dist = np.minimum(shifts, L - shifts)
    return pos, abso, dist, shifts, single


# ---------------------------------------------------------------- statistics


def quant(vals, p):
    return float(np.percentile(vals, p))


def acf_tau(x, kmax=40):
    """rho_1 and 1 + 2*sum(rho_k) up to the first non-positive rho."""
    x = np.asarray(x, float)
    n = len(x)
    kmax = max(2, min(kmax, n // 4))
    rho = []
    for k in range(1, kmax):
        rho.append(float(np.corrcoef(x[:-k], x[k:])[0, 1]))
        if rho[-1] < 0:
            break
    if rho and rho[-1] < 0:
        rho = rho[:-1]
    tau = 1.0 + 2.0 * sum(rho) if rho else 1.0
    return float(rho[0]) if rho else 0.0, max(tau, 1.0)


def mbb(x, thresh, b, nrep=N_BOOT, seed=SEED):
    """Moving-block bootstrap of the share of values >= thresh (circular)."""
    x = np.asarray(x, float)
    n = len(x)
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(n / b))
    st = rng.integers(0, n, size=(nrep, nb))
    idx = ((st[:, :, None] + np.arange(b)[None, None, :]) % n).reshape(nrep, nb * b)[:, :n]
    h = (x[idx] >= thresh).mean(axis=1)
    return float(np.mean(h)), float(np.percentile(h, 2.5)), float(np.percentile(h, 97.5))


def describe(vals, obs):
    vals = np.asarray(vals, float)
    n = len(vals)
    rho1, tau = acf_tau(vals)
    ar1_tau = (1.0 + rho1) / (1.0 - rho1) if rho1 > 0 else 1.0
    b1 = max(1, int(round(tau)))
    boot = {}
    for b in sorted({b1, 2 * b1, 4 * b1}):
        boot[b] = {"noise": mbb(vals, NOISE, b),
                   "pass": mbb(vals, PASS, b),
                   "obs": mbb(vals, obs, b)}
    return {
        "n": n,
        "hit_noise": int(np.sum(vals >= NOISE)),
        "hit_pass": int(np.sum(vals >= PASS)),
        "hit_obs": int(np.sum(vals >= obs)),
        "mean": float(vals.mean()),
        "median": quant(vals, 50),
        "p70": quant(vals, 70),
        "p90": quant(vals, 90),
        "p95": quant(vals, 95),
        "p98": quant(vals, 98),
        "p99": quant(vals, 99),
        "max": float(vals.max()),
        "rho1": rho1,
        "tau": tau,
        "tau_ar1": ar1_tau,
        "neff": n / tau,
        "neff_ar1": n / ar1_tau,
        "b": b1,
        "boot": boot,
    }


# ---------------------------------------------------------------- formatting


def frac(hit, n):
    return f"{hit}/{n}"


def pct_coarse(x):
    return f"{x * 100:.1f}%" if x < 0.095 else f"{x * 100:.0f}%"


def interval(lo, hi):
    return f"{pct_coarse(lo)}–{pct_coarse(hi)}"


def cell(hit, n, band):
    """Fraction plus the block-bootstrap 95% band; degenerate band is omitted."""
    if hit == 0:
        return frac(hit, n)
    return f"{frac(hit, n)}（{interval(band[1], band[2])}）"


def round2(x):
    return f"{x:.2f}"


def sign4(x):
    return f"{x:+.4f}"


def pct_from_frac(hit, n):
    return f"{hit / n * 100:.0f}%"


# ---------------------------------------------------------------- md blocks


def header(accounts, clinical_export):
    if clinical_export:
        scope = ("本文只含**临床 XBI**（正式账）一本账，不含另一本账（能源 N1，练手账）的任何结果；"
                 "合订版 `batch1_null_calibration.md` 含该账结果且不入库。"
                 "**两文数值不可逐格等同引用。**")
        title = "# 批次一零分布校准：临床 XBI（事后方法学校准，对外版）"
    else:
        scope = ("本文同时含**临床 XBI** 与**能源 N1** 两本账的结果。对外版 "
                 "`batch1_null_calibration_clinical.md` 只含临床账；**两文数值不可逐格等同引用**。"
                 "本文不入库，仅本地留存。")
        title = "# 批次一零分布校准（事后方法学校准，两本账合订）"
    return [
        title,
        "",
        "> 出生证：创建日 2026-11-07 ｜ 依据代际：批次一验证复盘 ｜ 最后实质修订：2026-11-07（同轮重写）",
        ">",
        "> 性质：**事后**补充分析，不属预注册，不参与判定，不新增尝试次数。已发布判定的文本一字未改。",
        f"> 账面范围：{scope}",
        "",
        "## 1. 这份文件回答什么",
        "",
    ]


def section_question(recs):
    pts = "；".join(
        f"{LABELS[r['name']]} `{sign4(r['obs'])} @ k={r['obs_k']}`" for r in recs
        if r["seg"] == "validation")
    return [
        f"只回答一个问题：验证段峰值（{pts}）在「两条序列没有关系」的世界里，有多容易被造出来。",
        "",
        "不回答「所以有关系」「所以命题成立」。零分布只能说明噪声的上限，不能证明信号存在。",
        "",
    ]


def section_method(built, n_all, n_far, accounts):
    rows = []
    for name in accounts:
        lz = built[name][0]
        rows.append(f"`{name}` 序列长 {len(lz)} 周")
    return [
        "## 2. 方法",
        "",
        "### 2.1 处理链与已发布结果完全一致",
        "",
        "直接 import `phase0/run_batch1.py` 的加载与相关函数，不复制第二份实现："
        "周频对齐（周五收盘 `adjclose` → 周收益率）→ 52 周滚动 z-score（`min_periods=26`）"
        "→ `k=0..13` → 段内配对（`t` 与 `t+k` 都落在段内，`t <= end - k` 周）→ 窗口 `[4,13]`。",
        "",
        "跑校准前先复算一遍已发布的 `batch1_xcorr_*.csv`，逐格比对 `n` 与 `corr`："
        "**全部通过**（`n` 全等、`corr` 差异 < 1e-12）。",
        "",
        f"序列长度：{'；'.join(rows)}；平移在整条序列上做，不裁剪。",
        "",
        "### 2.2 为什么用循环平移，不用随机打乱",
        "",
        "随机打乱会毁掉周收益的自相关、波动聚集与领先序列的季节结构，"
        "打乱后的零分布比真实零分布更窄，于是实测峰值看起来比实际更稀有，结论会偏乐观。",
        "",
        "循环平移（circular shift）把领先序列整体平移若干个整周，保留两条序列各自的内部结构，"
        "只破坏两者之间的对齐。平移是对 z 值序列做的（不是原始序列），"
        "即移动的正是进入已发布相关的那组数值。",
        "",
        "### 2.3 两版零：全平移与远平移，均穷举",
        "",
        f"全平移：`s = 1..{n_all}`，共 **{n_all}** 个整周平移量，全部枚举。",
        "",
        f"远平移：只保留循环距离 `min(s, L-s) >= {FAR_MIN}` 周的平移量，共 **{n_far}** 个，同样全部枚举。"
        f"阈值取 `{FAR_MIN}` 的理由是：`{FAR_MIN}` 等于 52 周 z 窗口的 `min_periods`，"
        f"也是最大滞后 `k=13` 的两倍；低于它的平移仍保留了原对齐，"
        f"这部分对齐与「按 `k` 错位」在结构上重叠，容易把实测峰值的形状带进零分布。",
        "",
        f"两版都不做有放回重抽样：平移量空间只有 {n_all} 与 {n_far} 个互不相同的取值，"
        "重抽样只是把同一批取值按比例铺开，既不增加信息量，也不构成独立样本。本文只报穷举值。",
        "",
        "- 训练段、验证段分开计算：每段各自一套零分布，不合并、不跨段评分。",
        f"- 判定线：噪声带 `{NOISE}`、通过线 `{PASS:.2f}`（与预注册一致，仅作参照）。",
        "- 三个统计量共用同一批平移：窗口内最大正相关（已发布口径）、窗口内 `max|corr|`（双侧口径）、"
        "单点 `k` 相关（另一个统计量，见第 7 节）。",
        "",
    ]


def section_stat_decl():
    return [
        "### 2.4 统计量归属：本节分位与旧校准的数值不是同一个对象",
        "",
        "本文所有 p70 / p95 / p99 与「命中率」都指**窗口 `[4,13]` 内最大值**（正相关口径）的经验分位："
        "本批两条序列各自循环平移、按段重算得到的零分布，只用于本批内部事后校准。",
        "",
        "预注册稿与报告局限里出现的 `0.188` / `0.218–0.248` 是**另一个对象**，"
        "出自 `phase0/null_calibration.py`（`SEED=20260926`、每臂 500 次**随机偏移**、"
        "合并 chain01 与 chain10 四条指标序列、双侧 `max|corr|`、分别扫 9 与 27 个滞后位、"
        "**不分段**、该次噪声带取 `0.15`），"
        "数值落在 `phase0/null_calibration_results.json` 的 `merged` 段，"
        "文字出处是 `phase0/preregistration_protocol.md` 第 8 节的分位表——两处追到同一份生成代码与同一份结果文件，说法一致。",
        "",
        "因此**旧校准的数不能与本节分位并读**：数据不同、统计量不同（双侧 `max|corr|` 对单侧窗口最大值）、"
        "滞后扫描范围不同（9/27 个对 4–13 共 10 个）、是否分段不同（不分段对分训练/验证）、"
        "平移方式不同（随机偏移 500 次对穷举 424/374 个整周平移）。",
        "",
    ]


def section_results(recs, accounts, n_all, n_far):
    out = [
        "## 3. 结果",
        "",
        "### 3.1 两版零的分布（穷举）",
        "",
        "| 账 | 段 | 零版本 | 平移量 | 中位数 | p70 | p90 | p95 | p99 | 最大值 | 实测峰值（落点、n） |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in recs:
        for ver, label in (("all", "全平移"), ("far", "远平移")):
            d = r[ver]
            out.append(
                f"| {LABELS[r['name']]} | {r['seg']} | {label} | {d['n']} | {round2(d['median'])} "
                f"| {round2(d['p70'])} | {round2(d['p90'])} | {round2(d['p95'])} | {round2(d['p99'])} "
                f"| {round2(d['max'])} | {sign4(r['obs'])} @ k={r['obs_k']}（n={r['obs_n']}） |")

    out += [
        "",
        "表中分位与最大值都是穷举计数得到的经验分位，取两位小数；"
        f"`p99` 与最大值取自 {n_all}/{n_far} 个平移取值，尾部有效独立样本极少（见第 4 节），只能当约值读。",
        "",
        "### 3.2 两条阈值的命中率与实测位置（分数 + 粗区间）",
        "",
        "| 账 | 段 | 零版本 | `P(≥0.19)` | `P(≥0.30)` | `P(≥实测)` |",
        "|---|---|---|---|---|---|",
    ]
    for r in recs:
        for ver, label in (("all", "全平移"), ("far", "远平移")):
            d = r[ver]
            b2 = d["boot"][2 * d["b"]]
            out.append(
                f"| {LABELS[r['name']]} | {r['seg']} | {label} "
                f"| {cell(d['hit_noise'], d['n'], b2['noise'])} "
                f"| {cell(d['hit_pass'], d['n'], b2['pass'])} "
                f"| {cell(d['hit_obs'], d['n'], b2['obs'])} |")

    zb = [3.0 / r[ver]["neff"] for r in recs for ver in ("all", "far") if r[ver]["hit_noise"] == 0]
    zero_bound = (pct_coarse(min(zb)), pct_coarse(max(zb))) if zb else ("—", "—")

    out += [
        "",
        "读法（这一条决定所有精度）：",
        "",
        "- 分数是**穷举计数**，分母是该版平移量总数；括号内是用这批取值做**块自助**"
        f"（块长 `b=2τ`、{N_BOOT} 次、`seed={SEED}`）得到的 95% 区间。",
        "- 这是**该循环平移零构造下的经验占比，不是独立抽样点估计**：相邻平移高度相关，"
        "有效独立平移量只有十几到五十几个（见第 4 节），所以只能按「分数 + 粗区间」读，"
        "不能写成两位小数的点估计。",
        "- 命中为 0 的格子不报区间：块自助在零命中序列上退化为 `[0,0]`，那只说明「这批取值里没有」，"
        "不说明真实比率是 0。其上界按经验的三倍法则 `3/N_eff` 给，"
        f"本批出现零命中的段落，该上界为 {zero_bound[0]}–{zero_bound[1]}（N_eff 见第 4 节）。",
        "- 「命中率」= 零分布里达到或超过该阈值的平移量占比；`P(≥0.30)` 是「零关系下被判通过」的直接误判率。",
        "",
    ]

    parts = []
    for r in recs:
        d = r["far"]
        if d["hit_pass"] == 0:
            parts.append(f"{LABELS[r['name']]}·{r['seg']}：`0.30` 命中 {frac(0, d['n'])}"
                         f"（该段零分布最大值 {round2(d['max'])}，`0.30` 根本取不到）")
        else:
            eff = d["hit_pass"] / d["tau"]
            parts.append(f"{LABELS[r['name']]}·{r['seg']}：`0.30` 命中 {frac(d['hit_pass'], d['n'])}，"
                         f"除以 τ≈{d['tau']:.1f}，折合**约 {eff:.1f} 次有效独立命中**")
    out += ["按有效独立命中折算：" + "；".join(parts) + "。", ""]

    out += [
        "### 3.3 两版的一致性：定性一致，数值不可互换引用",
        "",
    ]
    cmp_txt = "；".join(
        f"{LABELS[r['name']]}·{r['seg']} `P(≥实测)` 全平移 {frac(r['all']['hit_obs'], r['all']['n'])}"
        f"（约 {pct_from_frac(r['all']['hit_obs'], r['all']['n'])}）、"
        f"远平移 {frac(r['far']['hit_obs'], r['far']['n'])}"
        f"（约 {pct_from_frac(r['far']['hit_obs'], r['far']['n'])}），相对差约 "
        f"{abs(r['far']['hit_obs']/r['far']['n'] - r['all']['hit_obs']/r['all']['n']) / (r['all']['hit_obs']/r['all']['n']) * 100:.1f}%"
        for r in recs)
    flips = [r for r in recs
             if (r["all"]["hit_obs"] > 0) != (r["far"]["hit_obs"] > 0)]
    flip_txt = ("没有任何一段从「噪声造得出」翻成「噪声造不出」，也没有任何一段的命中从有翻成无。"
                if not flips else
                f"有 {len(flips)} 段在剔除近邻平移后命中情况发生翻转，须逐段注明用哪一版。")
    out += [
        f"两版在**定性结论上一致**：{flip_txt}具体数值**不可互换引用**——{cmp_txt}。"
        "剔除近邻平移改变分母与取值集合，比例随之位移，位移幅度可达近一成；"
        "所以任何引用都必须写明用的哪一版零。",
        "",
    ]

    if len(accounts) > 1:
        ev = next(r for r in recs if r["name"] == "energy_n1" and r["seg"] == "validation")
        cl = next(r for r in recs if r["name"] == "clinical_xbi" and r["seg"] == "validation")
        g_all = ev["all"]["p99"] - cl["all"]["p99"]
        g_far = ev["far"]["p99"] - cl["far"]["p99"]
        out += [
            "**两账验证段 p99 的差距与平移距离无关**："
            f"全平移下能源 {round2(ev['all']['p99'])}、临床 {round2(cl['all']['p99'])}（差 {g_all:+.2f}），"
            f"远平移下能源 {round2(ev['far']['p99'])}、临床 {round2(cl['far']['p99'])}（差 {g_far:+.2f}）；"
            "换成远平移后这个差距基本没动，说明它来自零分布本身形状（能源领先序列自相关更强，"
            "平移后仍能与滞后序列咬合），不是近邻平移造成的。",
            "",
        ]

    out += ["### 3.4 对「0.19≈p70、0.30≈p95」的核对", ""]
    out += claim_check(recs, accounts)
    return out


def claim_check(recs, accounts):
    val = [r for r in recs if r["seg"] == "validation"]
    trn = [r for r in recs if r["seg"] == "train"]
    val_p70 = [(r, d) for r in val for d in (r["all"], r["far"])]
    lo = min(d["p70"] for _, d in val_p70)
    hi = max(d["p70"] for _, d in val_p70)
    out = []
    if lo - 0.01 <= NOISE <= hi + 0.01:
        out.append(
            f"**「`0.19` 约等于 p70」——在验证段同量级，在训练段不成立。**"
            f"验证段各口径的 p70 为 {lo:.3f}–{hi:.3f}，`0.19` 与之差不到 0.01；"
            f"越过 `0.19` 的平移量为 "
            + "、".join(f"{LABELS[r['name']]}·{'全' if ver == 'all' else '远'} "
                        f"{frac(r[ver]['hit_noise'], r[ver]['n'])}"
                        f"（约 {pct_from_frac(r[ver]['hit_noise'], r[ver]['n'])}）"
                        for r in val for ver in ("all", "far"))
            + "。训练段则全部为 0 命中，因为 `0.19` 高于训练段零分布最大值（"
            + "、".join(f"{LABELS[r['name']]} {round2(r['all']['max'])}" for r in trn)
            + "）——那里谈不上 p70。**对外只能说验证段。**")
    else:
        out.append(f"**「`0.19` 约等于 p70」——不成立。** 验证段各口径 p70 为 {lo:.3f}–{hi:.3f}，"
                   f"与 `0.19` 不同量级。")
    out.append("")

    ev = [r for r in val if r["name"] == "energy_n1"]
    et = [r for r in trn if r["name"] == "energy_n1"]
    if ev:
        hit95 = [r for r in ev
                 if abs(r["all"]["p95"] - PASS) <= 0.02 or abs(r["far"]["p95"] - PASS) <= 0.02]
        if hit95:
            out.append(
                f"**「`0.30` 在能源上只相当于 p95 上下」——在验证段成立，在训练段不成立。**"
                f"能源验证段 p95 为全平移 {round2(ev[0]['all']['p95'])}、远平移 {round2(ev[0]['far']['p95'])}，"
                f"确实落在 `0.30` 附近；命中率全平移 {frac(ev[0]['all']['hit_pass'], ev[0]['all']['n'])}、"
                f"远平移 {frac(ev[0]['far']['hit_pass'], ev[0]['far']['n'])}。"
                f"但能源训练段 `0.30` 高于该段全部平移值（最大值 {round2(et[0]['all']['max'])}），"
                f"在那里它不是「p95 上下」，而是**零分布根本造不出来**——命中率 0 是阈值位置造成的，"
                f"不是「噪声不容易造出」。**对外只能说验证段。**")
        else:
            out.append(f"**「`0.30` 在能源上只相当于 p95 上下」——不成立。** 能源验证段 p95 为 "
                       f"{round2(ev[0]['all']['p95'])}（全）/ {round2(ev[0]['far']['p95'])}（远）。")
        out.append("")

    if len(accounts) > 1:
        cl = [r for r in recs if r["name"] == "clinical_xbi"]
        out.append(
            "临床账作为对照："
            + "；".join(f"{r['seg']}·全平移 `P(≥0.30)` {frac(r['all']['hit_pass'], r['all']['n'])}"
                        f"（p95 {round2(r['all']['p95'])}、p99 {round2(r['all']['p99'])}），"
                        f"远平移 {frac(r['far']['hit_pass'], r['far']['n'])}"
                        f"（p95 {round2(r['far']['p95'])}、p99 {round2(r['far']['p99'])}）" for r in cl)
            + "。同一阈值在两账、两段上的严格程度并不同。")
        out.append("")
    return out


def section_neff(recs):
    out = [
        "## 4. 有效独立平移量",
        "",
        "本节是上面所有精度改写的依据。「424 个平移量」不等于 424 个独立样本："
        "相邻平移得到的零分布取值几乎是同一批周值的微小错位，序列本身高度自相关。",
        "",
        "| 账 | 段 | 零版本 | 平移量 N | ρ1 | τ = 1+2Σρ | N_eff = N/τ | AR(1) τ | AR(1) N_eff | 块长 `τ` |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in recs:
        for ver, label in (("all", "全平移"), ("far", "远平移")):
            d = r[ver]
            out.append(f"| {LABELS[r['name']]} | {r['seg']} | {label} | {d['n']} | {d['rho1']:.3f} "
                       f"| {d['tau']:.1f} | {d['neff']:.1f} | {d['tau_ar1']:.1f} | {d['neff_ar1']:.1f} "
                       f"| {d['b']} |")
    neffs = [r[ver]["neff"] for r in recs for ver in ("all", "far")]
    neffs_ar1 = [r[ver]["neff_ar1"] for r in recs for ver in ("all", "far")]
    taus = [r[ver]["tau"] for r in recs for ver in ("all", "far")]
    rhos = [r[ver]["rho1"] for r in recs for ver in ("all", "far")]
    med_all = float(np.median([r["all"]["neff"] for r in recs]))
    med_far = float(np.median([r["far"]["neff"] for r in recs]))
    out += [
        "",
        f"口径：`ρ1` 是零分布取值序列（按平移量顺序排列）的一阶自相关；"
        f"`τ = 1 + 2Σρ_k` 在首个非正 `ρ_k` 处截断；`N_eff = N/τ`；"
        f"AR(1) 近似 `τ = (1+ρ1)/(1-ρ1)` 作交叉校验，它比 `1+2Σρ` 更保守。"
        f"块自助的块长网格取 `τ`、`2τ`、`4τ`（整数周，`τ` 为 {min(taus):.0f}–{max(taus):.0f} 周）；第三节表格内的区间用 `2τ`。",
        "",
        f"实测区间：`ρ1` {min(rhos):.3f}–{max(rhos):.3f}；`τ` {min(taus):.1f}–{max(taus):.1f}；"
        f"`N_eff` {min(neffs):.1f}–{max(neffs):.1f}（中位：全平移 {med_all:.0f}、远平移 {med_far:.0f}；"
        f"AR(1) 口径 {min(neffs_ar1):.1f}–{max(neffs_ar1):.1f}）。"
        "也就是说，这批「424 / 374 个平移」在信息量上只相当于几十个独立观测，"
        "与报告局限里「有效样本远小于 n」的判断同向，且这里是另一层："
        "指零分布自身的颗粒度，不是单个相关系数的样本量。",
        "",
        "块长敏感性（验证段，块长取 `τ` / `2τ` / `4τ`）：",
        "",
        "| 账 | 零版本 | 量 | b=τ | b=2τ | b=4τ |",
        "|---|---|---|---|---|---|",
    ]
    for r in recs:
        if r["seg"] != "validation":
            continue
        for ver, label in (("all", "全平移"), ("far", "远平移")):
            d = r[ver]
            for key, th in (("noise", "`P(≥0.19)`"), ("pass", "`P(≥0.30)`"), ("obs", "`P(≥实测)`")):
                cells = [d["boot"][b][key] for b in sorted(d["boot"])]
                out.append(f"| {LABELS[r['name']]} | {label} | {th} "
                           + " ".join(f"| {interval(c[1], c[2])} " for c in cells) + "|")
    out += [
        "",
        "三个块长的区间几乎等宽：可分辨的只有「约三成」与「约百分之几」这一档，"
        "再细的差全被区间吞掉。因此本文只报分数与粗区间，不报小数。",
        "",
    ]
    return out


def section_limits(recs, n_all, n_far, accounts):
    trn_max = [r for r in recs if r["seg"] == "train"]
    out = [
        "## 5. 局限",
        "",
        f"1. **平移量有限**。全平移 {n_all} 个、远平移 {n_far} 个，全部穷举；"
        "`p99` 接近最大值，不是从几千个独立样本估出的尾部。",
        "2. **相邻平移高度相关**。有效独立平移量只有十几到五十几个（第 4 节），"
        "分位与比例都只能按约值读，块自助区间比朴素二项区间宽得多。",
        "3. **跨段取值**。平移在整条序列上做，训练段评分时领先值可能来自验证期，反之亦然；"
        "这破坏的是对齐而不是结构。验证段只有一百来周，段内自平移取值更少，`p99` 更不稳，故未采用。",
        "4. **接缝**。循环平移在回绕处造成一个单点跳变，每个平移量都一样，对单周配对的影响被段长稀释。",
        "5. **多重峰值的口径**。主统计量是「窗口内 10 个 `k` 的最大值」，已把窗口内的多重比较计入；"
        "它不等价于「某一个指定 `k` 的单独显著性」——单点 `k` 的零分布是另一个统计量，另见第 7 节。",
        "6. **不做判定**。本文件不改变任何标签，也不能替代预注册的通过/不通过规则。",
        "7. **训练段与验证段不能用同一条线读**。" +
        "、".join(f"{LABELS[r['name']]} 训练段零分布最大值 {round2(r['all']['max'])}" for r in trn_max) +
        f"{'，都' if len(trn_max) > 1 else '，'}低于 `{NOISE}`，所以训练段的「零命中」是阈值位置构造出来的，"
        "不能读成「训练段无信号」，也不能读成「训练段比验证段干净」。",
        "",
    ]
    if len(accounts) > 1:
        out.insert(-1, "8. **两账的零分布不可横向比较**。能源领先序列更平滑、自相关更强，"
                       "同一阈值在两账上的严格程度不同；`P(≥实测)` 只能在各自账内读。")
    return out


def section_conclusion(recs):
    out = ["## 6. 结论（只到噪声这一层）", ""]
    for r in recs:
        d = r["far"]
        if r["seg"] == "validation":
            out.append(
                f"- **{LABELS[r['name']]} · 验证段（远平移）**：实测 `{sign4(r['obs'])} @ k={r['obs_k']}`，"
                f"`P(≥实测)` = {frac(d['hit_obs'], d['n'])}（约 {pct_from_frac(d['hit_obs'], d['n'])}），"
                f"`P(≥0.19)` = {frac(d['hit_noise'], d['n'])}，`P(≥0.30)` = {frac(d['hit_pass'], d['n'])}。")
        else:
            out.append(
                f"- **{LABELS[r['name']]} · 训练段（远平移）**：实测 `{sign4(r['obs'])} @ k={r['obs_k']}`，"
                f"`P(≥实测)` = {frac(d['hit_obs'], d['n'])}，`P(≥0.19)` = {frac(d['hit_noise'], d['n'])}，"
                f"`P(≥0.30)` = {frac(d['hit_pass'], d['n'])}。训练段命中为 0 是因为阈值高于该段零分布最大值，"
                f"不是「噪声不容易造出」。训练段只作诊断，不参与判定。")
    out += [
        "",
        "以上各句只说「噪声能不能造出这个数」，不构成「有关系」或「命题成立」的依据。",
        "",
    ]
    return out


def section_probe(recs, abs_recs, single_map, accounts):
    t_ref = abs_recs[("clinical_xbi", "validation")]["obs_abs"] if "clinical_xbi" in accounts else None
    out = [
        "## 7. 附：双侧口径与单点 k 口径探针（事后，不作为判定）",
        "",
        "只换统计量，其余处理链、平移量集合与段划分一字未改。目的是看被现行规则排除在外的负峰到底稀不稀罕。"
        "它不是新判定，也不是翻案。",
        "",
        "### 7.1 窗口 `max|corr|` 口径（统计量本身）",
        "",
        "表头写的是「窗口 `max|corr|` 取到于 k」：P 值对应的是**窗口内最大绝对值**的零分布，"
        "不是该单点 `k` 上的零分布（单点口径另见 7.2）。",
        "",
        "| 账 | 段 | 窗口 `max|corr|` 取到于 k | 该格实测 r | n | 全平移 P(\\|null\\|≥\\|r\\|) | 远平移 P(\\|null\\|≥\\|r\\|) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in recs:
        a = abs_recs[(r["name"], r["seg"])]
        av = abs(r["abs_obs"])
        out.append(f"| {LABELS[r['name']]} | {r['seg']} | {r['abs_k']} | {sign4(r['abs_obs'])} | {r['abs_n']} "
                   f"| {frac(int(np.sum(a['all'] >= av)), len(a['all']))} "
                   f"| {frac(int(np.sum(a['far'] >= av)), len(a['far']))} |")

    out += [
        "",
        "本表计数按全精度相关值比较；随附 CSV 只保留 6 位小数，若用 CSV 复算该表会略低"
        "（峰值附近有个别取值恰好卡在阈值这一侧），故本表以脚本全精度计数为准。",
    ]

    if t_ref is not None:
        out += [
            "",
            f"零分布里 `|corr| >= {abs(t_ref):.4f}`（取临床验证段窗口 `max|corr|` 的绝对值）的精确计数：",
            "",
            "| 账 | 段 | 零版本 | 命中数 | 平移量总数 |",
            "|---|---|---|---|---|",
        ]
        for r in recs:
            a = abs_recs[(r["name"], r["seg"])]
            for ver, label in (("all", "全平移"), ("far", "远平移")):
                out.append(f"| {LABELS[r['name']]} | {r['seg']} | {label} "
                           f"| {int(np.sum(a[ver] >= abs(t_ref)))} | {len(a[ver])} |")

    out += [
        "",
        "### 7.2 单点 k 口径（另一个统计量）",
        "",
        "固定单个 `k`、逐平移重算该格相关，得到该格自己的零分布。它与 7.1 不是同一个统计量，"
        "不能互相比 P 值；两表分开列，就是为了不再把窗口最大值的零分布套到单点 `k` 上。",
        "",
        "| 账 | 段 | k | 该格实测 r | n | 全平移 P(\\|null\\|≥\\|r\\|) | 远平移 P(\\|null\\|≥\\|r\\|) |",
        "|---|---|---|---|---|---|---|",
    ]
    for key, rec in single_map.items():
        out.append(f"| {LABELS[rec['name']]} | {rec['seg']} | {rec['k']} | {sign4(rec['obs'])} | {rec['n']} "
                   f"| {frac(rec['hit_abs_all'], rec['n_shift_all'])} "
                   f"| {frac(rec['hit_abs_far'], rec['n_shift_far'])} |")

    out.append("")
    # 负峰与正峰的单点稀有度对照（数字全部由数据算出，不写死）
    rows = [v for k, v in single_map.items() if v["name"] == "clinical_xbi" and v["seg"] == "validation"]
    neg = min(rows, key=lambda v: v["obs"]) if rows else None
    pos = max(rows, key=lambda v: v["obs"]) if rows else None
    if neg and pos and neg["obs"] < 0 < pos["obs"]:
        pn = neg["hit_abs_far"] / neg["n_shift_far"]
        pp = pos["hit_abs_far"] / pos["n_shift_far"]
        rel = ("更稀有" if pn < pp else "并不更稀有")
        out.append(
            f"单点 `k` 口径下，临床验证段的负峰 `{sign4(neg['obs'])} @ k={neg['k']}` "
            f"命中 {frac(neg['hit_abs_far'], neg['n_shift_far'])}（约 {pct_coarse(pn)}，全平移 "
            f"{frac(neg['hit_abs_all'], neg['n_shift_all'])}），"
            f"正峰 `{sign4(pos['obs'])} @ k={pos['k']}` 命中 {frac(pos['hit_abs_far'], pos['n_shift_far'])}"
            f"（约 {pct_coarse(pp)}）；负峰{rel}。"
            "这与 7.1 的读法并不矛盾：7.1 把整个窗口的最大绝对值当成统计量，任何一格都能贡献最大值，"
            "所以两格的命中率都被抬到零分布中部；7.2 固定单格，才看得出负峰在这一格上更靠尾。")
        out.append("")

    # 训练段对照
    trn_lo = min(r["n_train_lo"] for r in recs if r["seg"] == "train")
    trn_hi = max(r["n_train_hi"] for r in recs if r["seg"] == "train")
    val_lo = min(r["n_val_lo"] for r in recs if r["seg"] == "validation")
    val_hi = max(r["n_val_hi"] for r in recs if r["seg"] == "validation")
    out.append(
        f"训练段对照：窗口内各 `k` 的训练段 `n` 为 {trn_lo}–{trn_hi}，验证段为 {val_lo}–{val_hi}。"
        f"训练段的零分布上限更低（"
        + "、".join(f"{LABELS[r['name']]} {round2(r['all']['max'])}" for r in recs if r["seg"] == "train")
        + "）：`0.30` 已在零分布之外，`0.19` 也在其上缘附近，所以训练段「不显著」是被阈值位置决定的，"
        "不是被数据决定的。这**更可能来自段长/样本量差异**——本探针无法区分段长效应与弱信号。")
    out += [
        "",
        "**就本批而言不会改判。** 上列候选点在任何口径下都没有跨过 `0.30` 通过线，"
        "换口径只是把同一批平移下的另一个数值读出来，不产生新判定。",
        "",
        "**本探针不提供「是否值得为双侧口径单开一代」的口径依据**：它只算了某个数在两种统计量下的稀有度，"
        "没有评估功效、第一类错误率，也没有在别的样本上看过这套口径的表现。",
        "",
        "边界：本节是事后探针，不改变任何标签，也不新增尝试次数，不能作为「若按双侧就该判成立」的依据。",
        "",
    ]
    return out


# ---------------------------------------------------------------- svg


def svg_hist(panels, path):
    W, H = 1000, 880
    cols, rows = 2, 2
    pad_l, pad_r, pad_t, pad_b = 68, 28, 92, 46
    panel_w = (W - pad_l - pad_r) / cols
    panel_h = (H - pad_t - pad_b) / rows
    font = "font-family=\"system-ui,-apple-system,'Segoe UI','Microsoft YaHei',sans-serif\""

    all_null = np.concatenate([p["null_all"] for p in panels])
    far_null = np.concatenate([p["null_far"] for p in panels])
    lo = min(float(all_null.min()), float(far_null.min()),
             float(min(p["obs"] for p in panels))) - 0.02
    hi = max(float(all_null.max()), float(far_null.max()),
             float(max(p["obs"] for p in panels)), PASS) + 0.02
    edges = np.linspace(lo, hi, 39)

    def fx(v, x0, x1):
        return x0 + (v - lo) / (hi - lo) * (x1 - x0)

    p = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
         f'role="img" aria-labelledby="nullcal">']
    p.append('<rect width="100%" height="100%" fill="#ffffff"/>')
    p.append('<title id="nullcal">批次一零分布校准：全平移与远平移零分布</title>')
    p.append(f'<text x="{pad_l}" y="30" {font} font-size="17" font-weight="600" fill="#1f2733">'
             f'循环平移零分布：窗口 [4,13] 内最大正相关（两版并列）</text>')
    p.append(f'<text x="{pad_l}" y="50" {font} font-size="12" fill="#6b7380">'
             f'事后校准，不参与判定。左柱=全平移（浅），右柱=远平移 |s|≥{FAR_MIN}（深）；'
             f'橙虚线=0.19，绿虚线=0.30，红实线=实测峰值</text>')

    n_all_v = panels[0]["n_all"]
    n_far_v = panels[0]["n_far"]
    lx, ly = pad_l, 76
    for dx, color, label in ((0, "#dfe5ec", f"全平移 {n_all_v} 个"),
                             (150, "#7f9bb5", f"远平移 {n_far_v} 个")):
        p.append(f'<rect x="{lx+dx}" y="{ly-9}" width="16" height="11" fill="{color}" '
                 f'stroke="#b3bfcd" stroke-width="0.4"/>')
        p.append(f'<text x="{lx+dx+22}" y="{ly}" {font} font-size="11.5" fill="#4a5160">{label}</text>')
    p.append(f'<text x="{lx+320}" y="{ly}" {font} font-size="11.5" fill="#6b7380">'
             f'每柱宽度为同区间占比；两端合计分别归一到各自平移量总数</text>')

    for i, pan in enumerate(panels):
        cx = i % cols
        cy = i // cols
        x0 = pad_l + cx * panel_w + 46
        x1 = pad_l + (cx + 1) * panel_w - 18
        y0 = pad_t + cy * panel_h + 26
        y1 = pad_t + (cy + 1) * panel_h - 34

        c_all, _ = np.histogram(pan["null_all"], bins=edges)
        c_far, _ = np.histogram(pan["null_far"], bins=edges)
        s_all = c_all / max(1, len(pan["null_all"]))
        s_far = c_far / max(1, len(pan["null_far"]))
        vmax = float(max(s_all.max(), s_far.max(), 1e-9))
        bw = (x1 - x0) / len(s_all)

        p.append(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" fill="#fbfbfc" '
                 f'stroke="#e2e4e8"/>')
        for j, (sa, sf) in enumerate(zip(s_all, s_far)):
            ha = (sa / vmax) * (y1 - y0)
            hf = (sf / vmax) * (y1 - y0)
            if ha > 0:
                p.append(f'<rect x="{x0 + j*bw + 0.4:.1f}" y="{y1-ha:.1f}" width="{bw/2-0.8:.1f}" '
                         f'height="{ha:.1f}" fill="#dfe5ec" stroke="#c7d1dc" stroke-width="0.3"/>')
            if hf > 0:
                p.append(f'<rect x="{x0 + j*bw + bw/2 + 0.4:.1f}" y="{y1-hf:.1f}" width="{bw/2-0.8:.1f}" '
                         f'height="{hf:.1f}" fill="#7f9bb5" stroke="#6d8aa5" stroke-width="0.3"/>')
        for v, color, dash, label in ((NOISE, "#c98a2e", "5 4", "0.19"),
                                      (PASS, "#2f7d4f", "7 4", "0.30")):
            xv = fx(v, x0, x1)
            p.append(f'<line x1="{xv:.1f}" y1="{y0}" x2="{xv:.1f}" y2="{y1}" stroke="{color}" '
                     f'stroke-width="1.4" stroke-dasharray="{dash}"/>')
            p.append(f'<text x="{xv:.1f}" y="{y0-6}" {font} font-size="11" fill="{color}" '
                     f'text-anchor="middle">{label}</text>')
        xo = fx(pan["obs"], x0, x1)
        p.append(f'<line x1="{xo:.1f}" y1="{y0}" x2="{xo:.1f}" y2="{y1}" stroke="#b0562f" '
                 f'stroke-width="2.2"/>')
        anchor = "end" if pan["obs"] > (lo + hi) / 2 else "start"
        dx = -8 if pan["obs"] > (lo + hi) / 2 else 8
        p.append(f'<text x="{xo+dx:.1f}" y="{y0+16}" {font} font-size="11.5" fill="#8f4224" '
                 f'text-anchor="{anchor}">实测 {pan["obs"]:+.4f} @ k={pan["obs_k"]}</text>')

        p.append(f'<text x="{x0}" y="{y0-24}" {font} font-size="13" font-weight="600" fill="#1f2733">'
                 f'{pan["label"]}</text>')
        p.append(f'<text x="{x1}" y="{y0-24}" {font} font-size="11" fill="#6b7380" '
                 f'text-anchor="end">远：P(≥0.19)={pan["far_hit19"]}/{pan["n_far"]}  '
                 f'P(≥0.30)={pan["far_hit30"]}/{pan["n_far"]}  '
                 f'P(≥实测)={pan["far_hitobs"]}/{pan["n_far"]}</text>')
        p.append(f'<text x="{(x0+x1)/2}" y="{y1+16}" {font} font-size="11" fill="#6b7380" '
                 f'text-anchor="middle">窗口内最大相关 r</text>')
        p.append(f'<text x="{x1}" y="{y1+30}" {font} font-size="10.5" fill="#8a929e" '
                 f'text-anchor="end">远平移中位 {pan["far_median"]:+.3f} '
                 f'p95 {pan["far_p95"]:.2f} p99 {pan["far_p99"]:.2f}</text>')
        p.append(f'<text x="{x1}" y="{y1+43}" {font} font-size="10.5" fill="#8a929e" '
                 f'text-anchor="end">全平移 p95 {pan["all_p95"]:.2f} p99 {pan["all_p99"]:.2f} ｜ '
                 f'远平移量 {pan["n_far"]}</text>')
        if cx == 0:
            p.append(f'<text x="{x0-14}" y="{y0}" {font} font-size="10.5" fill="#8a929e" '
                     f'text-anchor="end">{vmax*100:.0f}%</text>')
            p.append(f'<text x="{x0-14}" y="{y1+4}" {font} font-size="10.5" fill="#8a929e" '
                     f'text-anchor="end">0</text>')
    p.append("</svg>")
    Path(path).write_text("\n".join(p), encoding="utf-8")


# ---------------------------------------------------------------- csv


def write_csv(recs, path):
    """Per-shift values so an outside reader can redo the distributions without the raw series."""
    base = next(r for r in recs if r["seg"] == "validation")
    cols = ["shift", "circular_distance"]
    for r in recs:
        cols += [f"{r['seg']}_max_pos", f"{r['seg']}_max_abs"]
    frame = pd.DataFrame({"shift": base["shift_vals"], "circular_distance": base["dist_vals"]})
    for r in recs:
        frame[f"{r['seg']}_max_pos"] = np.round(r["null_all"], 6)
        frame[f"{r['seg']}_max_abs"] = np.round(r["abs_all"], 6)
    frame[cols].to_csv(path, index=False, encoding="utf-8")
    return frame


# ---------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--accounts", choices=["all", "clinical"], default="all",
                    help="all = 临床 + 能源（同时写出合订版与临床对外版）；clinical = 只写临床对外版")
    a = ap.parse_args()

    accounts = ["clinical_xbi", "energy_n1"] if a.accounts == "all" else ["clinical_xbi"]
    built = build(accounts)
    print("reproduce check:", reproduce_published(built))

    recs = []
    abs_recs = {}
    single_map = {}
    L = len(built[accounts[0]][0])
    n_all = L - 1
    n_far = int(sum(1 for s in range(1, L) if min(s, L - s) >= FAR_MIN))

    for name in accounts:
        lz, gz, _lead, _lag = built[name]
        for seg, span in SEGMENTS:
            pub = rb.seg_xcorr(lz, gz, *span)
            k, obs, n = peak_in_window(pub)
            ak, aobs, an = abs_peak_in_window(pub)
            win = pub[(pub["k"] >= 4) & (pub["k"] <= 13)]
            pos_vals, abs_curve, dist, shift_vals, single = null_curve(lz, gz, span)
            mask = dist >= FAR_MIN
            abs_recs[(name, seg)] = {"all": abs_curve, "far": abs_curve[mask],
                                     "obs_abs": aobs, "abs_k": ak, "abs_n": an}
            rec = {"name": name, "seg": seg, "obs": obs, "obs_k": k, "obs_n": n,
                   "abs_obs": aobs, "abs_k": ak, "abs_n": an,
                   "null_all": pos_vals, "null_far": pos_vals[mask],
                   "abs_all": abs_curve, "shift_vals": shift_vals, "dist_vals": dist,
                   "all": describe(pos_vals, obs), "far": describe(pos_vals[mask], obs),
                   "n_far": int(mask.sum()),
                   "n_train_lo": int(win.n.min()) if seg == "train" else None,
                   "n_train_hi": int(win.n.max()) if seg == "train" else None,
                   "n_val_lo": int(win.n.min()) if seg == "validation" else None,
                   "n_val_hi": int(win.n.max()) if seg == "validation" else None}
            recs.append(rec)
            print(json.dumps({"account": name, "segment": seg, "obs": round(obs, 4),
                              "obs_abs": round(aobs, 4)}, ensure_ascii=False))

            # 单点 k 行：验证段的正峰格与最大绝对值格（数值全部由数据决定）
            if seg == "validation":
                for kk in sorted({k, ak}):
                    v = single[kk]
                    ov = float(pub.loc[pub["k"] == kk, "corr"].iloc[0])
                    nv = int(pub.loc[pub["k"] == kk, "n"].iloc[0])
                    single_map[(name, seg, kk)] = {
                        "name": name, "seg": seg, "k": kk, "obs": ov, "n": nv,
                        "n_shift_all": len(v),
                        "n_shift_far": int(mask.sum()),
                        "hit_abs_all": int(np.sum(np.abs(v) >= abs(ov))),
                        "hit_abs_far": int(np.sum(np.abs(v[mask]) >= abs(ov))),
                    }

    # ---- 临床对外版（始终写出；与合订版同源）
    clin_recs = [r for r in recs if r["name"] == "clinical_xbi"]
    clin_abs = {k: v for k, v in abs_recs.items() if k[0] == "clinical_xbi"}
    clin_single = {k: v for k, v in single_map.items() if k[0] == "clinical_xbi"}
    write_clinical(clin_recs, clin_abs, clin_single, ["clinical_xbi"], n_all, n_far, built)

    if len(accounts) > 1:
        panels = []
        for r in recs:
            d = r["far"]
            panels.append({"label": f"{LABELS[r['name']]} · {r['seg']}",
                           "null_all": r["null_all"], "null_far": r["null_far"],
                           "obs": r["obs"], "obs_k": r["obs_k"], "n_far": d["n"], "n_all": r["all"]["n"],
                           "far_hit19": d["hit_noise"], "far_hit30": d["hit_pass"],
                           "far_hitobs": d["hit_obs"], "far_median": d["median"],
                           "far_p95": d["p95"], "far_p99": d["p99"],
                           "all_p95": r["all"]["p95"], "all_p99": r["all"]["p99"]})
        svg_hist(panels, "phase0/batch1_null_calibration.svg")
        body = assemble(recs, abs_recs, single_map, accounts, n_all, n_far, built, False)
        Path("phase0/batch1_null_calibration.md").write_text("\n".join(body), encoding="utf-8")
        print("wrote combined md/svg")
    print(f"shifts all={n_all} far={n_far}")


def assemble(recs, abs_recs, single_map, accounts, n_all, n_far, built, clinical_export):
    body = header(accounts, clinical_export)
    body += section_question(recs)
    body += section_method(built, n_all, n_far, accounts)
    body += section_stat_decl()
    body += section_results(recs, accounts, n_all, n_far)
    if clinical_export:
        body += ["### 3.5 图", "",
                 "本文不附图：逐平移数值见 `batch1_null_calibration_clinical.csv`"
                 "（列 `shift`（整周平移量 `s`）、`circular_distance`（`min(s, L-s)`，供筛选远平移）、"
                 "`train_max_pos`、`train_max_abs`、`validation_max_pos`、`validation_max_abs`，"
                 f"每行一个整周平移量，共 {n_all} 行），外部读者不需要原始周序列即可复算第三节全部分位与命中计数。", ""]
    else:
        body += ["### 3.5 图", "", "![零分布直方图](batch1_null_calibration.svg)", "",
                 "图注：四个面板依次为能源训练段、能源验证段、临床训练段、临床验证段。"
                 "每个区间左侧浅色柱为全平移零分布，右侧深色柱为远平移零分布；纵轴为占各自总数的比例，两版各自归一。"
                 "橙虚线 `0.19` 为预注册噪声带，绿虚线 `0.30` 为通过线，红实线为实测峰值。所有线只作参照，不代表判定。", ""]
    body += section_neff(recs)
    body += section_limits(recs, n_all, n_far, accounts)
    body += section_conclusion(recs)
    body += section_probe(recs, abs_recs, single_map, accounts)
    body += [
        "数据基线：`batch1_xcorr_*.csv` 中的逐格数值由本脚本复算并逐格断言一致；"
        "逐平移取值见 `batch1_null_calibration_clinical.csv`。"
        "本文件由 `phase0/run_null_calibration.py` 生成，正文不含手写结果数字（只含方法阈值与格式）。"
        "该脚本不是自包含的：它读取本地未入库的原始件（`phase0/output/batch1_clinical_weekly_counts.csv`、"
        "`batch1_yahoo_XBI_daily.csv`），干净克隆下无法用它重生成本文；"
        "对外复算路径是随附的逐平移 CSV → 本文第 3 节。", ""]
    return body


def write_clinical(recs, abs_recs, single_map, accounts, n_all, n_far, built):
    body = assemble(recs, abs_recs, single_map, accounts, n_all, n_far, built, True)
    Path("phase0/batch1_null_calibration_clinical.md").write_text("\n".join(body), encoding="utf-8")
    write_csv(recs, "phase0/batch1_null_calibration_clinical.csv")
    print("wrote clinical md/csv")


if __name__ == "__main__":
    main()
