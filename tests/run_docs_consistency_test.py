# -*- coding: utf-8 -*-
"""文档一致性守卫（最小版）：把"同一事实多副本漂移"变成 CI 红灯。

范围：docs/*.md + 产品详细概念.md（历史存档也扫，防止旧口径被当成现状）。
不扫：临时文件-*（工作底稿）、AGENTS.md（正文本身列出被禁措辞）、design-system/（Figma 生成物）。

规则（每条都对应一次真实踩坑）：
  LINK  相对链接必须指向存在的文件（docs 结构重整后不留断链）
  M3    禁止过期排期措辞「M3 后 / M3 之后 / M3 上线」，除非同行写明已取消或禁止
  REPORT 「报告生成器」不得被称作导出物/导出器，除非同行明确否定
  ARCH  禁止修订考古句（已同步删除 / 此前为 / 修正 § / 本次修订）
  T2    同一行出现 T2 与 55%、1.2 时，必须标注为历史假设或禁止重算

运行：python tests/run_docs_consistency_test.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = sorted((ROOT / "docs").glob("*.md")) + [ROOT / "产品详细概念.md"]

FAILS = []
COUNTS = {"LINK": 0, "M3": 0, "REPORT": 0, "ARCH": 0, "T2": 0}


def fail(rule, path, lineno, line, why):
    COUNTS[rule] += 1
    rel = path.relative_to(ROOT)
    FAILS.append(f"[{rule}] {rel}:{lineno} {why} :: {line.strip()[:100]}")


LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
M3 = re.compile(r"M3\s*(?:后|之后|上线)")


def check_links(path, lines):
    for lineno, line in enumerate(lines, 1):
        for raw in LINK.findall(line):
            target = raw.strip().split("#", 1)[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:", "file:")):
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                fail("LINK", path, lineno, line, f"链接目标不存在: {target}")


def check_rules(path, lines):
    for lineno, line in enumerate(lines, 1):
        if M3.search(line) and not any(k in line for k in ("已取消", "~~", "不得")):
            fail("M3", path, lineno, line, "出现过期 M3 排期措辞且未标注取消")

        if "报告生成器" in line and ("导出物" in line or "导出器" in line):
            if not any(k in line for k in ("不是", "不借")):
                fail("REPORT", path, lineno, line, "报告生成器被误称为导出物/导出器")

        for phrase in ("已同步删除", "此前为", "修正 §", "本次修订"):
            if phrase in line:
                fail("ARCH", path, lineno, line, f"修订考古句: {phrase}")

        if "T2" in line and "55%" in line and "1.2" in line:
            if not any(k in line for k in ("假设", "未执行", "§J", "不得", "从未执行", "不构成失败")):
                fail("T2", path, lineno, line, "T2 口径未标注为历史假设或禁止重算")


total_lines = 0

for path in TARGETS:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    total_lines += len(lines)
    check_links(path, lines)
    check_rules(path, lines)

print(f"扫描 {len(TARGETS)} 个文档，共 {total_lines} 行")
print("规则命中：" + "  ".join(f"{k}={v}" for k, v in COUNTS.items()))

if FAILS:
    print("\n== 失败 ==")
    for item in FAILS:
        print("  " + item)
    print(f"\n共 {len(FAILS)} 处违规：文档漂移必须当场修复，不允许带病提交。")
    sys.exit(1)

print("\n全部通过：链接完整、无 M3 残留、报告生成器口径一致、无修订考古句、T2 口径有标注。")
