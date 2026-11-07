"""对账：从账本现算累计命中情况。

口径：
* 每个 ``id`` 只取其**最新一条**判定（账本顺序即时间顺序）。
* 命中率分母只含已判定（hit + miss）；``undetermined`` 单列，绝不进分母、
  也不折算成 miss。
* 样本少时不报点估计，只报 Wilson 95% 区间；区间一律写成整数百分比（粗区间），
  不用两位小数冒充精度。
"""
from __future__ import annotations

import math

POINT_ESTIMATE_MIN = 20


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n <= 0:
        return None
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def latest_verdicts(entries: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for entry in entries:
        if entry.get("kind") == "verdict":
            latest[entry["id"]] = entry
    return latest


def summarize(entries: list[dict], point_min: int = POINT_ESTIMATE_MIN) -> dict:
    registrations: dict[str, dict] = {}
    for entry in entries:
        if entry.get("kind") == "registration":
            registrations.setdefault(entry["id"], entry)
    verdicts = latest_verdicts(entries)

    hit = miss = undetermined = 0
    undetermined_ids: list[dict] = []
    by_source: dict[str, dict] = {}
    rows: list[dict] = []

    for reg_id, reg in registrations.items():
        src = reg["criterion"]["source"]
        key = f"{src['provider']}:{src['id']}"
        bucket = by_source.setdefault(key, {"hit": 0, "miss": 0, "undetermined": 0,
                                            "no_verdict": 0})
        verdict = verdicts.get(reg_id)
        if verdict is None:
            bucket["no_verdict"] += 1
            rows.append({"id": reg_id, "source": key, "verdict": None,
                         "reason_code": None})
            continue
        kind = verdict["verdict"]
        bucket[kind] += 1
        if kind == "hit":
            hit += 1
        elif kind == "miss":
            miss += 1
        else:
            undetermined += 1
            undetermined_ids.append({"id": reg_id, "reason_code": verdict.get("reason_code")})
        rows.append({"id": reg_id, "source": key, "verdict": kind,
                     "reason_code": verdict.get("reason_code")})

    decided = hit + miss
    ci = wilson(hit, decided)
    hit_rate = {
        "k": hit,
        "n": decided,
        "ci95": None if ci is None else [round(ci[0] * 100, 1), round(ci[1] * 100, 1)],
        "point": None,
        "point_reported": False,
        "rule": f"样本 n<{point_min} 只报区间、不报点估计" if decided < point_min
                else f"n≥{point_min} 才报点估计",
    }
    if decided >= point_min:
        hit_rate["point"] = round(hit / decided * 100, 1)
        hit_rate["point_reported"] = True

    return {
        "registered": len(registrations),
        "verified": len(registrations) - sum(1 for r in rows if r["verdict"] is None),
        "no_verdict": sum(1 for r in rows if r["verdict"] is None),
        "hit": hit,
        "miss": miss,
        "undetermined": undetermined,
        "decided": decided,
        "hit_rate": hit_rate,
        "undetermined_ids": undetermined_ids,
        "by_source": by_source,
        "rows": rows,
        "note": "undetermined 不计入命中率分母；未判定与无法判定分开计数",
    }


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def rate_line(summary: dict) -> str:
    rate = summary["hit_rate"]
    if rate["n"] == 0:
        return "命中率：没有已判定样本，无区间可报"
    lo, hi = rate["ci95"]
    body = f"{rate['n']} 条可判中 {rate['k']} 条命中"
    ci_text = f"按 Wilson 方法 95% 区间 {_pct(lo / 100)}–{_pct(hi / 100)}"
    if rate["point_reported"]:
        return f"命中率：{body}；{ci_text}；点估计 {rate['point']:.1f}%"
    return f"命中率：{body}；{ci_text}；样本不足以给点估计"


def to_markdown(summary: dict) -> str:
    lines = [
        "| 指标 | 数值 |",
        "|---|---|",
        f"| 注册数 | {summary['registered']} |",
        f"| 已判定 | {summary['decided']} |",
        f"| 命中 hit | {summary['hit']} |",
        f"| 未命中 miss | {summary['miss']} |",
        f"| 无法判定 undetermined | {summary['undetermined']} |",
        f"| 尚无判定 | {summary['no_verdict']} |",
        "",
        rate_line(summary),
        "",
        "| 事件 | 来源 | 判定 | 原因码 |",
        "|---|---|---|---|",
    ]
    for row in summary["rows"]:
        lines.append(f"| {row['id']} | {row['source']} | {row['verdict'] or '—'} "
                     f"| {row['reason_code'] or '—'} |")
    return "\n".join(lines)
