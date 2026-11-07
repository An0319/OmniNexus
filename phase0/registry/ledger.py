"""append-only 账本：只追加单条，写入时刻显式传入。

与 ``phase0/append_batch1_ledger.py`` 同一套纪律，但是**独立文件**
（默认 ``phase0/registry/registry.ledger.jsonl``），与批次一账本物理隔离：

* ``at`` 必须由调用方给出，本模块不读系统时钟，没有「拿当前时间兜底」的分支。
* 既有字节从不重写；追加前先校验文件尾部可解析，坏账本上不再堆行。
* 每条记录带 ``prev_record_sha256``，形成哈希链，便于只读校验「中间没被改过」。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

DEFAULT_LEDGER = Path(__file__).resolve().parent / "registry.ledger.jsonl"


class LedgerError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return [ln for ln in text.splitlines() if ln.strip()]


def entry_sha256(line: str) -> str:
    return hashlib.sha256(line.encode("utf-8")).hexdigest()


def read_entries(path: Path | str = DEFAULT_LEDGER) -> list[dict]:
    path = Path(path)
    out: list[dict] = []
    for i, line in enumerate(_lines(path), 1):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise LedgerError("LEDGER_PARSE",
                              f"{path} 第 {i} 行不是合法 JSON：{exc}") from exc
    return out


def tail_parseable(path: Path) -> bool:
    lines = _lines(path)
    if not lines:
        return True
    try:
        json.loads(lines[-1])
    except json.JSONDecodeError:
        return False
    return True


def append(path: Path | str, record: dict, *, at: str) -> dict:
    """追加一条记录。``at`` 必填且必须来自调用方。

    返回落账后的完整记录（含 ``at`` 与 ``prev_record_sha256``）。
    """
    path = Path(path)
    if not at:
        raise LedgerError("AT_REQUIRED", "写入时刻 at 必须显式传入，不接受空值")
    if "at" in record:
        raise LedgerError("AT_IN_PAYLOAD", "记录里不得自带 at；写入时刻只能由调用方传入")
    if "prev_record_sha256" in record:
        raise LedgerError("PREV_IN_PAYLOAD", "prev_record_sha256 由账本层写入，调用方不得预置")

    if path.exists():
        if not tail_parseable(path):
            raise LedgerError("LEDGER_TAIL_BAD", f"{path} 尾部不是合法 JSON，拒绝继续追加")
        prev = entry_sha256(_lines(path)[-1])
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        prev = None

    full = {"at": at, **record, "prev_record_sha256": prev}
    line = json.dumps(full, ensure_ascii=False)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")
    return full


def verify_chain(path: Path | str = DEFAULT_LEDGER) -> dict:
    """只读校验哈希链。返回 ``{"ok": bool, "count": int, "problems": [...]}``。"""
    path = Path(path)
    problems: list[dict] = []
    lines = _lines(path)
    prev = None
    for idx, line in enumerate(lines, 1):
        digest = entry_sha256(line)
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append({"line": idx, "problem": "not_json", "detail": str(exc)})
            prev = digest
            continue
        if entry.get("prev_record_sha256") != prev:
            problems.append({
                "line": idx,
                "problem": "prev_hash_mismatch",
                "expected": prev,
                "found": entry.get("prev_record_sha256"),
            })
        prev = digest
    return {"ok": not problems, "count": len(lines), "problems": problems,
            "head_sha256": prev}
