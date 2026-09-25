# -*- coding: utf-8 -*-
"""omninexus.guard —— 预注册纪律锁（M1）。

工具化的 p-hacking 防线：判定参数（judgement/lead/lag）一旦运行过一次，
即被指纹锁定。此后任何修改必须同时满足：

  1. 在链 YAML 的 revisions 中登记修订（date + reason）；
  2. 该修订 counts_as_attempt=true 时，budget.used 必须同步 +1。

否则工具拒绝运行。修订历史与运行记录全部落盘（chains/<id>.record.json），
进 git，可公开审计——防自欺不靠自觉，靠代码。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

# 纪律敏感字段：改了任何一处都视为"换了实验"，必须走修订流程
SENSITIVE_FIELDS = ("judgement", "lead", "lag")


@dataclass
class GuardResult:
    ok: bool
    message: str
    revisions_seen: int = 0  # 放行后应写入记录的"已见修订数"


def fingerprint(cfg: dict) -> str:
    """对纪律敏感字段计算稳定指纹（排序后 sha256）。"""
    payload = {k: cfg.get(k) for k in SENSITIVE_FIELDS}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def check_discipline(cfg: dict, record_path: Path) -> GuardResult:
    """跑前检查：参数变更必须配修订登记与尝试记账，否则拒绝运行。"""
    fp = fingerprint(cfg)
    revisions = cfg.get("revisions") or []

    if not record_path.exists():
        return GuardResult(True, "首次运行：判定参数指纹将随本次判定一起记录。",
                           len(revisions))

    record = json.loads(record_path.read_text(encoding="utf-8"))

    if record.get("fingerprint") == fp:
        return GuardResult(True, "判定参数与上次运行一致，正常执行。",
                           max(len(revisions), record.get("revisions_seen", 0)))

    # 参数变了：必须登记修订，且尝试记账同步
    seen = record.get("revisions_seen", 0)
    new_revs = revisions[seen:]
    if not new_revs:
        return GuardResult(False, (
            "[纪律锁] 判定参数被修改，但 YAML 中没有登记修订，工具拒绝运行。\n"
            f"  上次指纹 {record.get('fingerprint', '?')[:12]}… != 当前 {fp[:12]}…\n"
            "  请二选一：\n"
            "  A. 还原 judgement/lead/lag 的修改；\n"
            "  B. 在 YAML 的 revisions 中登记 {date, reason, counts_as_attempt}，\n"
            "     并将 budget.used +1（counts_as_attempt=true 时）。修订即尝试。"))

    counts = sum(1 for r in new_revs if r.get("counts_as_attempt", True))
    old_used = record.get("budget_used", 0)
    new_used = (cfg.get("budget") or {}).get("used", 0)
    if counts and new_used - old_used != counts:
        return GuardResult(False, (
            f"[纪律锁] 已登记修订 {len(new_revs)} 条（其中 {counts} 条计入尝试），"
            f"但 budget.used 从 {old_used} 变为 {new_used}，与修订不符，工具拒绝运行。\n"
            f"  请把 budget.used 改为 {old_used + counts} 后重跑（修订即尝试，防 p-hacking）。"))

    return GuardResult(True, f"放行：检测到 {len(new_revs)} 条已登记修订，记账一致。",
                       len(revisions))


def write_record(record_path: Path, cfg: dict, verdicts: list[dict]) -> None:
    """判定完成后写入运行记录（进 git，公开可审计）。"""
    record = {
        "chain_id": cfg.get("chain_id"),
        "last_run": dt.datetime.now().isoformat(timespec="seconds"),
        "fingerprint": fingerprint(cfg),
        "budget_used": (cfg.get("budget") or {}).get("used", 0),
        "revisions_seen": len(cfg.get("revisions") or []),
        "last_verdicts": verdicts,
    }
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2),
                           encoding="utf-8")
