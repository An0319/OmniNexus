# -*- coding: utf-8 -*-
"""P0-1 零假设校准：我们的判定线（0.3 / 0.15）到底是"经验值"还是"惯例值"？

问题
----
两次实验共 5 个指标，max|corr| 全部 < 0.17。但"多大算大"从来没有依据——
因为我们**从没跑过安慰剂链**：不知道在"两条序列毫无关系"的前提下，
沿着 9 个或 27 个滞后位挑最大值，这个 max|corr| 本身能有多大。

本脚本回答一个问题
------------------
"两条毫无关系的序列，走同一条管线（对齐→滚动z→交叉相关→取27个滞后位最大值），
 能凭空跑出多大的相关性？"

方法（四种互证，避免单一假设）
------------------------------
1. 循环旋转（rotation）：把领先面整体平移随机偏移，**完全保持**序列自身的
   分布与自相关结构，只破坏跨序列对齐。N=500 次 → max|corr| 零分布。【主口径】
2. FFT 相位随机化：保持功率谱（=自相关）不变、随机化相位，生成替代序列。
   与 (1) 交叉验证——两者接近才敢下结论。【交叉验证】
3. 跨域真实配对：链01的领先面 × 链10的滞后面（人形机器人论文 vs 光模块代理股），
   明显无关的真实数据对，作为"真实数据下的零点"。【真实数据参照】
4. 合成基准：白噪声（无自相关）与随机游走（强自相关），展示自相关如何抬高零点。
   → 解释为什么"成交额"这类慢变量更容易虚高。【机制解释】

纪律声明（重要）
----------------
本校准**不用于给任何已判定链翻案**——判定的对象是"链"，判定线一旦写死就不回头。
本校准只用于给**下一条链**的预注册定价：先写进预注册章节，再跑。
按协议登记为「方法性修订」（不计入尝试额度）并公开披露。

运行：python phase0/null_calibration.py
输出：phase0/null_calibration_results.json（结论，入库可审计）
      phase0/output/null_calibration_raw.csv（每次抽样明细，体积大不入库）
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from omninexus.core import align_weekday, roll_z, xcorr  # noqa: E402

OUT = ROOT / "phase0" / "output"
SEED = 20260926          # 固定种子：结果可复现
N_DRAWS = 500            # 每种方法的抽样次数
MIN_PAIRS = 30           # 与 core.xcorr 一致：有效配对少于 30 返回 NaN

# 两条已判定链的配置（口径必须与实际判定时完全一致，否则校准无意义）
CHAINS = {
    "chain01": {"lead": "openalex_weekly.csv", "lag": "sector_weekly.csv",
                "prefix": "chain01", "lag_range": range(0, 9)},
    "chain10": {"lead": "openalex_weekly_chain10.csv", "lag": "sector_weekly_chain10.csv",
                "prefix": "chain10", "lag_range": range(0, 27)},
}
# 已判定的观测值（协议修订记录登记）：用于回答"我们的发现落在噪声分布的哪个位置"
OBSERVED = {
    "chain01": {"周收益率": (-0.108, 7), "周成交额": (-0.123, 1)},
    "chain10": {"周收益率": (0.149, 20), "周成交额": (0.167, 26)},
}


def load_series(chain: str):
    """按判定时的口径重建 lead_z 与两个滞后面（周收益率、周成交额）。"""
    cfg = CHAINS[chain]
    papers = pd.read_csv(OUT / cfg["lead"], index_col=0, parse_dates=True).iloc[:, 0]
    papers.index = align_weekday(papers.index)
    lead_z = roll_z(papers)

    wk = pd.read_csv(OUT / cfg["lag"], index_col=0, parse_dates=True)
    return lead_z, {"周收益率": roll_z(wk["ret"]), "周成交额": roll_z(wk["amount"])}


def max_abs_corr(lead: pd.Series, lag: pd.Series, lag_range) -> float:
    """管线同口径：整条滞后扫描里 |corr| 的最大值。"""
    tbl = xcorr(lead, lag, lag_range).dropna()
    return float(tbl.abs().max()) if len(tbl) else np.nan


def rotation_null(lead: pd.Series, lag: pd.Series, lag_range, rng, n=N_DRAWS):
    """方法1：循环旋转。保持序列分布/自相关，仅破坏跨序列对齐。"""
    v = lead.to_numpy(dtype=float)
    out = []
    for _ in range(n):
        off = int(rng.integers(1, len(v)))          # 1..n-1，避免恒等
        rot = pd.Series(np.roll(v, off), index=lead.index)
        out.append(max_abs_corr(rot, lag, lag_range))
    return np.array(out, dtype=float)


def phase_null(lead: pd.Series, lag: pd.Series, lag_range, rng, n=N_DRAWS):
    """方法2：FFT 相位随机化。保持功率谱（自相关），随机化相位。"""
    x = lead.to_numpy(dtype=float)
    n_obs = len(x)
    out = []
    for _ in range(n):
        X = np.fft.rfft(x - x.mean())
        ph = np.exp(1j * rng.uniform(0, 2 * np.pi, len(X)))
        ph[0] = 1.0
        if n_obs % 2 == 0:
            ph[-1] = 1.0
        y = np.fft.irfft(X * ph, n=n_obs) + x.mean()
        sur = pd.Series(y, index=lead.index)
        out.append(max_abs_corr(sur, lag, lag_range))
    return np.array(out, dtype=float)


def synth_null(kind: str, index, lag: pd.Series, lag_range, rng, n=N_DRAWS):
    """方法4：合成基准。white=白噪声；rw=随机游走（强自相关，模拟成交额类慢变量）。"""
    steps = rng.standard_normal((n, len(index)))
    if kind == "rw":
        steps = np.cumsum(steps, axis=1)
    out = [max_abs_corr(pd.Series(steps[i], index=index), lag, lag_range)
           for i in range(n)]
    return np.array(out, dtype=float)


def describe(null: np.ndarray, pass_corr: float, noise_band: float) -> dict:
    """零分布摘要 + 我们自己的判定线在零分布里的位置（即真实假阳性率）。"""
    d = {"n_draws": int(len(null)), "mean": round(float(null.mean()), 3),
         "p50": round(float(np.percentile(null, 50)), 3),
         "p90": round(float(np.percentile(null, 90)), 3),
         "p95": round(float(np.percentile(null, 95)), 3),
         "p99": round(float(np.percentile(null, 99)), 3),
         "max": round(float(null.max()), 3)}
    # 关键数字：毫无关系的数据里，有多大比例会越我们的线 → 单指标假阳性率
    d["fp_rate_at_pass_corr"] = round(float((null > pass_corr).mean()), 4)
    d["fp_rate_at_noise_band"] = round(float((null > noise_band).mean()), 4)
    return d


def main():
    rng = np.random.default_rng(SEED)
    results = {"seed": SEED, "n_draws": N_DRAWS,
               "discipline_note": "本校准不用于给已判定链翻案，只用于给下一条链的预注册判定线定价。",
               "chains": {}}
    raw_rows = []

    for chain, cfg in CHAINS.items():
        print(f"\n{'='*72}\n零假设校准：{chain}（滞后扫描 0..{max(cfg['lag_range'])}，"
              f"共 {len(cfg['lag_range'])} 个滞后位）\n{'='*72}")
        lead_z, lags = load_series(chain)
        n_lag = len(cfg["lag_range"])
        results["chains"][chain] = {"n_lags": n_lag, "metrics": {}}

        for name, lag_z in lags.items():
            rot = rotation_null(lead_z, lag_z, cfg["lag_range"], rng)
            pha = phase_null(lead_z, lag_z, cfg["lag_range"], rng)
            wht = synth_null("white", lead_z.index, lag_z, cfg["lag_range"], rng)
            rwk = synth_null("rw", lead_z.index, lag_z, cfg["lag_range"], rng)

            d_rot = describe(rot, 0.3, 0.15)
            d_pha = describe(pha, 0.3, 0.15)
            obs_c, obs_k = OBSERVED[chain][name]
            obs = abs(obs_c)
            pct_rank = float((rot < obs).mean())     # 我们的发现落在噪声分布的第几百分位

            print(f"\n-- 指标：{name} --")
            print(f"  旋转法零分布  : 中位 {d_rot['p50']:.3f} | p95 {d_rot['p95']:.3f} "
                  f"| p99 {d_rot['p99']:.3f} | 最大 {d_rot['max']:.3f}")
            print(f"  相位法零分布  : 中位 {d_pha['p50']:.3f} | p95 {d_pha['p95']:.3f} "
                  f"| p99 {d_pha['p99']:.3f} | 最大 {d_pha['max']:.3f}")
            print(f"  白噪声/随机游走: 中位 {np.median(wht):.3f} / {np.median(rwk):.3f} "
                  f"| p95 {np.percentile(wht,95):.3f} / {np.percentile(rwk,95):.3f}")
            print(f"  ★ 随机数据越线概率：> 0.15（噪声带）{d_rot['fp_rate_at_noise_band']:.1%}"
                  f"  |  > 0.3（通过线）{d_rot['fp_rate_at_pass_corr']:.1%}")
            print(f"  ★ 我们实测的峰值 |corr|={obs:.3f}@{obs_k} 周，"
                  f"落在零分布第 {pct_rank:.0%} 百分位"
                  f"{'（即：比随机配对的中位数还低）' if pct_rank < 0.5 else ''}")

            results["chains"][chain]["metrics"][name] = {
                "rotation": d_rot, "phase": d_pha,
                "white_noise": {"p50": round(float(np.median(wht)), 3),
                                "p95": round(float(np.percentile(wht, 95)), 3)},
                "random_walk": {"p50": round(float(np.median(rwk)), 3),
                                "p95": round(float(np.percentile(rwk, 95)), 3)},
                "observed": {"corr": obs_c, "k": obs_k, "abs": round(obs, 3),
                             "percentile_in_null": round(pct_rank, 4)},
            }
            raw_rows += [{"chain": chain, "metric": name, "method": "rotation", "max_abs_corr": v}
                         for v in rot]
            raw_rows += [{"chain": chain, "metric": name, "method": "phase", "max_abs_corr": v}
                         for v in pha]

    # ---------- 合并两条链：总体假阳性率（决定"下一条链"判定线的依据） ----------
    all_rot = np.array([r["max_abs_corr"] for r in raw_rows if r["method"] == "rotation"])
    print(f"\n{'='*72}\n合并口径（两条链 4 个指标序列，共 {len(all_rot)} 次抽样）\n{'='*72}")
    merged = describe(all_rot, 0.3, 0.15)
    print(f"  零分布：中位 {merged['p50']:.3f} | p90 {merged['p90']:.3f} "
          f"| p95 {merged['p95']:.3f} | p99 {merged['p99']:.3f} | 最大 {merged['max']:.3f}")
    print(f"  随机数据越线概率：> 0.15 → {merged['fp_rate_at_noise_band']:.1%}"
          f"；> 0.3 → {merged['fp_rate_at_pass_corr']:.1%}")
    results["merged"] = merged

    # 三次链尝试 × 2 指标的整体假阳性概率（独立性近似，用于暴露"尝试预算"的真实风险）
    fp = merged["fp_rate_at_pass_corr"]
    results["family_wise"] = {
        "per_metric_chain_fp": fp,
        "over_3_chains_2_metrics_note": round(1 - (1 - fp) ** 6, 4),
    }
    print(f"\n  若跑满 3 条链 × 2 指标（6 次判定），至少出现一次假阳性的概率 ≈ "
          f"{1 - (1 - fp) ** 6:.1%}（独立性近似）")

    (ROOT / "phase0" / "null_calibration_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(raw_rows).to_csv(OUT / "null_calibration_raw.csv", index=False)
    print("\n结论已写入 phase0/null_calibration_results.json（入库可审计）")


if __name__ == "__main__":
    main()
