# -*- coding: utf-8 -*-
"""诊断2：备选数据源连通性（新浪/腾讯/直连东财）"""
import requests

# 1. 直连东财 push2（看是不是 IP 被拒）
try:
    r = requests.get("https://push2his.eastmoney.com/api/qt/stock/kline/get",
                     params={"secid": "0.300308", "klt": "101", "fqt": "0",
                             "beg": "20250101", "end": "20250201",
                             "fields1": "f1", "fields2": "f51"},
                     headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                     timeout=15)
    print(f"[eastmoney direct] HTTP {r.status_code}, len={len(r.text)}")
except Exception as e:
    print(f"[eastmoney direct] FAIL: {e.__class__.__name__}: {str(e)[:100]}")

# 2. 新浪日线
try:
    import akshare as ak
    df = ak.stock_zh_a_daily(symbol="sz300308", start_date="20250101", end_date="20250201")
    print(f"[sina daily] OK rows={len(df)}, cols={list(df.columns)[:8]}")
except Exception as e:
    print(f"[sina daily] FAIL: {e.__class__.__name__}: {str(e)[:100]}")

# 3. 腾讯行情
try:
    r = requests.get("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
                     params={"param": "sz300308,day,2025-01-01,2025-02-01,20,"},
                     timeout=15)
    print(f"[tencent] HTTP {r.status_code}, keys={list(r.json().get('data', {}).keys())[:3]}")
except Exception as e:
    print(f"[tencent] FAIL: {e.__class__.__name__}: {str(e)[:100]}")
