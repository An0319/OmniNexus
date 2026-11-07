"""Ruler 自检：用临床 XBI 数据跑一遍，逐格对照今天已入库的校准文档。

对照对象 `phase0/batch1_null_calibration_clinical.md`（§3.1 分位、§3.2 命中计数、
§4 有效独立平移量）与随附 CSV `phase0/batch1_null_calibration_clinical.csv`。
阈值比对用文档里的固定线 `0.19` / `0.30`；尺子自身输出的 p70 / p95 是分段阈值，
另列核对（不应等于 `0.19` / `0.30`）。

运行（仓库根目录）：
  python phase0/controls/selfcheck.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

PHASE0 = Path(__file__).resolve().parent.parent
if str(PHASE0) not in sys.path:
    sys.path.insert(0, str(PHASE0))

import run_batch1 as rb  # noqa: E402
import run_null_calibration as rnc  # noqa: E402
import ruler  # noqa: E402

# 文档里的期望值（全部来自已入库文档，逐格核对用）
EXPECT = {
    ("train", "all"): dict(n=424, k=11, corr=0.0578, n_pair=285,
                           median=0.08, p70=0.09, p95=0.15, p99=0.16, max=0.16,
                           hit19=0, hit30=0, hit_peak=344, neff=29.8, b=14),
    ("train", "far"): dict(n=374, k=11, corr=0.0578, n_pair=285,
                           median=0.08, p70=0.10, p95=0.15, p99=0.16, max=0.16,
                           hit19=0, hit30=0, hit_peak=303, neff=26.1, b=14),
    ("validation", "all"): dict(n=424, k=13, corr=0.2035, n_pair=91,
                                median=0.16, p70=0.19, p95=0.28, p99=0.30, max=0.33,
                                hit19=130, hit30=6, hit_peak=101, neff=55.6, b=8),
    ("validation", "far"): dict(n=374, k=13, corr=0.2035, n_pair=91,
                                median=0.15, p70=0.19, p95=0.28, p99=0.31, max=0.33,
                                hit19=124, hit30=6, hit_peak=97, neff=49.9, b=7),
}

fails = []


def check(label, got, want, tol=0.0):
    ok = (got == want) if tol == 0 else (abs(got - want) <= tol)
    print(f"{'PASS' if ok else 'FAIL'}  {label}: got={got} want={want}")
    if not ok:
        fails.append(label)


def main() -> int:
    built = rnc.build(["clinical_xbi"])
    _lz, _gz, lead, lag = built["clinical_xbi"]
    rep = ruler.measure(
        lead, lag,
        segments=[("train", *rb.TRAIN), ("validation", *rb.VALID)],
        lag_range=(0, 13), window=(4, 13))

    print(rep.to_markdown())
    print()

    csv = rnc.pd.read_csv(PHASE0 / "batch1_null_calibration_clinical.csv")
    for seg in rep.segments:
        for ver, view in (("all", seg.all_shifts), ("far", seg.far_shifts)):
            exp = EXPECT[(seg.name, ver)]
            tag = f"{seg.name}/{ver}"
            check(f"{tag} n_shifts", view.n, exp["n"])
            check(f"{tag} peak k", seg.peak_k, exp["k"])
            check(f"{tag} peak corr", round(seg.peak_corr, 4), exp["corr"])
            check(f"{tag} peak n", seg.peak_n, exp["n_pair"])
            for q in ("median", "p70", "p95", "p99"):
                got = getattr(view, q) if q != "p99" else float(np.percentile(view.values, 99))
                check(f"{tag} {q}", round(got, 2), exp[q])
            check(f"{tag} max", round(view.max, 2), exp["max"])
            check(f"{tag} P(>=0.19)", int(np.sum(view.values >= 0.19)), exp["hit19"])
            check(f"{tag} P(>=0.30)", int(np.sum(view.values >= 0.30)), exp["hit30"])
            check(f"{tag} P(>=peak)", int(np.sum(view.values >= seg.peak_corr)), exp["hit_peak"])
            check(f"{tag} N_eff", round(view.neff, 1), exp["neff"], tol=0.05)
            check(f"{tag} block", view.block, 2 * exp["b"])
            # 与入库 CSV 逐格一致（CSV 为 6 位小数）
            col = f"{seg.name}_max_pos"
            if ver == "all":
                got = np.round(view.values, 6)
                want = csv[col].to_numpy()
            else:
                got = np.round(view.values, 6)
                want = csv.loc[csv["circular_distance"] >= rnc.FAR_MIN, col].to_numpy()
            check(f"{tag} 与 CSV 逐格", np.array_equal(got, want), True)

    print()
    print("分段阈值（尺子自身口径，不是常数）：")
    for seg in rep.segments:
        print(f"  {seg.name}: p70 全={seg.all_shifts.p70:.2f} 远={seg.far_shifts.p70:.2f}；"
              f"p95 全={seg.all_shifts.p95:.2f} 远={seg.far_shifts.p95:.2f}；"
              f"峰值 95% 区间={seg.corr_ci}")
    print()
    print(f"RESULT: {'PASS' if not fails else 'FAIL ' + ', '.join(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
