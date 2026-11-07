"""三条路测算（探索性沙箱，非预注册）：换频率 / 缩命题 / 重排切分。

设计见 `phase0/controls/paths_design.md`（跑前写定）。本文件只做编排与单位换算：
统计核心（滚动 z、段内配对、窗口峰值、循环平移零分布、块自助区间）一律走
`phase0/ruler.py` 的 `measure()`；注入公式、判定、内插一律从
`phase0/controls/run_power.py` 复用，不写第二份统计逻辑。

单位换算只在日频路径上发生（`run_power._one_block` 的 `shift(K0)` 与段尾都按行）：
日频的 k0 换成 21 行（= 3 周）、预热换成 260 行（= 52 周）、`far_min` 换成 130 行
（= 26 周）、段尾余量换成 60 行。滞后网格仍是 `k=0..8`（周），由尺子内部的
`Timedelta(weeks=k)` 决定。

用法（仓库根目录）：
  python phase0/controls/run_paths.py --bench          # 单段计时
  python phase0/controls/run_paths.py --reps 1 --dry   # 冒烟
  python phase0/controls/run_paths.py --reps 30        # 正式
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

PHASE0 = Path(__file__).resolve().parent.parent
if str(PHASE0) not in sys.path:
    sys.path.insert(0, str(PHASE0))

import ruler  # noqa: E402
import run_batch1 as rb  # noqa: E402
import run_null_calibration as rnc  # noqa: E402
import run_power as rp  # noqa: E402

DATA = PHASE0 / "controls" / "data"
SUMMARY = PHASE0 / "controls" / "paths_summary.json"

R_GRID = rp.R_GRID
# 日频网格：开跑前实测单任务约 128s（1480+520 行），故从设计的 6 点降到 5 点、
# 并向高 r 挪（日频 N_eff 更大，检出线预期低于周频但不会低到 0.05 附近）。
# 见 `paths_design.md` §2.2（开跑前修正，未见过任何日频输出）。
D_R_GRID = [0.10, 0.15, 0.20, 0.25, 0.30]
W_R_GRID = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
WINDOW = rp.WINDOW
LAG_RANGE = rp.LAG_RANGE
ALPHA = rp.ALPHA_V2

# ---- 日频：与周频同一组常数（行数语义），只把数据换成日频；见设计 §2.1
D_TRAIN, D_VALID = 1480, 520      # 交易日 ≈ 296 / 104 周
D_K0 = rp.K0                      # 3 行
D_FAR = ruler.FAR_MIN             # 26 行

# ---- 重排切分：总跨度 400 周不变，只改两段比例；另重算 104 周验证段做基线对表
W_LENS = {"baseline valid": 104,
          "1:1 train": 200, "1:1 valid": 200,
          "1:2 train": 133, "1:2 valid": 267}

# 日频两段里训练段（1480 行）单任务约 98s、验证段（520 行）约 30s，且日频任务受内存带宽
# 制约（5 进程并行只有约 1.7 倍加速）。默认两段都跑，可经环境变量只跑验证段；
# 命令行 --daily-seg 会设置该变量（Windows spawn 下由子进程继承）。
DAILY_SEGS = ("train", "validation")

_G: dict = {}


def _init_worker() -> None:
    w = pd.read_csv(DATA / "weekly_controls.csv", parse_dates=["week_friday"],
                    index_col="week_friday")
    d = pd.read_csv(DATA / "daily_controls.csv", parse_dates=["date"], index_col="date")
    _G["w_crude"] = w["crude_ret"].dropna()
    _G["w_gas"] = w["gas_ret"].dropna()
    _G["d_crude"] = d["crude_ret"].dropna()
    _G["d_gas"] = d["gas_ret"].dropna()
    _G["w"] = w
    _G["daily_segs"] = tuple(os.environ.get("PATHS_DAILY_SEGS", ",".join(DAILY_SEGS)).split(","))


def _obs_eff(lead_z, lag_z, k: int, span) -> tuple[float, float]:
    """独立观测当量：峰值滞后的配对乘积序列自身的 `acf_tau` → `N_eff = n/tau`。

    用现成的 `ruler._pair`（段内配对）与 `run_null_calibration.acf_tau`，不另写统计。
    该值随注入强度略变，故按格取中位数、并与名义样本数一起读。
    """
    pair = ruler._pair(lead_z, lag_z, k, span)
    prod = (pair["lead"] * pair["lag"]).to_numpy(float)
    _rho1, tau = rnc.acf_tau(prod)
    return float(tau), float(len(prod) / tau)


def _one_block_daily(r: float, seg: str, n_len: int, rng):
    """直接复用 `run_power._one_block`（混合公式、块起点、噪声远平移），只重算段尾。

    `_one_block` 按 `Timedelta(weeks=n_len-1)` 算终点，那是周频的日历算术；日频的段尾
    必须按「第 n_len 个观测」取，故只改这一处。
    """
    lead, lag, (name, start, _end_weekly) = rp._one_block(
        r, _G["d_crude"], _G["d_gas"], seg, n_len, rng)
    end = lag.index[rp.WARM + n_len - 1]
    return lead, lag, (name, start, end)


def rep_daily(task: tuple[float, int]) -> dict:
    r, rep = task
    seed = rp.SEED_BASE + 1000 * int(round(r * 100)) + rep
    lens = {"train": D_TRAIN, "validation": D_VALID}
    rows = []
    for seg in _G.get("daily_segs", DAILY_SEGS):
        n_len = lens[seg]
        rng = np.random.default_rng(seed + (0 if seg == "train" else 101))
        lead, lag, span = _one_block_daily(r, seg, n_len, rng)
        out = ruler.measure(lead, lag, [span], LAG_RANGE, WINDOW,
                            far_min=D_FAR, n_boot=ruler.N_BOOT, seed=seed)
        s = out.segments[0]
        strict, far, p_all, p_far, ci = rp._sig(s)
        lz, gz = rb.roll_z(lead), rb.roll_z(lag)
        realized = float(rb.seg_xcorr(lz, gz, span[1], span[2], lags=[rp.K0])["corr"].iloc[0])
        tau_obs, neff_obs = _obs_eff(lz, gz, s.peak_k, span[1:])
        rows.append({"r": r, "rep": rep, "seg": seg, "realized_k0": realized,
                     "peak_k": s.peak_k, "peak_corr": s.peak_corr, "n": s.peak_n,
                     "p_all": p_all, "p_far": p_far,
                     "ci_lo": None if ci is None else ci[0],
                     "ci_hi": None if ci is None else ci[1],
                     "sig": bool(strict), "sig_far": bool(far),
                     "neff_far": float(s.far_shifts.neff),
                     "shifts_far": int(s.far_shifts.n),
                     "tau_far": float(s.far_shifts.tau),
                     "tau_obs": tau_obs, "neff_obs": neff_obs})
    return {"rows": rows, "kind": "daily"}


def rep_weekly_len(task: tuple[float, int, str]) -> dict:
    """重排切分：给定段长跑单段注入（同一混合公式与同一尺子）。"""
    r, rep, tag = task
    n_len = W_LENS[tag]
    # 标签进种子：同一 (r, rep) 下不同段长必须各自独立取块，否则 1:1 两段会是同一实现
    seed = (rp.SEED_BASE + 1000 * int(round(r * 100)) + rep
            + 5000 * (1 + list(W_LENS).index(tag)))
    rng = np.random.default_rng(seed)
    lead, lag, span = rp._one_block(r, _G["w_crude"], _G["w_gas"], tag, n_len, rng)
    out = ruler.measure(lead, lag, [span], LAG_RANGE, WINDOW, n_boot=ruler.N_BOOT, seed=seed)
    s = out.segments[0]
    strict, far, p_all, p_far, ci = rp._sig(s)
    lz, gz = rb.roll_z(lead), rb.roll_z(lag)
    realized = float(rb.seg_xcorr(lz, gz, span[1], span[2], lags=[rp.K0])["corr"].iloc[0])
    tau_obs, neff_obs = _obs_eff(lz, gz, s.peak_k, span[1:])
    return {"rows": [{"r": r, "rep": rep, "seg": tag, "realized_k0": realized,
                      "peak_k": s.peak_k, "peak_corr": s.peak_corr, "n": s.peak_n,
                      "p_all": p_all, "p_far": p_far,
                      "ci_lo": None if ci is None else ci[0],
                      "ci_hi": None if ci is None else ci[1],
                      "sig": bool(strict), "sig_far": bool(far),
                      "neff_far": float(s.far_shifts.neff),
                      "shifts_far": int(s.far_shifts.n),
                      "tau_far": float(s.far_shifts.tau),
                      "tau_obs": tau_obs, "neff_obs": neff_obs}],
            "kind": "weekly_len"}


def _summarize(rows: list[dict], tags: list[str], reps: int, grid: list[float]) -> dict:
    out = {"reps": reps, "grid": grid, "segments": {}}
    for tag in tags:
        sub = [x for x in rows if x["seg"] == tag]
        curve = []
        for r in grid:
            cell = [x for x in sub if x["r"] == r]
            curve.append({
                "r": r,
                "far": sum(x["sig_far"] for x in cell) / len(cell),
                "strict": sum(x["sig"] for x in cell) / len(cell),
                "n_median": float(np.median([x["n"] for x in cell])),
                "realized_k0": float(np.median([x["realized_k0"] for x in cell]),
                                     ),
                "neff_far": float(np.median([x["neff_far"] for x in cell]),
                                  ),
                "tau_far": float(np.median([x["tau_far"] for x in cell]),
                                 ),
                "shifts_far": int(np.median([x["shifts_far"] for x in cell]),
                                  ),
                "neff_obs": float(np.median([x["neff_obs"] for x in cell]),
                                  ),
                "tau_obs": float(np.median([x["tau_obs"] for x in cell]),
                                 ),
                "se_80": float(np.sqrt(0.8 * 0.2 / len(cell))),
            })
        out["segments"][tag] = {
            "curve": curve,
            "r80": rp.cross_threshold([(c["r"], c["far"]) for c in curve], 0.80),
            "r50": rp.cross_threshold([(c["r"], c["far"]) for c in curve], 0.50),
            "r80_strict": rp.cross_threshold([(c["r"], c["strict"]) for c in curve], 0.80),
            "r50_strict": rp.cross_threshold([(c["r"], c["strict"]) for c in curve], 0.50),
        }
    return out


def _done_keys(raw: Path) -> set:
    keys = set()
    if raw.exists():
        for line in raw.read_text(encoding="utf-8").splitlines():
            if line.strip():
                keys.add(tuple(json.loads(line)["task"]))
    return keys


def _all_rows(raw: Path) -> list[dict]:
    rows: list[dict] = []
    if raw.exists():
        for line in raw.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows += json.loads(line)["rows"]
    return rows


def _run(tasks, fn, workers: int, label: str, raw: Path, budget: float) -> list[dict]:
    """按波次提交，单次调用到达 `budget` 秒就停（已完成的逐条落盘，可续跑）。"""
    done = _done_keys(raw)
    pend = [t for t in tasks if tuple(t) not in done]
    t0 = time.time()
    keep = min(workers * 2, len(pend))
    if keep == 0:
        return _all_rows(raw)
    with ProcessPoolExecutor(max_workers=min(workers, keep), initializer=_init_worker) as ex:
        while pend and time.time() - t0 < budget:
            wave, pend = pend[:workers], pend[workers:]
            futs = {ex.submit(fn, t): t for t in wave}
            for fu in as_completed(futs):
                got = fu.result()
                with raw.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps({**got, "task": futs[fu]}, ensure_ascii=False) + "\n")
            print(f"[{label}] 完成 {len(tasks) - len(pend)}/{len(tasks)}，"
                  f"{time.time()-t0:.0f}s", flush=True)
    return _all_rows(raw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--budget", type=float, default=480.0, help="单次调用最多跑多少秒")
    ap.add_argument("--part", choices=["daily", "weekly", "both"], default="both")
    ap.add_argument("--daily-seg", choices=["both", "train", "validation"], default="both")
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    os.environ["PATHS_DAILY_SEGS"] = ("train,validation" if args.daily_seg == "both"
                                      else args.daily_seg)

    if args.bench:
        _init_worker()
        rng = np.random.default_rng(rp.SEED_BASE)
        for tag, n_len, fn in (("daily train 1480", D_TRAIN, "d"),
                               ("daily valid 520", D_VALID, "d"),
                               ("weekly 200", 200, "w")):
            t0 = time.time()
            if fn == "d":
                lead, lag, span = _one_block_daily(0.3, tag, n_len, rng)
                ruler.measure(lead, lag, [span], LAG_RANGE, WINDOW, far_min=D_FAR)
            else:
                lead, lag, span = rp._one_block(0.3, _G["w_crude"], _G["w_gas"], tag, n_len, rng)
                ruler.measure(lead, lag, [span], LAG_RANGE, WINDOW)
            print(f"bench {tag}: {time.time()-t0:.1f}s", flush=True)
        return 0

    summary = json.loads(SUMMARY.read_text(encoding="utf-8")) if SUMMARY.exists() else {}
    summary.update({"design": "phase0/controls/paths_design.md"})
    t0 = time.time()

    if args.part in ("daily", "both"):
        raw = PHASE0 / "controls" / "paths_raw_daily.jsonl"
        tasks = [(r, rep) for r in D_R_GRID for rep in range(args.reps)]
        rows = _run(tasks, rep_daily, args.workers, "daily", raw, args.budget)
        done = sum(1 for t in tasks if tuple(t) in _done_keys(raw))
        if done == len(tasks):
            segs = (["train", "validation"] if args.daily_seg == "both"
                    else [args.daily_seg])
            summary["daily"] = {"train_days": D_TRAIN, "valid_days": D_VALID, "k0_rows": D_K0,
                                "far_min_rows": D_FAR, "warm_rows": rp.WARM,
                                "segments_run": segs,
                                "tasks_done": done, "tasks_total": len(tasks),
                                **_summarize(rows, segs, args.reps, D_R_GRID)}
        else:
            print(f"[daily] 未完成 {done}/{len(tasks)}，本轮不写汇总", flush=True)

    if args.part in ("weekly", "both"):
        raw = PHASE0 / "controls" / "paths_raw_weekly.jsonl"
        tasks = [(r, rep, tag) for tag in W_LENS for r in W_R_GRID for rep in range(args.reps)]
        rows = _run(tasks, rep_weekly_len, args.workers, "weekly", raw, args.budget)
        done = sum(1 for t in tasks if tuple(t) in _done_keys(raw))
        if done == len(tasks):
            summary["weekly_split"] = {"tasks_done": done, "tasks_total": len(tasks),
                                       **_summarize(rows, list(W_LENS), args.reps, W_R_GRID)}
        else:
            print(f"[weekly] 未完成 {done}/{len(tasks)}，本轮不写汇总", flush=True)

    summary["last_call_s"] = round(time.time() - t0, 1)
    SUMMARY.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.dry:
        return 0

    for kind in ("daily", "weekly_split"):
        if kind not in summary:
            continue
        print(f"\n== {kind} ==")
        for tag, s in summary[kind]["segments"].items():
            c0 = s["curve"][0]
            print(f"  {tag}: n_med={c0['n_median']:.0f} r80={s['r80']} r50={s['r50']} "
                  f"neff_obs={c0['neff_obs']:.0f} se80={c0['se_80']:.3f}")
            for c in s["curve"]:
                print(f"    r={c['r']:.2f} far={c['far']*100:5.1f}% strict={c['strict']*100:5.1f}% "
                      f"realized_k0={c['realized_k0']:+.3f}")
    print(f"\nlast_call {summary['last_call_s']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
