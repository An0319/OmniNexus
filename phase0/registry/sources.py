"""数据源接入：FRED 序列与 Yahoo 日线。

只回答两件事：现在能不能取到、取到的字段是否齐全。原始响应只在内存里用，
不落盘、不入库；对外只留指纹（URL、SHA256、行数、首末日期、抓取时刻）。
抓取时刻由调用方显式传入，本模块不读系统时钟。
"""
from __future__ import annotations

import hashlib
import io
import json
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"
YAHOO_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
             "?period1={p1}&period2={p2}&interval=1d&events=div%7Csplit"
             "&includeAdjustedClose=true")
UA = {"User-Agent": "Mozilla/5.0 (OmniNexus registry)"}
TIMEOUT = 90

# 进程内记忆：同一次运行里同一来源只抓一次，避免重复打网络。
# 缓存的是「序列 + 原始响应 SHA256」，因此被缓存命中时指纹仍然完整。
# 不落盘、不跨进程；自检脚本会在核验前显式清空，证明核验不依赖注册时的副本。
_CACHE: dict[tuple[str, str], tuple[pd.Series, str]] = {}


class SourceUnavailable(RuntimeError):
    """数据源当前不可用。``code`` 直接成为「无法判定」的原因码。"""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def reset_cache() -> None:
    _CACHE.clear()


def _get(url: str) -> bytes:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise SourceUnavailable("SOURCE_HTTP", f"HTTP {exc.code}（{url}）") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceUnavailable("SOURCE_UNREACHABLE",
                                f"{type(exc).__name__}: {exc}（{url}）") from exc


def _sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _clean(series: pd.Series) -> pd.Series:
    series = series.dropna()
    series = series[~series.index.duplicated(keep="last")].sort_index()
    return series


def _parse_fred(body: bytes, series_id: str) -> pd.Series:
    try:
        frame = pd.read_csv(io.BytesIO(body))
    except Exception as exc:  # noqa: BLE001 - 任何解析失败都归为不可用
        raise SourceUnavailable("SOURCE_PARSE", f"FRED 响应不是 CSV：{exc}") from exc
    if series_id not in frame.columns:
        raise SourceUnavailable("SOURCE_FIELD_MISSING",
                                f"响应列 {list(frame.columns)} 中没有 {series_id}")
    if "observation_date" not in frame.columns:
        raise SourceUnavailable("SOURCE_FIELD_MISSING", "FRED 响应缺少 observation_date 列")
    values = pd.to_numeric(frame[series_id], errors="coerce")
    series = _clean(pd.Series(values.to_numpy(), index=pd.to_datetime(frame["observation_date"])))
    if series.empty:
        raise SourceUnavailable("SOURCE_EMPTY", "FRED 序列清洗后没有任何数值")
    return series


def _parse_yahoo(body: bytes) -> pd.Series:
    try:
        result = json.loads(body)["chart"]["result"][0]
        stamps = pd.to_datetime(result["timestamp"], unit="s", utc=True)
        stamps = stamps.tz_localize(None).normalize()
        adj = result["indicators"]["adjclose"][0]["adjclose"]
    except Exception as exc:  # noqa: BLE001
        raise SourceUnavailable("SOURCE_PARSE", f"Yahoo 响应结构不符：{exc}") from exc
    series = _clean(pd.Series(adj, index=stamps))
    if series.empty:
        raise SourceUnavailable("SOURCE_EMPTY", "Yahoo adjclose 清洗后没有任何数值")
    return series


def _url(provider: str, series_id: str, at: str) -> str:
    if provider == "fred":
        return FRED_URL.format(series_id)
    if provider == "yahoo":
        p1 = 915148800  # 1999-01-01
        return YAHOO_URL.format(sym=urllib.parse.quote(series_id), p1=p1,
                                p2=int(pd.Timestamp(at).timestamp()))
    raise SourceUnavailable("SOURCE_PROVIDER", f"未知 provider={provider!r}")


def probe(provider: str, series_id: str, field: str, at: str) -> tuple[pd.Series, dict]:
    """取一次数，返回序列与指纹。取不到就抛 ``SourceUnavailable``。"""
    key = (provider, series_id)
    cached = _CACHE.get(key)
    if cached is not None:
        series, digest = cached
        from_cache = True
    else:
        body = _get(_url(provider, series_id, at))
        series = _parse_fred(body, series_id) if provider == "fred" else _parse_yahoo(body)
        digest = _sha(body)
        _CACHE[key] = (series, digest)
        from_cache = False
    fingerprint = {
        "provider": provider,
        "id": series_id,
        "field": field,
        "url": _url(provider, series_id, at),
        "fetched_at_utc": at,
        "sha256": digest,
        "rows": int(len(series)),
        "first": str(series.index.min().date()),
        "last": str(series.index.max().date()),
        "from_process_cache": from_cache,
    }
    return series, fingerprint
