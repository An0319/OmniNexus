#!/usr/bin/env python3
"""物化看板所需的仓库侧快照（M2 数据契约，清单 §5/§5★）。

产出三份，全部入库、全部只读外部输入：
- chains/<id>.profile.json  「判定剖线快照」：滞后位相关系数 + 判定参数（清单 §5★）
- chains/<id>.zseries.json  「z 曲线快照」：领先面/滞后面周频归一序列（链详情页 C5）
- chains/revisions.json     「修订登记」：各链 YAML revisions 块的结构化（时间线页 C8）

只读既有产出（phase0/output/*.csv、chains/*.yaml），不触发回测、不改判定参数、
不写 data/。判定结论的唯一真相是 chains/project_budget.json 的 attempts[].note，
本脚本只做结构化，判定状态由作者裁定（VERDICT 写死），不从阈值机械推导。

用法：python scripts/materialize_profiles.py
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHAINS_DIR = ROOT / "chains"
OUTPUT_DIR = ROOT / "phase0" / "output"

SCHEMA_VERSION = "1.0"

# 链级判定结论：与 chains/project_budget.json 的 attempts[].note 逐条对应。
# 这是"成文结论的结构化"，不含判定逻辑；判定参数改动必须回 chains/*.yaml 并登记修订。
VERDICT = {
    "chain01": {"status": "falsified", "decided_utc_date": "2026-09-25"},
    "chain10": {"status": "not_passed", "decided_utc_date": "2026-09-25"},
    "chain20": {"status": "not_passed", "decided_utc_date": "2026-09-26"},
}

# xcorr / 周频文件命名不统一（首链无后缀），显式登记，避免靠猜。
FILES = {
    "chain01": {"xcorr": "xcorr.csv", "lag_weekly": "sector_weekly.csv"},
    "chain10": {"xcorr": "xcorr_chain10.csv", "lag_weekly": "sector_weekly_chain10.csv"},
    "chain20": {"xcorr": "xcorr_chain20.csv", "lag_weekly": "sector_weekly_chain20.csv"},
}

# 前视位登记（chain20.yaml：pass_window 之外的 k=0 只作诊断，不可交易化）
FORWARD_LOOK = {"chain20": 0}

# z 曲线快照：chain20 无 zseries 产出（隔夜快传导链未做周频归一），前端走「无数据」灰态。
ZSERIES_FILES = {
    "chain01": "zseries.csv",
    "chain10": "zseries_chain10.csv",
}


def load_yaml(path: Path) -> dict:
    try:
        import yaml  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("需要 PyYAML：pip install pyyaml") from exc
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def read_xcorr(path: Path) -> dict[str, list[dict]]:
    """xcorr CSV → {指标名: [{k, corr}, ...]}。"""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    metrics: dict[str, list[dict]] = {}
    for row in rows:
        k = int(row["lead超前周数"])
        for key, value in row.items():
            if key == "lead超前周数" or value in (None, ""):
                continue
            metrics.setdefault(key, []).append({"k": k, "corr": float(value)})
    return metrics


def count_weeks(path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return sum(1 for _ in fh) - 1


def classify(lags: list[dict], judgement: dict) -> dict:
    """按已锁定的判定参数派生指标状态；不新增阈值，只读 yaml 里的既有值。

    只判"判定窗口内是否触线"，不外推"证伪"——证伪是作者对整条链的裁定
    （见 VERDICT），不是单指标阈值能机械推出的结论。
    """
    noise = judgement.get("noise_band")
    pass_corr = judgement["pass_corr"]
    lo, hi = judgement["pass_window"]

    peak = max(lags, key=lambda d: abs(d["corr"]))
    in_window = [d for d in lags if lo <= d["k"] <= hi]
    best = max(in_window, key=lambda d: abs(d["corr"])) if in_window else None

    if best is not None and abs(best["corr"]) >= pass_corr:
        status = "verified"
    elif best is not None and noise is not None and abs(best["corr"]) >= noise:
        status = "greyzone"
    else:
        status = "not_passed"

    return {
        "status": status,
        "best_in_window": best,
        "peak": peak,
        "peak_outside_window": bool(best is None or peak["k"] != best["k"]),
        "lags": lags,
    }


def build(chain_id: str) -> dict:
    files = FILES[chain_id]
    spec = load_yaml(CHAINS_DIR / f"{chain_id}.yaml")
    judgement = spec["judgement"]
    metrics_raw = read_xcorr(OUTPUT_DIR / files["xcorr"])
    total_weeks = count_weeks(OUTPUT_DIR / files["lag_weekly"])
    lag_max = judgement["lag_range"][1]

    metrics = [
        {"name": name, **classify(lags, judgement)}
        for name, lags in metrics_raw.items()
    ]

    verdict = dict(VERDICT[chain_id])
    verdict["note"] = spec.get("title", "")
    fl_k = FORWARD_LOOK.get(chain_id)
    forward_look = (
        {
            "k": fl_k,
            "tradable": False,
            "rationale": "同周共动：A 股当周收盘早于美股当周收盘，不可交易化",
        }
        if fl_k is not None
        else None
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "chain_id": chain_id,
        "title": spec["title"],
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_files": [
            f"chains/{chain_id}.yaml",
            f"phase0/output/{files['xcorr']}",
            f"phase0/output/{files['lag_weekly']}",
        ],
        "judgement": {
            "lag_range": judgement["lag_range"],
            "pass_window": judgement["pass_window"],
            "pass_corr": judgement["pass_corr"],
            "noise_band": judgement.get("noise_band"),
            "null_median": judgement.get("null_median"),
        },
        "verdict": verdict,
        "forward_look": forward_look,
        "samples": {
            "total_weeks": total_weeks,
            "effective_weeks": total_weeks - lag_max,
            "basis": "周频（周一），重叠窗口按最大滞后位扣减",
        },
        "pipeline": {
            "lead": spec["lead"]["source"],
            "lag": spec["lag"]["source"],
            "steps": ["align", "normalize", "judge"],
        },
        "metrics": metrics,
    }


def _num(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return round(float(value), 6)


def build_zseries(chain_id: str) -> dict:
    """zseries CSV → 周频归一序列。

    裁掉开头「两序列皆缺」的预热段（回归窗口尚未重叠），但保留中间的真缺口，
    前端据此画显式断口——绝不跨缺段连线、绝不把缺失补成零。
    """
    source = ZSERIES_FILES[chain_id]
    with (OUTPUT_DIR / source).open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    points = [
        {
            "date": row.get("") or row.get("date") or "",
            "lead": _num(row.get("lead_z")),
            "lag_ret": _num(row.get("lag_z_周收益率")),
            "lag_amount": _num(row.get("lag_z_周成交额")),
        }
        for row in rows
    ]
    start = next(
        (i for i, p in enumerate(points) if p["lead"] is not None or p["lag_ret"] is not None),
        0,
    )
    return {
        "chain_id": chain_id,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_file": f"phase0/output/{source}",
        "points": points[start:],
    }


def build_revisions() -> dict:
    """各链 YAML revisions 块 → 统一登记（时间线页 C8 的「修订」事件源）。"""
    revisions: dict[str, list[dict]] = {}
    for chain_id in FILES:
        spec = load_yaml(CHAINS_DIR / f"{chain_id}.yaml")
        revisions[chain_id] = [
            {
                "date": str(item.get("date", "")),
                "reason": item.get("reason", ""),
                "counts_as_attempt": bool(item.get("counts_as_attempt", False)),
            }
            for item in spec.get("revisions", [])
        ]
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_files": [f"chains/{chain_id}.yaml" for chain_id in FILES],
        "revisions": revisions,
    }


def _write(target: Path, payload: dict) -> None:
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"wrote {target.relative_to(ROOT)}")


def main() -> int:
    for chain_id in FILES:
        _write(CHAINS_DIR / f"{chain_id}.profile.json", build(chain_id))
    for chain_id in ZSERIES_FILES:
        _write(CHAINS_DIR / f"{chain_id}.zseries.json", build_zseries(chain_id))
    _write(CHAINS_DIR / "revisions.json", build_revisions())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
