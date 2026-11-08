"""用 zh 规则集跑 80 条中文样本，和 A 侧标注逐条比。

用法：
    python phase0/timeline/eval_zh_rules.py

口径（三种并列，缺一不可；每种都带自己的基准线）：
- 严格三态：引擎出事件 → 是；拒绝码属「判不了」类 → 说不清；其余拒绝 → 不是。
- 二态折叠：说不清两侧都按「不是」计。【换了问题】
- 只看判了的：分母只算引擎给出「是/不是」的条目。【换了问题】
- 窗口放到 2020-01-01 ~ 2026-12-31，只为让「时点可解析」单独显形，不拿窗口卡样本。
- 这 80 条来自归纳规则用的 420 条，属开发集，只作回归检查，不承当准确率。
- 只报差异，不修改任何判定去迎合标注。
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from timeline import build_event, load_ruleset  # noqa: E402

UNDECIDABLE = {"insufficient_evidence", "missing_time", "out_of_window", "zh_carrier_unverified"}
START = dt.date(2020, 1, 1)
END = dt.date(2026, 12, 31)


def to_raw(it: dict) -> dict:
    lead = (it.get("lead") or "").strip()
    return {
        "source_id": "zh_sample",
        "title": it["title"],
        "link": it["url"],
        "url_kind": "aggregator",
        "date": it.get("pubdate") or "",
        "excerpt": lead or it["title"],
        "excerpt_kind": None,
        "source_name": it.get("source_site") or "unknown",
        "fetched_at_utc": it.get("fetched_at_utc") or "",
        "subject_hint": None,
        "action_hint": None,
        "object": None,
    }


def main() -> int:
    items = json.loads((HERE / "zh_samples" / "items.json").read_text(encoding="utf-8"))["items"]
    labels = json.loads((HERE / "zh_samples" / "labels_a.json").read_text(encoding="utf-8"))["labels"]
    lab = {x["id"]: x for x in labels}
    rs = load_ruleset("zh")

    rows = []
    for it in items:
        ev, reason = build_event(to_raw(it), START, END, ruleset=rs)
        got = "是" if ev is not None else ("说不清" if reason in UNDECIDABLE else "不是")
        want = lab[it["id"]]["is_event"]
        rows.append(
            {
                "id": it["id"],
                "category": it["category"],
                "title": it["title"],
                "want": want,
                "got": got,
                "reason": reason,
                "action": ev["action"] if ev else None,
                "subject": ev["subject"] if ev else None,
            }
        )

    n = len(rows)
    agree3 = sum(r["want"] == r["got"] for r in rows)
    base3 = sum(r["want"] != "是" for r in rows)

    fold = lambda v: "不是" if v == "说不清" else v  # noqa: E731
    agree2 = sum(fold(r["want"]) == fold(r["got"]) for r in rows)
    base2 = sum(fold(r["want"]) != "是" for r in rows)

    decided = [r for r in rows if r["got"] != "说不清"]
    agree1 = sum(r["want"] == r["got"] for r in decided)
    base1 = sum(r["want"] != "是" for r in decided)

    print(f"[口径1 严格三态]    n={n} agree={agree3} rate={agree3 / n:.4f} 基准线(全判不是)={base3}/{n}={base3 / n:.4f}")
    print(f"[口径2 二态折叠]    n={n} agree={agree2} rate={agree2 / n:.4f} 基准线={base2}/{n}={base2 / n:.4f}  【换了问题：说不清按不是计】")
    print(f"[口径3 只看判了的]  n={len(decided)} agree={agree1} rate={agree1 / len(decided):.4f} 基准线={base1}/{len(decided)}={base1 / len(decided):.4f}  【换了问题：分母只算引擎给出是/不是的】")
    if decided and base3:
        print(f"[留出情况] 引擎判不了={n - len(decided)} 条（占 {1 - len(decided) / n:.1%}），口径3 不回答这部分")

    # 三档池的运营口径：量的是「收进哪一档」，与分桶是否一致不是同一个问题
    want_yes = sum(r["want"] == "是" for r in rows)
    fp_rows = [r for r in rows if r["got"] == "是" and r["want"] != "是"]
    fn_rows = [r for r in rows if r["want"] == "是" and r["got"] != "是"]
    pend_rows = [r for r in rows if r["got"] == "说不清"]
    print("\n四栏各自回答不同问题，任何一栏都不得称为「实际准确率」。")
    print(f"[池1 误收]    {len(fp_rows)}/{n} = {len(fp_rows) / n:.4f}  基准线(全判是)={base3}/{n} = {base3 / n:.4f}  【人判不是/说不清，引擎判是】")
    print(f"[池2 漏收]    {len(fn_rows)}/{n} = {len(fn_rows) / n:.4f}  基准线(全判不是)={want_yes}/{n} = {want_yes / n:.4f}  【人判是，引擎没判是】")
    print(f"[池3 落待定]  {len(pend_rows)}/{n} = {len(pend_rows) / n:.4f}  基准线(全判是/全判不是)=0/{n} = 0.0000  【待定是三档设计里的位置，不是错误】")
    print("判不了构成（code × A 侧）:", dict(Counter((r["reason"], r["want"]) for r in pend_rows)))

    # 「一致」要拆成「有据」与「侥幸」：沉默与规则命中长得一样，可信度不一样
    SILENT = {"insufficient_evidence", "missing_time", "out_of_window", "zh_carrier_unverified"}
    PARSE_DEFAULT = {"unparsed_subject", "unparsed_action"}  # 词表没覆盖/解析失败：按默认路径判「不是」
    grounded_agree = [r for r in rows if r["want"] == r["got"] and (r["got"] == "是" or not (r["reason"] in SILENT or r["reason"] in PARSE_DEFAULT))]
    lucky_agree = [r for r in rows if r["want"] == r["got"] and r["got"] == "不是" and r["reason"] in PARSE_DEFAULT]
    lucky = [r for r in rows if r["want"] != "是" and r["got"] == "说不清"]
    silent_opp = [r for r in rows if r["want"] == "是" and r["got"] == "说不清"]
    grounded_opp = [r for r in rows if r["got"] == "是" and r["want"] != "是"]
    print(f"\n[一致构成] 有据一致={len(grounded_agree)}  侥幸一致(48内默认路径)={len(lucky_agree)}  无据且结论相反={len(silent_opp)}  有据但结论相反(误收)={len(grounded_opp)}")
    print(f"  另有「侥幸一致(单列栏)」={len(lucky)}：A 判不是、引擎沉默，折叠口径2里看似一致，不计入任何分子")
    print("  48 条一致按拒绝码构成:", dict(Counter(r["reason"] for r in rows if r["want"] == r["got"])))
    print("  「侥幸一致」（单列，不计入任何一栏的分子）：")
    for r in lucky:
        print(f"    {r['id']} [{r['category']}] A={r['want']} 引擎=沉默 code={r['reason']} | {r['title'][:64]}")
    print("matrix", {(a, b): sum(1 for r in rows if r["want"] == a and r["got"] == b) for a in ["是", "不是", "说不清"] for b in ["是", "不是", "说不清"]})
    print("按类别（严格三态）:", {c: f"{sum(r['want'] == r['got'] for r in rows if r['category'] == c)}/{sum(1 for r in rows if r['category'] == c)}" for c in sorted({r['category'] for r in rows})})
    print("拒绝码分布:", dict(Counter(r["reason"] for r in rows if r["reason"])))
    print("\n差异逐条：")
    for r in rows:
        if r["want"] != r["got"]:
            print(f"  {r['id']} [{r['category']}] A={r['want']} 引擎={r['got']} code={r['reason']} action={r['action']} subject={r['subject']} | {r['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
