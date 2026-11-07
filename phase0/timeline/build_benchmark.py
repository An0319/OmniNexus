"""基准集抽样：从固定快照 raw_items.json 里抽 25 条新闻源条目，供人工标注。

抽样规则（写死，避免挑样本）：
- 只取新闻源（google_news / bing_news），时间窗内的条目
- 按 (time, source_id, title) 排序后等间隔抽取，间隔 = floor(n / 25)，从第 1 条开始
- 每条只保留 title + 前 120 字摘要 + url + date + source（短引用，非原文分发）

用法：python phase0/timeline/build_benchmark.py --raw phase0/timeline/out/raw_items.json \
        --start 2026-10-01 --end 2026-11-08 --out phase0/timeline/benchmark_items.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from timeline import NEWS_SOURCES, parse_date  # noqa: E402

TARGET = 25


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "benchmark_items.json"))
    args = ap.parse_args()

    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    raw = json.loads(Path(args.raw).read_text(encoding="utf-8"))

    pool = []
    for it in raw:
        if it.get("source_id") not in NEWS_SOURCES:
            continue
        d = parse_date(it.get("date", ""))
        if d is None or not (start <= d.date() <= end):
            continue
        if len((it.get("excerpt") or "").strip()) < 20:
            continue
        pool.append(it)
    pool.sort(key=lambda x: (parse_date(x["date"]), x["source_id"], x["title"].lower()))

    if not pool:
        print("池子里没有合格条目", file=sys.stderr)
        return 1

    step = max(1, len(pool) // TARGET)
    picked = [pool[i] for i in range(0, len(pool), step)][:TARGET]

    items = []
    for idx, it in enumerate(picked, 1):
        items.append(
            {
                "id": f"B{idx:02d}",
                "title": it["title"][:160],
                "excerpt": (it.get("excerpt") or "")[:120],
                "url": it["link"],
                "date": it["date"],
                "source_id": it["source_id"],
                "source_name": it.get("source_name"),
                "fetched_at_utc": it.get("fetched_at_utc"),
            }
        )
    out = Path(args.out)
    out.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"池子 {len(pool)} 条，等间隔 {step}，抽样 {len(items)} 条 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
