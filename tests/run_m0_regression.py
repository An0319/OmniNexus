# -*- coding: utf-8 -*-
"""M0 回归校验：core 计算路径与旧脚本（phase0/lead_lag_check.py v3）输出逐位一致。

设计：完全离线——领先面读现有缓存 CSV，滞后面读现有周线 CSV，只回归
"对齐 → 标准化 → 交叉相关 → 判定" 路径；抓数逻辑本身未改动（代码搬移+参数化）。

运行：python tests/run_m0_regression.py
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from omninexus.core import align_weekday, judge, roll_z, xcorr  # noqa: E402

OUT = ROOT / "phase0" / "output"
FAILURES = []


def check(name, cond, detail=""):
    tag = "PASS" if cond else "FAIL"
    print(f"  [{tag}] {name} {detail}")
    if not cond:
        FAILURES.append(name)


def regress_chain(chain: str, lead_csv: str, sector_csv: str, xcorr_csv: str,
                  lag_range, pass_window, noise_band, expected_verdicts):
    print(f"\n== 回归：{chain} ==")
    # 领先面：现有缓存 -> 对齐周一 -> 标准化（与旧脚本 main() 一致）
    papers = pd.read_csv(OUT / lead_csv, index_col=0, parse_dates=True).iloc[:, 0]
    papers.index = align_weekday(papers.index)
    lead_z = roll_z(papers)

    # 滞后面：现有周线 CSV（close/amount/ret，旧脚本 to_weekly 的产物）
    wk = pd.read_csv(OUT / sector_csv, index_col=0, parse_dates=True)
    lag_targets = {"周收益率": wk["ret"], "周成交额": wk["amount"]}

    got = pd.DataFrame({n: xcorr(lead_z, roll_z(raw), lag_range)
                        for n, raw in lag_targets.items()}).round(3)
    expected = pd.read_csv(OUT / xcorr_csv, index_col=0)
    expected.index = expected.index.astype(int)

    check(f"{chain} xcorr 形状", got.shape == expected.shape,
          f"got={got.shape} expected={expected.shape}")
    if got.shape == expected.shape:
        diff = (got - expected).abs().max().max()
        check(f"{chain} xcorr 逐位一致（max|diff|<1e-9）", diff < 1e-9, f"max|diff|={diff}")

    verdicts = judge(got, pass_window, 0.3, noise_band)
    for exp in expected_verdicts:
        v = next(x for x in verdicts if x["metric"] == exp["metric"])
        check(f"{chain} 判定 {exp['metric']}",
              v["status"] == exp["status"] and v.get("k_best") == exp["k_best"]
              and v.get("corr") == exp["corr"],
              f"got={v} expected={exp}")


# 判定期望值 = 旧脚本 v3 实际输出（phase0 修订记录已登记）
regress_chain(
    "chain01", "openalex_weekly.csv", "sector_weekly.csv", "xcorr.csv",
    lag_range=range(0, 9), pass_window=(1, 4), noise_band=0.15,
    expected_verdicts=[
        {"metric": "周收益率", "status": "NO_TRANSMISSION", "k_best": 7, "corr": -0.108},
        {"metric": "周成交额", "status": "NO_TRANSMISSION", "k_best": 1, "corr": -0.123},
    ])

regress_chain(
    "chain10", "openalex_weekly_chain10.csv", "sector_weekly_chain10.csv",
    "xcorr_chain10.csv",
    lag_range=range(0, 27), pass_window=(4, 13), noise_band=0.15,
    expected_verdicts=[
        {"metric": "周收益率", "status": "NO_TRANSMISSION", "k_best": 20, "corr": 0.149},
        {"metric": "周成交额", "status": "GREY", "k_best": 26, "corr": 0.167},
    ])

print("\n== 结果 ==")
if FAILURES:
    print(f"回归失败：{FAILURES}")
    sys.exit(1)
print("全部通过：core 计算路径与 phase0 v3 逐位一致。M0 泛化成立。")
