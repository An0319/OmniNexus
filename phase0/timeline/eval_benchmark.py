"""基准评测：拿人工标注比对抽取器输出，算出召回/精确/字段准确率。

指标定义（写死，避免事后改口径）：
- lenient recall：人工标为事件的条目里，抽取器**是否入表**（不论字段对错）
- strict recall：入表且 action 正确且 subject 合格且 value_kind 一致（人工标 none 则不查）
- lenient precision：入表的条目里，有多少条人工也标为事件
- strict precision：入表且与某条人工事件对得上（action + subject 合格）
- subject 合格判据：人工主体 token 至少有 60% 出现在抽取主体里（去停用词、忽略大小写）

用法：
    python phase0/timeline/eval_benchmark.py --items phase0/timeline/benchmark_items.json \
        --raw phase0/timeline/out/raw_items.json --labels phase0/timeline/benchmark_labels_dev.json \
        --start 2026-10-01 --end 2026-11-08
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from timeline import STOPWORDS, build_event, parse_date  # noqa: E402

FLOORS = {
    "lenient_recall": 0.70,
    "strict_recall": 0.45,
    "lenient_precision": 0.70,
    "action_accuracy": 0.60,
    "subject_accuracy": 0.60,
}


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOPWORDS and len(w) > 1}


def subject_ok(label_subject: str, extracted: str) -> bool:
    lt = tokens(label_subject)
    et = tokens(extracted)
    if not lt:
        return False
    return len(lt & et) / len(lt) >= 0.6


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--extractor", choices=["rules", "model"], default="rules",
                    help="rules=timeline.build_event；model=extract_model.extract_item（本机 Ollama）")
    ap.add_argument("--cache", default=None, help="model 抽取的结果缓存，重跑不重复调用")
    args = ap.parse_args()

    cache = None
    if args.extractor == "model":
        from extract_model import extract_item, warm_up  # noqa: PLC0415
        cache = {}
        if args.cache and Path(args.cache).exists():
            cache = json.loads(Path(args.cache).read_text(encoding="utf-8"))
        print(f"[warmup] {warm_up()}s（模型加载，不计入单条耗时）", file=sys.stderr)

    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    items = json.loads(Path(args.items).read_text(encoding="utf-8"))
    labels = {x["id"]: x for x in json.loads(Path(args.labels).read_text(encoding="utf-8"))}
    raw = json.loads(Path(args.raw).read_text(encoding="utf-8"))
    by_url = {it["link"]: it for it in raw}

    rows = []
    tp_strict = tp_lenient = emitted = 0
    labeled_events = 0
    action_ok = subject_cnt = subject_ok_cnt = 0

    for it in items:
        lab = labels.get(it["id"])
        if not lab:
            print(f"[warn] 缺标注：{it['id']}", file=sys.stderr)
            continue
        raw_item = by_url.get(it["url"])
        if raw_item is None:
            print(f"[warn] raw 快照里找不到 {it['id']}，可能快照已过期", file=sys.stderr)
            continue
        if args.extractor == "model":
            ev, reason = extract_item(raw_item, start, end, cache)
        else:
            ev, reason = build_event(raw_item, start, end)
        is_event_label = bool(lab["event"])
        if is_event_label:
            labeled_events += 1
        row = {
            "id": it["id"],
            "label_event": is_event_label,
            "emitted": ev is not None,
            "reject_reason": reason,
            "title": it["title"][:90],
        }
        if ev is not None:
            emitted += 1
            row["action"] = ev["action"]
            row["subject"] = ev["subject"]
            if is_event_label:
                tp_lenient += 1
                a_ok = ev["action"] == lab["action"]
                s_ok = subject_ok(lab["subject"], ev["subject"])
                v_ok = lab["value_kind"] in (None, "none") or ev["value"]["kind"] == lab["value_kind"]
                row.update({"action_ok": a_ok, "subject_ok": s_ok, "value_ok": v_ok})
                action_ok += int(a_ok)
                subject_cnt += 1
                subject_ok_cnt += int(s_ok)
                if a_ok and s_ok and v_ok:
                    tp_strict += 1
        rows.append(row)

    lenient_recall = tp_lenient / labeled_events if labeled_events else 0.0
    strict_recall = tp_strict / labeled_events if labeled_events else 0.0
    lenient_precision = tp_lenient / emitted if emitted else 0.0
    strict_precision = tp_strict / emitted if emitted else 0.0
    action_acc = action_ok / subject_cnt if subject_cnt else 0.0
    subject_acc = subject_ok_cnt / subject_cnt if subject_cnt else 0.0

    summary = {
        "n_items": len(items),
        "n_labeled_events": labeled_events,
        "n_emitted": emitted,
        "lenient_recall": round(lenient_recall, 3),
        "strict_recall": round(strict_recall, 3),
        "lenient_precision": round(lenient_precision, 3),
        "strict_precision": round(strict_precision, 3),
        "action_accuracy": round(action_acc, 3),
        "subject_accuracy": round(subject_acc, 3),
        "floors": FLOORS,
        "pass": {
            "lenient_recall": lenient_recall >= FLOORS["lenient_recall"],
            "strict_recall": strict_recall >= FLOORS["strict_recall"],
            "lenient_precision": lenient_precision >= FLOORS["lenient_precision"],
            "action_accuracy": action_acc >= FLOORS["action_accuracy"],
            "subject_accuracy": subject_acc >= FLOORS["subject_accuracy"],
        },
        "rows": rows,
    }

    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False, indent=2))
    print("\n逐条：")
    for r in rows:
        mark = "OK " if (r["emitted"] and r["label_event"]) else ("REJ" if not r["emitted"] else "FP ")
        print(
            f"  {r['id']} {mark} emit={r['emitted']} label={r['label_event']} "
            f"action={r.get('action')} subject={str(r.get('subject'))[:40]} "
            f"{'aOK' if r.get('action_ok') else ''}{'sOK' if r.get('subject_ok') else ''} "
            f"reason={r.get('reject_reason')} | {r['title'][:60]}"
        )
    if args.out:
        Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[write] {args.out}")
    if args.cache and cache is not None:
        Path(args.cache).write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        lat = [v["stats"]["latency_s"] for v in cache.values() if v.get("stats")]
        toc = [v["stats"]["output_tokens"] for v in cache.values() if v.get("stats", {}).get("output_tokens")]
        print(json.dumps({
            "cache_entries": len(cache),
            "latency_s_avg": round(sum(lat) / len(lat), 2) if lat else None,
            "latency_s_max": max(lat) if lat else None,
            "output_tokens_avg": round(sum(toc) / len(toc), 1) if toc else None,
            "cost_cny_per_item": 0.0,
            "cost_note": "本机 Ollama 推理，无 API 计费；成本仅为电费与占用时长",
        }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
