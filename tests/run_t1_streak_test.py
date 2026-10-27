# -*- coding: utf-8 -*-
"""T1 连续日计数测试：双 cron 下的 streak 幂等性（完全离线，临时目录）。

守护的不变量（docs/T1-工具化设计.md §13）：
  1. 同一 UTC 日跑两次 → runs 累加，streak 只算一天（不翻倍）；
  2. 当日首次失败、再次成功 → 当日达标，streak 正常 +1；
  3. 当日首次成功、再次失败 → 状态不降级，已达标的事实不被后续失败抹掉；
  4. 整日无运行 → 登记 missing + breaks，streak 归零（不补、不豁免）。

任何一条被破坏，都会让 T1 的 30 天计时失去可信度。

运行：python tests/run_t1_streak_test.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import daily_update as du  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        FAILURES.append(name)


OK = {"chain01": {"status": "ok", "failure_reasons": []},
      "chain10": {"status": "ok", "failure_reasons": []}}
BAD = {"chain01": {"status": "ok", "failure_reasons": []},
       "chain10": {"status": "failed", "failure_reasons": ["光模块为空"]}}


def new_doc():
    return {"project": "omninexus", "target_days": 30, "current_streak": 0,
            "started_utc_date": None, "last_success_utc_date": None,
            "last_run_utc": None, "days": [], "breaks": [], "resets": []}


def day(doc, date):
    return next(d for d in doc["days"] if d["utc_date"] == date)


with tempfile.TemporaryDirectory() as tmp:
    # _update_streak 落盘到模块级 STREAK_PATH，测试期间指向临时目录
    du.STREAK_PATH = Path(tmp) / "streak.json"

    print("== 场景1：同一 UTC 日跑两次（均成功）→ runs=2，streak 不翻倍 ==")
    doc = new_doc()
    du._update_streak(doc, "2026-10-01", "2026-10-01T00:30:00Z", OK, True)
    du._update_streak(doc, "2026-10-01", "2026-10-01T12:30:00Z", OK, True)
    d = day(doc, "2026-10-01")
    check("runs=2", d["runs"] == 2, f"got={d['runs']}")
    check("status=success", d["status"] == "success")
    check("current_streak=1", doc["current_streak"] == 1, f"got={doc['current_streak']}")

    print("== 场景2：次日首跑失败、再次成功 → 当日达标，streak=2 ==")
    du._update_streak(doc, "2026-10-02", "2026-10-02T00:30:00Z", BAD, False)
    check("首跑后 status=failure", day(doc, "2026-10-02")["status"] == "failure")
    check("首跑后 streak 仍为 1", doc["current_streak"] == 1, f"got={doc['current_streak']}")
    du._update_streak(doc, "2026-10-02", "2026-10-02T12:30:00Z", OK, True)
    d = day(doc, "2026-10-02")
    check("再跑后 status=success", d["status"] == "success")
    check("失败原因被清空", d["failure_reasons"] == [])
    check("current_streak=2", doc["current_streak"] == 2, f"got={doc['current_streak']}")
    check("last_success=10-02", doc["last_success_utc_date"] == "2026-10-02")

    print("== 场景3：当日已达标后，第二次运行失败 → 状态不降级 ==")
    du._update_streak(doc, "2026-10-03", "2026-10-03T00:30:00Z", OK, True)
    du._update_streak(doc, "2026-10-03", "2026-10-03T12:30:00Z", BAD, False)
    d = day(doc, "2026-10-03")
    check("status 仍为 success", d["status"] == "success")
    check("runs=2", d["runs"] == 2, f"got={d['runs']}")
    check("current_streak=3", doc["current_streak"] == 3, f"got={doc['current_streak']}")
    check("breaks 未误记", len(doc["breaks"]) == 0, f"got={len(doc['breaks'])}")

    print("== 场景4：整日无运行（10-04 缺失）→ 登记 missing + breaks，streak 归零 ==")
    du._close_previous_days(doc, "2026-10-05")
    d = day(doc, "2026-10-04")
    check("status=missing", d["status"] == "missing")
    check("登记了断更", [b["utc_date"] for b in doc["breaks"]] == ["2026-10-04"],
          f"got={doc['breaks']}")
    check("断更前连续 3 天", doc["breaks"][0]["streak_lost"] == 3,
          f"got={doc['breaks'][0]['streak_lost']}")
    du._update_streak(doc, "2026-10-05", "2026-10-05T00:30:00Z", OK, True)
    check("current_streak=1（重新起算）", doc["current_streak"] == 1,
          f"got={doc['current_streak']}")
    check("started_utc_date=10-05", doc["started_utc_date"] == "2026-10-05",
          f"got={doc['started_utc_date']}")

    print("== 场景5：STREAK_PATH 确实落盘（供 workflow 提交快照） ==")
    saved = json.loads(du.STREAK_PATH.read_text(encoding="utf-8"))
    check("天数=5", len(saved["days"]) == 5, f"got={len(saved['days'])}")
    check("current_streak 与内存一致", saved["current_streak"] == doc["current_streak"])

print("\n== 结果 ==")
if FAILURES:
    print(f"测试失败：{FAILURES}")
    sys.exit(1)
print("5 个场景全部通过：双 cron 下 streak 幂等、达标不降级、断更归零。")
