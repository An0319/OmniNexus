# -*- coding: utf-8 -*-
"""诊断：东财板块接口连通性测试（找出能用的取数路径）"""
import akshare as ak

tests = [
    ("板块列表 stock_board_industry_name_em", lambda: ak.stock_board_industry_name_em().head(3)),
    ("板块历史 光模块", lambda: ak.stock_board_industry_hist_em(symbol="光模块", period="daily", start_date="20250101", end_date="20250201").head(3)),
    ("板块历史 通信设备", lambda: ak.stock_board_industry_hist_em(symbol="通信设备", period="daily", start_date="20250101", end_date="20250201").head(3)),
    ("指数历史 光模块指数", lambda: None),
]

for name, fn in tests:
    if fn is None:
        continue
    try:
        df = fn()
        print(f"[OK] {name}: rows={len(df)}")
        print(df.to_string())
    except Exception as e:
        print(f"[FAIL] {name}: {e.__class__.__name__}: {str(e)[:120]}")
