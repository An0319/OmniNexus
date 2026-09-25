# -*- coding: utf-8 -*-
"""P0-3 纪律锁对抗测试：M1 的 guard 真的挡得住"想作弊的人"吗？

与 tests/run_m1_guard_test.py 的分工
------------------------------------
run_m1_guard_test.py 测的是**正常路径**（6 个场景：首跑/未变/改参/修订/技术性）；
本文件测的是**攻击路径**——一个想绕开纪律的人会怎么做。

攻击清单（每条都是"人真的会这么干"的作弊法）
--------------------------------------------
A1 删记录洗白：把 chains/<id>.record.json 删掉再跑 → 期望：拒绝
   （否则"改参数 → 删记录 → 跑"就成了一条免费通道）
A2 记账舞弊：把 budget.used 从 2 改回 0，参数一字不动 → 期望：拒绝
   （指纹只覆盖判定参数，改 used 不会触发指纹变化 → 已用额度被抹掉）
A3 技术性豁免滥用：改判定线 pass_corr 0.3→0.2，同时登记一条
   counts_as_attempt=false 的"技术性修订" → 期望：拒绝
   （否则只要把改判定线包装成"技术性"，就能不计尝试地改判定线）
A4 伪造指纹：手改 record.json 里的 fingerprint 使其与当前参数一致，
   企图让 guard 以为"参数没变" → 期望：运行日志留痕，篡改被发现
A5 正常路径不回归：确保加固后 5 条正常路径行为不变

运行：python tests/run_p0_guard_adversarial.py
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from omninexus.guard import (  # noqa: E402
    check_discipline, fingerprint, init_ledger, write_record)

FAILURES = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        FAILURES.append(name)


def cfg_used(used: int, **over) -> dict:
    """一条"已经跑过两次"的链配置（判定参数与 chain01 同构）。"""
    cfg = {
        "chain_id": "atk",
        "judgement": {"lag_range": [0, 26], "pass_window": [4, 13],
                      "pass_corr": 0.3, "noise_band": 0.15},
        "lead": {"params": {"keywords": ["a", "b"], "weeks_back": 312,
                            "cache_file": "c.csv"}},
        "lag": {"params": {"sector": "机器人", "proxy_stock": "sh688017",
                           "proxy_name": "绿的谐波", "weeks_back": 312}},
        "budget": {"max_attempts": 3, "used": used},
        "revisions": [{"date": "2026-09-25", "reason": "初版", "counts_as_attempt": True},
                      {"date": "2026-09-25", "reason": "换链#1", "counts_as_attempt": True}],
    }
    cfg.update(over)
    return cfg


VERDICTS = [{"metric": "周收益率", "status": "GREY", "k_best": 20, "corr": 0.149}]
BASE = cfg_used(2)


def fresh(tmp: Path):
    """建一条"已跑两次"的链台账（含 record.json 与 append-only 运行日志）。"""
    record = tmp / "atk.record.json"
    init_ledger(record, BASE, note="测试用历史初始化")
    return record


with tempfile.TemporaryDirectory() as tmpd:
    tmp = Path(tmpd)

    print("== A1 删记录洗白：删掉 record.json 再跑 ==")
    record = fresh(tmp)
    record.unlink()
    g = check_discipline(BASE, record)
    check("拒绝（记录缺失但 YAML 声明已用 2 次）", not g.ok, f"ok={g.ok}")
    print(f"       guard 说：{g.message.splitlines()[0][:70]}")

    print("== A2 记账舞弊：budget.used 2 -> 0，参数不动 ==")
    record = fresh(tmp)
    cheat = cfg_used(0)
    check("指纹未变（说明指纹确实覆盖不到 used）",
          fingerprint(cheat) == fingerprint(BASE))
    g = check_discipline(cheat, record)
    check("拒绝（已用额度不得回退）", not g.ok, f"ok={g.ok}")
    print(f"       guard 说：{g.message.splitlines()[0][:70]}")

    print("== A3 技术性豁免滥用：改判定线 + 标为不计尝试 ==")
    record = fresh(tmp)
    cheat = cfg_used(2, judgement={"lag_range": [0, 26], "pass_window": [4, 13],
                                   "pass_corr": 0.2, "noise_band": 0.15})
    cheat["revisions"] = BASE["revisions"] + [
        {"date": "2026-09-26", "reason": "放宽及格线（自称技术性）",
         "counts_as_attempt": False}]
    g = check_discipline(cheat, record)
    check("拒绝（判定线变化必须计入尝试）", not g.ok, f"ok={g.ok}")
    print(f"       guard 说：{g.message.splitlines()[0][:70]}")

    print("== A4 伪造指纹：手改 record.json 让指纹与当前参数一致 ==")
    record = fresh(tmp)
    cheat = cfg_used(2, judgement={"lag_range": [0, 26], "pass_window": [4, 13],
                                   "pass_corr": 0.2, "noise_band": 0.15})
    rec = json.loads(record.read_text(encoding="utf-8"))
    rec["fingerprint"] = fingerprint(cheat)      # 伪造：假装参数从没变过
    rec["last_verdicts"] = [{"metric": "周收益率", "status": "PASS", "k_best": 5, "corr": 0.42}]
    record.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    g = check_discipline(cheat, record)
    check("拒绝（运行日志与记录不一致，篡改被发现）", not g.ok, f"ok={g.ok}")
    print(f"       guard 说：{g.message.splitlines()[0][:70]}")

    print("== A5 正常路径不回归 ==")
    record = fresh(tmp)
    check("参数未变 -> 放行", check_discipline(BASE, record).ok)
    ok_rev = cfg_used(3, judgement={"lag_range": [0, 26], "pass_window": [4, 13],
                                    "pass_corr": 0.2, "noise_band": 0.15})
    ok_rev["revisions"] = BASE["revisions"] + [
        {"date": "2026-09-26", "reason": "协议修订：判定线调整", "counts_as_attempt": True}]
    check("改参 + 登记修订 + used+1 -> 放行", check_discipline(ok_rev, record).ok)
    write_record(record, ok_rev, VERDICTS)
    tech = {**ok_rev, "lead": {"params": {**ok_rev["lead"]["params"], "mailto": "x@y.z"}}}
    tech["revisions"] = ok_rev["revisions"] + [
        {"date": "2026-09-26", "reason": "联系方式调整（技术性）", "counts_as_attempt": False}]
    check("纯技术性修订（不动判定口径）-> 放行", check_discipline(tech, record).ok)
    newc = {**BASE, "chain_id": "atk2", "budget": {"max_attempts": 3, "used": 0}}
    check("新链首跑（used=0，无记录）-> 放行",
          check_discipline(newc, tmp / "atk2.record.json").ok)

print("\n== 结果 ==")
if FAILURES:
    print(f"对抗测试失败（防线被击穿）：{FAILURES}")
    sys.exit(1)
print("全部通过：4 类作弊路径均被拒绝，5 条正常路径不受影响。")
