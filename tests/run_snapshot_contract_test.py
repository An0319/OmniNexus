# -*- coding: utf-8 -*-
"""快照契约守卫（N2）：看板 data.ts 用 `as unknown as` 断言装载 JSON，
TypeScript 构建期不校验实际形状——字段漂移会被断言吞掉，build 绿不等于契约对。
本测试在 CI 层校验数据形状，把契约漂移变成红灯。

校验对象（看板静态导入的全部数据文件）：
  data/snapshot_chain*.json   日更快照（引擎产出 → 看板展示的契约）
  data/streak.json            T1 计时账
  chains/project_budget.json  项目尝试账本（钉死 max_attempts，防静默放宽额度）
  chains/chain*.profile.json  物化 profile 与链 YAML 的 judgement 一致性

设计原则：
  只要求「必需键存在 + 枚举合法 + 关键交叉一致」，容忍新增键——
  E1 哈希链将来给 streak.json 加 last_commit_sha 时本守卫无需返工。
  streak 一致性复用 tools/daily_update._streak_before（不复制第二份算法）。

运行：python tests/run_snapshot_contract_test.py
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import daily_update as du  # noqa: E402  复用 streak 算法，防双副本漂移

DATA = ROOT / "data"
CHAINS = ROOT / "chains"

FAILS = []
CHECKS = [0]


def check(cond: bool, label: str, detail: str = "") -> bool:
    CHECKS[0] += 1
    if cond:
        print(f"  [PASS] {label}" + (f" {detail}" if detail else ""))
    else:
        print(f"  [FAIL] {label} {detail}")
        FAILS.append(f"{label} {detail}")
    return cond


def is_iso_date(s) -> bool:
    if not isinstance(s, str):
        return False
    try:
        dt.date.fromisoformat(s)
        return True
    except ValueError:
        return False


def non_empty_series(series) -> bool:
    return (isinstance(series, dict) and len(series) > 0
            and any(isinstance(v, dict) and len(v) > 0 for v in series.values()))


# ---------------- 快照（snapshot_chain*.json） ----------------
def check_snapshot(path: Path) -> None:
    name = path.name
    snap = json.loads(path.read_text(encoding="utf-8"))
    print(f"== 快照契约：{name} ==")

    check(path.name == f"snapshot_{snap.get('chain_id')}.json",
          "chain_id 与文件名一致", f"({snap.get('chain_id')})")
    check(snap.get("status") in ("ok", "failed"), "status 枚举合法", f"({snap.get('status')})")
    check(isinstance(snap.get("failure_reasons"), list), "failure_reasons 是列表")
    check(isinstance(snap.get("run_utc"), str) and snap.get("run_utc"), "run_utc 存在")

    lead = snap.get("lead")
    lag = snap.get("lag")
    check(isinstance(lead, dict) and lead.get("source") in ("openalex", "us_index"),
          "lead.source 已登记", f"({lead.get('source') if isinstance(lead, dict) else type(lead).__name__})")
    check(isinstance(lead, dict) and isinstance(lead.get("points"), int),
          "lead.points 是整数")
    check(isinstance(lead, dict) and isinstance(lead.get("degraded"), bool),
          "lead.degraded 是布尔")
    check(isinstance(lag, dict) and lag.get("source") == "em_sector",
          "lag.source == em_sector")
    path_val = lag.get("path") if isinstance(lag, dict) else None
    check(path_val is None or (isinstance(path_val, str) and path_val.startswith("路径")),
          "lag.path 是降级路径标记或 null", f"({path_val!r})")

    if snap.get("status") == "ok":
        # 门禁语义：status=ok ⟹ 两面都有数据且无失败原因（看板据此渲染绿灯）
        check(snap.get("failure_reasons") == [], "ok 快照 failure_reasons 为空")
        check(isinstance(lead, dict) and is_iso_date(lead.get("latest")),
              "ok 快照 lead.latest 是 ISO 日期", f"({lead.get('latest') if isinstance(lead, dict) else None})")
        check(isinstance(lead, dict) and non_empty_series(lead.get("series")),
              "ok 快照 lead.series 非空")
        check(isinstance(lag, dict) and is_iso_date(lag.get("latest")),
              "ok 快照 lag.latest 是 ISO 日期")
        lag_series = lag.get("series") if isinstance(lag, dict) else None
        check(isinstance(lag_series, dict) and isinstance(lag_series.get("ret"), dict)
              and len(lag_series.get("ret")) > 0, "ok 快照 lag.series.ret 非空")


# ---------------- streak.json ----------------
def check_streak() -> None:
    print("== 快照契约：streak.json ==")
    doc = json.loads((DATA / "streak.json").read_text(encoding="utf-8"))

    check(doc.get("project") == "omninexus", "project 标识正确")
    check(isinstance(doc.get("target_days"), int) and doc["target_days"] > 0,
          "target_days 是正整数", f"({doc.get('target_days')})")
    check(isinstance(doc.get("current_streak"), int) and doc["current_streak"] >= 0,
          "current_streak 是非负整数", f"({doc.get('current_streak')})")

    days = doc.get("days")
    check(isinstance(days, list) and len(days) > 0, "days 非空列表", f"({len(days) if isinstance(days, list) else 0} 条)")
    if not isinstance(days, list) or not days:
        return

    dates = [d.get("utc_date") for d in days]
    check(all(is_iso_date(x) for x in dates), "days.utc_date 全部 ISO 日期")
    check(dates == sorted(dates), "days 按日期升序")
    check(all(d.get("status") in ("success", "failure", "missing") for d in days),
          "days.status 枚举合法")
    check(all(isinstance(d.get("runs"), int) and d["runs"] >= 0 for d in days),
          "days.runs 非负整数")
    check(all(isinstance(d.get("failure_reasons"), list) for d in days),
          "days.failure_reasons 是列表")
    check(all(isinstance(d.get("chains"), dict) for d in days), "days.chains 是字典")

    check(isinstance(doc.get("breaks"), list), "breaks 是列表")
    check(isinstance(doc.get("resets"), list), "resets 是列表")

    # 交叉一致：streak 数字复用引擎自己的算法重算（today = 最后一条记录日）
    latest = days[-1]["utc_date"]
    expected = du._streak_before(days, latest) + (1 if days[-1]["status"] == "success" else 0)
    check(doc["current_streak"] == expected, "current_streak 与 days 重算一致",
          f"(记录 {doc['current_streak']} / 重算 {expected})")

    succ = [d["utc_date"] for d in days if d["status"] == "success"]
    if doc["current_streak"] > 0 and succ:
        check(doc.get("last_success_utc_date") == succ[-1], "last_success 指向最近成功日",
              f"({doc.get('last_success_utc_date')})")
        want_start = (dt.date.fromisoformat(latest)
                      - dt.timedelta(days=doc["current_streak"] - 1
                                     if days[-1]["status"] == "success"
                                     else doc["current_streak"])).isoformat()
        check(doc.get("started_utc_date") == want_start, "started 起点口径一致",
              f"({doc.get('started_utc_date')})")
    elif doc["current_streak"] == 0:
        check(doc.get("started_utc_date") is None, "streak=0 时 started 为 null")


# ---------------- 项目尝试账本 ----------------
def check_budget() -> None:
    print("== 快照契约：project_budget.json ==")
    doc = json.loads((CHAINS / "project_budget.json").read_text(encoding="utf-8"))
    attempts = doc.get("attempts")

    check(isinstance(doc.get("max_attempts"), int), "max_attempts 是整数")
    # 项目账本 3/3 已封存（审计 D10-C）：max_attempts 被写死在本守卫里，
    # 静默放宽额度会在此红灯。确需修订必须走修订登记并**有意识地**改本测试。
    check(doc.get("max_attempts") == 3, "max_attempts == 3（项目账本冻结值）",
          f"({doc.get('max_attempts')})")
    check(isinstance(attempts, list) and len(attempts) > 0, "attempts 非空列表")
    if isinstance(attempts, list):
        ns = [a.get("n") for a in attempts]
        check(ns == list(range(1, len(attempts) + 1)), "attempt 序号连续", f"({ns})")
        check(all(isinstance(a.get("chain_id"), str) and a.get("chain_id") for a in attempts),
              "attempt.chain_id 存在")
        check(all(is_iso_date(a.get("date")) for a in attempts), "attempt.date 是 ISO 日期")
        ids = [a.get("chain_id") for a in attempts]
        check(len(set(ids)) == len(ids), "chain_id 无重复（一链一尝试）")


# ---------------- profile 与链 YAML 一致性 ----------------
def check_profiles() -> None:
    print("== 快照契约：profile ↔ 链 YAML judgement ==")
    import yaml

    for yaml_path in sorted(CHAINS.glob("chain*.yaml")):
        cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        cid = cfg.get("chain_id") or yaml_path.stem
        profile_path = CHAINS / f"{cid}.profile.json"
        if not profile_path.exists():
            check(False, f"{cid} profile 存在", "(缺失)")
            continue
        profile = json.loads(profile_path.read_text(encoding="utf-8"))

        check(profile.get("chain_id") == cid, f"{cid} profile.chain_id 一致")
        check(profile.get("title") == cfg.get("title"), f"{cid} profile.title 与 YAML 一致")

        # YAML judgement 是预注册口径的唯一来源；profile 是看板展示物化——漂移即谎报判定参数
        yaml_j = dict(cfg.get("judgement") or {})
        prof_j = {k: v for k, v in (profile.get("judgement") or {}).items()
                  if not (k == "null_median" and v is None)}  # null_median 缺省 == null
        check(prof_j == yaml_j, f"{cid} judgement 物化与 YAML 一致",
              f"(YAML {yaml_j} / profile {prof_j})" if prof_j != yaml_j else "")


def main() -> int:
    print("== 快照契约守卫（看板数据形状 CI 校验）==\n")
    snapshots = sorted(DATA.glob("snapshot_chain*.json"))
    check(len(snapshots) > 0, "存在快照文件", f"({len(snapshots)} 份)")
    for p in snapshots:
        check_snapshot(p)
    print()
    check_streak()
    print()
    check_budget()
    print()
    check_profiles()

    print(f"\n== 结果 ==\n共 {CHECKS[0]} 项检查，{len(FAILS)} 处失败。")
    if FAILS:
        print("\n== 失败明细 ==")
        for f in FAILS:
            print("  " + f)
        print("\n契约漂移必须当场修复（修数据或修物化脚本），不允许带病提交。")
        return 1
    print("全部通过：快照/streak/账本/profile 与看板契约一致，新增键被容忍（E1 兼容）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
