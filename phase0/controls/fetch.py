"""抓取对照实验的数据并留痕（探索性沙箱，非预注册）。

来源：
  FRED DCOILWTICO（WTI 日）、GASREGW（美国常规零售汽油周）
  Yahoo chart API XLV / SLX / XLB / XLP 日线 adjclose

原始序列与派生序列**不入库**（与 phase0/output/* 同一口径）：只提交 snapshot.json
（来源 URL、抓取时刻、SHA256、行数、首末日期、二次抓取差异），原始件留在本地
phase0/controls/data/。同一份数据多次抓取时，每条来源保留 fetches 历史，不覆盖上次记录。

每份数据抓两次：第一次落盘，第二次只做逐值比对，结果写入 snapshot.json。
产物：
  phase0/controls/data/*.csv|*.json   原始件
  phase0/controls/data/weekly_controls.csv  周频派生序列（周五标签）
  phase0/controls/data/snapshot.json  抓取时刻、URL、行数、首末日期、SHA256

用法（仓库根目录）：
  python phase0/controls/fetch.py
"""
from __future__ import annotations

import hashlib
import io
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "phase0" / "controls" / "data"
OUT.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (research data fetch)"}
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
YAHOO = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
         "?period1={p1}&period2={p2}&interval=1d&events=div%7Csplit"
         "&includeAdjustedClose=true")


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def fred_bytes(series: str) -> bytes:
    return get(FRED.format(series))


def yahoo_bytes(sym: str, p1: int, p2: int) -> bytes:
    return get(YAHOO.format(sym=sym, p1=p1, p2=p2))


def friday_label(d) -> pd.Timestamp:
    d = pd.Timestamp(d)
    return d + pd.Timedelta(days=4 - d.weekday())


def weekly_last(index, values) -> pd.Series:
    s = pd.Series(values, index=pd.DatetimeIndex(index)).dropna()
    s.index = s.index.map(friday_label)
    return s.groupby(level=0).last().sort_index()


def parse_fred(b: bytes, col: str) -> pd.Series:
    df = pd.read_csv(io.BytesIO(b))
    df[col] = pd.to_numeric(df[col], errors="coerce")
    return weekly_last(pd.to_datetime(df["observation_date"]), df[col].to_numpy())


def parse_yahoo(b: bytes) -> pd.Series:
    res = json.loads(b)["chart"]["result"][0]
    ts = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_localize(None).normalize()
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    return weekly_last(ts, adj)


def stamp(series: pd.Series) -> dict:
    s = series.dropna()
    return {"rows": int(len(s)), "first": str(s.index.min().date()) if len(s) else None,
            "last": str(s.index.max().date()) if len(s) else None}


def prior_history(key: str, prev: dict | None) -> list:
    """把上次 snapshot 里该来源的记录接在本次前面，保证抓取历史不被覆盖。"""
    old = (prev or {}).get("sources", {}).get(key, {})
    if old.get("fetches"):
        return list(old["fetches"])
    if not old:
        return []
    return [{k: old.get(k) for k in ("fetched_at_utc", "sha256", "rows", "first", "last",
                                    "identical_on_refetch", "refetch_diff_count",
                                    "refetch_diff_max_abs")}]


def main() -> int:
    snap = OUT / "snapshot.json"
    prev = json.loads(snap.read_text(encoding="utf-8")) if snap.exists() else None
    meta = {"fetched_at_utc": now_utc(), "sources": {}}

    # ---- FRED（两次抓取，比对逐行文本）
    for series in ("DCOILWTICO", "GASREGW"):
        t0 = now_utc()
        b1 = fred_bytes(series)
        t1 = now_utc()
        b2 = fred_bytes(series)
        (OUT / f"fred_{series}.csv").write_bytes(b1)
        same = b1 == b2
        parsed = parse_fred(b1, series)
        rec = {
            "fetched_at_utc": t0, "second_fetch_at_utc": t1,
            "sha256": sha(b1), "second_sha256": sha(b2),
            "identical_on_refetch": same, **stamp(parsed),
        }
        meta["sources"][series] = {
            "url": FRED.format(series), **rec,
            "raw_lines": int(len(b1.splitlines())),
            "fetches": prior_history(series, prev) + [rec],
        }

    # ---- Yahoo（两次抓取；时间戳与 adjclose 逐值比对）
    for sym, p1 in (("XLV", 915148800), ("SLX", 1133395200),
                    ("XLB", 915148800), ("XLP", 915148800)):
        p2 = int(datetime(2026, 11, 7, tzinfo=timezone.utc).timestamp())
        t0 = now_utc()
        b1 = yahoo_bytes(sym, p1, p2)
        t1 = now_utc()
        b2 = yahoo_bytes(sym, p1, p2)
        (OUT / f"yahoo_{sym}.json").write_bytes(b1)
        s1, s2 = parse_yahoo(b1), parse_yahoo(b2)
        same = bool(s1.equals(s2))
        diff = (s1 - s2).abs()
        diff_dates = [str(d.date()) for d in diff[diff > 0].index[-5:]]
        rec = {
            "fetched_at_utc": t0, "second_fetch_at_utc": t1,
            "sha256": sha(b1), "second_sha256": sha(b2),
            "identical_on_refetch": same, **stamp(s1),
            "refetch_diff_count": int((diff > 0).sum()),
            "refetch_diff_max_abs": float(diff.max()) if len(diff) else 0.0,
            "refetch_diff_last_dates": diff_dates,
        }
        meta["sources"][sym] = {
            "url": YAHOO.format(sym=sym, p1=p1, p2=p2), **rec,
            "fetches": prior_history(sym, prev) + [rec],
        }

    # ---- 周频派生：收益率（对照链统一用周收益）
    crude = parse_fred(OUT.joinpath("fred_DCOILWTICO.csv").read_bytes(), "DCOILWTICO")
    gas = parse_fred(OUT.joinpath("fred_GASREGW.csv").read_bytes(), "GASREGW")
    sectors = {s: parse_yahoo((OUT / f"yahoo_{s}.json").read_bytes())
               for s in ("XLV", "SLX", "XLB", "XLP")}

    frame = pd.DataFrame({
        "crude_ret": crude.pct_change(),
        "gas_ret": gas.pct_change(),
        **{f"{s.lower()}_ret": v.pct_change() for s, v in sectors.items()},
    }).sort_index()
    frame.index.name = "week_friday"
    frame.to_csv(OUT / "weekly_controls.csv", float_format="%.10f")

    meta["weekly_controls"] = {
        "path": str((OUT / "weekly_controls.csv").relative_to(ROOT)),
        "sha256": sha((OUT / "weekly_controls.csv").read_bytes()),
        **{c: stamp(frame[c]) for c in frame.columns},
    }
    (OUT / "snapshot.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
    print(json.dumps(meta, indent=2, ensure_ascii=False))
    bad = [k for k, v in meta["sources"].items() if not v["identical_on_refetch"]]
    if bad:
        print(f"note: 二次抓取存在差异（已逐值记录）：{', '.join(bad)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
