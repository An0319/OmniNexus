"""用 zh 规则集跑 80 条中文样本，和 A 侧标注逐条比。

用法：
    python phase0/timeline/eval_zh_rules.py

口径：
- 三态回填：引擎出事件 → 是；拒绝码属「判不了」类 → 说不清；其余拒绝 → 不是。
- 窗口放到 2020-01-01 ~ 2026-12-31，只为让「时点可解析」单独显形，不拿窗口卡样本。
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
    agree = sum(r["want"] == r["got"] for r in rows)
    print(f"n={n} agree={agree} rate={agree / n:.4f} 基准线(全判不是)={sum(r['want'] != '是' for r in rows)}/{n}")
    print("matrix", {(a, b): sum(1 for r in rows if r["want"] == a and r["got"] == b) for a in ["是", "不是", "说不清"] for b in ["是", "不是", "说不清"]})
    print("按类别:", {c: f"{sum(r['want'] == r['got'] for r in rows if r['category'] == c)}/{sum(1 for r in rows if r['category'] == c)}" for c in sorted({r['category'] for r in rows})})
    print("拒绝码分布:", dict(Counter(r["reason"] for r in rows if r["reason"])))
    print("\n差异逐条：")
    for r in rows:
        if r["want"] != r["got"]:
            print(f"  {r['id']} [{r['category']}] A={r['want']} 引擎={r['got']} code={r['reason']} action={r['action']} subject={r['subject']} | {r['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
