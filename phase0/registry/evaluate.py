"""到期核验：只读 criterion 判定，产出 hit / miss / undetermined。

关键约束：
* 判定函数不接受 claim 文本，也不看任何自由叙述——判据是否真能机器判，
  靠的就是「换掉句子、结论不变」。
* 第三种状态是真实状态：取不到数、字段缺失、窗口没被覆盖、观测数不够，
  一律记 ``undetermined`` 并写原因码，绝不折算成 miss。
* 未到期（``expires_on + settlement_lag_days`` 之前）抛 ``NotDue``，不落任何判定。
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

import criterion as C
import sources as S
import timeutil as T

HIT, MISS, UNDETERMINED = "hit", "miss", "undetermined"


class NotDue(RuntimeError):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _window(series: pd.Series, start: str, end: str) -> pd.Series:
    mask = (series.index >= pd.Timestamp(start)) & (series.index <= pd.Timestamp(end))
    return series.loc[mask]


def _aggregate(window: pd.Series, aggregate: str) -> float:
    values = window.to_numpy(dtype=float)
    if aggregate == "min":
        return float(values.min())
    if aggregate == "max":
        return float(values.max())
    if aggregate == "last":
        return float(values[-1])
    if aggregate == "mean":
        return float(values.mean())
    if aggregate == "pct_change":
        first, last = float(values[0]), float(values[-1])
        return (last / first - 1.0) * 100.0
    raise ValueError(f"unknown aggregate {aggregate!r}")


def evaluate(record: dict, at: str) -> dict:
    """对一条注册记录做到期核验，返回判定记录（不含账本层字段）。

    ``record`` 只需含 ``id`` / ``expires_on`` / ``criterion``；
    明确不使用 ``claim``。
    """
    criterion = C.validate(record["criterion"])
    expires = date.fromisoformat(record["expires_on"])
    at_date = T.utc_date(at)
    due = expires + timedelta(days=int(criterion["settlement_lag_days"]))
    if at_date < due:
        raise NotDue(f"{record['id']} 未到期：{at_date} 早于结算日 {due}")

    src = criterion["source"]
    base = {
        "kind": "verdict",
        "id": record["id"],
        "criterion_sha256": C.criterion_sha256(criterion),
        "expires_on": record["expires_on"],
    }
    try:
        series, fingerprint = S.probe(src["provider"], src["id"], src["field"], at)
    except S.SourceUnavailable as exc:
        return {
            **base,
            "verdict": UNDETERMINED,
            "reason_code": exc.code,
            "reason_detail": exc.detail,
            "observed": None,
            "source_fingerprint": None,
        }

    start, end = criterion["window"]["start"], criterion["window"]["end"]
    window = _window(series, start, end)
    observed = {
        "window": {"start": start, "end": end},
        "n": int(len(window)),
        "first_obs": str(window.index.min().date()) if len(window) else None,
        "last_obs": str(window.index.max().date()) if len(window) else None,
        "aggregate": criterion["aggregate"],
        "value": None,
    }

    def undetermined(code: str, detail: str) -> dict:
        return {**base, "verdict": UNDETERMINED, "reason_code": code,
                "reason_detail": detail, "observed": observed,
                "source_fingerprint": fingerprint}

    if len(window) == 0:
        return undetermined("NO_OBSERVATIONS_IN_WINDOW",
                            f"窗口 {start}..{end} 内没有任何观测")

    last_obs = window.index.max().date()
    gap = (date.fromisoformat(end) - last_obs).days
    if gap > criterion["coverage_slack_days"]:
        return undetermined(
            "WINDOW_NOT_COVERED",
            f"窗口末 {end} 之前最后一个观测是 {last_obs}，间隔 {gap} 天，"
            f"超过允许的 {criterion['coverage_slack_days']} 天")

    if len(window) < criterion["min_observations"]:
        return undetermined(
            "INSUFFICIENT_OBSERVATIONS",
            f"窗口内只有 {len(window)} 个观测，少于要求的 {criterion['min_observations']} 个")

    if criterion["aggregate"] == "pct_change" and float(window.iloc[0]) == 0.0:
        return undetermined("AGGREGATE_UNDEFINED", "窗口首条观测为 0，涨跌幅无定义")

    value = _aggregate(window, criterion["aggregate"])
    observed["value"] = round(value, 6)
    threshold = float(criterion["threshold"])
    passed = value >= threshold if criterion["comparator"] == "gte" else value <= threshold
    return {
        **base,
        "verdict": HIT if passed else MISS,
        "reason_code": None,
        "reason_detail": None,
        "observed": observed,
        "source_fingerprint": fingerprint,
    }
