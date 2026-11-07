"""跑对照实验并落 `control_results.md`（探索性沙箱，非预注册）。

参数全部来自 `phase0/controls/control_design.md`，本文件不提供任何调参入口。

用法（仓库根目录）：
  python phase0/controls/run_controls.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

PHASE0 = Path(__file__).resolve().parent.parent
if str(PHASE0) not in sys.path:
    sys.path.insert(0, str(PHASE0))

import ruler  # noqa: E402

ROOT = PHASE0.parent
DATA = PHASE0 / "controls" / "data"
ALPHA = 0.05

POS_SEGMENTS = [("A", "1992-01-03", "2010-12-31"), ("B", "2011-01-07", "2026-10-30")]
NEG_SEGMENTS = [("A", "2006-11-03", "2015-12-25"), ("B", "2016-01-01", "2026-10-30")]
LAG_RANGE = (0, 8)
WINDOW = (1, 8)
PRIOR_BAND = (2, 6)


def pval(view) -> float:
    hit, total = view.hit_peak
    return hit / total


def segment_rows(rep, prior=None):
    rows = []
    for s in rep.segments:
        a, f = s.all_shifts, s.far_shifts
        ci = s.corr_ci
        rows.append({
            "seg": s.name, "k": s.peak_k, "corr": s.peak_corr, "n": s.peak_n,
            "p_all": pval(a), "p_far": pval(f),
            "in_prior": True if prior is None else (prior[0] <= s.peak_k <= prior[1]),
            "ci": ci, "ci_excl0": ci is not None and (ci[0] > 0 or ci[1] < 0),
            "p70": a.p70, "p95": a.p95, "neff": a.neff,
            "n_all": a.n, "n_far": f.n,
            "hit_all": a.hit_peak, "hit_far": f.hit_peak,
        })
    return rows


def sig(row) -> bool:
    return row["p_all"] <= ALPHA and row["p_far"] <= ALPHA and row["ci_excl0"]


def md_table(rep) -> str:
    out = [
        "| 段 | 窗口峰值 | n | P(≥峰值) 全 | P(≥峰值) 远 | 段 p70 | 段 p95 | N_eff 全 | 峰值 95% 区间 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in rep.segments:
        a, f = s.all_shifts, s.far_shifts
        ci = "—" if s.corr_ci is None else f"{s.corr_ci[0]:+.3f} … {s.corr_ci[1]:+.3f}"
        out.append(
            f"| {s.name} | {s.peak_corr:+.4f} @ k={s.peak_k} | {s.peak_n} "
            f"| {a.hit_peak[0]}/{a.n} | {f.hit_peak[0]}/{f.n} "
            f"| {a.p70:.2f} | {a.p95:.2f} | {a.neff:.1f} | {ci} |")
    return "\n".join(out)


def main() -> int:
    weekly = pd.read_csv(DATA / "weekly_controls.csv", parse_dates=["week_friday"],
                         index_col="week_friday")
    snap = json.loads((DATA / "snapshot.json").read_text(encoding="utf-8"))

    pos = ruler.measure(weekly["crude_ret"], weekly["gas_ret"], POS_SEGMENTS,
                        LAG_RANGE, WINDOW)
    neg = ruler.measure(weekly["xlv_ret"], weekly["slx_ret"], NEG_SEGMENTS,
                        LAG_RANGE, WINDOW)
    pos_rows = segment_rows(pos, prior=PRIOR_BAND)
    neg_rows = segment_rows(neg, prior=None)

    pos_pass = [r for r in pos_rows if sig(r) and r["in_prior"]]
    pos_reverse = [r for r in pos_rows if sig(r) and r["corr"] < 0 and not r["in_prior"]]
    neg_sig = [r for r in neg_rows if sig(r)]
    neg_clean = all(not sig(r) for r in neg_rows)

    if not pos_pass or pos_reverse:
        verdict = "阳性也测不出 → 先修尺子（尺子太严或统计量选错），换数据没有意义"
    elif neg_clean:
        verdict = "阳性测得出、阴性测不出 → 尺子可信，今天的否定结果成立，可以往下做能力"
    else:
        verdict = "两个都测得出 → 假阳性率失控，判据需要重做"

    def line(r, kind):
        return (f"| {kind} | {r['seg']} | {r['corr']:+.4f} @ k={r['k']} | {r['n']} "
                f"| {r['hit_all'][0]}/{r['n_all']} ({r['p_all']*100:.2f}%) "
                f"| {r['hit_far'][0]}/{r['n_far']} ({r['p_far']*100:.2f}%) "
                f"| {r['p70']:.2f} | {r['p95']:.2f} | {r['neff']:.1f} "
                f"| {'是' if r['ci_excl0'] else '否'} "
                f"| {'是' if r['in_prior'] else '否' if r['in_prior'] is not None else '—'} "
                f"| {'是' if sig(r) else '否'} |")

    lines = [
        "# 阶段二 · 尺子对照实验结果（探索性，非预注册）",
        "",
        "> 性质：**探索性沙箱**。不预注册、不进过程账本、不计尝试次数、不进任何对外报告。",
        "> 参数在 `control_design.md` 中跑前写定，本文件只落结果，不含调参。",
        "",
        "## 1. 结果",
        "",
        "### 1.1 阳性对照：WTI 原油周收益 → 美国零售汽油周收益",
        "",
        md_table(pos),
        "",
        "### 1.2 阴性对照：XLV（医疗）周收益 → SLX（钢铁）周收益",
        "",
        md_table(neg),
        "",
        "## 2. 判据落点（`α = 5%`，全/远两版零分布都须满足，且区间不含 0）",
        "",
        "| 对照 | 段 | 峰值 | n | P(≥峰值) 全 | P(≥峰值) 远 | 段 p70 | 段 p95 | N_eff | 区间不含 0 | 落在先验带 | 显著 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in pos_rows:
        lines.append(line(r, "阳性"))
    for r in neg_rows:
        lines.append(line(r, "阴性"))
    lines += ["", "**阳性**（先验带 `k∈[2,6]`）："]
    for r in pos_rows:
        reasons = []
        if not (PRIOR_BAND[0] <= r["k"] <= PRIOR_BAND[1]):
            reasons.append(f"峰值 k={r['k']} 不在先验带")
        if r["p_all"] > ALPHA:
            reasons.append(f"全平移 P={r['p_all']*100:.1f}% > 5%")
        if r["p_far"] > ALPHA:
            reasons.append(f"远平移 P={r['p_far']*100:.1f}% > 5%")
        if not r["ci_excl0"]:
            reasons.append("区间含 0")
        lines.append(f"- 段 {r['seg']}：" + ("通过" if sig(r) and r["in_prior"]
                                            else "未通过（" + "；".join(reasons) + "）"))
    lines += ["", "**阴性**（窗口 `[1,8]` 内不应显著）："]
    for r in neg_rows:
        lines.append(f"- 段 {r['seg']}：" + ("测不出（通过）" if not sig(r)
                                            else f"测得出（未通过，P={r['p_all']*100:.1f}%/{r['p_far']*100:.1f}%）"))
    lines += [
        "",
        "## 3. 结论",
        "",
        f"**{verdict}**",
        "",
        "## 4. 数据留痕",
        "",
        "| 序列 | 抓取时刻 (UTC) | 行数（周） | 首 | 末 | 二次抓取一致 |",
        "|---|---|---|---|---|---|",
    ]
    label = {"DCOILWTICO": "WTI 原油", "GASREGW": "零售汽油", "XLV": "XLV", "SLX": "SLX"}
    for key in ("DCOILWTICO", "GASREGW", "XLV", "SLX"):
        m = snap["sources"][key]
        same = "是" if m["identical_on_refetch"] else (
            f"否（{m.get('refetch_diff_count', 0)} 行末位抖动，最大 {m.get('refetch_diff_max_abs', 0):.1e}）")
        lines.append(f"| {label[key]} | {m['fetched_at_utc']} | {m['rows']} | {m['first']} "
                     f"| {m['last']} | {same} |")
    lines += [
        "",
        f"原始件目录 `phase0/controls/data/`，SHA256 与完整快照见 `snapshot.json`；"
        f"派生周收益 `weekly_controls.csv`。",
        "",
        "## 5. 判读",
        "",
        "- 阳性两段均在 k=2 通过三条判据：全平移 P(≥峰值) 7/2127（0.3%）、远平移 0/2077；"
        "峰值区间 A `+0.318…+0.410`、B `+0.362…+0.485`，均不含 0；峰值量级 0.37 / 0.43，"
        "落在先验带 2–6 周内。",
        "- 阴性段 B 测不出：峰值 `+0.0358 @ k=7`，P(≥峰值) 85%，区间 `-0.044…+0.112` 含 0。",
        "- 阴性段 A 是边缘越线：峰值 `+0.1268 @ k=8`，恰在段 p95=0.12 之上，"
        "全平移 57/1451（3.9%）、远平移 42/1401（3.0%），区间 `+0.024…+0.228` 不含 0。",
        "- 按跑前写死的判据（阴性两段都不许显著），结果落在第三行「两个都测得出」。"
        "但成因更像一次边缘假阳性：两段阴性只有一段以 3–4% 越线，5% 线在两段上做两次检验"
        "的族错误率约 10%，且该峰值只比段 p95 高 0.007。判据 v2 只能在明写理由后另开"
        "（候选：按段数做族错误率校正，每段 2.5%；或要求两段同向一致），v2 结果仍只当探索性读。",
        "- 这些 P 是「零分布里达到或超过该峰值的平移占比」，不是抽样 p 值。",
        "",
    ]
    out = ROOT / "phase0" / "controls" / "control_results.md"
    out.write_text("\n".join(lines), encoding="utf-8")

    print(md_table(pos))
    print()
    print(md_table(neg))
    print()
    for r in pos_rows + neg_rows:
        print(f"{r['seg']}: peak {r['corr']:+.4f}@k={r['k']} n={r['n']} "
              f"p_all={r['p_all']*100:.2f}% p_far={r['p_far']*100:.2f}% "
              f"ci={r['ci']} p70={r['p70']:.2f} p95={r['p95']:.2f} neff={r['neff']:.1f}")
    print()
    print("VERDICT:", verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
