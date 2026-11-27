# -*- coding: utf-8 -*-
"""tests/check_workflow_paths.py —— 检查 workflow 的 push.paths 是否漏了它自己调用的脚本。

为什么要有这条：2026-11-27 改 `tools/daily_sentinel.py` 没有触发任何 CI，
因为 `daily-update.yml` 的 `push.paths` 只列了两个文件。清单是手写的，手写就会漏，
漏了不会报错，只会静默少跑一次验证。本脚本把这条清单变成可执行检查：

    扫描每个 workflow 的 run 步骤 → 找出它调用的 tools/*.py
    → 与同一个 workflow 的 on.push.paths 做差集 → 缺了就失败并给出要补的那一行

不误报的两条规则：
  1. 没有 `on.push.paths` 的 workflow 视为「不限制路径」，直接跳过
     （本脚本自己被 validate.yml 调用，validate.yml 就不写 paths）。
  2. paths 支持 glob（如 `tools/**`），用 fnmatch 判断是否覆盖。

用法：
    python tests/check_workflow_paths.py                     # 检查仓库内全部 workflow
    python tests/check_workflow_paths.py --workflows-dir DIR # 指定目录（用于反例验证）
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / ".github" / "workflows"

# 只认 tools/ 下的脚本：其余（omninexus/、scripts/）故意不管，避免本检查自己扩大范围
SCRIPT_RE = re.compile(r"(tools/[A-Za-z0-9_\-./]+\.py)")


def _on_push_paths(doc: dict) -> list[str] | None:
    """取 on.push.paths。PyYAML 会把顶层 `on:` 解析成布尔 True，这里两种都认。"""
    on = doc.get("on", doc.get(True))
    if not isinstance(on, dict):
        return None
    push = on.get("push")
    if not isinstance(push, dict):
        return None
    paths = push.get("paths")
    if paths is None:
        return None
    if isinstance(paths, str):
        return [paths]
    return [str(p) for p in paths]


def _run_scripts(doc: dict) -> set[str]:
    found: set[str] = set()
    jobs = doc.get("jobs") or {}
    for job in jobs.values():
        for step in (job or {}).get("steps") or []:
            cmd = step.get("run") if isinstance(step, dict) else None
            if not isinstance(cmd, str):
                continue
            for m in SCRIPT_RE.finditer(cmd):
                found.add(m.group(1).rstrip(".,;"))
    return found


def _covered(script: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(script, p) or p == script for p in patterns)


def check_dir(wf_dir: Path) -> tuple[list[str], int, int]:
    """返回 (错误信息, 检查的 workflow 数, 跳过的 workflow 数)。"""
    errors: list[str] = []
    checked = skipped = 0
    for f in sorted(list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml"))):
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            errors.append(f"{f.name}：YAML 解析失败：{e}")
            continue
        paths = _on_push_paths(doc)
        if paths is None:
            skipped += 1
            continue
        checked += 1
        for script in sorted(_run_scripts(doc)):
            if not _covered(script, paths):
                errors.append(
                    f"{f.name} 调用了 {script}，但 on.push.paths 未包含，补上这一行：\n"
                    f'      - "{script}"')
    return errors, checked, skipped


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflows-dir", default=str(DEFAULT_DIR))
    args = ap.parse_args(argv)

    wf_dir = Path(args.workflows_dir)
    if not wf_dir.is_dir():
        print(f"[paths] 目录不存在：{wf_dir}", flush=True)
        return 2
    errors, checked, skipped = check_dir(wf_dir)
    if errors:
        print("[paths] 失败：以下 workflow 的触发清单与实际调用不一致", flush=True)
        for e in errors:
            print("  ✗ " + e, flush=True)
        print(f"\n[paths] 已检查 {checked} 个带 paths 的 workflow，跳过 {skipped} 个不限路径的",
              flush=True)
        return 1
    print(f"[paths] 通过：{checked} 个带 paths 的 workflow 全部覆盖其调用的 tools 脚本"
          f"（跳过 {skipped} 个无 paths 的）", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
