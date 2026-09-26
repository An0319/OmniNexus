# -*- coding: utf-8 -*-
"""omninexus.sources —— 数据源适配层（插件化）。

M0 泛化说明：实现从 phase0/lead_lag_check.py 原样搬移并参数化，
抓取逻辑不改动（三级降级、断点缓存、429 快速终止均保持原行为）。

已注册源：
  - openalex     领先面：OpenAlex 周度论文计数（关键词可配，断点缓存）
  - us_index     领先面：新浪美股指数日线（.SOX/.IXIC，需 Referer；只有 OHLC+volume）
  - em_sector    滞后面：A股板块日线，四级降级
                 akshare 东财板块 → 裸requests东财直连
                 → 指数代理（akshare 新浪指数接口，无成交额）
                 → 新浪个股代理（含个股特质噪声）
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
# 新浪系接口对 Referer 有要求：缺了会被拒（P0-4 实测）
SINA_HEADERS = {**UA, "Referer": "https://finance.sina.com.cn"}
DEFAULT_MAILTO = "omninexus.phase0@example.com"


def default_out_dir() -> Path:
    """M0：输出与旧脚本同目录（phase0/output），保证回归可比、不分裂。"""
    return Path(__file__).resolve().parent.parent / "phase0" / "output"


# ---------------- 领先面：OpenAlex（带断点缓存与429快速终止） ----------------
def fetch_openalex_weekly(keywords: list[str], weeks_back: int,
                          cache_file: str | None = None,
                          out_dir: Path | None = None,
                          mailto: str = DEFAULT_MAILTO) -> pd.Series:
    """OpenAlex 周度论文计数。cache_file 缺省为 openalex_weekly_<首词>.csv。

    缓存命中（非缺失周）不重复请求；连续 5 周 429 立即终止（响亮失败）。
    """
    out_dir = out_dir or default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / (cache_file or f"openalex_weekly_{keywords[0].replace(' ', '_')}.csv")

    counts: dict = {}
    if cache.exists():
        s = pd.read_csv(cache, index_col=0, parse_dates=True).iloc[:, 0]
        if s.notna().sum() > 30:
            print(f"  [cache] 命中本地缓存 {s.notna().sum()} 有效周，续抓缺失/后续周")
            counts = {idx.date(): v for idx, v in s.items()}
        else:
            print("  [cache] 缓存无效（全缺失/样本不足），删除后重抓")
            cache.unlink()

    # API key 优先级：环境变量 > 本地密钥文件（openalex_key.local，已被 .gitignore 排除）
    api_key = os.environ.get("OPENALEX_API_KEY", "")
    key_file = Path(__file__).resolve().parent.parent / "phase0" / "openalex_key.local"
    if not api_key and key_file.exists():
        api_key = key_file.read_text(encoding="utf-8").strip()

    today = dt.date.today()
    session = requests.Session()
    query = " OR ".join(keywords)
    consecutive_fail = 0
    for w in range(weeks_back, -1, -1):
        end = today - dt.timedelta(weeks=w)
        start = end - dt.timedelta(weeks=1)
        if start in counts and pd.notna(counts[start]):
            continue  # 断点续传：已有非缺失值的周跳过
        params = {
            "filter": f"title_and_abstract.search:{query},"
                      f"from_publication_date:{start},to_publication_date:{end}",
            "mailto": mailto,
        }
        if api_key:
            params["api_key"] = api_key
        for attempt in range(3):
            try:
                r = session.get("https://api.openalex.org/works", params=params, timeout=30)
                if r.status_code == 429:
                    if attempt == 2:
                        counts[start] = np.nan
                        consecutive_fail += 1
                        if consecutive_fail >= 5:
                            raise SystemExit(
                                "\n[致命] OpenAlex 连续5周返回429：免费日额度已耗尽。\n"
                                "  - 免费额度按 IP 每日重置（UTC 午夜 / 首尔时间早上9点）\n"
                                "  - 或注册免费 API key：https://openalex.org/manage-api-keys\n"
                                "    设置环境变量 OPENALEX_API_KEY 后重跑\n"
                                "  - 已抓部分已缓存，重跑会续抓（不重复消耗额度）")
                        break
                    time.sleep(3)
                    continue
                r.raise_for_status()
                counts[start] = r.json()["meta"]["count"]
                consecutive_fail = 0
                break
            except SystemExit:
                raise
            except Exception:
                if attempt == 2:
                    counts[start] = np.nan
                else:
                    time.sleep(2 * (attempt + 1))
        if w % 40 == 0:
            print(f"  OpenAlex 进度：还剩 {w} 周（有效 {sum(1 for v in counts.values() if pd.notna(v))}）",
                  flush=True)
            pd.Series(counts).sort_index().to_csv(cache, header=["paper_count"])
    s = pd.Series(counts).sort_index()
    s.index = pd.to_datetime(s.index)
    s.rename("paper_count").to_csv(cache, header=True)
    return s.rename("paper_count")


# ---------------- 领先面：新浪美股指数日线 ----------------
def fetch_us_index_daily(symbol: str, weeks_back: int) -> pd.DataFrame | None:
    """新浪美股指数日线（.SOX 费半 / .IXIC 纳指）。返回 [close]，索引为交易日。

    P0-4 云端实测（出口 IP 20.104.167.75）：.SOX 3190 条（2014-01-16 起）、
    .IXIC 5718 条（2004-01-02 起）；**必须带 Referer**，否则被拒。
    响应形如：var d=([{"d":"2014-01-16","o":...,"c":...}, ...]);
    **只返回 OHLC+volume，没有成交额**——故本源的滞后面只能是价格类指标。

    已排除的候选（勿重试）：腾讯美股 usSOX 空数组、usIXIC/usSMH 退化为 1 条；
    新浪 .SOXX 返回 var d=(null)；stooq.com CSV 被 Cloudflare 换成 HTML 拦截页。
    """
    try:
        r = requests.get(
            "https://stock.finance.sina.com.cn/usstock/api/jsonp_v2.php/var%20d=/"
            "US_MinKService.getDailyK",
            params={"symbol": symbol, "___qn": "3"},
            headers=SINA_HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"  [领先面] 新浪美股 {symbol} 请求失败：{e.__class__.__name__}: {str(e)[:80]}")
        return None

    m = re.search(r"var\s+d\s*=\s*\((\[.*\])\)\s*;", r.text, re.S)
    if not m:
        print(f"  [领先面] 新浪美股 {symbol} 响应无法解析（{len(r.text)}B，"
              f"可能是限流/空数据）：{r.text[:80]}")
        return None
    try:
        rows = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        print(f"  [领先面] 新浪美股 {symbol} JSON 解析失败：{e}")
        return None
    if not rows:
        print(f"  [领先面] 新浪美股 {symbol} 返回空数组（该符号无数据）")
        return None

    df = pd.DataFrame([{"date": x["d"], "close": float(x["c"])}
                       for x in rows if x.get("c")])
    df["date"] = pd.to_datetime(df["date"])
    cutoff = pd.Timestamp(dt.date.today() - dt.timedelta(weeks=weeks_back))
    df = df[df["date"] >= cutoff].sort_values("date")
    if df.empty:
        print(f"  [领先面] 新浪美股 {symbol} 在 {weeks_back} 周窗口内无数据")
        return None
    print(f"  [领先面] 新浪美股 {symbol}：OK（{len(df)} 根日线，"
          f"{df['date'].min().date()}~{df['date'].max().date()}，无成交额字段）")
    return df.set_index("date")


# ---------------- 滞后面：东财板块四级降级 ----------------
def fetch_sector_daily(sector_name: str, proxy_stock: tuple[str, str],
                       weeks_back: int,
                       sector_code: str | None = None,
                       index_proxy: str | None = None,
                       try_em: bool = True) -> pd.DataFrame | None:
    """返回日线 [close] 或 [close, amount]，按四级降级依次尝试：

    路径1 akshare 东财板块 → 路径2 东财裸requests直连
    → 路径3 指数代理（新浪指数接口，**无成交额**）
    → 路径4 新浪个股代理（含个股特质噪声）

    sector_code：链配置里固定的东财板块代码（如 "BK0448"）。给了就跳过板块列表搜索，
    路径2 只发 1 次 K 线请求——云 IP 上列表搜索会突发 502（见 resolve_sector_code）。
    index_proxy：A股板块指数/ETF 代码（如 "sh512480"）。排在个股代理之前——
    它比个股少了个股特质噪声，是更干净的板块代理。
    try_em：是否允许走路径1/2。登记口径若是某个 ETF 指数，必须关掉东财板块那两级——
    「东财半导体行业板块」与「半导体ETF sh512480」是**不同标的**，不能互为降级；
    否则同一份链配置在不同出口 IP 上会静默取到不同标的的行情。

    实现注记：这里**不能**写成 `a() or b() or c()`。DataFrame 的真值判断会抛
    ValueError，而短路求值只对"最后一个操作数"免检——即只有降到最后一级才碰巧不炸
    （chain01/chain10 恰好都是降到最后一级成功，缺陷一直被掩盖）。故改为显式顺序判断。
    """
    daily = None
    if try_em:
        daily = fetch_via_akshare(sector_name, weeks_back)
        if daily is None:
            daily = fetch_via_em_direct(sector_name, weeks_back, sector_code=sector_code)
    else:
        print("  [路径1/2] 按链配置跳过东财板块（登记口径为固定指数，东财板块属不同标的）")
    if daily is None and index_proxy:
        daily = fetch_via_index_proxy(index_proxy, weeks_back)
    if daily is None:
        daily = fetch_via_sina_proxy(proxy_stock, weeks_back)
    return daily


def fetch_via_akshare(sector_name: str, weeks_back: int) -> pd.DataFrame | None:
    try:
        import akshare as ak
        start = (dt.date.today() - dt.timedelta(weeks=weeks_back)).strftime("%Y%m%d")
        end = dt.date.today().strftime("%Y%m%d")
        df = ak.stock_board_industry_hist_em(symbol=sector_name, period="daily",
                                             start_date=start, end_date=end, adjust="")
        df = df.rename(columns={"日期": "date", "收盘": "close", "成交额": "amount"})
        df["date"] = pd.to_datetime(df["date"])
        print("  [路径1] akshare 东财板块历史：OK")
        return df.set_index("date")[["close", "amount"]].sort_index()
    except Exception as e:
        print(f"  [路径1] akshare 失败：{e.__class__.__name__}")
        return None


def resolve_sector_code(sector_name: str, attempts: int = 3) -> tuple[str, str] | None:
    """搜索东财板块代码：行业板块(t:2) → 概念板块(t:3)，返回 (代码, 名称)。

    P0-2 云 IP 实测（2026-09-26）：本接口是路径2 唯一会挂的地方——突发请求会返
    502（HTML 非 JSON），而原先该步**无重试**，一挂即放弃整条路径。实测重试可救回。
    因此这里加 3 次重试（退避 2s/4s），并把返回码打印出来，供写进链配置固定使用。
    """
    for fs in ("m:90+t:2", "m:90+t:3"):
        for page in range(1, 6):
            data = None
            for i in range(attempts):
                try:
                    r = requests.get(
                        "https://push2.eastmoney.com/api/qt/clist/get",
                        params={"fs": fs, "pn": page, "pz": 100,
                                "fields": "f12,f14", "po": 1},
                        headers=UA, timeout=20)
                    r.raise_for_status()
                    data = r.json().get("data", {}).get("diff", {})
                    break
                except Exception as e:
                    print(f"  [路径2] 板块列表搜索失败（{fs} p{page}，"
                          f"第{i + 1}/{attempts} 次）：{e.__class__.__name__}")
                    if i < attempts - 1:
                        time.sleep(2 * (i + 1))
            if data is None:
                continue
            items = data.values() if isinstance(data, dict) else data
            for it in items:
                if sector_name in str(it.get("f14", "")):
                    return str(it["f12"]), str(it["f14"])
    return None


def fetch_via_em_direct(sector_name: str, weeks_back: int,
                        sector_code: str | None = None) -> pd.DataFrame | None:
    """裸requests：拿板块代码（优先用配置固定值），再拉历史K线。

    sector_code 固定后每链只发 1 次 K 线请求，绕开云 IP 上会突发 502 的列表搜索。
    """
    try:
        if sector_code:
            bk_code, bk_name = sector_code, sector_name
            print(f"  [路径2] 使用链配置固定的板块代码 {bk_code}，跳过列表搜索")
        else:
            hit = resolve_sector_code(sector_name)
            if hit is None:
                print(f"  [路径2] 东财板块列表中未找到「{sector_name}」")
                return None
            bk_code, bk_name = hit
            print(f"  [路径2] 搜索到板块 {bk_name} {bk_code}（建议写进链配置固定，"
                  f"避免云 IP 上的列表搜索 502）")
        beg = (dt.date.today() - dt.timedelta(weeks=weeks_back)).strftime("%Y-%m-%d")
        end = dt.date.today().strftime("%Y-%m-%d")
        r = requests.get(
            "https://push2his.eastmoney.com/api/qt/stock/kline/get",
            params={"secid": f"90.{bk_code}", "klt": "101", "fqt": "0",
                    "beg": beg, "end": end,
                    "fields1": "f1,f2,f3", "fields2": "f51,f53,f57"},
            headers=UA, timeout=20)
        kl = r.json()["data"]["klines"]
        rows = []
        for line in kl:
            parts = line.split(",")
            # fields2: f51=日期, f53=收盘, f57=成交额
            rows.append((parts[0], float(parts[1]), float(parts[2])))
        df = pd.DataFrame(rows, columns=["date", "close", "amount"])
        df["date"] = pd.to_datetime(df["date"])
        print(f"  [路径2] 东财直连板块K线：OK（{bk_name} {bk_code}，{len(df)}根）")
        return df.set_index("date")[["close", "amount"]].sort_index()
    except Exception as e:
        print(f"  [路径2] 东财直连失败：{e.__class__.__name__}: {str(e)[:80]}")
        return None


def fetch_via_index_proxy(symbol: str, weeks_back: int) -> pd.DataFrame | None:
    """路径3 指数代理层：akshare 新浪指数接口，取 A股板块指数 / 板块 ETF 日线。

    比个股代理干净（没有个股特质噪声），但接口**只给 OHLC+volume、没有成交额**——
    这是接口限制而非主动取舍，故用本层时滞后面指标只剩周收益率（协议第9.3节）。

    P0-4 云端实测：stock_zh_index_daily("sh512480") 1771 条、2019-06-12 起；
    腾讯同标的（fqkline）只有 640 条（2024-02-02 起），样本窗口不足，已排除。
    """
    try:
        import akshare as ak
        df = ak.stock_zh_index_daily(symbol=symbol)
        df["date"] = pd.to_datetime(df["date"])
        cutoff = pd.Timestamp(dt.date.today() - dt.timedelta(weeks=weeks_back))
        df = df[df["date"] >= cutoff].sort_values("date")
        if df.empty:
            print(f"  [路径3] 新浪指数 {symbol} 在 {weeks_back} 周窗口内无数据")
            return None
        print(f"  [路径3] 新浪指数代理：OK（{symbol}，{len(df)} 根，"
              f"{df['date'].min().date()}~{df['date'].max().date()}，无成交额字段）")
        return df.set_index("date")[["close"]]
    except Exception as e:
        print(f"  [路径3] 新浪指数 {symbol} 失败：{e.__class__.__name__}")
        return None


def fetch_via_sina_proxy(proxy_stock: tuple[str, str], weeks_back: int) -> pd.DataFrame | None:
    """路径4 末级兜底：板块龙头个股新浪日线代理（含个股特质噪声，解读时须披露）。"""
    try:
        import akshare as ak
        sym, name = proxy_stock
        start = (dt.date.today() - dt.timedelta(weeks=weeks_back)).strftime("%Y%m%d")
        end = dt.date.today().strftime("%Y%m%d")
        df = ak.stock_zh_a_daily(symbol=sym, start_date=start, end_date=end)
        df = df.rename(columns={"date": "date", "close": "close", "amount": "amount"})
        df["date"] = pd.to_datetime(df["date"])
        print(f"  [路径4] 新浪个股代理：OK（{name}，注意：个股代理含个股特质噪声）")
        return df.set_index("date")[["close", "amount"]].sort_index()
    except Exception as e:
        print(f"  [路径4] 新浪个股失败：{e.__class__.__name__}")
        return None


# 源注册表推迟到 M1（三次法则：出现第三个源时再做通用分发）
