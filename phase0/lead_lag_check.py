# -*- coding: utf-8 -*-
"""
阶段0生死验证 v2：AI学术热度是否领先 光模块板块 资金流/价格？
==========================================================
v2 改进：
  - OpenAlex 抓完立即落盘缓存，支持断点续传（不再怕中途崩）
  - 板块取数三级降级：akshare板块 -> 裸requests东财 -> 新浪个股代理（中际旭创300308）
判定（预注册，跑之前写死，不许改参再试）：
  - 峰值出现在超前1~4周且 corr > 0.3 -> 传导迹象成立
  - |corr| < 0.15 -> 首链逻辑存疑，换链（上限2次）
"""
import time
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import requests

OUT_DIR = Path(__file__).parent / "output"
OUT_DIR.mkdir(exist_ok=True)

# ---------------- 预注册参数 ----------------
KEYWORDS = ["large language model", "inference optimization"]
WEEKS_BACK = 260
LAG_RANGE = range(0, 9)
Z_ROLL = 52
SECTOR_NAME = "光模块"
PROXY_STOCK = ("sz300308", "中际旭创")   # 三级降级：光模块龙头个股
MAILTO = "omninexus.phase0@example.com"

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


# ---------------- 领先面：OpenAlex（带断点缓存） ----------------
def fetch_openalex_weekly() -> pd.Series:
    cache = OUT_DIR / "openalex_weekly.csv"
    counts = {}
    if cache.exists():
        s = pd.read_csv(cache, index_col=0, parse_dates=True).iloc[:, 0]
        if s.notna().sum() > 30:
            print(f"  [cache] 命中本地缓存 {s.notna().sum()} 有效周，续抓缺失/后续周")
            counts = {idx.date(): v for idx, v in s.items()}
        else:
            print("  [cache] 缓存无效（全缺失/样本不足），删除后重抓")
            cache.unlink()

    import os
    # API key 优先级：环境变量 > 本地密钥文件（openalex_key.local，已被 .gitignore 排除）
    api_key = os.environ.get("OPENALEX_API_KEY", "")
    key_file = Path(__file__).parent / "openalex_key.local"
    if not api_key and key_file.exists():
        api_key = key_file.read_text(encoding="utf-8").strip()

    today = dt.date.today()
    session = requests.Session()
    query = " OR ".join(KEYWORDS)
    consecutive_fail = 0
    for w in range(WEEKS_BACK, -1, -1):
        end = today - dt.timedelta(weeks=w)
        start = end - dt.timedelta(weeks=1)
        # 已有非缺失值的周跳过（断点续传），NaN 周重试
        if start in counts and pd.notna(counts[start]):
            continue
        params = {
            "filter": f"title_and_abstract.search:{query},"
                      f"from_publication_date:{start},to_publication_date:{end}",
            "mailto": MAILTO,
        }
        if api_key:
            params["api_key"] = api_key
        for attempt in range(3):
            try:
                r = session.get("https://api.openalex.org/works", params=params, timeout=30)
                if r.status_code == 429:
                    # 限额明确耗尽：区分真限额 vs 偶发，连续5周429则终止
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
            # 分段落盘，中途崩也不丢
            pd.Series(counts).sort_index().to_csv(cache, header=["paper_count"])
    s = pd.Series(counts).sort_index()
    s.index = pd.to_datetime(s.index)
    s.rename("paper_count").to_csv(cache, header=True)
    return s.rename("paper_count")


# ---------------- 滞后面：三级降级取数 ----------------
def fetch_via_akshare() -> pd.DataFrame | None:
    try:
        import akshare as ak
        start = (dt.date.today() - dt.timedelta(weeks=WEEKS_BACK)).strftime("%Y%m%d")
        end = dt.date.today().strftime("%Y%m%d")
        df = ak.stock_board_industry_hist_em(symbol=SECTOR_NAME, period="daily",
                                             start_date=start, end_date=end, adjust="")
        df = df.rename(columns={"日期": "date", "收盘": "close", "成交额": "amount"})
        df["date"] = pd.to_datetime(df["date"])
        print("  [路径1] akshare 东财板块历史：OK")
        return df.set_index("date")[["close", "amount"]].sort_index()
    except Exception as e:
        print(f"  [路径1] akshare 失败：{e.__class__.__name__}")
        return None


def fetch_via_em_direct() -> pd.DataFrame | None:
    """裸requests：先从东财板块列表找到目标板块代码，再拉历史K线。"""
    try:
        # 列出全部行业板块（fs=m:90+t:2），翻页取全
        bk_code, bk_name = None, None
        for page in range(1, 6):
            r = requests.get(
                "https://push2.eastmoney.com/api/qt/clist/get",
                params={"fs": "m:90+t:2", "pn": page, "pz": 100,
                        "fields": "f12,f14", "po": 1},
                headers=UA, timeout=20)
            data = r.json().get("data", {}).get("diff", {})
            items = data.values() if isinstance(data, dict) else data
            for it in items:
                if SECTOR_NAME in str(it.get("f14", "")):
                    bk_code, bk_name = it["f12"], it["f14"]
                    break
            if bk_code:
                break
        if not bk_code:
            print(f"  [路径2] 东财板块列表中未找到「{SECTOR_NAME}」")
            return None
        # 拉板块历史K线
        beg = (dt.date.today() - dt.timedelta(weeks=WEEKS_BACK)).strftime("%Y-%m-%d")
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


