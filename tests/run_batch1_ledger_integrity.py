"""批次一过程账本的只读完整性校验。

账本 `phase0/batch1.record.runs.jsonl` 只追加不覆写；本脚本只读，永不写入。
两项检查：
  1. 每一行都是合法 JSON 对象（坏行会让账本失去可审计性）；
  2. 可选回归校验：前 N 行字节未被改动（追加之后旧行必须逐字节不变）。

运行（仓库根目录）：
  python tests/run_batch1_ledger_integrity.py
  python tests/run_batch1_ledger_integrity.py --prefix-lines 9
  python tests/run_batch1_ledger_integrity.py --prefix-lines 9 --prefix-sha256 <hex>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "phase0" / "batch1.record.runs.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix-lines", type=int, default=0,
                    help="只校验前 N 行的字节哈希")
    ap.add_argument("--prefix-sha256", default="",
                    help="与前 N 行字节哈希比对（需配合 --prefix-lines）")
    a = ap.parse_args()

    if not LEDGER.exists():
        print(f"[FAIL] ledger missing: {LEDGER}")
        return 1
    raw = LEDGER.read_bytes()
    lines = raw.splitlines(keepends=True)
    lines = [ln for ln in lines if ln.strip()]

    bad = []
    for i, ln in enumerate(lines, 1):
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError as exc:
            bad.append(f"line {i}: {exc}")
            continue
        if not isinstance(obj, dict) or not obj.get("event"):
            bad.append(f"line {i}: not an object with 'event'")

    full = hashlib.sha256(raw).hexdigest()
    print(f"file={LEDGER}")
    print(f"lines={len(lines)} bytes={len(raw)}")
    print(f"sha256={full}")
    print(f"json_objects_ok={len(lines) - len(bad)}/{len(lines)}")
    for b in bad:
        print(f"  [FAIL] {b}")

    rc = 0 if not bad else 1
    if a.prefix_lines:
        if a.prefix_lines > len(lines):
            print(f"[FAIL] --prefix-lines {a.prefix_lines} exceeds file lines {len(lines)}")
            return 1
        prefix = b"".join(lines[:a.prefix_lines])
        ph = hashlib.sha256(prefix).hexdigest()
        print(f"prefix_lines={a.prefix_lines} prefix_sha256={ph}")
        if a.prefix_sha256:
            ok = ph.lower() == a.prefix_sha256.lower()
            print(f"[{'PASS' if ok else 'FAIL'}] prefix bytes unchanged")
            if not ok:
                rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
