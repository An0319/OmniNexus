"""Append one event to phase0/batch1.record.runs.jsonl.

只追加：既有字节从不重写。`--at` 必须显式传入，没有默认值，因此不会把
「当前时间」悄悄当成写入时刻。追加前默认校验文件尾部可解析，防止在坏账本
上继续堆行。

用法（在仓库根目录执行）：
  python phase0/append_batch1_ledger.py --at 2026-11-07T09:10:02Z \
      --payload '{"event": "verification_rerun", "counts_as_attempt": false}'
  python phase0/append_batch1_ledger.py --at ... --payload-file tmp.json --no-tail-check
"""
import argparse
import json
import sys
from pathlib import Path

LEDGER = Path("phase0/batch1.record.runs.jsonl")


def tail_parseable(path: Path) -> bool:
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return True
    try:
        json.loads(lines[-1])
    except json.JSONDecodeError:
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", required=True,
                    help="写入时刻，ISO-8601 UTC；必须显式传入，无默认值")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--payload", help="一条事件的 JSON 对象字符串")
    src.add_argument("--payload-file", help="含一条事件 JSON 对象的文件")
    ap.add_argument("--no-tail-check", action="store_true",
                    help="跳过「文件尾部可解析」校验")
    a = ap.parse_args()

    if not LEDGER.exists():
        print(f"ledger missing: {LEDGER}", file=sys.stderr)
        return 2
    raw = a.payload if a.payload is not None else Path(a.payload_file).read_text(encoding="utf-8")
    try:
        entry = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"payload is not valid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(entry, dict) or not entry.get("event"):
        print("payload must be an object with a non-empty 'event'", file=sys.stderr)
        return 2
    if "at" in entry:
        print("payload must not carry 'at'; pass it explicitly via --at", file=sys.stderr)
        return 2
    if not a.no_tail_check and not tail_parseable(LEDGER):
        print("existing ledger tail is not parseable; refuse to append", file=sys.stderr)
        return 2

    ev = entry.pop("event")
    record = {"event": ev, "at": a.at, **entry}
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print("appended:", json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
