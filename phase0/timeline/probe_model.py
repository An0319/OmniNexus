"""模型接口可用性探针：回答「本机能不能真的调到一个模型」，不做效果评估。

用法：python phase0/timeline/probe_model.py
输出：phase0/timeline/model_probe.json（只存模型名、耗时、token 数、是否返回合法 JSON、
     是否编造原文片段；不存第三方原文全文，只存标题短引用）
"""

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE = "http://127.0.0.1:11434"
CANDIDATES = [
    "svjack/Qwen3-4B-Instruct-2507-heretic:latest",
    "mgraffam/qwen3.5-opus4.6-heretic:latest",
    "satgeze/qwenpaw-9b-heretic-1m:Q4_K_M",
]

ACTION_ENUM = [
    "trial_start", "trial_result", "approval", "rejection", "halt", "designation",
    "deal", "partnership", "funding", "policy", "registration", "publication",
    "personnel", "other",
]

SCHEMA = {
    "type": "object",
    "properties": {
        "is_event": {"type": "boolean"},
        "reject_reason": {
            "type": "string",
            "enum": ["none", "not_an_event", "unparsed_action", "unparsed_subject",
                     "missing_time", "missing_excerpt"],
        },
        "time": {"type": "string"},
        "subject": {"type": "string"},
        "action": {"type": "string", "enum": ACTION_ENUM + ["none"]},
        "object": {"type": "string"},
        "value_kind": {"type": "string", "enum": ["money", "percent", "phase", "count", "none"]},
        "value_raw": {"type": "string"},
        "excerpt": {"type": "string"},
    },
    "required": ["is_event", "reject_reason", "time", "subject", "action", "object",
                 "value_kind", "value_raw", "excerpt"],
}

SYSTEM = """你是新闻事件抽取器。输入一条新闻条目的标题与摘要，输出一个 JSON 对象，字段严格遵守给定 schema。

规则：
1. 只有「在某个具体时点发生了什么」才算事件；评论、指南、问答、综述、产品介绍、人物故事不算，置 is_event=false、reject_reason=not_an_event。
2. action 只能取给定枚举值。若标题与摘要都看不出动作，置 is_event=false、reject_reason=unparsed_action，不要猜。
3. subject 必须能在标题或摘要原文中找到对应字面（机构名、公司名、药名、项目名）；找不到就置 reject_reason=unparsed_subject。
4. time 必须来自条目给出的发布时间；缺失就置 missing_time。
5. excerpt 必须从给定标题或摘要中逐字复制至少 20 个连续字符，不得改写、不得补全。
6. 不要输出除 JSON 以外的任何内容。"""


def post(path, payload, timeout=120):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path, timeout=10):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def build_user(item):
    return (
        f"标题：{item['title']}\n"
        f"摘要：{item['excerpt']}\n"
        f"发布时间（源给出）：{item['date']}\n"
        f"来源：{item['source_name']}\n"
    )


def main():
    out = {"probed_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "endpoint": BASE, "api_style": "ollama /api/chat, JSON Schema 约束",
           "models_available": [], "results": []}

    try:
        tags = get("/api/tags")
    except Exception as e:  # noqa: BLE001
        out["fatal"] = f"服务未响应：{type(e).__name__}: {e}"
        json.dump(out, open("phase0/timeline/model_probe.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print(out["fatal"])
        return
    out["models_available"] = [m["name"] for m in tags.get("models", [])]

    items = json.load(open("phase0/timeline/benchmark_items.json", encoding="utf-8"))[:3]

    for model in CANDIDATES:
        if model not in out["models_available"]:
            out["results"].append({"model": model, "skipped": "模型未安装"})
            continue
        for item in items:
            payload = {
                "model": model,
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": build_user(item)}],
                "stream": False,
                "format": SCHEMA,
                "options": {"temperature": 0},
            }
            t0 = time.time()
            try:
                resp = post("/api/chat", payload)
            except Exception as e:  # noqa: BLE001
                out["results"].append({"model": model, "id": item["id"],
                                       "error": f"{type(e).__name__}: {e}"})
                continue
            dt = round(time.time() - t0, 2)
            content = resp.get("message", {}).get("content", "")
            try:
                parsed = json.loads(content)
                valid = True
            except json.JSONDecodeError:
                parsed, valid = None, False
            excerpt_ok = bool(parsed) and (
                str(parsed.get("excerpt", "")).strip() in (item["title"] + "\n" + item["excerpt"])
            )
            out["results"].append({
                "model": model,
                "id": item["id"],
                "latency_s": dt,
                "prompt_tokens": resp.get("prompt_eval_count"),
                "output_tokens": resp.get("eval_count"),
                "json_valid": valid,
                "excerpt_verbatim": excerpt_ok,
                "is_event": (parsed or {}).get("is_event") if isinstance(parsed, dict) else None,
                "action": (parsed or {}).get("action") if isinstance(parsed, dict) else None,
                "title_short": item["title"][:90],
            })
            print(f"{model} {item['id']} {dt}s valid={valid} excerpt_ok={excerpt_ok}")

    json.dump(out, open("phase0/timeline/model_probe.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
