"""功效曲线：注入式模拟（探索性，非预注册）。

设计见 `phase0/controls/control_design_v2.md` §2：把已知强度 r 的领先关系注入真实周收益
序列，跑完整流程（同一处理链 + 同一把尺子：窗口内取最大、分段、循环平移零分布、
按 v2 每段 2.5% 判定），统计检出率。

本文件不提供调参入口；参数全部写死在此处并在设计文档中同步固定。

用法（仓库根目录）：
  python phase0/controls/run_power.py            # 全网格
  python phase0/controls/run_power.py --reps 2    # 冒烟测试（结果不用于报告）
"""
from __future__ import annotations

import argparse
import json
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

ROOT = PHASE0.parent
DATA = PHASE0 / "controls" / "data"
RAW = PHASE0 / "controls" / "power_raw.jsonl"
SUMMARY = PHASE0 / "controls" / "power_summary.json"

R_GRID = [round(0.10 + 0.05 * i, 2) for i in range(9)]   # 0.10 .. 0.50
REPS = 60
K0 = 3                    # 注入滞后（窗口 [1,8] 内、阳性先验带 [2,6] 内）
TRAIN_LEN = 296           # 批次一训练段实际周数
VALID_LEN = 104           # 批次一验证段实际周数
WARM = 52                 # 滚动 z 的 52 周窗 + 余量
PAD = 13                  # 段尾配对余量（窗口上界 8 + 少量缓冲）
SEED_BASE = 20261107
ALPHA_V2 = 0.025
FAR_MIN = ruler.FAR_MIN
WINDOW = (1, 8)
LAG_RANGE = (0, 8)

_G: dict = {}


def _load() -> tuple[pd.Series, pd.Series]:
    w = pd.read_csv(DATA / "weekly_controls.csv", parse_dates=["week_friday"],
                    index_col="week_friday")
    return w["crude_ret"].dropna(), w["gas_ret"].dropna()


def _init_worker() -> None:
    _G["crude"], _G["gas"] = _load()


def _one_block(r: float, crude: pd.Series, gas: pd.Series, seg: str, n_len: int, rng):
    """单段注入：每次重复各自取一段真实原油块，噪声取汽油全历史的圆周远平移片段。

    重复之间必须换实现：领先块起点随机、汽油平移量随机（均落在远平移区），
    否则 60 次「重复」只是同一个实现换自助种子，检出率会退化成单次实现的 0/100 阶跃。
    """
    need = K0 + WARM + n_len + PAD
    common = crude.index.intersection(gas.index)
    crude_c = crude.reindex(common)
    gas_c = gas.reindex(common)
    off = int(rng.integers(0, len(crude_c) - need + 1))
    lead = crude_c.iloc[off:off + need].copy()
    shift = int(rng.integers(FAR_MIN, len(gas_c) - FAR_MIN))
    rolled = pd.Series(np.roll(gas_c.to_numpy(), shift), index=gas_c.index)
    noise = rolled.reindex(lead.index)
    sd_ratio = float(np.std(lead, ddof=1) / np.std(noise, ddof=1))
    lag = (r * lead.shift(K0) + np.sqrt(1.0 - r * r) * noise * sd_ratio).dropna()
    start = lag.index[WARM]
    end = start + pd.Timedelta(weeks=n_len - 1)
    return lead, lag, (seg, start, end)


def one_rep(task: tuple[float, int]) -> dict:
    r, rep = task
    crude, gas = _G["crude"], _G["gas"]
    seed = SEED_BASE + 1000 * int(round(r * 100)) + rep
    rows = []
    for seg, n_len in (("train", TRAIN_LEN), ("validation", VALID_LEN)):
        rng = np.random.default_rng(seed + (0 if seg == "train" else 101))
        lead, lag, span = _one_block(r, crude, gas, seg, n_len, rng)
        out = ruler.measure(lead, lag, [span], LAG_RANGE, WINDOW,
                            n_boot=ruler.N_BOOT, seed=seed)
        s = out.segments[0]
        strict, far, p_all, p_far, ci = _sig(s)
        # 注入是否生效：z 化后在 k0 处的实测相关（与名义 r 对照）
        import run_batch1 as rb  # noqa: WPS433  同一处理链
        lz, gz = rb.roll_z(lead), rb.roll_z(lag)
        realized = float(rb.seg_xcorr(lz, gz, span[1], span[2], lags=[K0])["corr"].iloc[0])
        rows.append({
            "r": r, "rep": rep, "seg": seg, "realized_k0": realized,
            "peak_k": s.peak_k, "peak_corr": s.peak_corr, "n": s.peak_n,
            "p_all": p_all, "p_far": p_far,
            "ci_lo": None if ci is None else ci[0],
            "ci_hi": None if ci is None else ci[1],
            "sig": bool(strict), "sig_far": bool(far),
        })
    return {"rows": rows}


