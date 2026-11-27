# -*- coding: utf-8 -*-
"""tools/daily_sentinel.py —— T1 旁路哨兵：专抓「跑成功了，数是空的」这类静默失败。

为什么存在：2026-09-30 的坑是「跑成功了但数是空的」——请求不报错、issue 不响，
问题在门禁才暴露，而门禁之外无人复核。现在的报警只在「完全失败」时触发，
漏了「成功收下空数据 / 长期靠降级路径顶替 / 计时悄悄归零」这三类。

三条铁律（与生产流程的边界）：
  1) 旁路：日更成不成由 daily_update.py 决定；本脚本只读产物，绝不回写快照与 streak。
  2) 不反噬：所有异常在本脚本内捕获并降级为「检查失败」，退出码恒为 0；
     workflow 侧再加 continue-on-error——哨兵自己崩了，也绝不让日更跟着挂。
  3) 分得开：issue 标题统一带「[哨兵]」前缀，与「T1 日更失败：」是两类通知。

只写不验的监控等于没有监控：本文件自带 --self-test，构造「空产物 / 连续降级 /
计时倒退」三种情形并打印报警原文，用来证明它真的会叫。

用法：
  python tools/daily_sentinel.py                 # CI 默认：检查 + 开 issue（去重）
  python tools/daily_sentinel.py --dry-run       # 只打印，不开 issue、不写状态
  python tools/daily_sentinel.py --self-test     # 本地自测三种报警是否真会叫
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CHAINS_DIR = ROOT / "chains"
REPORT_NAME = "sentinel_report.json"

# 连续降级阈值 N 的取法：90 天，满一个 90 天报一次。
# 原取 30（复用 streak.target_days）的理由已作废——接受降级不是月度决策，修复也不在
# 月内发生；按月问一次，人会习惯性点「继续」，反而训练出免疫。90 天≈一个季度，
# 与「要不要排期修」这种量级的决定相称。
# 另：状态变化（主路径恢复 / 降级链增减 / 变成没数据）不走周期，一变就报（见 check_changes）。
N_DEGRADED_DAYS = 90


# ---------------- 基础 IO ----------------
def _load_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(p: Path, obj: dict) -> None:
    """原子写：先写临时文件再替换，避免半个文件被下一次运行读到。"""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(p)


def _today_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def _yesterday(day: str) -> str:
    return (dt.date.fromisoformat(day) - dt.timedelta(days=1)).isoformat()


# ---------------- 检查一：产物为空 / 未更新 ----------------
def _face_points(face: dict) -> int:
    """一个「面」里有几个点。points / weekly_points / series 长度取最大。"""
    if not isinstance(face, dict):
        return 0
    n = 0
    for key in ("points", "weekly_points"):
        try:
            n = max(n, int(face.get(key) or 0))
        except (TypeError, ValueError):
            pass
    series = face.get("series") or {}
    if isinstance(series, dict):
        for v in series.values():
            if isinstance(v, dict):
                n = max(n, len(v))
    return n


def check_products(data_dir: Path, today: str) -> list[dict]:
    """逐链核对「今天的产物到底有没有数」。

    与 daily_update._gate 不是一层：_gate 在取数当场判；本检查在日更跑完之后
    独立复核落到磁盘的产物，防的是「门禁被绕过 / 日更中途崩了写了个旧快照」。
    """
    snaps = sorted(data_dir.glob("snapshot_*.json"))
    problems: list[str] = []
    ok_chains: list[str] = []

    if not snaps:
        problems.append("data/ 下没有任何 snapshot_*.json（日更未产出）")
    for p in snaps:
        doc = _load_json(p) or {}
        cid = doc.get("chain_id") or p.stem.replace("snapshot_", "")
        reasons = []
        run_date = str(doc.get("run_utc") or "")[:10]
        if run_date != today:
            reasons.append(f"产物未更新（run_utc={doc.get('run_utc') or '缺失'}，非今日）")
        for face, label in (("lead", "领先面"), ("lag", "滞后面")):
            f = doc.get(face) or {}
            if _face_points(f) <= 0 or not f.get("latest"):
                reasons.append(f"{label}为空")
        if reasons:
            problems.append(f"{cid}：" + "；".join(reasons))
        else:
            ok_chains.append(cid)

    if not problems:
        return []
    body = "\n".join([
        "【哨兵】日更产物为空或未更新",
        "",
        f"检查时刻（UTC 日期）：{today}",
        "命中：",
        *[f"- {x}" for x in problems],
        (f"通过：{', '.join(ok_chains)}" if ok_chains else "通过：无"),
        "",
        "判定：按「跑成功了但数是空的」处理——判为失败，不作为有效产物收下。",
        "（日更本身的退出码仍由 daily_update.py 决定；本检查是旁路复核，不改日更结论。）",
        "",
        "排查顺序：",
        "1) 看当日运行日志里四路取数是否每一路都报了错；",
        "2) 看 data/snapshot_<链>.json 的 run_utc 是不是今天；",
        "3) 看 omninexus/sources.py 的 _demote_if_empty 是否被新代码绕过。",
    ])
    return [{
        "key": "empty",
        "severity": "error",
        "title": f"[哨兵] 日更产物为空或未更新（{today}）",
        "body": body,
        "summary": "；".join(problems),
    }]


# ---------------- 检查二：连续降级 ----------------
def _sector_chains(chains_dir: Path) -> set[str]:
    """登记口径是「东财板块」的链（try_em 未显式关闭）。

    chain20 登记口径就是固定指数（try_em: false），它走指数代理是**设计如此**，
    不是降级；把它算进来会让「降级天数」永远为真，等于没这个检查。
    """
    out = set()
    for f in sorted(chains_dir.glob("*.yaml")):
        try:
            cfg = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        cid = cfg.get("chain_id") or f.stem
        params = (cfg.get("lag") or {}).get("params") or {}
        if params.get("try_em", True) is not False:
            out.add(cid)
    return out


def today_degraded_paths(data_dir: Path, sector_chains: set[str]) -> dict[str, str]:
    """今日在降级路径上的链 → 实际路径文案。"""
    hit = {}
    for cid in sorted(sector_chains):
        doc = _load_json(data_dir / f"snapshot_{cid}.json") or {}
        lag = doc.get("lag") or {}
        if lag.get("degraded") is True:
            hit[cid] = str(lag.get("path") or "未知路径")
    return hit


def _today_has_product(data_dir: Path, sector_chains: set[str]) -> bool:
    """今天是否至少有一条板块链拿到了数（决定「中断日」还是「主路径恢复」）。"""
    for cid in sorted(sector_chains):
        doc = _load_json(data_dir / f"snapshot_{cid}.json") or {}
        if _face_points(doc.get("lag") or {}) > 0:
            return True
    return False


def update_degraded_counter(state: dict, today: str, degraded: dict[str, str],
                            has_product: bool) -> tuple[int, str | None]:
    """维护「连续降级天数」。同日重复运行幂等，不重复计数。

    三种日子的区别：
      degraded    → 计数 +1；
      primary     → 有产物但走主路径 → 计数清零（这才叫恢复）；
      中断日      → 没产物 → 不计入、也不清零（中断由失败通知覆盖）。
    """
    days = int(state.get("degraded_days") or 0)
    since = state.get("degraded_since")
    last = state.get("degraded_last_date")

    if degraded:
        if last != today:
            days += 1
            since = since or today
        state["degraded_last_date"] = today
        state["degraded_since"] = since or today
        state["degraded_days"] = days
    elif has_product:
        state["degraded_days"] = 0
        state["degraded_since"] = None
        state["degraded_last_date"] = today
        days = 0
    return days, state.get("degraded_since")


def check_degraded(state: dict, today: str, days: int, since: str | None,
                   degraded: dict[str, str]) -> list[dict]:
    if days < N_DEGRADED_DAYS:
        return []
    bucket = days // N_DEGRADED_DAYS
    if int(state.get("last_alert_bucket") or 0) >= bucket:
        return []                     # 这个 bucket 已经提醒过，不逐日刷屏
    state["last_alert_bucket"] = bucket
    paths = "\n".join(f"- {k}：{v}" for k, v in degraded.items()) or "-（今日未检出）"
    body = "\n".join([
        f"【哨兵】板块口径连续降级 {days} 天，满 {bucket * N_DEGRADED_DAYS} 天复核期。",
        "",
        "这是一次需要你做的决定，不是故障通知：",
        "  A. 继续接受并续期 —— 下一个 90 天到期再问一次；",
        "  B. 排期修复 —— 决定投入工时去找更稳的板块源。",
        "",
        "不回复的默认含义：**继续接受**。不影响任何数据、不影响日更、不需要你立刻做什么。",
        "",
        f"起始日：{since or '未知'}　当前连续：{days} 天（阈值 {N_DEGRADED_DAYS} 天/次）",
        "",
        "今日实际路径：",
        paths,
        "",
        "背景：降级已被接受（phase0/数据口径-降级接受记录.md）。本条只是把「到期了」摆到桌面上，",
        "不是催办，也不改变任何判定。若主路径恢复或降级链发生变化，会另发「状态变化」告警，",
        "不受这个周期约束。",
    ])
    return [{
        "key": "degraded",
        "severity": "warning",
        # 标题不带数字：同一个话题长期只用这一张，靠追加评论保留时间线，不刷列表
        "title": "[哨兵] 板块口径连续降级：需要一次决定",
        "body": body,
        "summary": f"连续降级 {days} 天（自 {since or '未知'}），满第 {bucket} 个复核期",
    }]


# ---------------- 检查二·补：状态变化立即告警（不受周期限制） ----------------
def check_changes(prev_state: dict, today_status: dict[str, str],
                  today_degraded: dict[str, str]) -> list[dict]:
    """三条即时告警：主路径恢复 / 降级链数量变化 / 从降级变成没数据。

    它们比周期提醒重要：周期说的是「还是老样子」，变化说的是「情况已经变了」。
    首次运行没有基线（prev 为空），此时不报，避免把「刚装上」误报成变化。
    """
    prev_status = prev_state.get("today_chain_status") or {}
    if not prev_status:
        return []
    prev_degraded = set(prev_state.get("today_degraded_paths") or {})
    findings: list[dict] = []

    recovered = sorted(c for c, s in today_status.items() if s == "primary" and c in prev_degraded)
    newly = sorted(c for c, s in today_status.items() if s == "degraded" and c not in prev_degraded)
    lost = sorted(c for c, s in today_status.items()
                  if s == "none" and prev_status.get(c) in ("degraded", "primary"))

    if recovered:
        findings.append({
            "key": "change_recovered", "severity": "warning",
            "title": "[哨兵·即时] 主路径恢复",
            "body": "\n".join([
                "【哨兵·即时】有链从降级路径回到了主路径。",
                "",
                "恢复的链：" + "、".join(recovered),
                "（前一运行日仍在降级：" + "、".join(sorted(prev_degraded)) + "）",
                "",
                "含义：降级计数会从今天起归零，周期提醒随之停。",
                "请顺手确认一句：这是真的主路径通了，还是取数路径被改动过？",
                "本条不需回复；确认后关掉即可。",
            ]),
            "summary": "主路径恢复：" + "、".join(recovered),
        })
    if newly:
        findings.append({
            "key": "change_new_degraded", "severity": "warning",
            "title": "[哨兵·即时] 降级链数量变化",
            "body": "\n".join([
                "【哨兵·即时】降级链数量发生变化（进了哪条、出了哪条见下）。",
                "",
                "新进入降级：" + "、".join(f"{c}（{today_degraded.get(c, '未知路径')}）" for c in newly),
                ("离开降级：" + "、".join(recovered) if recovered else "离开降级：无"),
                f"当前降级链合计：{len(today_degraded)} 条",
                "",
                "含义：降级范围在扩大或缩小。这不是故障，但值得知道是哪天变的。",
            ]),
            "summary": "新降级：" + "、".join(newly),
        })
    if lost:
        findings.append({
            "key": "change_lost", "severity": "error",
            "title": "[哨兵·即时] 有链从降级变成没有数据",
            "body": "\n".join([
                "【哨兵·即时】这些链前一运行日还有数，今天一条都没有：",
                "",
                *[f"- {c}（前一日状态：{prev_status.get(c)}）" for c in lost],
                "",
                "这不是降级，是断。降级至少还有代理数据，断是什么都没有。",
                "先看当日 run 日志里四路取数是否全部报错；若只是单链，看该链配置。",
            ]),
            "summary": "无数据：" + "、".join(lost),
        })
    return findings


# ---------------- 检查二·补 2：上一次心跳发送失败 ----------------
def check_heartbeat(state: dict, hb: dict | None) -> list[dict]:
    """心跳失败由「下一次运行」来报，不依赖当次——当次嗓子坏了，喊不出来。

    heartbeat_state.json 由 tools/heartbeat_ping.py 写、由提交步骤入库；
    本条只负责读它并汇报，汇报过的那一次不再重复（同一张 issue 里追加）。
    """
    if not hb or hb.get("last_ok") is not False:
        return []
    attempt = str(hb.get("last_attempt_utc") or "未知时刻")
    if state.get("heartbeat_notified_utc") == attempt:
        return []
    state["heartbeat_notified_utc"] = attempt
    return [{
        "key": "heartbeat", "severity": "error",
        "title": "[哨兵] 上一次心跳发送失败",
        "body": "\n".join([
            "【哨兵】上一次运行的心跳没有发出去。",
            "",
            f"失败时刻：{attempt}（{hb.get('kind', '未知类型')} 心跳）",
            f"错误：{hb.get('last_error') or '未记录'}",
            "",
            "为什么由这条而不是当场报：心跳挂掉时，当场那条 warning 也没人看得见",
            "（用坏掉的嗓子喊自己哑了）。所以改由下一次正常运行的哨兵来报。",
            "",
            "现在能确定的：本步已经跑到，说明日更流程本身恢复了。",
            "还不能确定的：上次那条心跳最终是否送达——请到 healthchecks 侧看一眼；",
            "若那边也没有记录，说明问题是 URL 或出网，不是本仓库。",
            "本条在下次心跳成功后不再重复；若仍未恢复，下一天会在这张 issue 里追加。",
        ]),
        "summary": f"心跳失败于 {attempt}",
    }]


# ---------------- 检查三：streak 归零 / 倒退 ----------------
def check_streak(state: dict, streak: dict | None) -> list[dict]:
    if not streak:
        return [{
            "key": "streak", "severity": "error",
            "title": "[哨兵] 连续达标计时不可读（streak.json 缺失或损坏）",
            "body": "【哨兵】data/streak.json 读不到，无法判断连续达标计时。\n"
                    "这本身就要人看一眼：文件被删、被改坏，或日更没走到写账那一步。",
            "summary": "streak.json 不可读",
        }]
    cur = int(streak.get("current_streak") or 0)
    prev = state.get("last_streak_seen")
    prev_i = int(prev) if prev is not None else None

    reason = None
    if cur == 0 and prev_i != 0:
        reason = f"归零（上次记录 {prev_i if prev_i is not None else '—'} 天 → 今日 0 天）"
    elif prev_i is not None and cur < prev_i:
        reason = f"倒退（上次记录 {prev_i} 天 → 今日 {cur} 天）"
    state["last_streak_seen"] = cur
    if reason is None:
        return []
    body = "\n".join([
        "【哨兵】连续达标计时归零或倒退",
        "",
        f"现状：{reason}",
        f"最后成功日（streak.json 记载）：{streak.get('last_success_utc_date') or '—'}",
        f"最近运行时刻：{streak.get('last_run_utc') or '—'}",
        "",
        "为何单独开一张：这类变化说明「当日两班都没成功」或「账没走到写计时那一步」，"
        "等下一次调度就已经晚了一个班次。",
        "与「T1 日更失败：」通知的区别：那张按失败当场开；这张专盯计时口径的突变，"
        "即使失败通知被漏看，计时归零也会留下痕迹。",
    ])
    return [{
        "key": "streak", "severity": "error",
        "title": f"[哨兵] 连续达标计时归零或倒退（{_today_utc()}）",
        "body": body,
        "summary": reason,
    }]


# ---------------- 报警出口（打印 + GitHub annotation + issue，去重） ----------------
def _gh(*args: str) -> str | None:
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _open_sentinel_issues() -> dict[str, int]:
    out = _gh("issue", "list", "--state", "open", "--search", "哨兵 in:title",
              "--json", "number,title", "--limit", "50")
    if not out:
        return {}
    try:
        return {x.get("title", ""): int(x.get("number") or 0) for x in json.loads(out)}
    except (ValueError, TypeError):
        return {}


def emit(finding: dict, dry_run: bool, existing: dict[str, int]) -> None:
    """先打印（本地也能看见），CI 里再写 issue。只写不验的监控等于没有监控。

    同一件事不开第二张：标题已存在就追加评论，保留时间线、不刷列表。
    """
    print("\n" + "=" * 68, flush=True)
    print(finding["title"], flush=True)
    print("-" * 68, flush=True)
    print(finding["body"], flush=True)
    print("=" * 68 + "\n", flush=True)

    if os.environ.get("GITHUB_ACTIONS"):
        # annotation 让报警直接出现在运行摘要里，不必点进日志
        print(f"::{finding['severity']}::{finding['title']}", flush=True)

    if dry_run or not os.environ.get("GH_TOKEN"):
        return
    num = existing.get(finding["title"])
    if num:
        if _gh("issue", "comment", str(num), "--body", finding["body"]):
            print(f"（同一话题已开着 #{num}，追加评论，不新开）", flush=True)
        return
    url = _gh("issue", "create", "--title", finding["title"], "--body", finding["body"])
    if url:
        print(f"已开哨兵通知：{url}", flush=True)


# ---------------- 主流程 ----------------
def _commit_state(root: Path, sha: str, sector_chains: set[str]) -> str:
    """某一天的板块口径状态：none（无有效产物）/ degraded / primary。

    读不到就当 none（不阻塞检查）。只要有任一条板块链拿到数且走了降级路径，
    这一天就算 degraded——降级是链级事实，不因另一条链恰好正常而被掩盖。
    """
    state = "none"
    for cid in sorted(sector_chains):
        try:
            r = subprocess.run(
                ["git", "-C", str(root), "show", f"{sha}:data/snapshot_{cid}.json"],
                capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return "none"
        if r.returncode != 0:
            continue
        try:
            doc = json.loads(r.stdout)
        except ValueError:
            continue
        lag = doc.get("lag") or {}
        if _face_points(lag) <= 0:
            continue
        if lag.get("degraded") is True:
            return "degraded"
        state = "primary"
    return state


def _history_degraded_days(root: Path, sector_chains: set[str],
                           today: str, limit: int = 400) -> int:
    """首次启用时从 git 历史回填「截至昨天的连续降级天数」。

    为什么必须回填：降级已经悄悄跑了约两个月，若从今天起从 0 计数，
    要再等 30 天才响——那正是这次要消灭的沉默。CI 的 checkout 是 fetch-depth: 0，
    本地也有完整历史；没有 git 时安全返回 0（退化为从今天起算）。

    计数口径：按「有有效产物的运行日」数。某天整日取数中断（none）不计入、
    也不清零——中断本身由失败通知覆盖；清零会掩盖「其实从未回到主路径」。
    遇到真正的 primary 日才停。
    """
    paths = [f"data/snapshot_{cid}.json" for cid in sorted(sector_chains)]
    if not paths:
        return 0
    try:
        r = subprocess.run(["git", "-C", str(root), "log", "--format=%H %ad",
                            "--date=short", "--", *paths],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return 0
    if r.returncode != 0:
        return 0
    per_day: dict[str, str] = {}
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] < today and parts[1] not in per_day:
            per_day[parts[1]] = parts[0]      # git log 新→旧，取当日最后一次提交
    days = 0
    for day in sorted(per_day, reverse=True)[:limit]:
        st = _commit_state(root, per_day[day], sector_chains)
        if st == "degraded":
            days += 1
        elif st == "primary":
            break
        # none：中断日，跳过不计
    return days


def today_chain_status(data_dir: Path, sector_chains: set[str]) -> dict[str, str]:
    """今日每条板块链的状态：primary / degraded / none。"""
    out: dict[str, str] = {}
    for cid in sorted(sector_chains):
        lag = (_load_json(data_dir / f"snapshot_{cid}.json") or {}).get("lag") or {}
        if _face_points(lag) <= 0:
            out[cid] = "none"
        elif lag.get("degraded") is True:
            out[cid] = "degraded"
        else:
            out[cid] = "primary"
    return out


def run(data_dir: Path, chains_dir: Path, today: str,
        dry_run: bool) -> tuple[dict, list[dict]]:
    """跑全部检查，返回 (状态, 报警列表)。即时告警排在周期提醒之前。"""
    state_path = data_dir / REPORT_NAME
    state = _load_json(state_path) or {}

    findings: list[dict] = []
    findings += check_products(data_dir, today)

    sector_chains = _sector_chains(chains_dir)
    degraded = today_degraded_paths(data_dir, sector_chains)
    has_product = _today_has_product(data_dir, sector_chains)
    status = today_chain_status(data_dir, sector_chains)

    # 变化告警优先：它说的是「情况变了」，比「还是老样子」重要
    findings += check_changes(state, status, degraded)

    # 首次启用（无历史状态）：从 git 历史回填，避免「刚装上所以从 0 开始」
    if "degraded_last_date" not in state and degraded:
        hist = _history_degraded_days(data_dir.resolve().parent, sector_chains, today)
        state["degraded_bootstrapped_from_history"] = hist
        if hist > 0:
            state["degraded_days"] = hist
            state["degraded_last_date"] = _yesterday(today)
            state["degraded_since"] = (
                dt.date.fromisoformat(today) - dt.timedelta(days=hist)).isoformat()

    days, since = update_degraded_counter(state, today, degraded, has_product)
    findings += check_degraded(state, today, days, since, degraded)
    findings += check_heartbeat(state, _load_json(data_dir / "heartbeat_state.json"))
    findings += check_streak(state, _load_json(data_dir / "streak.json"))
    state["today_chain_status"] = status

    state["last_checked_utc"] = dt.datetime.now(dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    state["last_checked_date"] = today
    state["sector_chains"] = sorted(sector_chains)
    state["today_degraded_paths"] = degraded
    state["findings"] = [{"key": f["key"], "summary": f["summary"]} for f in findings]
    state["error"] = None

    if not dry_run:
        _write_json(state_path, state)
    return state, findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T1 旁路哨兵（只读产物，不反噬日更）")
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    ap.add_argument("--chains-dir", default=str(CHAINS_DIR))
    ap.add_argument("--dry-run", action="store_true", help="只打印，不开 issue、不写状态")
    ap.add_argument("--self-test", action="store_true", help="构造三种情形，验证报警会叫")
    args = ap.parse_args(argv)

    if args.self_test:
        return _self_test()

    today = _today_utc()
    data_dir = Path(args.data_dir)
    try:
        _state, findings = run(data_dir, Path(args.chains_dir), today, args.dry_run)
        existing = _open_sentinel_issues() if not args.dry_run else {}
        for f in findings:
            emit(f, args.dry_run, existing)
        if not findings:
            print(f"[哨兵] {today} 检查均通过（产物有数、未长期降级、状态未变化、计时未倒退）",
                  flush=True)
    except Exception as e:  # 铁律 2：哨兵自己崩了，只报检查失败，不改日更结论
        msg = f"[哨兵] 检查自身失败：{e.__class__.__name__}: {str(e)[:200]}"
        print(msg, flush=True)
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::warning::{msg}", flush=True)
        # 崩了也要留痕：写进状态文件，让下一次运行知道「那天没查成」
        if not args.dry_run:
            try:
                state = _load_json(data_dir / REPORT_NAME) or {}
                state["error"] = msg
                state["last_error_utc"] = dt.datetime.now(dt.timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ")
                _write_json(data_dir / REPORT_NAME, state)
            except Exception:
                pass
            try:
                body = ("【哨兵】检查自身失败\n\n"
                        f"{msg}\n\n"
                        "含义：日更本身可能完全正常，只是哨兵没跑通——"
                        "当天的「产物为空 / 状态变化 / 连续降级 / 心跳 / 计时」等于没查。\n"
                        "处置：看运行日志里 daily_sentinel.py 的 traceback；"
                        "不要因此判定日更失败。")
                if not os.environ.get("GH_TOKEN"):
                    print("（无 GH_TOKEN，跳过开 issue）", flush=True)
                else:
                    exist = _open_sentinel_issues()
                    num = exist.get("[哨兵] 检查自身失败")
                    if num:
                        _gh("issue", "comment", str(num), "--body", body)
                    else:
                        _gh("issue", "create", "--title", "[哨兵] 检查自身失败", "--body", body)
            except Exception:
                pass
    return 0                          # 恒 0：绝不改变日更的结论


def _self_test() -> int:
    """构造三种情形，逐个跑出报警原文。断言「每种都真的产生了对应通知」。"""
    print("== 哨兵自测：构造情形 → 看报警是否真的叫 ==", flush=True)
    today = _today_utc()
    tmp = Path(tempfile.mkdtemp(prefix="sentinel_selftest_"))
    fired: set[str] = set()
    try:
        data = tmp / "data"
        chains = tmp / "chains"
        data.mkdir()
        chains.mkdir()
        (chains / "chain01.yaml").write_text(
            "chain_id: chain01\nlag:\n  params:\n    sector: 光模块\n", encoding="utf-8")
        (chains / "chain20.yaml").write_text(
            "chain_id: chain20\nlag:\n  params:\n    try_em: false\n", encoding="utf-8")

        # 情形 A：跑成功但产物是空的（滞后面 0 点）
        _write_json(data / "snapshot_chain01.json", {
            "chain_id": "chain01", "status": "ok", "failure_reasons": [],
            "lead": {"points": 5, "latest": today, "series": {"count": {"x": 1}}},
            "lag": {"points": 0, "path": "路径4 个股代理", "degraded": True,
                    "series": {"ret": {}}},
            "run_utc": f"{today}T00:00:00Z",
        })
        for f in check_products(data, today):
            emit(f, True, {})
            fired.add(f["key"])

        # 情形 B：连续降级，昨天已 89 天，今天第 90 天 → 跨过 90 天复核期
        state = {"degraded_days": 89, "degraded_since": "2026-08-30",
                 "degraded_last_date": _yesterday(today), "last_alert_bucket": 0,
                 "last_streak_seen": 12}
        degraded = today_degraded_paths(data, _sector_chains(chains))
        days, since = update_degraded_counter(state, today, degraded, True)
        for f in check_degraded(state, today, days, since, degraded):
            emit(f, True, {})
            fired.add(f["key"])

        # 情形 C：计时倒退 12 → 0
        _write_json(data / "streak.json", {"current_streak": 0,
                                           "last_success_utc_date": "2026-11-26",
                                           "last_run_utc": f"{today}T00:00:00Z"})
        for f in check_streak({"last_streak_seen": 12}, _load_json(data / "streak.json")):
            emit(f, True, {})
            fired.add(f["key"])

        # 情形 D：主路径恢复（前一日降级，今天 primary）
        prev = {"today_chain_status": {"chain01": "degraded", "chain10": "degraded"},
                "today_degraded_paths": {"chain01": "路径4 个股代理",
                                         "chain10": "路径4 个股代理"}}
        today_status = {"chain01": "primary", "chain10": "degraded"}
        for f in check_changes(prev, today_status, {"chain10": "路径4 个股代理"}):
            emit(f, True, {})
            fired.add(f["key"])

        # 情形 E：降级链数量变化（chain10 从 primary 变 degraded）
        prev2 = {"today_chain_status": {"chain01": "degraded", "chain10": "primary"},
                 "today_degraded_paths": {"chain01": "路径4 个股代理"}}
        for f in check_changes(prev2, today_status,
                               {"chain01": "路径4 个股代理", "chain10": "路径4 个股代理"}):
            emit(f, True, {})
            fired.add(f["key"])

        # 情形 F：从降级变成完全没有数据
        prev3 = {"today_chain_status": {"chain01": "degraded", "chain10": "degraded"},
                 "today_degraded_paths": {"chain01": "路径4 个股代理",
                                          "chain10": "路径4 个股代理"}}
        for f in check_changes(prev3, {"chain01": "none", "chain10": "degraded"}, {}):
            emit(f, True, {})
            fired.add(f["key"])

        # 情形 G：上一次心跳失败，由本次运行报出
        _write_json(data / "heartbeat_state.json", {
            "kind": "success", "last_ok": False,
            "last_attempt_utc": "2026-11-27T00:00:00Z",
            "last_error": "curl exit 6: Could not resolve host",
        })
        for f in check_heartbeat({}, _load_json(data / "heartbeat_state.json")):
            emit(f, True, {})
            fired.add(f["key"])

        need = {"empty", "degraded", "streak", "change_recovered",
                "change_new_degraded", "change_lost", "heartbeat"}
        print(f"== 自测结果：期望 {sorted(need)}，实际 {sorted(fired)} ==", flush=True)
        if fired == need:
            print("通过：七种报警都真的叫了。", flush=True)
            return 0
        print("失败：有报警没有叫，监控等于没做。", flush=True)
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
