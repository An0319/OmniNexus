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

# 连续降级阈值 N 的取法（不拍脑袋）：项目里已有的唯一定期复核数字是
# streak 的 target_days = 30（30 天无人值守里程碑）。哨兵复用同一个数，
# 避免再发明一个阈值。含义：降级连续满 30 天 = 到了「还这样用吗」的复核点，
# 不是故障。满一个 30 天为一个 bucket，每跨一个 bucket 提醒一次，不逐日刷屏。
N_DEGRADED_DAYS = 30


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
        f"【哨兵】板块口径连续降级 {days} 天（已满第 {bucket} 个 {N_DEGRADED_DAYS} 天复核期）",
        "",
        f"起始日：{since or '未知'}　当前连续：{days} 天",
        f"阈值 N={N_DEGRADED_DAYS} 的原因：项目里已有的唯一定期复核数字是 streak 的"
        f" target_days={N_DEGRADED_DAYS}，复用同一个数，不另造阈值。",
        "",
        "今日实际路径：",
        paths,
        "",
        "说明：降级已被接受（见 phase0/数据口径-降级接受记录.md），本通知是"
        "「又满一个复核期，请确认是否还这样用」的提醒，不是新故障，也不是要求立刻动手。",
        "若决定继续接受：关掉本通知即可；下一个复核期到期会再提醒一次。",
        "若降级结束（主路径恢复）：本通知可关，且计数会自动归零。",
    ])
    return [{
        "key": "degraded",
        "severity": "warning",
        "title": f"[哨兵] 板块口径连续降级满 {bucket * N_DEGRADED_DAYS} 天（复核提醒）",
        "body": body,
        "summary": f"连续降级 {days} 天（自 {since or '未知'}）",
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


def _open_sentinel_titles() -> set[str]:
    out = _gh("issue", "list", "--state", "open", "--search", "哨兵 in:title",
              "--json", "title", "--limit", "50")
    if not out:
        return set()
    try:
        return {x.get("title", "") for x in json.loads(out)}
    except ValueError:
        return set()


def emit(finding: dict, dry_run: bool, existing: set[str]) -> None:
    """先打印（本地也能看见），CI 里再开 issue。只写不验的监控等于没有监控。"""
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
    if finding["title"] in existing:
        print("（同名哨兵通知已开着，不重复开）", flush=True)
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


def run(data_dir: Path, chains_dir: Path, today: str,
        dry_run: bool) -> tuple[dict, list[dict]]:
    """跑三项检查，返回 (状态, 报警列表)。alert 去重状态就地推进后才落盘。"""
    state_path = data_dir / REPORT_NAME
    state = _load_json(state_path) or {}

    findings: list[dict] = []
    findings += check_products(data_dir, today)

    sector_chains = _sector_chains(chains_dir)
    degraded = today_degraded_paths(data_dir, sector_chains)
    has_product = _today_has_product(data_dir, sector_chains)

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

    findings += check_streak(state, _load_json(data_dir / "streak.json"))

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
    try:
        _state, findings = run(Path(args.data_dir), Path(args.chains_dir),
                               today, args.dry_run)
        existing = _open_sentinel_titles() if not args.dry_run else set()
        for f in findings:
            emit(f, args.dry_run, existing)
        if not findings:
            print(f"[哨兵] {today} 三项检查均通过（产物有数、未长期降级、计时未倒退）",
                  flush=True)
    except Exception as e:  # 铁律 2：哨兵自己崩了，只报检查失败，不改日更结论
        msg = f"[哨兵] 检查自身失败：{e.__class__.__name__}: {str(e)[:200]}"
        print(msg, flush=True)
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::warning::{msg}", flush=True)
        if not args.dry_run:
            try:
                body = ("【哨兵】检查自身失败\n\n"
                        f"{msg}\n\n"
                        "含义：日更本身可能完全正常，只是哨兵没跑通——"
                        "今天的「产物为空 / 连续降级 / 计时倒退」三项等于没查。\n"
                        "处置：看运行日志里 daily_sentinel.py 的 traceback；"
                        "不要因此判定日更失败。")
                if not os.environ.get("GH_TOKEN"):
                    print("（无 GH_TOKEN，跳过开 issue）", flush=True)
                elif "[哨兵] 检查自身失败" not in _open_sentinel_titles():
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
            emit(f, True, set())
            fired.add(f["key"])

        # 情形 B：连续降级，昨天已 29 天，今天第 30 天 → 跨过复核期
        state = {"degraded_days": 29, "degraded_since": "2026-10-29",
                 "degraded_last_date": _yesterday(today), "last_alert_bucket": 0,
                 "last_streak_seen": 12}
        degraded = today_degraded_paths(data, _sector_chains(chains))
        days, since = update_degraded_counter(state, today, degraded, True)
        for f in check_degraded(state, today, days, since, degraded):
            emit(f, True, set())
            fired.add(f["key"])

        # 情形 C：计时倒退 12 → 0
        _write_json(data / "streak.json", {"current_streak": 0,
                                           "last_success_utc_date": "2026-11-26",
                                           "last_run_utc": f"{today}T00:00:00Z"})
        for f in check_streak({"last_streak_seen": 12}, _load_json(data / "streak.json")):
            emit(f, True, set())
            fired.add(f["key"])

        need = {"empty", "degraded", "streak"}
        print(f"== 自测结果：期望 {sorted(need)}，实际 {sorted(fired)} ==", flush=True)
        if fired == need:
            print("通过：三种报警都真的叫了。", flush=True)
            return 0
        print("失败：有报警没有叫，监控等于没做。", flush=True)
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
