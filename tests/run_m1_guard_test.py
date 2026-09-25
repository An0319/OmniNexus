# -*- coding: utf-8 -*-
"""M1 纪律锁测试：guard 的 6 个场景（完全离线，临时目录）。

运行：python tests/run_m1_guard_test.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from omninexus.guard import check_discipline, fingerprint, write_record  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
    if not cond:
        FAILURES.append(name)


BASE_CFG = {
    "chain_id": "test",
    "judgement": {"lag_range": [0, 8], "pass_window": [1, 4], "pass_corr": 0.3, "noise_band": 0.15},
    "lead": {"params": {"keywords": ["a", "b"], "weeks_back": 260}},
    "lag": {"params": {"sector": "光模块", "weeks_back": 260}},
    # used=0：P0-3 加固后，"首次运行"仅指链尚未用过额度的情况；
    # 若 YAML 声明已用过而台账缺失，会被纪律锁判为「删档洗白」直接拒绝
    # （见 tests/run_p0_guard_adversarial.py A1）。
    "budget": {"max_attempts": 3, "used": 0},
}
VERDICTS = [{"metric": "周收益率", "status": "NO_TRANSMISSION", "k_best": 7, "corr": -0.108}]

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    record = tmp / "test.record.json"

    print("== 场景1：首次运行（无记录）-> 放行 ==")
    g = check_discipline(BASE_CFG, record)
    check("放行", g.ok)

    print("== 场景2：跑过一次后，参数未变 -> 放行 ==")
    write_record(record, BASE_CFG, VERDICTS)
    g = check_discipline(BASE_CFG, record)
    check("放行", g.ok)

    print("== 场景3：改判定参数、未登记修订 -> 拒绝 ==")
    tampered = {**BASE_CFG, "judgement": {**BASE_CFG["judgement"], "pass_corr": 0.2}}
    check("指纹确实变化", fingerprint(tampered) != fingerprint(BASE_CFG))
    g = check_discipline(tampered, record)
    check("拒绝", not g.ok)

    print("== 场景4：登记修订但 budget.used 没加 -> 拒绝 ==")
    tampered["revisions"] = [{"date": "2026-09-26", "reason": "调及格线", "counts_as_attempt": True}]
    g = check_discipline(tampered, record)
    check("拒绝", not g.ok)

    print("== 场景5：修订 + used+1 -> 放行 ==")
    tampered["budget"] = {**BASE_CFG["budget"], "used": 1}
    g = check_discipline(tampered, record)
    check("放行", g.ok)

    print("== 场景6：技术性修订（不计尝试）+ used 不变 -> 放行 ==")
    write_record(record, tampered, VERDICTS)  # 场景5的记录落盘
    tech = {**tampered, "lead": {"params": {**tampered["lead"]["params"], "cache_file": "x.csv"}}}
    tech["revisions"] = tampered["revisions"] + [
        {"date": "2026-09-26", "reason": "缓存文件名调整（技术性）", "counts_as_attempt": False}]
    g = check_discipline(tech, record)
    check("放行", g.ok)

print("\n== 结果 ==")
if FAILURES:
    print(f"测试失败：{FAILURES}")
    sys.exit(1)
print("6 个场景全部通过：纪律锁行为符合协议（修订即尝试，拒绝静默改参）。")
