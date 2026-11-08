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
