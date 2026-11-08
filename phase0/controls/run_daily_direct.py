"""日频直接测检出率 + 训练段补跑（探索性沙箱，非预注册）。

只做编排与统计汇总：注入块、混合公式、段尾行号重算一律复用
`phase0/controls/run_paths.py`；尺子一律复用 `phase0/ruler.py` 的 `measure()`；
判定与内插复用 `phase0/controls/run_power.py` 的 `_sig` / `cross_threshold`。
不修改 `ruler.py`，也不改动 `run_paths.py` 的既有行为。

口径：
- 固定真值 `r`，日频，每格 200 次独立重复（每次独立取块起点与噪声平移量）。
- 段长按交易日行数：验证 520 / 780，训练 1480。
- `k0 = 3 行（交易日）`、`WARM = 52 行`、`far_min = 26 行`、窗口 `[1,8] 行`
  ——即尺子的「行数语义」，不是「1–8 周」。
- 主口径 = 远平移（`P_far ≤ 2.5%` 且区间不含 0）；严格双版（全+远）并列。

用法（仓库根目录）：
  python phase0/controls/run_daily_direct.py --bench
  python phase0/controls/run_daily_direct.py --stage direct --reps 200 --workers 16 --budget 480
  python phase0/controls/run_daily_direct.py --stage train  --reps 200 --workers 16 --budget 480
"""
from __future__ import annotations

import os

# 多进程并行下让每进程单线程跑 BLAS，避免 24 核被线程池互相抢占
for _key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
             "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_key, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor, as_completed  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

PHASE0 = Path(__file__).resolve().parent.parent
if str(PHASE0) not in sys.path:
    sys.path.insert(0, str(PHASE0))

import ruler  # noqa: E402
import run_batch1 as rb  # noqa: E402
import run_power as rp  # noqa: E402
import run_paths as rpath  # noqa: E402

SUMMARY = rpath.SUMMARY
RAW = PHASE0 / "controls" / "paths_raw_direct.jsonl"

# 段长（交易日行数）：有效验证段的两种跨度 + 训练段
LENS = {"valid520": 520, "valid780": 780, "train1480": 1480}
SEED_CAMPAIGN = 20261108

DIRECT_R = [0.20, 0.25]
TRAIN_R = [0.15, 0.20, 0.25, 0.30]

_G: dict = {}


def seed_of(r: float, tag: str, rep: int) -> int:
    """按 (段长, r, 重复序号) 派生种子；段长项用 100000 分隔，避免与 r 偏移相互撞车。"""
    li = list(LENS).index(tag)
    return SEED_CAMPAIGN + 100000 * li + 1000 * int(round(r * 100)) + rep


def _init_worker() -> None:
    rpath._init_worker()


def rep_direct(task: tuple[float, str, int]) -> dict:
    r, tag, rep = task
    n_len = LENS[tag]
    seed = seed_of(r, tag, rep)
    rng = np.random.default_rng(seed)
    lead, lag, span = rpath._one_block_daily(r, tag, n_len, rng)
    out = ruler.measure(lead, lag, [span], rpath.LAG_RANGE, rpath.WINDOW,
                        far_min=rpath.D_FAR, n_boot=ruler.N_BOOT, seed=seed)
    s = out.segments[0]
    strict, far, p_all, p_far, ci = rp._sig(s)
    lz, gz = rb.roll_z(lead), rb.roll_z(lag)
    realized = float(rb.seg_xcorr(lz, gz, span[1], span[2], lags=[rp.K0])["corr"].iloc[0])
    return {"rows": [{"r": r, "tag": tag, "rep": rep, "n_len": n_len,
                      "realized_k0": realized,
                      "peak_k": s.peak_k, "peak_corr": s.peak_corr, "n": s.peak_n,
                      "p_all": p_all, "p_far": p_far,
                      "ci_lo": None if ci is None else ci[0],
                      "ci_hi": None if ci is None else ci[1],
                      "sig": bool(strict), "sig_far": bool(far),
                      "neff_far": float(s.far_shifts.neff),
                      "shifts_far": int(s.far_shifts.n),
                      "tau_far": float(s.far_shifts.tau)}],
            "kind": "direct"}


