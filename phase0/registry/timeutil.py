"""时间口径：本目录所有时刻都由调用方显式传入，不读系统时钟。"""
from __future__ import annotations

from datetime import date, datetime, timezone


class TimeFormatError(ValueError):
    pass


def parse_iso_utc(text: str) -> datetime:
    """解析 ISO-8601 时刻；必须带时区（推荐 ``...Z``）。"""
    if not isinstance(text, str) or not text.strip():
        raise TimeFormatError("时刻必须显式传入（ISO-8601，带时区）")
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TimeFormatError(f"不是合法 ISO-8601 时刻：{text!r}") from exc
    if stamp.tzinfo is None:
        raise TimeFormatError(f"时刻缺少时区：{text!r}")
    return stamp.astimezone(timezone.utc)


def utc_date(text: str) -> date:
    return parse_iso_utc(text).date()
