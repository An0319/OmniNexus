"""模型抽取：调本机 Ollama 模型把新闻条目抽成 schema 字段。

约束的落点（本机实测：Ollama 0.40.13 的 `format` 只保证 JSON 语法，**不强制 enum**，
所以结构约束不能交给解码器）：
1. 时间取源给出的发布时间，不采信模型自报时间。
2. 原文片段必须是条目原文的逐字子串（≥20 字）。
3. 主体必须能在原文里找到字面。
4. action 必须落在闭集内；模型给出集外值或字段类型不对，**同一条只允许一次修复重试**，
   仍不合法就返回显式拒绝态 `schema_invalid` / `unparsed_action`，不替它猜一个最像的。

用法：
    python phase0/timeline/extract_model.py --raw phase0/timeline/out/raw_items.json \
        --start 2026-10-01 --end 2026-11-08 --cache phase0/timeline/model_cache_dev.json \
        --out phase0/timeline/out_model/events.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from timeline import ACTIONS, SPACE_RE, parse_date, validate_event  # noqa: E402

BASE = "http://127.0.0.1:11434"
MODEL = "svjack/Qwen3-4B-Instruct-2507-heretic:latest"
EXTRACT_METHOD = "model_v1"
VALUE_KINDS = ("money", "percent", "phase", "count", "none")

SYSTEM = f"""你是新闻事件抽取器。读入一条新闻条目的标题与摘要，只输出一个 JSON 对象，形如：

{{"is_event": true, "reject_reason": "none", "subject": "AstraZeneca", "action": "partnership",
 "action_text": "launch", "object": "clinical trial AI collaboration", "value_kind": "none",
 "value_raw": "", "excerpt": "AstraZeneca and Oracle launch global AI collaboration"}}

字段要求（类型必须完全一致）：
- is_event：布尔。
- reject_reason：字符串，只能取 "none" / "not_an_event" / "unparsed_action" / "unparsed_subject"。
- subject：字符串，必须是标题或摘要里逐字出现的机构/公司/药名/项目名。
- action：字符串，只能取以下之一：{", ".join(sorted(ACTIONS))}。各值含义：
  trial_start=启动/开始/招募/入组/首个患者给药/加入一项试验；
  trial_result=公布试验结果/达到终点/给出疗效或安全性数据；
  approval=获批/批准/上市许可/clearance；rejection=拒绝/驳回/不予批准；
  halt=暂停/中止/关停/终止；designation=孤儿药/突破性疗法/快速通道/优先审评；
  deal=收购/授权/许可交易；partnership=合作/联手/联盟（当事方共同开展的非试验事务）；
  funding=融资/拨款/投资；policy=政策/法规/指南/监管要求/政府计划；
  registration=登记/注册；publication=论文/预印本/研究发表；personnel=任命/离职/人事。
  冲突消解：标题主事件是「启动或加入一项临床试验」时取 trial_start，即使出现 launch/team up/join；
  只有当事方共同开展的不是试验本身（如技术平台、数据合作）才取 partnership。
- action_text：字符串（支撑动作判断的那几个原文词，逐字出现）。
- object：字符串，可为空字符串。
- value_kind：字符串，只能取 "money" / "percent" / "phase" / "count" / "none"。
- value_raw：字符串，原文里的数值片段，无则空字符串。
- excerpt：字符串，从标题或摘要逐字复制的 ≥20 个连续字符，不改写、不翻译、不补全。

判定规则：
1. 只有「在某个具体时点发生了什么」才算事件。评论、问答、指南、综述、产品介绍、人物故事、招聘、
   方法学论文介绍，一律 is_event=false、reject_reason=not_an_event。
2. 标题与摘要都看不出动作，就 is_event=false、reject_reason=unparsed_action；**不要猜最像的动作**。
3. 主体在原文找不到字面，就 reject_reason=unparsed_subject。
4. 只输出 JSON，不要解释，不要用数组代替字符串。

示例（只学格式与判定，不要照抄内容）：
例1 标题「X and Y Launch Exclusive Clinical Trial of Z for Ovarian Cancer」→
{{"is_event": true, "reject_reason": "none", "subject": "X and Y", "action": "trial_start",
 "action_text": "Launch", "object": "Clinical Trial of Z", "value_kind": "none",
 "value_raw": "", "excerpt": "X and Y Launch Exclusive Clinical Trial of Z for Ovarian Cancer"}}
