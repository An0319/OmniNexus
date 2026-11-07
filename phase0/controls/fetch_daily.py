"""抓取日频序列，只回答「日频数据能不能公开拿到」（探索性沙箱）。

复用 `fetch.py` 的取数与留痕工具（`get` / `sha` / `yahoo_bytes` / `now_utc` /
`prior_history`），不另写抓取逻辑。日频解析与周频不同（不做周五聚合），故本脚本自带
两行解析。

产物（均不入库，`phase0/controls/data/*` 已被 .gitignore 拦下）：
  data/fred_DCOILWTICO_daily.csv   日频 WTI
  data/yahoo_UGA.json              日频美国汽油基金（若可得）
  data/yahoo_RB_F.json             日频 RBOB 汽油期货（若可得，备选）
  data/daily_controls.csv          日频收益率派生（crude_ret + 可用的汽油腿）
  data/snapshot.json               追加 `DCOILWTICO_DAILY` / `UGA` / `RB=F` 三个来源记录

用法（仓库根目录）：
  python phase0/controls/fetch_daily.py
"""
from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / "data"
OUT.mkdir(parents=True, exist_ok=True)
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fetch as f  # noqa: E402  同目录取数与留痕工具

P1 = 1104537600                      # 2005-01-01 UTC
P2 = int(datetime(2026, 11, 8, tzinfo=timezone.utc).timestamp())


def parse_yahoo_daily(b: bytes) -> pd.Series:
    res = json.loads(b)["chart"]["result"][0]
    ts = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_localize(None).normalize()
    s = pd.Series(res["indicators"]["adjclose"][0]["adjclose"], index=ts).dropna()
    return s[~s.index.duplicated(keep="last")].sort_index()


def parse_fred_daily(b: bytes, col: str) -> pd.Series:
    df = pd.read_csv(io.BytesIO(b))
    df[col] = pd.to_numeric(df[col], errors="coerce")
    s = pd.Series(df[col].to_numpy(), index=pd.to_datetime(df["observation_date"])).dropna()
    return s[~s.index.duplicated(keep="last")].sort_index()


def record(key: str, url: str, b1: bytes, b2: bytes, s1: pd.Series, s2: pd.Series,
           prev: dict, freq: str) -> tuple[dict, dict]:
    diff = (s1 - s2).abs()
    rec = {
        "fetched_at_utc": f.now_utc(), "second_fetch_at_utc": f.now_utc(),
        "sha256": f.sha(b1), "second_sha256": f.sha(b2),
        "identical_on_refetch": bool(s1.equals(s2)) and b1 == b2,
        "freq": freq, "rows": int(len(s1)),
        "first": str(s1.index.min().date()), "last": str(s1.index.max().date()),
        "refetch_diff_count": int((diff > 0).sum()),
        "refetch_diff_max_abs": float(diff.max()) if len(diff) else 0.0,
    }
    entry = {
        "url": url, **rec,
        "raw_lines": int(len(b1.splitlines())),
        "fetches": f.prior_history(key, prev) + [rec],
    }
    return rec, entry


def main() -> int:
    snap_path = OUT / "snapshot.json"
    prev = json.loads(snap_path.read_text(encoding="utf-8")) if snap_path.exists() else {}
    meta = dict(prev)
    srcs = dict(prev.get("sources", {}))
    notes: list[str] = []

    # ---- FRED 日频 WTI（同一条 id，但保存日频原始件并单独记一行）
    b1 = f.fred_bytes("DCOILWTICO")
    b2 = f.fred_bytes("DCOILWTICO")
    (OUT / "fred_DCOILWTICO_daily.csv").write_bytes(b1)
    s1, s2 = parse_fred_daily(b1, "DCOILWTICO"), parse_fred_daily(b2, "DCOILWTICO")
    _, srcs["DCOILWTICO_DAILY"] = record("DCOILWTICO_DAILY", f.FRED.format("DCOILWTICO"),
                                         b1, b2, s1, s2, prev, "daily")
    crude = s1

    # ---- Yahoo 日频汽油腿：UGA 为主，RB=F 备选；两个都试，只报实际拿到的
    gas: pd.Series | None = None
    for key, sym, fname in (("UGA", "UGA", "yahoo_UGA.json"),
                            ("RB=F", "RB=F", "yahoo_RB_F.json")):
        url = f.YAHOO.format(sym=urllib.parse.quote(sym), p1=P1, p2=P2)
        try:
            b1 = f.yahoo_bytes(urllib.parse.quote(sym), P1, P2)
            b2 = f.yahoo_bytes(urllib.parse.quote(sym), P1, P2)
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError, IndexError) as exc:
            notes.append(f"{key}: 抓取失败（{type(exc).__name__}: {exc}）")
            srcs[key] = {"url": url, "fetched_at_utc": f.now_utc(), "ok": False,
                         "error": f"{type(exc).__name__}: {exc}", "freq": "daily"}
            continue
        (OUT / fname).write_bytes(b1)
        s1, s2 = parse_yahoo_daily(b1), parse_yahoo_daily(b2)
        if len(s1) < 1000:
            notes.append(f"{key}: 行数仅 {len(s1)}，不足以覆盖 30 年日频")
        _, srcs[key] = record(key, url, b1, b2, s1, s2, prev, "daily")
        srcs[key]["ok"] = True
        if gas is None and sym == "UGA":
            gas = s1

    # ---- 日频派生：两条腿都按日对齐，收益率
    if gas is None:
        notes.append("汽油腿：UGA 与 RB=F 均未取到，日频模拟缺滞后序列")
        notes.append("日频路径在数据层面中断，按设计 §5 写明原因，不换标的凑数")
    else:
        common = crude.index.intersection(gas.index)
        frame = pd.DataFrame({
            "crude_ret": crude.reindex(common).pct_change(),
            "gas_ret": gas.reindex(common).pct_change(),
        })
        frame.index.name = "date"
        frame.to_csv(OUT / "daily_controls.csv", float_format="%.10f")
        meta["daily_controls"] = {
            "path": str((OUT / "daily_controls.csv").relative_to(ROOT)),
            "sha256": f.sha((OUT / "daily_controls.csv").read_bytes()),
            **{c: f.stamp(frame[c]) for c in frame.columns},
        }

    meta["sources"] = srcs
    meta.setdefault("notes", [])
    meta["notes"] = list(meta["notes"]) + notes
    snap_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    out = {"daily_controls": meta.get("daily_controls"),
           "sources": {k: {kk: srcs[k].get(kk) for kk in
                           ("freq", "rows", "first", "last", "ok", "identical_on_refetch")}
                       for k in ("DCOILWTICO_DAILY", "UGA", "RB=F") if k in srcs},
           "notes": notes}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