def _sig(seg) -> tuple[bool, bool, float, float, tuple]:
    """返回 (v2 严格判据, 远平移判据, P全, P远, 区间)。"""
    a, f = seg.all_shifts, seg.far_shifts
    p_all = a.hit_peak[0] / a.n
    p_far = f.hit_peak[0] / f.n
    ci = seg.corr_ci
    ci_excl0 = ci is not None and (ci[0] > 0 or ci[1] < 0)
    strict = p_all <= ALPHA_V2 and p_far <= ALPHA_V2 and ci_excl0
    far = p_far <= ALPHA_V2 and ci_excl0
    return strict, far, p_all, p_far, ci


def cross_threshold(points: list[tuple[float, float]], level: float):
    """网格线性内插求检出线；网格内无交点则报 None 并注明在网格外。"""
    pts = sorted(points)
    if level <= pts[0][1]:
        return {"value": pts[0][0], "note": "低于网格下界 0.10，网格外"}
    if level > pts[-1][1]:
        return {"value": None, "note": "高于网格上界 0.50，网格外"}
    for (r1, p1), (r2, p2) in zip(pts, pts[1:]):
        if p1 < level <= p2:
            return {"value": round(r1 + (level - p1) * (r2 - r1) / (p2 - p1), 4),
                    "note": "线性内插"}
    return {"value": None, "note": "未找到交点"}


def aggregate(rows: list[dict], reps: int) -> dict:
    curve = []
    for r in R_GRID:
        tr = [x for x in rows if x["r"] == r and x["seg"] == "train"]
        va = [x for x in rows if x["r"] == r and x["seg"] == "validation"]
        va_by_rep = {x["rep"]: x for x in va}
        both = [x for x in tr if x["sig_far"] and va_by_rep.get(x["rep"], {}).get("sig_far")
                and np.sign(va_by_rep[x["rep"]]["peak_corr"]) == np.sign(x["peak_corr"])]
        curve.append({
            "r": r,
            "train": len([x for x in tr if x["sig_far"]]) / len(tr),
            "validation": len([x for x in va if x["sig_far"]]) / len(va),
            "train_strict": len([x for x in tr if x["sig"]]) / len(tr),
            "validation_strict": len([x for x in va if x["sig"]]) / len(va),
            "both_same_dir": len(both) / len(tr),
            "peak_n_train": float(np.median([x["n"] for x in tr])),
            "peak_n_valid": float(np.median([x["n"] for x in va])),
            "realized_k0_train": float(np.median([x["realized_k0"] for x in tr])),
            "realized_k0_valid": float(np.median([x["realized_k0"] for x in va])),
        })
    out = {"reps": reps, "grid": R_GRID, "curve": curve}
    for seg in ("train", "validation"):
        out[f"r80_{seg}"] = cross_threshold([(c["r"], c[seg]) for c in curve], 0.80)
        out[f"r50_{seg}"] = cross_threshold([(c["r"], c[seg]) for c in curve], 0.50)
        out[f"r80_{seg}_strict"] = cross_threshold([(c["r"], c[f"{seg}_strict"]) for c in curve], 0.80)
        out[f"r50_{seg}_strict"] = cross_threshold([(c["r"], c[f"{seg}_strict"]) for c in curve], 0.50)
    out["r80_both"] = cross_threshold([(c["r"], c["both_same_dir"]) for c in curve], 0.80)
    out["r50_both"] = cross_threshold([(c["r"], c["both_same_dir"]) for c in curve], 0.50)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=REPS)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    tasks = [(r, rep) for r in R_GRID for rep in range(args.reps)]
    t0 = time.time()
    rows = []
    RAW.write_text("", encoding="utf-8")
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_init_worker) as ex:
        futs = {ex.submit(one_rep, t): t for t in tasks}
        for i, fu in enumerate(as_completed(futs), 1):
            got = fu.result()
            rows += got["rows"]
            with RAW.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({**got, "task": futs[fu]}, ensure_ascii=False) + "\n")
            if i % 30 == 0:
                print(f"{i}/{len(tasks)} tasks, {time.time()-t0:.0f}s", flush=True)

    out = aggregate(rows, args.reps)
    out["realized_k0_median"] = float(np.median([x["realized_k0"] for x in rows]))
    out["elapsed_s"] = round(time.time() - t0, 1)
    SUMMARY.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("realized_k0_median", "r80_train", "r50_train",
                                           "r80_validation", "r50_validation",
                                           "r80_both", "r50_both", "elapsed_s")},
                     indent=2, ensure_ascii=False))
    for c in out["curve"]:
        print(f"r={c['r']:.2f} train={c['train']*100:5.1f}% valid={c['validation']*100:5.1f}% "
              f"both={c['both_same_dir']*100:5.1f}% n={c['peak_n_train']:.0f}/{c['peak_n_valid']:.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
