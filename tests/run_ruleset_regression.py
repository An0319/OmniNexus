"""英文规则集回归锁：改造前后逐条判定必须一致。

用法：
    python tests/run_ruleset_regression.py

基准：tests/fixtures/timeline_en_baseline.json 由**改造前**的 rules_v2 生成，
记录 4 套基准样本（dev / test / val / def）共 97 条的逐条判定。
本测试不重算任何指标，只验证「同输入、同判定」——README 口径见 AGENTS.md R24。
判据与引擎解耦后（rulesets/en.json），这里任何一格变化都说明重构改了行为，必须修回去。
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMELINE_DIR = ROOT / "phase0" / "timeline"
sys.path.insert(0, str(TIMELINE_DIR))

from timeline import build_event, load_ruleset  # noqa: E402

SETS = {
    "dev": "benchmark_items.json",
    "test": "benchmark_items_test.json",
    "val": "benchmark_items_val.json",
    "def": "benchmark_items_def.json",
}


def verdict(raw: dict, start: dt.date, end: dt.date, rs) -> dict:
    ev, reason = build_event(raw, start, end, ruleset=rs)
    return {
        "emitted": ev is not None,
        "reason": reason,
        "action": ev["action"] if ev else None,
        "subject": ev["subject"] if ev else None,
        "value_kind": ev["value"]["kind"] if ev else None,
    }


def main() -> int:
    baseline = json.loads((ROOT / "tests" / "fixtures" / "timeline_en_baseline.json").read_text(encoding="utf-8"))
    rs = load_ruleset("en")
    diffs = []
    checked = 0
    for tag, fn in SETS.items():
        items = json.loads((TIMELINE_DIR / fn).read_text(encoding="utf-8"))
        start, end = (dt.date.fromisoformat(x) for x in baseline[tag]["window"])
        for it in items:
            checked += 1
            raw = dict(it)
            raw["link"] = it["url"]
            got = verdict(raw, start, end, rs)
            want = baseline[tag]["items"][it["id"]]
            if got != want:
                diffs.append((tag, it["id"], want, got))
    if diffs:
        for tag, item_id, want, got in diffs:
            print(f"[FAIL] {tag}/{item_id}\n  want={want}\n  got ={got}")
        print(f"\n{len(diffs)}/{checked} 条判定变了")
        return 1
    print(f"[OK] {checked} 条英文判定与改造前逐条一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