def fetch_via_sina_proxy() -> pd.DataFrame | None:
    """降级：用光模块龙头个股（中际旭创）新浪日线作代理。"""
    try:
        import akshare as ak
        sym, name = PROXY_STOCK
        start = (dt.date.today() - dt.timedelta(weeks=WEEKS_BACK)).strftime("%Y%m%d")
        end = dt.date.today().strftime("%Y%m%d")
        df = ak.stock_zh_a_daily(symbol=sym, start_date=start, end_date=end)
        df = df.rename(columns={"date": "date", "close": "close", "amount": "amount"})
        df["date"] = pd.to_datetime(df["date"])
        print(f"  [路径3] 新浪个股代理：OK（{name}，注意：个股代理含个股特质噪声）")
        return df.set_index("date")[["close", "amount"]].sort_index()
    except Exception as e:
        print(f"  [路径3] 新浪个股失败：{e.__class__.__name__}")
        return None


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    wk = pd.DataFrame()
    wk["close"] = daily["close"].resample("W").last()
    wk["amount"] = daily["amount"].resample("W").sum()
    wk["ret"] = wk["close"].pct_change()
    # 统一周标签：全部对齐到该周的周一，与 OpenAlex 的 start-of-week 索引可 join
    wk.index = wk.index - pd.to_timedelta(wk.index.dayofweek, unit="D")
    return wk


# ---------------- 统计 ----------------
def roll_z(s: pd.Series, window: int = Z_ROLL) -> pd.Series:
    m = s.rolling(window, min_periods=26).mean()
    sd = s.rolling(window, min_periods=26).std()
    return (s - m) / sd


def xcorr(lead: pd.Series, lag: pd.Series, lags) -> pd.Series:
    out = {}
    for k in lags:
        pair = pd.concat([lead.shift(k).rename("lead"), lag.rename("lag")], axis=1).dropna()
        out[k] = pair["lead"].corr(pair["lag"]) if len(pair) > 30 else np.nan
    return pd.Series(out).rename("corr")


def main():
    print("== 阶段0 v2：AI学术热度 -> 光模块板块 领先滞后验证 ==", flush=True)

    print("[1/4] OpenAlex 周度论文计数（窄口径：" + " | ".join(KEYWORDS) + "）", flush=True)
    papers = fetch_openalex_weekly()
    # 统一周标签到周一（OpenAlex 按 start-of-week 抓取，标签落在周五）
    papers.index = papers.index - pd.to_timedelta(papers.index.dayofweek, unit="D")
    print(f"  论文计数：{len(papers)} 周，缺失 {papers.isna().sum()} 周")

    print("[2/4] 板块数据（三级降级）", flush=True)
    daily = fetch_via_akshare() or fetch_via_em_direct() or fetch_via_sina_proxy()
    if daily is None:
        print("三条路径全部失败，终止。")
        return 1
    wk = to_weekly(daily)

    print("[3/4] 对齐 + 滚动z-score + 交叉相关", flush=True)
    lead_z = roll_z(papers).rename("lead_z")
    lag_targets = {"周收益率": wk["ret"], "周成交额": wk["amount"]}

    results, series = {}, {"lead_z": lead_z, "papers": papers}
    for name, lag_raw in lag_targets.items():
        lag_z = roll_z(lag_raw).rename("lag_z")
        results[name] = xcorr(lead_z, lag_z, LAG_RANGE)
        series[f"lag_z_{name}"] = lag_z

    print("[4/4] 输出", flush=True)
    corr_tbl = pd.DataFrame(results).round(3)
    corr_tbl.index.name = "lead超前周数"
    print("\n== 交叉相关表（lead = 学术热度z，超前 k 周）==")
    print(corr_tbl)

    verdict_lines = []
    for name in corr_tbl.columns:
        c = corr_tbl[name].dropna()
        if c.empty:
            verdict_lines.append(f"· {name}：样本不足，无法判定")
            continue
        k_best = c.abs().idxmax()
        c_best = c.loc[k_best]
        if 1 <= k_best <= 4 and c_best > 0.3:
            v = "✅ 传导迹象成立"
        elif abs(c_best) < 0.15:
            v = "❌ 无传导迹象"
        else:
            v = "⚠️ 信号弱/滞后位置不对，需换链评估"
        verdict_lines.append(f"· {name}：峰值 corr={c_best:+.3f} @ 超前{k_best}周 -> {v}")
    print("\n== 预注册判定 ==")
    print("\n".join(verdict_lines))

    wk.to_csv(OUT_DIR / "sector_weekly.csv")
    corr_tbl.to_csv(OUT_DIR / "xcorr.csv")
    pd.DataFrame(series).to_csv(OUT_DIR / "zseries.csv")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
        plt.rcParams["axes.unicode_minus"] = False
        fig, axes = plt.subplots(2, 1, figsize=(12, 8))
        ax = axes[0]
        ax.plot(lead_z.index, lead_z.values, label="学术热度 z（OpenAlex）")
        for name, lag_z in series.items():
            if name.startswith("lag_z_"):
                ax.plot(lag_z.index, lag_z.values, alpha=0.6, label=name[6:] + " z")
        ax.legend(); ax.set_title("领先面 vs 滞后面（滚动52周 z-score）")
        ax = axes[1]
        corr_tbl.plot.bar(ax=ax)
        ax.set_title("交叉相关：lead 超前 k 周"); ax.set_xlabel("超前周数"); ax.axhline(0, c="k", lw=0.5)
        plt.tight_layout()
        plt.savefig(OUT_DIR / "lead_lag.png", dpi=150)
        print(f"\n图已保存：{OUT_DIR / 'lead_lag.png'}")
    except Exception as e:
        print(f"[warn] 画图失败（不影响结果）：{e}")

    print("\n完成。CSV 与图在 output/ 目录。")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
