# -*- coding: utf-8 -*-
"""run_chain —— 配置驱动跑一条链。

用法：python -m omninexus.run_chain chains/chain01.yaml

链 YAML 结构以 chains/ 下现有配置为准。
预注册纪律：judgement 与 budget 写入后不可静默修改（M1 起工具强制）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yaml

from .core import STATUS_CN, align_weekday, judge, roll_z, to_weekly, xcorr
from .guard import check_discipline, init_ledger, write_record
from .sources import (DEFAULT_MAILTO, default_out_dir, fetch_openalex_weekly,
                      fetch_sector_daily, fetch_us_index_daily)


def run_chain(config_path: str, init: bool = False, fetch_only: bool = False) -> int:
    config_path = str(config_path)
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    chain_id = cfg["chain_id"]
    j = cfg["judgement"]
    # 注意：不能写 `Path(cfg.get(...)) or None`——Path("") 是 Path('.')，真值为真，
    # 会让 out_dir 变成仓库根目录，把数据落到 .gitignore 覆盖不到的地方。
    _out_cfg = (cfg.get("output") or {}).get("out_dir")
    out_dir = Path(_out_cfg) if _out_cfg else None

    # 预注册纪律锁：判定参数被修改而未登记修订 -> 拒绝运行
    record_path = Path(config_path).parent / f"{chain_id}.record.json"

    # --init-ledger：为「已有历史但还没台账」的链建档（P0-3 加固后首次运行前需要）
    if init:
        if record_path.exists():
            print(f"[台账] {record_path.name} 已存在，无需初始化。")
            return 0
        init_ledger(record_path, cfg,
                    note="按 phase0/preregistration_protocol.md 修订记录表的历史状态建档")
        print(f"[台账] 已为 {chain_id} 建档：budget.used="
              f"{(cfg.get('budget') or {}).get('used', 0)}、"
              f"revisions_seen={len(cfg.get('revisions') or [])}。"
              f"运行日志 {record_path.with_suffix('.runs.jsonl').name} 已留首行。")
        return 0

    guard = check_discipline(cfg, record_path)
    print(guard.message, flush=True)
    if not guard.ok:
        return 2

    print(f"== {chain_id}：{cfg.get('title', '')} ==", flush=True)

    print("[1/4] 领先面抓取", flush=True)
    lp = cfg["lead"]["params"]
    lead_source = cfg["lead"].get("source", "openalex")
    if lead_source == "us_index":
        # 价格类领先面：取日线 -> 周收益率（水平值不平稳，不能直接滚动 z 后做相关）
        daily_lead = fetch_us_index_daily(lp["symbol"], lp["weeks_back"])
        if daily_lead is None:
            print("领先面取数失败，终止（不降级——领先面没有替代源）。")
            return 1
        lead_raw = to_weekly(daily_lead)["ret"].dropna()
        lead_raw.index = align_weekday(lead_raw.index)
        print(f"  领先面周收益率：{len(lead_raw)} 周"
              f"（{lead_raw.index.min().date()}~{lead_raw.index.max().date()}）")
    else:
        papers = fetch_openalex_weekly(
            keywords=lp["keywords"], weeks_back=lp["weeks_back"],
            cache_file=lp.get("cache_file"), out_dir=out_dir,
            mailto=lp.get("mailto", DEFAULT_MAILTO))
        papers.index = align_weekday(papers.index)
        lead_raw = papers
        print(f"  论文计数：{len(papers)} 周，缺失 {papers.isna().sum()} 周")

    print("[2/4] 滞后面抓取（四级降级）", flush=True)
    lp2 = cfg["lag"]["params"]
    daily = fetch_sector_daily(
        sector_name=lp2.get("sector"), proxy_stock=(lp2.get("proxy_stock"), lp2.get("proxy_name")),
        weeks_back=lp2["weeks_back"], sector_code=lp2.get("sector_code"),
        index_proxy=lp2.get("index_proxy"), try_em=lp2.get("try_em", True))
    if daily is None:
        print("四条路径全部失败，终止。")
        return 1
    wk = to_weekly(daily)

    # 取数预检出口（M3 无人值守的连通性冒烟测试也走这里）：
    # 只落两面周频序列、报告日期范围，**不计算交叉相关、不判定、不记账**——
    # 因此不消耗尝试额度，也不可能提前泄露判定结果。
    if fetch_only:
        out = out_dir or default_out_dir()
        out.mkdir(parents=True, exist_ok=True)
        prefix = cfg.get("output", {}).get("prefix", chain_id)
        lead_raw.to_csv(out / f"lead_weekly_{prefix}.csv", header=["lead"])
        wk.to_csv(out / f"sector_weekly_{prefix}.csv")
        print("\n[fetch-only] 已落盘两面周频序列（未计算相关、未判定、未记账）：")
        print(f"  领先面 {len(lead_raw)} 周：{lead_raw.index.min().date()}~"
              f"{lead_raw.index.max().date()}")
        print(f"  滞后面 {len(wk)} 周：{wk.index.min().date()}~{wk.index.max().date()}"
              f"，列={list(wk.columns)}")
        both = lead_raw.index.intersection(wk.index)
        print(f"  两面交集 {len(both)} 周：{both.min().date()}~{both.max().date()}"
              f"（扣掉滚动z预热 25 周后约 {max(len(both) - 25, 0)} 个有效配对周）")
        return 0

    print("[3/4] 对齐 + 滚动z-score + 交叉相关", flush=True)
    lead_z = roll_z(lead_raw).rename("lead_z")
    # 成交额为可选指标：新源只给 OHLC+volume（无 amount），此时不伪造该指标
    lag_targets = {"周收益率": wk["ret"]}
    if "amount" in wk.columns:
        lag_targets["周成交额"] = wk["amount"]
    else:
        print("  滞后面无成交额字段（接口限制）——本链判定指标只有周收益率")
    results = {name: xcorr(lead_z, roll_z(raw), range(j["lag_range"][0], j["lag_range"][1] + 1))
               for name, raw in lag_targets.items()}
    corr_tbl = pd.DataFrame(results).round(3)
    corr_tbl.index.name = "lead超前周数"
    print("\n== 交叉相关表（lead 超前 k 周）==")
    print(corr_tbl)

    window = tuple(j["pass_window"])
    if j["lag_range"][0] < window[0]:
        print(f"\n注：k={j['lag_range'][0]} 位于通过窗口 {list(window)} 之外，"
              "只作「同周共动」的前视诊断——以周为单位对齐时，A股当周收盘（周五15:00北京）"
              "早于美股当周收盘（周六凌晨北京），该位上的因果方向不可交易化。")

    print("\n== 预注册判定（及格线：corr>"
          f"{j['pass_corr']} 且 k∈[{window[0]},{window[1]}]，"
          f"噪声带 |corr|<{j['noise_band']}）==")
    verdicts = judge(corr_tbl, window, j["pass_corr"], j["noise_band"],
                     null_median=j.get("null_median"))
    for v in verdicts:
        if v["status"] == "NO_DATA":
            print(f"· {v['metric']}：{STATUS_CN[v['status']]}")
        else:
            print(f"· {v['metric']}：峰值 corr={v['corr']:+.3f} @ 超前{v['k_best']}周 "
                  f"-> {STATUS_CN[v['status']]}")

    print("[4/4] 输出", flush=True)
    prefix = cfg.get("output", {}).get("prefix", chain_id)
    out = out_dir or default_out_dir()
    wk.to_csv(out / f"sector_weekly_{prefix}.csv")
    corr_tbl.to_csv(out / f"xcorr_{prefix}.csv")
    write_record(record_path, cfg, verdicts)
    print(f"完成。输出在 {out}（前缀 {prefix}）；纪律记录 {record_path.name} 已更新。")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(run_chain(args[0], init="--init-ledger" in sys.argv,
                       fetch_only="--fetch-only" in sys.argv))
