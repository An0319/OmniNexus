# -*- coding: utf-8 -*-
"""run_chain —— 配置驱动跑一条链。

用法：python -m omninexus.run_chain chains/chain01.yaml

链 YAML 结构见 docs/T1-工具化设计.md 第5节。
预注册纪律：judgement 与 budget 写入后不可静默修改（M1 起工具强制）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yaml

from .core import STATUS_CN, align_weekday, judge, roll_z, to_weekly, xcorr
from .guard import check_discipline, init_ledger, write_record
from .sources import fetch_openalex_weekly, fetch_sector_daily


def run_chain(config_path: str, init: bool = False) -> int:
    config_path = str(config_path)
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    chain_id = cfg["chain_id"]
    j = cfg["judgement"]
    out_dir = Path(cfg.get("output", {}).get("out_dir", "")) or None

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
    papers = fetch_openalex_weekly(
        keywords=lp["keywords"], weeks_back=lp["weeks_back"],
        cache_file=lp.get("cache_file"), out_dir=out_dir,
        mailto=lp.get("mailto", "omninexus.phase0@example.com"))
    papers.index = align_weekday(papers.index)
    print(f"  论文计数：{len(papers)} 周，缺失 {papers.isna().sum()} 周")

    print("[2/4] 滞后面抓取（三级降级）", flush=True)
    lp2 = cfg["lag"]["params"]
    daily = fetch_sector_daily(
        sector_name=lp2["sector"], proxy_stock=(lp2["proxy_stock"], lp2["proxy_name"]),
        weeks_back=lp2["weeks_back"], sector_code=lp2.get("sector_code"))
    if daily is None:
        print("三条路径全部失败，终止。")
        return 1
    wk = to_weekly(daily)

    print("[3/4] 对齐 + 滚动z-score + 交叉相关", flush=True)
    lead_z = roll_z(papers).rename("lead_z")
    lag_targets = {"周收益率": wk["ret"], "周成交额": wk["amount"]}
    results = {name: xcorr(lead_z, roll_z(raw), range(j["lag_range"][0], j["lag_range"][1] + 1))
               for name, raw in lag_targets.items()}
    corr_tbl = pd.DataFrame(results).round(3)
    corr_tbl.index.name = "lead超前周数"
    print("\n== 交叉相关表（lead 超前 k 周）==")
    print(corr_tbl)

    print("\n== 预注册判定（及格线：corr>"
          f"{j['pass_corr']} 且 k∈[{j['pass_window'][0]},{j['pass_window'][1]}]，"
          f"噪声带 |corr|<{j['noise_band']}）==")
    verdicts = judge(corr_tbl, tuple(j["pass_window"]), j["pass_corr"], j["noise_band"])
    for v in verdicts:
        if v["status"] == "NO_DATA":
            print(f"· {v['metric']}：{STATUS_CN[v['status']]}")
        else:
            print(f"· {v['metric']}：峰值 corr={v['corr']:+.3f} @ 超前{v['k_best']}周 "
                  f"-> {STATUS_CN[v['status']]}")

    print("[4/4] 输出", flush=True)
    prefix = cfg.get("output", {}).get("prefix", chain_id)
    from .sources import default_out_dir
    out = out_dir or default_out_dir()
    wk.to_csv(out / f"sector_weekly_{prefix}.csv")
    corr_tbl.to_csv(out / f"xcorr_{prefix}.csv")
    write_record(record_path, cfg, verdicts)
    print(f"完成。输出在 {out}（前缀 {prefix}）；纪律记录 {record_path.name} 已更新。")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sys.exit(run_chain(args[0], init="--init-ledger" in sys.argv))
