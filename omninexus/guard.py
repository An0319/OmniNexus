# -*- coding: utf-8 -*-
"""omninexus.guard —— 预注册纪律锁（M1 + P0-3 加固）。

工具化的 p-hacking 防线：判定参数一旦锁定，此后任何修改都必须留下痕迹并付账。

放行条件（三条同时满足）
------------------------
  1. 在链 YAML 的 revisions 中登记修订（date + reason）；
  2. 改动了**实质性字段**（判定口径/取数口径）时，至少一条修订
     counts_as_attempt=true，且 budget.used 同步 +1；
  3. 台账（record.json）与只追加运行日志（*.runs.jsonl）一致。

P0-3 加固（2026-09-26，对抗测试发现 4 类作弊路径后补上）
--------------------------------------------------------
  H1 判定线不许"技术性豁免"：judgement 或取数口径变化 → 强制计入尝试额度
  H2 已用额度不许回退：budget.used 只能增不能减（防"记账舞弊"抹掉历史）
  H3 台账不许删：record 缺失而 YAML 声明已用过 / 日志仍在 → 拒绝运行
  H4 运行历史只追加不覆写：每次运行追加一行到 *.runs.jsonl，覆写留痕

边界（诚实声明）
----------------
本锁防的是"无意间的自欺"和"顺手改参"，**不是防恶意伪造**——能改文件的人
也能改日志。最终保证来自两件事：①链 YAML 与台账都进 git，删改在公开历史里
留痕；②协议的修订记录表人工双账。工具只是把作弊的**成本**抬高到"必须留下
可被第三方发现的痕迹"。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

# 纪律敏感字段：改了任何一处都视为"换了实验"，必须走修订流程
SENSITIVE_FIELDS = ("judgement", "lead", "lag")

# 实质性字段：改动 = 换了实验的"数字口径"，禁止用"技术性修订"豁免
SUBSTANTIVE = {
    "judgement": ("lag_range", "pass_window", "pass_corr", "noise_band"),
    "lead": ("keywords", "weeks_back"),
    "lag": ("sector", "proxy_stock", "weeks_back"),
}


@dataclass
class GuardResult:
    ok: bool
    message: str
    revisions_seen: int = 0  # 放行后应写入记录的"已见修订数"


def _sha256(payload) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def fingerprint(cfg: dict) -> str:
    """纪律敏感字段的整体指纹（judgement + lead + lag 全量）。"""
    return _sha256({k: cfg.get(k) for k in SENSITIVE_FIELDS})


def substantive_fingerprint(cfg: dict) -> str:
    """实质性指纹：只覆盖会改变"算出来的数"的字段。

    用于区分「真的改了实验」与「只是换了缓存文件名/联系方式」——
    前者必须计入尝试额度，后者允许作为技术性修订放行。
    """
    payload = {}
    for section, keys in SUBSTANTIVE.items():
        src = cfg.get(section) or {}
        params = src.get("params", src) if isinstance(src, dict) else {}
        payload[section] = {k: params.get(k) for k in keys}
    return _sha256(payload)


def runs_log_path(record_path: Path) -> Path:
    """只追加运行日志：chains/<id>.record.runs.jsonl"""
    return record_path.with_suffix(".runs.jsonl")


def _last_log_entry(record_path: Path) -> dict | None:
    log = runs_log_path(record_path)
    if not log.exists():
        return None
    lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return json.loads(lines[-1]) if lines else None


def _append_run_log(record_path: Path, entry: dict) -> None:
    log = runs_log_path(record_path)
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def init_ledger(record_path: Path, cfg: dict, note: str) -> None:
    """为"已有历史但还没台账"的链建档（如 chain01/chain10 的既有尝试）。

    只允许在建档时使用一次：把 YAML 已声明的 budget.used 与 revisions 固化，
    并在运行日志里留下"历史初始化"这一行，之后任何回退都会被 H2/H3 挡住。
    """
    entry = {
        "event": "init_ledger",
        "at": dt.datetime.now().isoformat(timespec="seconds"),
        "note": note,
        "fingerprint": fingerprint(cfg),
        "substantive_fingerprint": substantive_fingerprint(cfg),
        "budget_used": (cfg.get("budget") or {}).get("used", 0),
        "revisions_seen": len(cfg.get("revisions") or []),
    }
    record_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    _append_run_log(record_path, entry)


def check_discipline(cfg: dict, record_path: Path) -> GuardResult:
    """跑前检查：参数变更必须配修订登记与尝试记账，否则拒绝运行。"""
    fp = fingerprint(cfg)
    sfp = substantive_fingerprint(cfg)
    revisions = cfg.get("revisions") or []
    used = (cfg.get("budget") or {}).get("used", 0)
    log = runs_log_path(record_path)

    # ---- H3：台账缺失。若 YAML 声明已用过、或运行日志还在 → 疑似删档洗白 ----
    if not record_path.exists():
        if used > 0 or log.exists():
            return GuardResult(False, (
                "[纪律锁] 找不到运行台账，但链 YAML 声明 budget.used="
                f"{used}（或运行日志仍在），拒绝运行。\n"
                "  这通常意味着台账被删除——删掉记录并不能抹掉已用掉的尝试额度。\n"
                "  若确属「为既有历史首次建档」，请显式执行：\n"
                f"    python -m omninexus.run_chain <链YAML> --init-ledger\n"
                "  该操作会把 YAML 中声明的已用次数固化进台账，并在运行日志留痕。"))
        return GuardResult(True, "首次运行：判定参数指纹将随本次判定一起记录。",
                           len(revisions))

    record = json.loads(record_path.read_text(encoding="utf-8"))

    # ---- A4：台账与只追加日志不一致 → 台账被改写 ----
    last = _last_log_entry(record_path)
    if last and last.get("fingerprint") != record.get("fingerprint"):
        return GuardResult(False, (
            "[纪律锁] 台账与运行日志不一致：台账里的参数指纹被人为改写。\n"
            f"  台账指纹 {str(record.get('fingerprint'))[:12]}…；"
            f"日志末行 {str(last.get('fingerprint'))[:12]}…\n"
            "  台账与 YAML 均纳入 git，请还原为真实历史后重跑。"))

    # ---- H2：已用额度不得回退 ----
    old_used = record.get("budget_used", 0)
    if used < old_used:
        return GuardResult(False, (
            f"[纪律锁] budget.used 从 {old_used} 回退到 {used}，拒绝运行。\n"
            "  已用掉的尝试额度不可退还——调小它等于抹掉历史（记账舞弊）。\n"
            f"  请改回 {old_used} 或更大。"))

    if record.get("fingerprint") == fp:
        return GuardResult(True, "判定参数与上次运行一致，正常执行。",
                           max(len(revisions), record.get("revisions_seen", 0)))

    # ---- 参数变了：必须登记修订，且尝试记账同步 ----
    seen = record.get("revisions_seen", 0)
    new_revs = revisions[seen:]
    if not new_revs:
        return GuardResult(False, (
            "[纪律锁] 判定参数被修改，但 YAML 中没有登记修订，工具拒绝运行。\n"
            f"  上次指纹 {str(record.get('fingerprint', '?'))[:12]}… != 当前 {fp[:12]}…\n"
            "  请二选一：\n"
            "  A. 还原 judgement/lead/lag 的修改；\n"
            "  B. 在 YAML 的 revisions 中登记 {date, reason, counts_as_attempt}，\n"
            "     并将 budget.used +1（counts_as_attempt=true 时）。修订即尝试。"))

    counts = sum(1 for r in new_revs if r.get("counts_as_attempt", True))

    # ---- H1：实质性字段变化禁止"技术性豁免" ----
    if substantive_fingerprint(cfg) != record.get("substantive_fingerprint", sfp) \
            and counts == 0:
        return GuardResult(False, (
            "[纪律锁] 判定口径或取数口径发生变化，但新增修订全部标记为"
            "「不计尝试」——拒绝运行。\n"
            "  判定线、滞后范围、通过窗口、关键词、板块/代理股、样本窗口的变化，\n"
            "  都属于「换了实验」，必须计入尝试额度（修订即尝试）。\n"
            "  「不计尝试」仅适用于缓存文件名、联系方式等不影响计算结果的字段。"))

    if counts and used - old_used != counts:
        return GuardResult(False, (
            f"[纪律锁] 已登记修订 {len(new_revs)} 条（其中 {counts} 条计入尝试），"
            f"但 budget.used 从 {old_used} 变为 {used}，与修订不符，工具拒绝运行。\n"
            f"  请把 budget.used 改为 {old_used + counts} 后重跑（修订即尝试，防 p-hacking）。"))

    return GuardResult(True, f"放行：检测到 {len(new_revs)} 条已登记修订，记账一致。",
                       len(revisions))


def write_record(record_path: Path, cfg: dict, verdicts: list[dict]) -> None:
    """判定完成后写入台账（进 git，公开可审计），并追加运行日志（H4）。"""
    entry = {
        "chain_id": cfg.get("chain_id"),
        "last_run": dt.datetime.now().isoformat(timespec="seconds"),
        "fingerprint": fingerprint(cfg),
        "substantive_fingerprint": substantive_fingerprint(cfg),
        "budget_used": (cfg.get("budget") or {}).get("used", 0),
        "revisions_seen": len(cfg.get("revisions") or []),
        "last_verdicts": verdicts,
    }
    record_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    _append_run_log(record_path, entry)