def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson 95% 区间（小样本比正态近似稳）。"""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    ctr = (p + z * z / (2 * n)) / den
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, ctr - half), min(1.0, ctr + half))


def _cells(rows: list[dict], reps: int) -> dict:
    cells = {}
    for tag in LENS:
        for r in sorted({x["r"] for x in rows if x["tag"] == tag}):
            cell = [x for x in rows if x["tag"] == tag and x["r"] == r]
            hits = sum(x["sig_far"] for x in cell)
            hits_strict = sum(x["sig"] for x in cell)
            lo, hi = wilson(hits, len(cell))
            cells[f"{tag}|r={r:.2f}"] = {
                "tag": tag, "r": r, "n_len": LENS[tag],
                "reps_done": len(cell), "reps_target": reps,
                "hit_far": hits, "rate_far": hits / len(cell),
                "ci95_far": [round(lo, 4), round(hi, 4)],
                "hit_strict": hits_strict, "rate_strict": hits_strict / len(cell),
                "n_median": float(np.median([x["n"] for x in cell])),
                "peak_k_median": int(np.median([x["peak_k"] for x in cell])),
                "realized_k0": float(np.median([x["realized_k0"] for x in cell])),
                "neff_far": float(np.median([x["neff_far"] for x in cell]),
                ),
                "tau_far": float(np.median([x["tau_far"] for x in cell]),
                ),
                "peak_corr_median": float(np.median([x["peak_corr"] for x in cell]),
                ),
            }
    return cells


def _stage_summary(rows: list[dict], tags: list[str], grid: list[float],
                   reps: int, tasks_total: int, tasks_done: int) -> dict:
    cells = _cells(rows, reps)
    out = {"reps_target": reps, "tasks_done": tasks_done, "tasks_total": tasks_total,
           "complete": tasks_done == tasks_total, "cells": cells}
    for tag in tags:
        pts = [(c["r"], c["rate_far"]) for k, c in cells.items()
               if c["tag"] == tag and c["reps_done"] == reps]
        if len(pts) >= 2:
            out.setdefault("thresholds", {})[tag] = {
                "r80": rp.cross_threshold(pts, 0.80),
                "r50": rp.cross_threshold(pts, 0.50),
                "grid": [p[0] for p in pts],
                "rates": [round(p[1], 4) for p in pts],
            }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["direct", "train", "both"], default="direct")
    ap.add_argument("--reps", type=int, default=200)
    ap.add_argument("--train-grid", default=",".join(f"{x:.2f}" for x in TRAIN_R),
                    help="训练段网格子集（逗号分隔），用于按剩余机时取舍")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--budget", type=float, default=480.0)
    ap.add_argument("--bench", action="store_true")
    args = ap.parse_args()

    if args.bench:
        _init_worker()
        rng = np.random.default_rng(SEED_CAMPAIGN)
        for tag in LENS:
            t0 = time.time()
            lead, lag, span = rpath._one_block_daily(0.2, tag, LENS[tag], rng)
            ruler.measure(lead, lag, [span], rpath.LAG_RANGE, rpath.WINDOW,
                          far_min=rpath.D_FAR)
            print(f"bench {tag} n={LENS[tag]}: {time.time()-t0:.1f}s", flush=True)
        return 0

    summary = json.loads(SUMMARY.read_text(encoding="utf-8")) if SUMMARY.exists() else {}
    t0 = time.time()

    if args.stage in ("direct", "both"):
        # 先跑 r=0.20 的两个段长（判读只依赖这两格），再跑 r=0.25 的斜率对照
        tasks = [(r, tag, rep) for r in DIRECT_R
                 for tag in ("valid520", "valid780") for rep in range(args.reps)]
        rows = rpath._run(tasks, rep_direct, args.workers, "direct", RAW, args.budget)
        done = len({tuple(t) for t in tasks} & rpath._done_keys(RAW))
        summary["direct"] = {
            "note": "固定真值 r 的直接检出率（日频，行数语义）；k0/WARM/far_min 都是交易日行数",
            "segments": _stage_summary(rows, ["valid520", "valid780"], DIRECT_R,
                                       args.reps, len(tasks), done)}

    if args.stage in ("train", "both"):
        grid = [float(x) for x in args.train_grid.split(",")]
        tasks = [(r, "train1480", rep) for r in grid for rep in range(args.reps)]
        rows = rpath._run(tasks, rep_direct, args.workers, "train", RAW, args.budget)
        done = len({tuple(t) for t in tasks} & rpath._done_keys(RAW))
        summary["direct_train"] = {
            "note": "日频训练段（1480 交易日），按剩余机时可跑的子集，仅报量级；k0/WARM/far_min 都是交易日行数",
            "segments": _stage_summary(rows, ["train1480"], grid,
                                       args.reps, len(tasks), done)}

    summary["last_call_s"] = round(time.time() - t0, 1)
    SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    for key in ("direct", "direct_train"):
        if key not in summary:
            continue
        blk = summary[key]["segments"]
        print(f"\n== {key} ==  {blk['tasks_done']}/{blk['tasks_total']}", flush=True)
        for name, c in blk["cells"].items():
            print(f"  {name}: {c['hit_far']}/{c['reps_done']} = {c['rate_far']*100:5.1f}% "
                  f"[{c['ci95_far'][0]*100:.1f}, {c['ci95_far'][1]*100:.1f}] "
                  f"strict {c['rate_strict']*100:4.1f}% n_med={c['n_median']:.0f} "
                  f"k_med={c['peak_k_median']} realized={c['realized_k0']:+.3f}", flush=True)
        for tag, t in blk.get("thresholds", {}).items():
            print(f"  {tag}: r80={t['r80']} r50={t['r50']}", flush=True)
    print(f"\nlast_call {summary['last_call_s']}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
