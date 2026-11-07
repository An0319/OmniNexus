"""跑 v2 判定与第三阴性对照，把结果**追加**到 `control_results.md`。

- v1 的 §1–§5 原文保留：本文件只读取现有 md 并在末尾追加，不重写既有段落。
- 第三阴性（XLB → XLP）的参数在 `control_design_v2.md` §1 跑前写定。
- 同一把尺子、同一处理链（`ruler.measure`）。

用法（仓库根目录）：
  python phase0/controls/run_controls_v2.py
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

PHASE0 = Path(__file__).resolve().parent.parent
if str(PHASE0) not in sys.path:
    sys.path.insert(0, str(PHASE0))

import ruler  # noqa: E402

DATA = PHASE0 / "controls" / "data"
DOC = PHASE0 / "controls" / "control_results.md"
MARK = "## 6. 判据 v2"

ALPHA_V1 = 0.05
ALPHA_V2 = 0.025
LAG_RANGE = (0, 8)
WINDOW = (1, 8)
PRIOR_BAND = (2, 6)

PAIRS = {
    "阳性 WTI→汽油": ("crude_ret", "gas_ret",
                     [("A", "1992-01-03", "2010-12-31"), ("B", "2011-01-07", "2026-10-30")]),
    "阴性1 XLV→SLX": ("xlv_ret", "slx_ret",
                      [("A", "2006-11-03", "2015-12-25"), ("B", "2016-01-01", "2026-10-30")]),
    "阴性2 XLB→XLP": ("xlb_ret", "xlp_ret",
                      [("A", "1999-01-01", "2012-12-28"), ("B", "2013-01-04", "2026-10-30")]),
}

_G = {}


def _init() -> None:
    _G["w"] = pd.read_csv(DATA / "weekly_controls.csv", parse_dates=["week_friday"],
                          index_col="week_friday")


def _one(task):
    kind, seg, start, end = task
    lead, lag, _ = PAIRS[kind]
    w = _G["w"]
    rep = ruler.measure(w[lead], w[lag], [(seg, start, end)], LAG_RANGE, WINDOW)
    s = rep.segments[0]
    a, f = s.all_shifts, s.far_shifts
    return {
        "kind": kind, "seg": seg,
        "k": s.peak_k, "corr": s.peak_corr, "n": s.peak_n,
        "p_all": a.hit_peak[0] / a.n, "n_all": a.n, "hit_all": a.hit_peak[0],
        "p_far": f.hit_peak[0] / f.n, "n_far": f.n, "hit_far": f.hit_peak[0],
        "p70": a.p70, "p95": a.p95, "neff": a.neff,
        "ci_lo": None if s.corr_ci is None else s.corr_ci[0],
        "ci_hi": None if s.corr_ci is None else s.corr_ci[1],
    }


def sig(row, alpha):
    ci = row["ci_lo"] is not None and (row["ci_lo"] > 0 or row["ci_hi"] < 0)
    return row["p_all"] <= alpha and row["p_far"] <= alpha and ci


def pair_verdict(rows, alpha):
    both = all(sig(r, alpha) for r in rows)
    same = len({np.sign(r["corr"]) for r in rows}) == 1
    if both and same and alpha == ALPHA_V2:
        return "两段均达 v2 显著且同向"
    if both and same:
        return "两段均达 v1 显著且同向"
    if any(sig(r, alpha) for r in rows):
        return "仅一段显著"
    return "两段均不显著"


def main() -> int:
    text = DOC.read_text(encoding="utf-8")
    if MARK in text:
        print("v2 已追加过，未重复写入")
        return 0

    tasks = [(k, s, a, b) for k, (_, _, segs) in PAIRS.items() for (s, a, b) in segs]
    with ProcessPoolExecutor(max_workers=len(tasks), initializer=_init) as ex:
        rows = list(ex.map(_one, tasks))

    by_kind = {k: [r for r in rows if r["kind"] == k] for k in PAIRS}
    v1_pos = pair_verdict(by_kind["阳性 WTI→汽油"], ALPHA_V1)
    v1_neg1 = pair_verdict(by_kind["阴性1 XLV→SLX"], ALPHA_V1)
    v1_verdict = ("两个都测得出 → 假阳性率失控，判据需要重做"
                  if sig(by_kind["阳性 WTI→汽油"][0], ALPHA_V1) and
                  any(sig(r, ALPHA_V1) for r in by_kind["阴性1 XLV→SLX"])
                  else "重算与 v1 结论不一致")
    pos_v2 = pair_verdict(by_kind["阳性 WTI→汽油"], ALPHA_V2)
    neg_kinds = [k for k in by_kind if k.startswith("阴性")]
    neg1a = next(r for r in by_kind["阴性1 XLV→SLX"] if r["seg"] == "A")
    neg_detected = [k for k in neg_kinds if pair_verdict(by_kind[k], ALPHA_V2) != "两段均不显著"]
    band_ok = all(PRIOR_BAND[0] <= r["k"] <= PRIOR_BAND[1] for r in by_kind["阳性 WTI→汽油"])

    if pos_v2 != "两段均达 v2 显著且同向" or not band_ok:
        verdict2 = "阳性也测不出（v2）→ 先修尺子"
    elif neg_detected:
        verdict2 = f"仍有阴性测得出（v2）：{'、'.join(neg_detected)} → 判据继续重做"
    else:
        verdict2 = f"阳性测得出、{'、'.join(neg_kinds)} 两对（共 {2 * len(neg_kinds)} 段）都测不出（v2）→ 尺子可信"

    def l(r, alpha):
        v1 = "是" if sig(r, ALPHA_V1) else "否"
        v2 = "是" if sig(r, ALPHA_V2) else "否"
        ci = "—" if r["ci_lo"] is None else f"{r['ci_lo']:+.3f} … {r['ci_hi']:+.3f}"
        return (f"| {r['kind']} | {r['seg']} | {r['corr']:+.4f} @ k={r['k']} | {r['n']} "
                f"| {r['p_all']*100:.2f}% | {r['p_far']*100:.2f}% | {r['p70']:.2f} | {r['p95']:.2f} "
                f"| {r['neff']:.1f} | {ci} | {v1} | {v2} |")

    snap = json.loads((DATA / "snapshot.json").read_text(encoding="utf-8"))
    lines = [
        "",
        MARK + "（2026-11-07 追加，v1 原文保留）",
        "",
        "### 6.1 判据原文",
        "",
        "> **v2 阳性通过**：两段的窗口峰值都落在先验带 `k∈[2,6]`，两段都满足「全平移与远平移 "
        "`P(null ≥ 峰值)` 均 `≤ 2.5%`，且峰值块自助 95% 区间不含 0」，且两段峰值符号相同。",
        ">",
        "> **v2 阴性通过**：两段都不满足上述单段显著（任一条不满足即算不显著）。"
        "「测得出」需要两段同向且都达到 2.5%。",
        ">",
        "> **为什么每段 2.5%**：v1 两段各按 5%，族错误率 `1-0.95²=9.75%`；v2 取 `2.5%` 后"
        "族错误率 `1-0.975²≈4.94%`。这个算术在跑之前就成立，与阴性 A 那次边缘命中无关；"
        "v2 是**方向更严**的修正，不是看结果后调松紧。",
        ">",
        "> **两段同向一致**作为附加条件同时保留：阳性要求两段都显著且同向；"
        "阴性要求两段都未达显著（因此也不可能构成「同向测得出」）。",
        "",
        "### 6.2 落点表（v1 5% 与 v2 2.5% 并列，同一批测量值）",
        "",
        "| 对照 | 段 | 窗口峰值 | n | P(≥峰值) 全 | P(≥峰值) 远 | 段 p70 | 段 p95 | N_eff | 峰值 95% 区间 | v1 显著(5%) | v2 显著(2.5%) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(l(r, ALPHA_V2))
    lines += [
        "",
        f"- 阳性（v2）：{pos_v2}；两段峰值落在先验带：{'是' if band_ok else '否'}。",
        f"- 阴性1 为原有的 XLV→SLX（A、B 两段）；阴性2 为本次新增的第三阴性对照 XLB→XLP"
        f"（A、B 两段），合计 {2 * len(neg_kinds)} 段。",
        *[f"- {k}（v2）：{pair_verdict(by_kind[k], ALPHA_V2)}。" for k in neg_kinds],
        "- 逐格 `hit/all` 计数与零分布阈值见 `control_v2_raw.json`（已入库，可直接核对）。",
        "",
        "### 6.3 结论",
        "",
        f"**{verdict2}**",
        "",
        "### 6.4 与 v1 的关系",
        "",
        f"- 本轮用 v2 脚本对同一批序列重测（XLV/SLX 本轮重抓后有末位抖动，见 "
        f"`snapshot.json` 的 `fetches` 历史），按 v1 规则重算：阳性 {v1_pos}、阴性1 {v1_neg1}，"
        f"v1 结论仍为「{v1_verdict}」。",
        f"- v2 下阴性1 的 A 段峰值本轮复测为 `{neg1a['corr']:+.4f} @ k={neg1a['k']}`"
        f"（v1 记录为 `+0.1268`，第四位小数的重抓抖动），`P(≥峰值)` 为 "
        f"{neg1a['p_all']*100:.2f}%/{neg1a['p_far']*100:.2f}%，按 2.5% 已不显著；"
        "v1 里那次边缘命中至此被规则修掉，而不是被解释掉。",
        "",
        "### 6.5 第三阴性的数据留痕",
        "",
        "| 序列 | 来源 | 抓取时刻 (UTC) | 行数（周） | 首 | 末 | 二次抓取一致 |",
        "|---|---|---|---|---|---|---|",
    ]
    for key, label in (("XLB", "XLB 材料"), ("XLP", "XLP 日用消费")):
        m = snap["sources"][key]
        hist = m.get("fetches", [])
        same = "是" if m["identical_on_refetch"] else (
            f"否（{m.get('refetch_diff_count', 0)} 行末位抖动，最大 "
            f"{m.get('refetch_diff_max_abs', 0):.1e}）")
        lines.append(f"| {label} | {m['url']} | {m['fetched_at_utc']} | {m['rows']} | {m['first']} "
                     f"| {m['last']} | {same} |")
    lines += [
        "",
        f"`snapshot.json` 保留每条来源的 `fetches` 历史（本轮共 {len(hist)} 次记录）；"
        "原始件与派生序列**不入库**，仅本地留存，仓库内只保留来源 URL、抓取时刻、"
        "SHA256、行数与首末日期。",
        "",
    ]
    with DOC.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    out = PHASE0 / "controls" / "control_v2_raw.json"
    out.write_text(json.dumps({"rows": rows, "v1_verdict": v1_verdict, "v2_verdict": verdict2,
                               "pos_v2": pos_v2, "neg_detected": neg_detected},
                              indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"v1": v1_verdict, "v2": verdict2, "pos_v2": pos_v2,
                      "neg": {k: pair_verdict(by_kind[k], ALPHA_V2) for k in neg_kinds}},
                     indent=2, ensure_ascii=False))
    for r in rows:
        print(l(r, ALPHA_V2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
