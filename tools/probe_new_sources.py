# -*- coding: utf-8 -*-
"""P0-4 新源探针：第三条链的领先面（美股半导体/科技）× 滞后面（A股板块代理）。

为什么必须单独探
----------------
第三条链（换链#2 · 隔夜快传导）的领先面是**美股指数/费半**，而现有
omninexus.sources 只有 OpenAlex 一个领先面接口——**我们还没有美股取数能力**。
同时，滞后面目前兜底到"个股代理"（绿的谐波），混着个股特质噪声；用户已拍板
新增一层「指数代理」（A股板块指数 / 板块 ETF，走腾讯或新浪源）。

两者都是"写进 §9.3 就不可修改"的取数口径，所以**先在云 IP 上验一遍**：
接口通不通、返回是不是真历史日线、样本够不够 5 年（≈1300 个交易日）。

本地首轮已排除的候选（记录在案，不再重复试探）
--------------------------------------------
  × stooq.com CSV：返回 200 但正文是 Cloudflare 拦截页（HTML，796B），非 CSV
  × 腾讯美股 usSOX：接口存在但 day 数组为空——腾讯没有费半这个符号
  × 新浪 A股 klc_kl.js：返回的是加密串（非明文日期），不能直接解析

不制造自己的限流
----------------
上一轮教训：探针自己发太猛会把后面的测量一起毒化。本脚本每个候选只问一次。

产出：probe_new_sources.json（结论）+ 标准输出（人类可读日志）
"""
import datetime as dt
import json
import re
import sys
import time
import traceback
from pathlib import Path

# 本脚本在 tools/ 下，Python 只把 tools/ 放进 sys.path；
# 显式补上仓库根目录，保证 `from omninexus.sources import ...` 在本地与 CI 都能跑。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RESULT = {"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
          "probes": {}}

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
SINA_REF = {**UA, "Referer": "https://finance.sina.com.cn"}

ROWS = 1600  # ≈6 年交易日，够 312 周样本

# 领先面候选（美股半导体/科技）
TENCENT_US = ["usIXIC", "usSOX", "usSOXX", "usSMH"]     # 纳指/费半/半导体ETF×2
SINA_US = [".IXIC", ".SOX", ".SOXX"]                    # 新浪美股：纳指/费半/半导体ETF

# 滞后面候选（A股半导体/芯片板块代理 + 对照）
TENCENT_CN = ["sh000905", "sh512480", "sz159995", "sh562500"]  # 中证500对照/半导体ETF/芯片ETF/机器人ETF
SINA_CN_AK = [("stock_zh_index_daily", "sh000905"), ("stock_zh_index_daily", "sh512480")]


def http_get(url, params=None, headers=None, timeout=20):
    import requests
    t0 = time.time()
    r = requests.get(url, params=params, headers=headers or {}, timeout=timeout)
    return r, round(time.time() - t0, 2)


def parse_tencent(body: str):
    """腾讯 fqkline：{code,data:{<sym>:{day:[ [date,open,close,high,low,vol], ... ]}}}"""
    j = json.loads(body)
    data = j.get("data") or {}
    for sym, blob in data.items():
        for key in ("day", "qfqday", "usday"):
            rows = (blob or {}).get(key) or []
            if rows:
                return len(rows), str(rows[0][0]), str(rows[-1][0])
    return 0, None, None


def parse_sina_us(body: str):
    """新浪美股日线：var d=([{"d":"2004-01-02","o":...}, ...]);"""
    m = re.search(r"var\s+d\s*=\s*\((\[.*\])\)\s*;", body, re.S)
    if not m:
        return 0, None, None
    rows = json.loads(m.group(1))
    if not rows:
        return 0, None, None
    return len(rows), str(rows[0].get("d")), str(rows[-1].get("d"))


def probe_tencent(label, sym, key, parser):
    url = ("https://web.ifzq.gtimg.cn/appstock/app/usfqkline/get" if label.startswith("us")
           else "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get")
    info = {"source": f"tencent:{sym}", "url": url}
    t0 = time.time()
    try:
        r, secs = http_get(url, params={"param": f"{sym},day,,,{ROWS},qfq"}, headers=UA)
        info.update({"status": r.status_code, "seconds": secs, "bytes": len(r.text)})
        rows, first, last = parser(r.text) if r.status_code == 200 else (0, None, None)
        info.update({"ok": rows >= 100, "rows": rows, "first": first, "last": last})
    except Exception as e:
        info.update({"ok": False, "seconds": round(time.time() - t0, 2),
                     "error": f"{type(e).__name__}: {str(e)[:200]}"})
    RESULT["probes"][key] = info
    print(f"    {label}: ok={info['ok']} rows={info.get('rows')} "
          f"{info.get('first')}~{info.get('last')} status={info.get('status')} "
          f"{info.get('seconds')}s {info.get('error', '')}")
    return info