例2 标题「Guest Commentary: Why Our State Needs More Trials」→
{{"is_event": false, "reject_reason": "not_an_event", "subject": "", "action": "other",
 "action_text": "", "object": "", "value_kind": "none",
 "value_raw": "", "excerpt": "Guest Commentary: Why Our State Needs More Trials"}}"""

_NUM_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")


def _post(payload, timeout=180):
    req = urllib.request.Request(
        BASE + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def warm_up():
    t0 = time.time()
    _post({"model": MODEL, "messages": [{"role": "user", "content": "ok"}],
           "stream": False, "options": {"temperature": 0, "num_predict": 4}})
    return round(time.time() - t0, 2)


def _ask(messages, timeout=180):
    t0 = time.time()
    resp = _post({"model": MODEL, "messages": messages, "stream": False,
                  "format": "json", "options": {"temperature": 0}}, timeout=timeout)
    stats = {"latency_s": round(time.time() - t0, 2),
             "prompt_tokens": resp.get("prompt_eval_count"),
             "output_tokens": resp.get("eval_count")}
    content = resp.get("message", {}).get("content", "")
    try:
        return json.loads(content), stats
    except json.JSONDecodeError:
        return None, stats


def call_model(item: dict) -> tuple[dict | None, dict]:
    user = (f"标题：{item['title']}\n摘要：{item.get('excerpt') or ''}\n"
            f"来源：{item.get('source_name') or 'unknown'}")
    return _ask([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}])


def repair_model(item: dict, bad: str, err: str) -> tuple[dict | None, dict]:
    user = (f"标题：{item['title']}\n摘要：{item.get('excerpt') or ''}\n"
            f"你上一次的输出是：{bad}\n错误：{err}\n"
            f"action 必须是以下之一（原样拼写）：{', '.join(sorted(ACTIONS))}。"
            f"请按字段要求重新输出 JSON。")
    return _ask([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], timeout=180)


def schema_error(parsed) -> str | None:
    if not isinstance(parsed, dict):
        return "输出不是 JSON 对象"
    req = ["is_event", "reject_reason", "subject", "action", "action_text",
           "object", "value_kind", "value_raw", "excerpt"]
    missing = [k for k in req if k not in parsed]
    if missing:
        return f"缺字段：{','.join(missing)}"
    if not isinstance(parsed["is_event"], bool):
        return "is_event 不是布尔"
    if parsed["action"] not in ACTIONS:
        return f'action 不在闭集：{parsed["action"]!r}'
    if not isinstance(parsed["action_text"], str):
        return "action_text 不是字符串"
    if not isinstance(parsed["subject"], str) or not isinstance(parsed["excerpt"], str):
        return "subject/excerpt 不是字符串"
    if parsed["value_kind"] not in VALUE_KINDS:
        return f"value_kind 不在枚举：{parsed['value_kind']!r}"
    if parsed["reject_reason"] not in ("none", "not_an_event", "unparsed_action", "unparsed_subject"):
        return f"reject_reason 不在枚举：{parsed['reject_reason']!r}"
    return None


def _verbatim(text: str, haystack: str) -> bool:
    norm = SPACE_RE.sub(" ", text).strip()
    return len(norm) >= 20 and norm in SPACE_RE.sub(" ", haystack)


def _number(raw: str, kind: str):
    m = _NUM_RE.search(raw or "")
    if not m:
        return None
    try:
        val = float(m.group(0).replace(",", ""))
    except ValueError:
        return None
    return int(val) if kind == "count" and val.is_integer() else val


def extract_item(item: dict, start: dt.date, end: dt.date, cache: dict | None = None) -> tuple[dict | None, str | None]:
    url = item.get("link")
    if not str(url or "").startswith(("http://", "https://")):
        return None, "missing_url"
    when = parse_date(item.get("date", ""))
    if when is None:
        return None, "missing_time"
    if not (start <= when.date() <= end):
        return None, "out_of_window"

    key = url
    if cache is not None and key in cache and cache[key].get("_ok"):
        parsed, stats = cache[key]["parsed"], cache[key]["stats"]
    else:
        parsed, stats = call_model(item)
        err = schema_error(parsed)
        if err:
            bad = json.dumps(parsed, ensure_ascii=False) if parsed is not None else "<非 JSON>"
            fixed, stats2 = repair_model(item, bad, err)
            stats = {"latency_s": round(stats["latency_s"] + stats2["latency_s"], 2),
                     "prompt_tokens": (stats.get("prompt_tokens") or 0) + (stats2.get("prompt_tokens") or 0),
                     "output_tokens": (stats.get("output_tokens") or 0) + (stats2.get("output_tokens") or 0),
                     "repair": True}
            parsed = fixed
            err = schema_error(parsed) if parsed is not None else "重试后仍非 JSON"
        if err:
            if cache is not None:
                cache[key] = {"parsed": None, "stats": stats, "_ok": True, "err": err}
            return None, "schema_invalid"
        if cache is not None:
            cache[key] = {"parsed": parsed, "stats": stats, "_ok": True}
    if parsed is None:
        return None, "schema_invalid"

    haystack = (item.get("title") or "") + "\n" + (item.get("excerpt") or "")
    if not parsed.get("is_event") or parsed.get("reject_reason") not in (None, "none"):
        return None, parsed.get("reject_reason") or "not_an_event"
    excerpt = (parsed.get("excerpt") or "").strip()
    if not _verbatim(excerpt, haystack):
        return None, "missing_excerpt"
    subject = (parsed.get("subject") or "").strip()
    if not subject or len(subject) > 80:
        return None, "unparsed_subject"
    if subject.lower() not in haystack.lower():
        return None, "subject_not_in_text"

    kind = parsed.get("value_kind") or "none"
    raw = parsed.get("value_raw") or ""
    value = {"kind": kind if kind in ("money", "percent", "phase", "count") else "none",
             "raw": raw, "number": None, "unit": None}
    if value["kind"] != "none":
        value["number"] = _number(raw, value["kind"])

    event = {
        "event_id": f"m-{abs(hash(url)) % 10**10:010d}",
        "time": when.date().isoformat(),
        "time_precision": "minute" if re.search(r"\d{1,2}:\d{2}", item.get("date", "")) else "day",
        "subject": subject,
        "action": parsed["action"],
        "action_text": parsed.get("action_text") or "",
        "object": (parsed.get("object") or "").strip() or None,
        "value": value,
        "source_url": url,
        "url_kind": item.get("url_kind", "publisher"),
        "source_name": item.get("source_name") or "unknown",
        "fetched_at_utc": item.get("fetched_at_utc"),
        "excerpt": excerpt[:400],
        "excerpt_kind": item.get("excerpt_kind", "summary"),
        "extract_method": EXTRACT_METHOD,
        "sources": [{
            "source_url": url,
            "source_name": item.get("source_name") or "unknown",
            "url_kind": item.get("url_kind", "publisher"),
            "fetched_at_utc": item.get("fetched_at_utc"),
            "excerpt": excerpt[:200],
        }],
        "_stats": stats,
    }
    reason = validate_event(event)
    return (None, reason) if reason else (event, None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--cache", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    raw = json.loads(Path(args.raw).read_text(encoding="utf-8"))
    cache = {}
    if args.cache and Path(args.cache).exists():
        cache = json.loads(Path(args.cache).read_text(encoding="utf-8"))

    print(f"[warmup] {warm_up()}s（模型加载，不计入单条耗时）")
    events, rejects, stats = [], [], []
    for it in raw:
        ev, reason = extract_item(it, start, end, cache)
        if ev is not None:
            stats.append(ev.pop("_stats"))
            events.append(ev)
        else:
            rejects.append({"source_url": it.get("link"), "reason": reason,
                            "title": (it.get("title") or "")[:90]})

    lat = [s["latency_s"] for s in stats]
    toc = [s["output_tokens"] for s in stats if s.get("output_tokens")]
    summary = {
        "model": MODEL, "extract_method": EXTRACT_METHOD,
        "raw": len(raw), "events": len(events), "rejects": len(rejects),
        "latency_s_avg": round(sum(lat) / len(lat), 2) if lat else None,
        "latency_s_max": max(lat) if lat else None,
        "output_tokens_avg": round(sum(toc) / len(toc), 1) if toc else None,
        "reject_reasons": {},
    }
    for r in rejects:
        summary["reject_reasons"][r["reason"]] = summary["reject_reasons"].get(r["reason"], 0) + 1

    if args.cache:
        Path(args.cache).write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"meta": summary, "events": events}, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
