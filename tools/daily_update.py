# -*- coding: utf-8 -*-
"""tools/daily_update.py —— T1 无人值守日更作业（只监控，不判定）。

依据：docs/T1-工具化设计.md 第13节（T1 点火前锁定）。
对 chains/*.yaml 下每条已登记链执行：取数（带降级）→ 质量门禁 → 写快照。

边界（§13.1 第4条）：
  本作业**不计算交叉相关、不判定、不改预算/修订/账本**——
  已判定链只做「数据新鲜度 + 降级披露」监控。

退出码：0 = 本次运行全部链成功；1 = 存在失败链（响亮失败，当日不得算达标）。
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from omninexus.core import align_weekday, to_weekly  # noqa: E402
from omninexus.sources import (fetch_openalex_weekly,  # noqa: E402
                               fetch_sector_daily, fetch_us_index_daily)

DATA_DIR = ROOT / "data"
CHAINS_DIR = ROOT / "chains"
STREAK_PATH = DATA_DIR / "streak.json"

# 监控窗口（周）：只用于回答"数据还取得回来吗、还新鲜吗"，
# 与链 YAML 里的判定窗口无关——本作业不判定。
MONITOR_WEEKS = 8

# 滞后面降级路径标记（与 sources.fetch_sector_daily 的日志前缀一致）
DEGRADE_PATHS = {
    "[路径1]": "东财板块(akshare)",
    "[路径2]": "东财直连",
    "[路径3]": "指数代理",
    "[路径4]": "个股代理",
}

DEFAULT_MAILTO = "omninexus.phase0@example.com"


# ---------------- 取数：捕获日志（降级层级要从日志里辨认） ----------------
def _captured(fn, *args, **kwargs):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = fn(*args, **kwargs)
    return result, buf.getvalue()


def _detect_degrade(log: str) -> str | None:
    """从取数日志里辨认实际生效的降级层级（§13.1 第3步要求如实标注）。"""
    hit = None
    for line in log.splitlines():
        if "OK" not in line:
            continue
        for mark, name in DEGRADE_PATHS.items():
            if mark in line:
                hit = f"{mark.strip('[]')} {name}"
    return hit


def _weekly_dict(s: pd.Series) -> dict:
    s = s.dropna()
    return {i.date().isoformat(): round(float(v), 6) for i, v in s.items()}


def _read_snapshot(chain_id: str) -> dict | None:
    p = DATA_DIR / f"snapshot_{chain_id}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _write_snapshot(snap: dict) -> None:
    p = DATA_DIR / f"snapshot_{snap['chain_id']}.json"
    p.write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")


# ---------------- 质量门禁（§13.1 第2条） ----------------
def _gate(snap: dict, face: str, label: str, series: pd.Series | None,
          prev_latest: str | None) -> None:
    """三条件任一命中即当日失败：面为空 / 关键列全 NaN / 最新日期比上次快照更旧。"""
    reasons = []
    face_doc = snap[face]
    latest = face_doc.get("latest")
    if series is None or len(series) == 0:
        reasons.append(f"{label}为空")
    else:
        if series.isna().all():
            reasons.append(f"{label}关键列全 NaN")
        if latest and prev_latest and latest < prev_latest:
            reasons.append(f"{label}最新日期倒退（{latest} < {prev_latest}）")
    if reasons:
        snap["status"] = "failed"
        snap["failure_reasons"].extend(reasons)


# ---------------- 领先面源注册表（接源 SOP 第③步的落点） ----------------
# 新源 = 写一个 builder（返回 (周度序列, 快照面)）+ 下方注册一行。
# 同时必须在 omninexus/guard.py 的 SUBSTANTIVE["lead"] 登记新参数名，
# 否则新参数不在实质性指纹保护内（改参数 = 换实验却不用付账）。
def _lead_openalex(lp: dict) -> tuple[pd.Series | None, dict]:
    """OpenAlex 学术热度周度计数。"""
    s, log = _captured(fetch_openalex_weekly, keywords=lp.get("keywords") or [],
                       weeks_back=MONITOR_WEEKS,
                       mailto=lp.get("mailto", DEFAULT_MAILTO))
    print(log, end="", flush=True)
    s = s.copy()
    s.index = align_weekday(s.index)
    valid = s.dropna()
    series = valid if len(valid) else None
    face = {"source": "openalex", "keywords": lp.get("keywords") or [],
            "latest": valid.index.max().date().isoformat() if len(valid) else None,
            "points": int(len(valid)),
            "missing_weeks": int(s.isna().sum()),
            "degraded": False,
            "series": {"count": _weekly_dict(valid)}}
    return series, face


def _lead_us_index(lp: dict) -> tuple[pd.Series | None, dict]:
    """美股指数周收益（滞后面走降级链时的镜像领先面）。"""
    daily, log = _captured(fetch_us_index_daily, lp.get("symbol"), MONITOR_WEEKS)
    print(log, end="", flush=True)
    if daily is not None and not daily.empty:
        series = to_weekly(daily)["ret"].dropna()
        face = {"source": "us_index", "symbol": lp.get("symbol"),
                "latest": daily.index.max().date().isoformat(),
                "points": int(len(series)),
                "degraded": False,
                "series": {"ret": _weekly_dict(series)}}
    else:
        series = None
        face = {"source": "us_index", "symbol": lp.get("symbol"),
                "points": 0, "degraded": False}
    return series, face


# 注册表：新源在此登记一行
LEAD_SOURCES = {
    "openalex": _lead_openalex,
    "us_index": _lead_us_index,
}


def probe_chain(cfg: dict) -> dict:
    """单链监控：取两面数据 + 过门禁 + 组快照。不判定。"""
    chain_id = cfg["chain_id"]
    prev = _read_snapshot(chain_id) or {}
    snap = {"chain_id": chain_id, "status": "ok", "failure_reasons": [],
            "lead": {}, "lag": {}}

    # ---- 领先面（源注册表调度；未登记源响亮失败，不静默回落） ----
    lead = cfg.get("lead") or {}
    lp = lead.get("params") or {}
    lead_source = lead.get("source", "openalex")
    builder = LEAD_SOURCES.get(lead_source)
    if builder is None:
        raise ValueError(
            f"未登记的领先面源：{lead_source!r}（已登记：{sorted(LEAD_SOURCES)}）"
            "——按接源 SOP 三步（探针→口径卡→登记）后再用"
        )
    lead_series, snap["lead"] = builder(lp)
    _gate(snap, "lead", "领先面", lead_series, (prev.get("lead") or {}).get("latest"))

    # ---- 滞后面（四级降级；实际走到哪一级由日志辨认） ----
    lp2 = (cfg.get("lag") or {}).get("params") or {}
    daily, log = _captured(fetch_sector_daily,
                           sector_name=lp2.get("sector"),
                           proxy_stock=(lp2.get("proxy_stock"), lp2.get("proxy_name")),
                           weeks_back=MONITOR_WEEKS,
                           sector_code=lp2.get("sector_code"),
                           index_proxy=lp2.get("index_proxy"),
                           try_em=lp2.get("try_em", True))
    print(log, end="", flush=True)
    path = _detect_degrade(log)
    lag_series = None
    if daily is not None and not daily.empty:
        wk = to_weekly(daily)
        lag_series = wk["ret"].dropna()
        snap["lag"] = {"source": "em_sector", "sector": lp2.get("sector"),
                       "latest": daily.index.max().date().isoformat(),
                       "weekly_points": int(len(wk)),
                       "has_amount": "amount" in wk.columns,
                       "path": path,
                       "degraded": bool(path and not path.startswith("路径1")),
                       "series": {"ret": _weekly_dict(lag_series),
                                  "amount": _weekly_dict(wk["amount"])
                                  if "amount" in wk.columns else {}}}
    else:
        snap["lag"] = {"source": "em_sector", "sector": lp2.get("sector"),
                       "points": 0, "path": path}
    _gate(snap, "lag", "滞后面", lag_series, (prev.get("lag") or {}).get("latest"))

    return snap


# ---------------- 连续达标账（§13.3） ----------------
def _load_streak() -> dict:
    if STREAK_PATH.exists():
        return json.loads(STREAK_PATH.read_text(encoding="utf-8"))
    return {
        "project": "omninexus",
        "target_days": 30,
        "rule": ("UTC 日界；当日至少一次完整成功运行即达标；"
                 "断更计时归零，不补、不豁免（docs/T1-工具化设计.md §13）"),
        "current_streak": 0,
        "started_utc_date": None,
        "last_success_utc_date": None,
        "last_run_utc": None,
        "days": [],
        "breaks": [],
    }


def _streak_before(days: list[dict], upto: str) -> int:
    """统计 upto 之前、连续无缺口且全部成功的天数。"""
    seq = sorted((d for d in days if d["utc_date"] < upto),
                 key=lambda d: d["utc_date"])
    streak, expect = 0, None
    for d in reversed(seq):
        cur = dt.date.fromisoformat(d["utc_date"])
        if expect is not None and (expect - cur).days != 1:
            break  # 中间有整日缺失 → 断更
        if d["status"] != "success":
            break
        streak += 1
        expect = cur
    return streak


def _close_previous_days(doc: dict, today: str) -> None:
    """结算所有已过去的日子：补齐缺失日期、登记断更。"""
    days = doc.setdefault("days", [])
    days.sort(key=lambda d: d["utc_date"])
    if days:
        cur = dt.date.fromisoformat(days[-1]["utc_date"]) + dt.timedelta(days=1)
        while cur.isoformat() < today:
            days.append({"utc_date": cur.isoformat(), "status": "missing", "runs": 0,
                         "chains": {}, "failure_reasons": ["无运行记录（workflow 未执行）"]})
            cur += dt.timedelta(days=1)
    for d in days:
        if d["utc_date"] >= today or d.get("closed"):
            continue
        d["closed"] = True
        if d["status"] == "success":
            continue
        doc.setdefault("breaks", []).append({
            "utc_date": d["utc_date"],
            "streak_lost": _streak_before(days, d["utc_date"]),
            "reasons": d.get("failure_reasons") or ["未记录原因"],
        })


def _update_streak(doc: dict, today: str, stamp: str,
                   results: dict, ok: bool) -> None:
    days = doc.setdefault("days", [])
    rec = next((d for d in days if d["utc_date"] == today), None)
    if rec is None:
        rec = {"utc_date": today, "status": "failure", "runs": 0,
               "chains": {}, "failure_reasons": []}
        days.append(rec)
    rec["runs"] = rec.get("runs", 0) + 1
    rec["chains"] = {c: s["status"] for c, s in results.items()}
    if ok:
        # 当日已达标：后续运行只叠加次数，不把状态降回失败
        rec["status"] = "success"
        rec["failure_reasons"] = []
    elif rec.get("status") != "success":
        rec["status"] = "failure"
        rec["failure_reasons"] = sorted({r for s in results.values()
                                         if s["status"] != "ok"
                                         for r in s.get("failure_reasons") or ["未知"]})
    days.sort(key=lambda d: d["utc_date"])

    doc["last_run_utc"] = stamp
    before = _streak_before(days, today)
    today_success = any(d["utc_date"] == today and d["status"] == "success"
                        for d in days)
    streak = before + (1 if today_success else 0)
    doc["current_streak"] = streak
    if streak > 0:
        # 起点口径修正（2026-09-30 修订）：当日未成功时连续段止于上一成功日，
        # 起点 = 今日 − streak 天；旧公式 today−(streak−1) 会把起点后移一天，
        # 且当日未成功时把 last_success 误记为今天。
        doc["started_utc_date"] = (dt.date.fromisoformat(today) - dt.timedelta(
            days=streak - 1 if today_success else streak)).isoformat()
        succ = [d["utc_date"] for d in days if d["status"] == "success"]
        doc["last_success_utc_date"] = today if today_success else succ[-1]
    else:
        doc["started_utc_date"] = None
    STREAK_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")


# ---------------- 主流程 ----------------
def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    today = now.date().isoformat()
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    doc = _load_streak()
    _close_previous_days(doc, today)

    results = {}
    for f in sorted(CHAINS_DIR.glob("*.yaml")):
        cfg = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        chain_id = cfg.get("chain_id") or f.stem
        print(f"== 日更监控：{chain_id} ==", flush=True)
        try:
            snap = probe_chain(cfg)
        except (Exception, SystemExit) as e:  # SystemExit：如 OpenAlex 连续 429 的响亮失败
            snap = {"chain_id": chain_id, "status": "failed", "lead": {}, "lag": {},
                    "failure_reasons": [f"未捕获中断 {e.__class__.__name__}: {str(e)[:120]}"]}
            print(f"  [失败] {snap['failure_reasons'][0]}", flush=True)
        snap["run_utc"] = stamp
        _write_snapshot(snap)
        results[chain_id] = snap
        for r in snap.get("failure_reasons") or []:
            print(f"  [门禁] {r}", flush=True)

    ok = bool(results) and all(s["status"] == "ok" for s in results.values())
    _update_streak(doc, today, stamp, results, ok)

    print(f"\n== 日更结果 {today}（UTC）==", flush=True)
    for cid, s in results.items():
        mark = "OK" if s["status"] == "ok" else "FAILED"
        extra = "" if s["status"] == "ok" else "：" + "；".join(s["failure_reasons"])
        print(f"  {cid}: {mark}{extra}", flush=True)
    print(f"  本次运行：{'成功' if ok else '失败'}"
          f"（当日仍需至少一次完整成功运行）", flush=True)
    print(f"  连续达标 {doc['current_streak']}/{doc['target_days']} 天"
          f"（起始 {doc['started_utc_date'] or '—'}）", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
