# -*- coding: utf-8 -*-
"""依赖方向守卫（架构审计 F2）：生产层禁止 import phase0。

规则：依赖单向——phase0（探索层）可以引 omninexus（内核），
生产层（omninexus/ tools/ scripts/）不得反向引 phase0。
发现即退出码 1（响亮失败）。工程修订，不消耗尝试预算。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("omninexus", "tools", "scripts")
PATTERN = re.compile(r"^\s*(?:from|import)\s+phase0\b", re.MULTILINE)


def main() -> int:
    hits = []
    for d in SCAN_DIRS:
        for py in (ROOT / d).rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            for m in PATTERN.finditer(text):
                line_no = text[:m.start()].count("\n") + 1
                hits.append(f"{py.relative_to(ROOT)}:{line_no}: {m.group(0).strip()}")
    if hits:
        print("依赖方向违规（生产层 import phase0）：")
        for h in hits:
            print(" ", h)
        return 1
    print(f"依赖方向守卫通过：{', '.join(SCAN_DIRS)} 无 phase0 import")
    return 0


if __name__ == "__main__":
    sys.exit(main())
