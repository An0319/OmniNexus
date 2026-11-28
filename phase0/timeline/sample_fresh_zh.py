"""从已接好的中文源采一批真实流样本并冻结。

只做三件事：取数（各源最新流，不按主题筛）→ 按固定时间窗过滤 → 去重后落盘。
不调用 build_event / eval，不写任何引擎判定结果；items.json 里没有 is_event / action / view。

用法：
    python phase0/timeline/sample_fresh_zh.py --start 2026-11-27T09:50:00Z --end 2026-11-28T09:50:00Z --out-dir phase0/timeline/zh_fresh_20261128

去重沿用 rulesets/zh.json 的 dedupe 参数（merge_sources / day_tolerance / jaccard_min）。
动作锚点只作「标题是否同一事」的文本特征，不产生 is_event 判定。
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from timeline import (  # noqa: E402
    FETCHERS,
    UA,
    detect_action,
    load_ruleset,
    norm_tokens,
    now_utc,
    parse_date,
    rss_items,
    tz_unmarked,
)

# 东财快讯的 showtime 是北京本地时间且无时区标记；按 UTC+8 还原真实时刻。
# 其它源用 epoch / GMT，不需要这条；仍未标记时区的条目按 UTC 解释并打 tz_unmarked。
NAIVE_UTC_OFFSET_HOURS = {"eastmoney_news": 8}


def ts(value: str) -> dt.datetime:
    parsed = parse_date(value)
    if parsed is None:
        raise SystemExit(f"时间窗不是可解析的时间：{value}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def action_of(item: dict, rs) -> str | None:
    """去重用的动作特征；不是事件判定。"""
    text = f"{item.get('title', '')}. {item.get('excerpt', '')}"
    return detect_action(text, rs)[0]


def fetch_google_top(limit: int, cfg: dict) -> list[dict]:
    """Google News 中文头条 RSS：无查询词的真实流。locale 仍只由规则集提供。"""
    hl, gl, ceid, source_id = (cfg.get(k) for k in ("hl", "gl", "ceid", "source_id"))
    if not all((hl, gl, ceid, source_id)):
        raise SystemExit("规则集 source_params.google_news 缺 hl/gl/ceid/source_id")
    url = f"https://news.google.com/rss?hl={hl}&gl={gl}&ceid={ceid}"
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    resp.raise_for_status()
    out = []
    for it in rss_items(resp.text)[:limit]:
        title = it["title"]
        name = it["source_name"]
        excerpt = it["excerpt"]
        if name:
            if title.endswith(f" - {name}"):
                title = title[: -(len(name) + 3)].strip()
            if excerpt.endswith(name):
                excerpt = excerpt[: -len(name)].strip()
        out.append(
            {
                "source_id": source_id,
                "title": title,
                "link": it["link"],
                "url_kind": "aggregator",
                "date": it["date"],
                "excerpt": excerpt or title,
                "excerpt_kind": None,
                "source_name": name or "Google News",
                "fetched_at_utc": now_utc(),
                "subject_hint": None,
                "action_hint": None,
                "object": None,
            }
        )
    return out


def dedupe(items: list[dict], rs) -> tuple[list[dict], int]:
    cfg = rs.dedupe
    merge_sources = set(cfg["merge_sources"])
    kept: list[dict] = []
    merged = 0
    for it in sorted(items, key=lambda x: (x["_dt"], x["_source_id"], x["title"])):
        for cur in kept:
            if it["_source_id"] not in merge_sources or cur["_source_id"] not in merge_sources:
                continue
            if abs((it["_dt"].date() - cur["_dt"].date()).days) > cfg["day_tolerance"]:
                continue
            a = norm_tokens(it["title"], rs)
            b = norm_tokens(cur["title"], rs)
            if not a or not b:
                continue
            if len(a & b) / len(a | b) < cfg["jaccard_min"]:
                continue
            if action_of(it, rs) != action_of(cur, rs):
                continue
            cur.setdefault("_also", []).append(it)
            merged += 1
            break
        else:
            kept.append(it)
    return kept, merged


def main() -> int:
    ap = argparse.ArgumentParser(description="采一批中文真实流样本并冻结（不判定）")
    ap.add_argument("--start", required=True, help="窗口起，ISO8601，UTC")
    ap.add_argument("--end", required=True, help="窗口止，ISO8601，UTC")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--target", type=int, default=120, help="0 表示全收，不抽样")
    ap.add_argument("--seed", type=int, default=20261128)
    ap.add_argument("--sources", default=None, help="逗号分隔；默认取规则集 default_sources.topic")
    args = ap.parse_args()

    start, end = ts(args.start), ts(args.end)
    if start >= end:
        raise SystemExit("窗口起止反了")

    rs = load_ruleset("zh")
    names = (
        [s.strip() for s in args.sources.split(",") if s.strip()]
        if args.sources
        else list(rs.default_sources["topic"])
    )

    raw: list[dict] = []
    source_stats: dict[str, dict] = {}
    for i, name in enumerate(names):
        if i:
            time.sleep(1.2)
        t0 = time.perf_counter()
        try:
            if name == "google_news":
                items = fetch_google_top(200, rs.params(name))
            else:
                items = FETCHERS[name]("", start.date(), end.date(), 200, cfg=rs.params(name))
            stat = {
                "fetched": len(items),
                "in_window": 0,
                "undated": 0,
                "out_of_window": 0,
                "tz_assumed": 0,
                "tz_unmarked_band": 0,
            }
            margin = dt.timedelta(days=1)
            for it in items:
                raw_date = it.get("date", "")
                when = parse_date(raw_date)
                if when is None:
                    stat["undated"] += 1
                    continue
                when = when.astimezone(dt.timezone.utc)
                if tz_unmarked(raw_date):
                    offset = NAIVE_UTC_OFFSET_HOURS.get(it.get("source_id"))
                    if offset is not None:
                        when -= dt.timedelta(hours=offset)
                        it["_tz_assumed"] = f"UTC+{offset}"
                        stat["tz_assumed"] += 1
                    else:
                        # 与引擎的窗口过滤同规则：无时区时间戳留 ±1 天保守带并打标
                        it["_tz_unmarked"] = True
                        stat["tz_unmarked_band"] += 1
                        if not (start - margin <= when <= end + margin):
                            stat["out_of_window"] += 1
                            continue
                elif not (start <= when <= end):
                    stat["out_of_window"] += 1
                    continue
                if it.get("_tz_assumed") and not (start <= when <= end):
                    stat["out_of_window"] += 1
                    continue
                it["_dt"] = when
                it["_source_id"] = it["source_id"]
                raw.append(it)
                stat["in_window"] += 1
            stat["elapsed_s"] = round(time.perf_counter() - t0, 2)
            print(f"[fetch] {name}: {len(items)} 条 / 窗内 {stat['in_window']} / {stat['elapsed_s']}s")
        except Exception as exc:  # noqa: BLE001 - 单源失败不拖垮整批
            stat = {
                "fetched": 0,
                "in_window": 0,
                "undated": 0,
                "out_of_window": 0,
                "elapsed_s": round(time.perf_counter() - t0, 2),
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            }
            print(f"[fetch] {name}: FAIL {stat['elapsed_s']}s {stat['error']}")
        source_stats[name] = stat

    before = len(raw)
    pool, merged = dedupe(raw, rs)
    after = len(pool)
    print(f"[dedupe] 去重前 {before} → 去重后 {after}（合并 {merged}）")

    sampled_out = 0
    final = pool
    if args.target and after > args.target:
        rng = random.Random(args.seed)
        final = sorted(rng.sample(pool, args.target), key=lambda x: (x["_dt"], x["_source_id"], x["title"]))
        sampled_out = after - args.target
        print(f"[sample] 从 {after} 条中定种随机取 {args.target} 条（seed={args.seed}）")

    items = []
    for n, it in enumerate(final, 1):
        row = {
            "id": f"S{n:03d}",
            "title": it.get("title", ""),
            "source": it.get("source_name") or "unknown",
            "source_id": it.get("source_id"),
            "url": it.get("link"),
            "published_at_utc": iso(it["_dt"]),
            "published_raw": it.get("date", ""),
            "fetched_at_utc": it.get("fetched_at_utc"),
            "excerpt": it.get("excerpt", ""),
        }
        if it.get("_tz_assumed"):
            row["time_tz_assumed"] = it["_tz_assumed"]
        if it.get("_tz_unmarked"):
            row["time_tz_unmarked"] = True
        also = it.get("_also") or []
        if also:
            row["also_in"] = [
                {
                    "source": x.get("source_name") or "unknown",
                    "source_id": x.get("source_id"),
                    "url": x.get("link"),
                    "published_at_utc": iso(x["_dt"]),
                }
                for x in also
            ]
        items.append(row)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    items_path = out_dir / "items.json"
    items_text = json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n"
    items_path.write_text(items_text, encoding="utf-8")
    digest = hashlib.sha256(items_path.read_bytes()).hexdigest()

    final_counts = Counter(x["source_id"] for x in items)
    fetched_range = [x["fetched_at_utc"] for x in items if x.get("fetched_at_utc")]
    manifest = {
        "sample_version": out_dir.name,
        "frozen_at_utc": now_utc(),
        "window_start_utc": iso(start),
        "window_end_utc": iso(end),
        "sampling_command": "python "
        + str(Path(sys.argv[0]).as_posix())
        + " "
        + " ".join(sys.argv[1:]),
        "sources_requested": names,
        "source_stats": source_stats,
        "raw_fetched_total": sum(v.get("fetched", 0) for v in source_stats.values()),
        "in_window_total": before,
        "undated_excluded": sum(v.get("undated", 0) for v in source_stats.values()),
        "out_of_window_excluded": sum(v.get("out_of_window", 0) for v in source_stats.values()),
        "tz_assumed_items": sum(v.get("tz_assumed", 0) for v in source_stats.values()),
        "tz_unmarked_band_items": sum(v.get("tz_unmarked_band", 0) for v in source_stats.values()),
        "before_dedupe": before,
        "duplicates_merged": merged,
        "after_dedupe": after,
        "target": args.target,
        "sampled_out": sampled_out,
        "random_seed": args.seed if sampled_out else None,
        "items_count": len(items),
        "items_sha256": digest,
        "items_bytes": len(items_path.read_bytes()),
        "per_source_items": dict(sorted(final_counts.items())),
        "fetched_at_utc_first": min(fetched_range) if fetched_range else None,
        "fetched_at_utc_last": max(fetched_range) if fetched_range else None,
        "dedupe": {
            "params": rs.dedupe,
            "note": "沿用 rulesets/zh.json 的 dedupe 参数；动作锚点只作标题同一事的文本特征，不产生 is_event 判定",
        },
        "engine_results_included": False,
        "freeze_rule": "此后不得增删；任何改动必须新建版本（新目录 + 新 manifest + 新 SHA-256）",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(f"[freeze] {len(items)} 条 → {items_path}")
    print(f"[freeze] sha256={digest}")
    print(f"[freeze] 各来源：{dict(sorted(final_counts.items()))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