def probe_sina_us(sym):
    key = f"us_sina_{sym}"
    info = {"source": f"sina_us:{sym}"}
    t0 = time.time()
    try:
        r, secs = http_get(
            "https://stock.finance.sina.com.cn/usstock/api/jsonp_v2.php/var%20d=/"
            "US_MinKService.getDailyK",
            params={"symbol": sym, "___qn": "3"}, headers=SINA_REF)
        info.update({"status": r.status_code, "seconds": secs, "bytes": len(r.text)})
        rows, first, last = parse_sina_us(r.text) if r.status_code == 200 else (0, None, None)
        info.update({"ok": rows >= 100, "rows": rows, "first": first, "last": last,
                     "head": r.text[:120].replace("\n", " ")})
    except Exception as e:
        info.update({"ok": False, "seconds": round(time.time() - t0, 2),
                     "error": f"{type(e).__name__}: {str(e)[:200]}"})
    RESULT["probes"][key] = info
    print(f"    新浪美股 {sym}: ok={info['ok']} rows={info.get('rows')} "
          f"{info.get('first')}~{info.get('last')} status={info.get('status')} "
          f"{info.get('seconds')}s {info.get('error', '')}")
    return info


def main():
    print("=" * 72)
    print("P0-4 新源探针（第三条链领先面 + 指数代理层候选）")
    print("=" * 72)

    env_url = "https://api.ipify.org"
    try:
        r, _ = http_get(env_url, headers=UA)
        egress = r.text.strip()
    except Exception as e:
        egress = f"取不到出口 IP：{e}"
    RESULT["egress_ip"] = egress
    print(f"\n[0] 出口 IP：{egress}")

    # ---------- 1) 领先面：美股半导体/科技 ----------
    print(f"\n[1] 领先面候选 · 腾讯（纳指/费半/半导体ETF，各取 {ROWS} 条）")
    for sym in TENCENT_US:
        probe_tencent(f"腾讯美股 {sym}", sym, f"us_tencent_{sym}", parse_tencent)

    print("\n[2] 领先面候选 · 新浪美股（需 Referer；首轮已验证 .IXIC 可用）")
    for sym in SINA_US:
        probe_sina_us(sym)

    # ---------- 3) 滞后面：A股板块代理 ----------
    print(f"\n[3] 滞后面候选 · 腾讯（中证500对照/半导体ETF/芯片ETF/机器人ETF）")
    for sym in TENCENT_CN:
        probe_tencent(f"腾讯A股 {sym}", sym, f"cn_tencent_{sym}", parse_tencent)

    # ---------- 4) 滞后面：akshare 新浪系指数接口 ----------
    print("\n[4] 滞后面候选 · akshare 新浪指数接口（对照）")
    try:
        import akshare as ak
        for fn_name, sym in SINA_CN_AK:
            key = f"akshare_{fn_name}_{sym}"
            t0 = time.time()
            try:
                df = getattr(ak, fn_name)(symbol=sym)
                info = {"ok": df is not None and len(df) > 0,
                        "rows": (0 if df is None else int(len(df))),
                        "seconds": round(time.time() - t0, 2),
                        "first": (None if df is None or len(df) == 0 else str(df.iloc[0, 0])),
                        "last": (None if df is None or len(df) == 0 else str(df.iloc[-1, 0]))}
            except Exception as e:
                info = {"ok": False, "seconds": round(time.time() - t0, 2),
                        "error": f"{type(e).__name__}: {str(e)[:200]}"}
            RESULT["probes"][key] = info
            print(f"    {fn_name}({sym}): ok={info['ok']} rows={info.get('rows')} "
                  f"{info.get('first')}~{info.get('last')} {info.get('seconds')}s "
                  f"{info.get('error', '')}")
    except Exception as e:
        print(f"    akshare 不可用：{type(e).__name__}: {e}")

    # ---------- 5) 结论 ----------
    p = RESULT["probes"]

    def ok_keys(prefix):
        return [k for k, v in p.items() if k.startswith(prefix) and v.get("ok")
                and (v.get("rows") or 0) >= 100]

    us_lead = [k for k, v in p.items()
               if k.startswith(("us_tencent_", "us_sina_")) and v.get("ok")]
    cn_lag = [k for k, v in p.items()
              if k.startswith(("cn_tencent_", "akshare_")) and v.get("ok")]
    RESULT["verdict"] = {
        "us_lead_candidates_ok": us_lead,
        "cn_lag_candidates_ok": cn_lag,
        "us_lead_usable": bool(us_lead),
        "cn_lag_usable": bool(cn_lag),
        "semiconductor_lead_usable": any("SOX" in k or "SOXX" in k or "SMH" in k
                                         for k in us_lead),
    }
    print("\n" + "=" * 72)
    print(f"领先面（美股）可用候选：{us_lead or '无'}")
    print(f"滞后面（A股板块代理）可用候选：{cn_lag or '无'}")
    print(f"其中「半导体专属」领先面可用={RESULT['verdict']['semiconductor_lead_usable']}")
    if RESULT["verdict"]["semiconductor_lead_usable"]:
        print("结论：费半/半导体ETF 在云 IP 上可取——第三条链可按「半导体」配对登记 §9.3")
    elif us_lead:
        print(f"结论：只能取到 {us_lead[0]} 这类宽基美股指数，费半不可得——"
              "第三条链的「同板块」配对须改为宽基对宽基，或换领先面")
    else:
        print("结论：云 IP 上拿不到任何美股指数日线——第三条链领先面需重新设计，"
              "**不得**盲目写进 §9.3")
    if cn_lag:
        print(f"结论：指数代理层可落地，首选 {cn_lag[0]}（须核对起始日期是否够样本窗口）")
    else:
        print("结论：A股板块代理在云 IP 上不可取，指数代理层方案需改或回退个股代理")

    Path("probe_new_sources.json").write_text(
        json.dumps(RESULT, ensure_ascii=False, indent=2), encoding="utf-8")
    print("结果已写入 probe_new_sources.json")


if __name__ == "__main__":
    main()
