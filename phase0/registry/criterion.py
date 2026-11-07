"""判据语法 criterion/v1：把一句预测压成机器可执行的判定式。

三条纪律（写进 syntax.md，代码里同样成立）：

1. 判定只读结构化字段——数据源、窗口、聚合方式、比较符、阈值、最小观测数、
   覆盖松弛天数、结算滞后天数。判定函数从不读 claim 文本。
2. 含糊表述在注册那一刻拒绝：claim 命中含糊词表直接报错；没有结构化 criterion
   的预测根本构不成一条注册记录，不存在「先收下再人工判」的路径。
3. 所有字段必填，不设隐藏默认值：默认值会让同一个判据在不同实现里语义不同，
   等价于把口径交给运气。
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date

SYNTAX_VERSION = "criterion/v1"

PROVIDERS = {
    "fred": {"field": "value", "id_pattern": r"^[A-Z0-9_]{2,32}$", "label": "FRED"},
    "yahoo": {"field": "adjclose", "id_pattern": r"^[A-Za-z0-9._\-^=]{1,20}$",
              "label": "Yahoo Finance"},
}
AGGREGATES = ("min", "max", "last", "mean", "pct_change")
COMPARATORS = ("gte", "lte")

REQUIRED_KEYS = (
    "syntax_version", "source", "window", "aggregate", "comparator",
    "threshold", "unit", "min_observations", "coverage_slack_days",
    "settlement_lag_days",
)

# 含糊词表。只用于拒绝「看起来能判、其实要人看」的句子，不用于判定。
VAGUE_TOKENS = (
    "大概率", "很可能", "可能", "或许", "也许", "有望", "或将",
    "走强", "走弱", "看好", "看空", "偏多", "偏空", "估计", "差不多",
    "显著", "趋势", "方向性", "应该会", "大概率上涨", "上涨概率", "下跌概率",
)
VAGUE_TOKENS_EN = ("likely", "probably", "maybe", "might", "roughly", "seems",
                   "arguably", "tends")

_AGG_LABEL = {
    "min": "窗口内最小观测值",
    "max": "窗口内最大观测值",
    "last": "窗口内最后一个观测值",
    "mean": "窗口内观测均值",
    "pct_change": "窗口首末观测涨跌幅（%）",
}
_SYM = {"gte": "≥", "lte": "≤"}


class CriterionError(ValueError):
    """判据不合规。``code`` 供调用方分支处理，``message`` 给人看。"""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _as_date(value, where: str) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise CriterionError("DATE_FORMAT", f"{where} 必须是 YYYY-MM-DD，收到 {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CriterionError("DATE_FORMAT", f"{where} 不是合法日期：{value!r}") from exc


def _as_int(value, where: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CriterionError("FIELD_TYPE", f"{where} 必须是整数，收到 {value!r}")
    if value < minimum:
        raise CriterionError("FIELD_RANGE", f"{where} 不能小于 {minimum}，收到 {value}")
    return value


def validate(criterion: dict) -> dict:
    """校验并归一化判据；不合规直接抛 ``CriterionError``。

    返回按固定键序排列的深拷贝，后续哈希与落账都以它为准。
    """
    if not isinstance(criterion, dict):
        raise CriterionError("CRITERION_MISSING",
                             "criterion 必须是对象；没有结构化判据的预测不得注册")
    unknown = sorted(set(criterion) - set(REQUIRED_KEYS))
    if unknown:
        raise CriterionError("UNKNOWN_FIELD",
                             f"不认识字段 {unknown}；未声明的语义不实现，避免口径漂移")
    missing = [k for k in REQUIRED_KEYS if k not in criterion]
    if missing:
        raise CriterionError("MISSING_FIELD", f"缺少必填字段 {missing}")

    if criterion["syntax_version"] != SYNTAX_VERSION:
        raise CriterionError("SYNTAX_VERSION",
                             f"syntax_version 必须是 {SYNTAX_VERSION!r}，"
                             f"收到 {criterion['syntax_version']!r}")

    src = criterion["source"]
    if not isinstance(src, dict) or set(src) != {"provider", "id", "field"}:
        raise CriterionError("SOURCE_INVALID",
                             "source 必须是对象且只含 provider/id/field 三个字段")
    provider = src["provider"]
    if provider not in PROVIDERS:
        raise CriterionError("SOURCE_PROVIDER",
                             f"未知数据源 provider={provider!r}；可选 {sorted(PROVIDERS)}")
    sid = src["id"]
    if not isinstance(sid, str) or not re.fullmatch(PROVIDERS[provider]["id_pattern"], sid):
        raise CriterionError("SOURCE_ID", f"{provider} 的 id 不合法：{sid!r}")
    if src["field"] != PROVIDERS[provider]["field"]:
        raise CriterionError("SOURCE_FIELD",
                             f"{provider} 只支持 field={PROVIDERS[provider]['field']!r}，"
                             f"收到 {src['field']!r}")

    win = criterion["window"]
    if not isinstance(win, dict) or set(win) != {"start", "end"}:
        raise CriterionError("WINDOW_INVALID", "window 必须是只含 start/end 的对象")
    start = _as_date(win["start"], "window.start")
    end = _as_date(win["end"], "window.end")
    if start > end:
        raise CriterionError("WINDOW_INVERTED",
                             f"window.start {start} 晚于 window.end {end}")

    if criterion["aggregate"] not in AGGREGATES:
        raise CriterionError("AGGREGATE_UNKNOWN",
                             f"aggregate={criterion['aggregate']!r} 不在 {AGGREGATES}")
    if criterion["comparator"] not in COMPARATORS:
        raise CriterionError("COMPARATOR_UNKNOWN",
                             f"comparator={criterion['comparator']!r} 不在 {COMPARATORS}")

    thr = criterion["threshold"]
    if isinstance(thr, bool) or not isinstance(thr, (int, float)) or not math.isfinite(thr):
        raise CriterionError("THRESHOLD_INVALID", f"threshold 必须是有限数值，收到 {thr!r}")

    unit = criterion["unit"]
    if not isinstance(unit, str) or not unit.strip():
        raise CriterionError("UNIT_INVALID", "unit 必须是非空字符串（阈值单位）")

    min_obs = _as_int(criterion["min_observations"], "min_observations", 1)
    slack = _as_int(criterion["coverage_slack_days"], "coverage_slack_days", 0)
    lag = _as_int(criterion["settlement_lag_days"], "settlement_lag_days", 0)
    if criterion["aggregate"] == "pct_change" and min_obs < 2:
        raise CriterionError("MIN_OBS_TOO_SMALL",
                             "pct_change 至少需要 2 个观测，min_observations 不得小于 2")

    return {
        "syntax_version": SYNTAX_VERSION,
        "source": {"provider": provider, "id": sid, "field": src["field"]},
        "window": {"start": win["start"], "end": win["end"]},
        "aggregate": criterion["aggregate"],
        "comparator": criterion["comparator"],
        "threshold": thr,
        "unit": unit,
        "min_observations": min_obs,
        "coverage_slack_days": slack,
        "settlement_lag_days": lag,
    }


def canonical_json(criterion: dict) -> str:
    return json.dumps(criterion, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def criterion_sha256(criterion: dict) -> str:
    return hashlib.sha256(canonical_json(criterion).encode("utf-8")).hexdigest()


def render_claim(criterion: dict) -> str:
    """由判据渲染出规范句式。账本里的成交口径以这句为准，不以自由文本为准。"""
    src = criterion["source"]
    label = f"{PROVIDERS[src['provider']]['label']}:{src['id']}"
    w = criterion["window"]
    thr = criterion["threshold"]
    thr_text = f"{thr:g}" if isinstance(thr, float) else str(thr)
    return (f"{label} 在 {w['start']} 至 {w['end']} 窗口内，"
            f"{_AGG_LABEL[criterion['aggregate']]} {_SYM[criterion['comparator']]} {thr_text} "
            f"{criterion['unit']}（至少 {criterion['min_observations']} 个观测）")


def lint_claim(text: str) -> None:
    """拒绝含糊句子。命中即抛 ``VAGUE_CLAIM``。"""
    if not isinstance(text, str) or len(text.strip()) < 4:
        raise CriterionError("CLAIM_INVALID", "claim 必须是至少 4 个字符的一句话")
    hits = [t for t in VAGUE_TOKENS if t in text]
    low = text.lower()
    hits += [t for t in VAGUE_TOKENS_EN if re.search(rf"\b{t}\b", low)]
    if hits:
        raise CriterionError(
            "VAGUE_CLAIM",
            f"claim 含含糊表述 {hits}；判据必须机器可判，含糊句子在注册这一刻就拒绝")
