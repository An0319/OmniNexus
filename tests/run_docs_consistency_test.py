# -*- coding: utf-8 -*-
"""文档一致性守卫（最小版）：把"同一事实多副本漂移"变成 CI 红灯。

范围：作者本地的私有设计文档（不随本仓库分发；历史存档也扫，防止旧口径被当成现状）。
边界：目标缺失时本守卫显式跳过并打印原因，不静默通过（本机存在时照常全量扫描，纪律不变）。
不扫：临时文件-*（工作底稿）、AGENTS.md（正文本身列出被禁措辞）。

规则（每条都对应一次真实踩坑）：
  LINK  相对链接必须指向存在的文件（docs 结构重整后不留断链）
  M3    禁止过期排期措辞「M3 后 / M3 之后 / M3 上线」，除非同行写明已取消或禁止
  REPORT 「报告生成器」不得被称作导出物/导出器，除非同行明确否定
  ARCH  禁止修订考古句（已同步删除 / 此前为 / 修正 § / 本次修订）
  T2    同一行出现 T2 与 55%、1.2 时，必须标注为历史假设或禁止重算
  POS   已退役的「套利引擎 / 实时预期差 / 信号」口径不得以**宣称句式**出现（2026-11-07 改为语义匹配：
        只拦「我们提供 / 本产品输出 X」这类现在时断言；「不得使用 X / 不采用 X / 已退役」这类约束句式放行，
        按分句判定，避免同一行前半否定、后半又宣称的情况被整行豁免）
        （产品详细概念.md＝历史存档、复盘-产品定位漂移.md＝事件记录，两文件豁免）

运行：python tests/run_docs_consistency_test.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [p for p in sorted((ROOT / "docs").glob("*.md")) + [ROOT / "产品详细概念.md"]
           if p.exists()]

FAILS = []
COUNTS = {"LINK": 0, "M3": 0, "REPORT": 0, "ARCH": 0, "T2": 0, "POS": 0}


def fail(rule, path, lineno, line, why):
    COUNTS[rule] += 1
    rel = path.relative_to(ROOT)
    FAILS.append(f"[{rule}] {rel}:{lineno} {why} :: {line.strip()[:100]}")


LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
M3 = re.compile(r"M3\s*(?:后|之后|上线)")
POS_TERMS = re.compile(r"跨域信息套利引擎|套利引擎|实时预期差|信号引擎|买卖信号|信号推送|信号")
POS_EXEMPT = {"产品详细概念.md", "复盘-产品定位漂移.md"}
POS_OK = ("历史", "退役", "不采用", "假设", "早期", "未实现", "旧叙事")
# 宣称句式：动词在前，术语在后（我们提供 X / 本产品主打 X / 核心是 X）
POS_ASSERT = re.compile(
    r"(?:提供|输出|主打|售卖|销售|支持|具备|承诺|推送|发放|作为产品|作为卖点|核心是|就是)"
    r"[^。；\n]{0,15}?(?:跨域信息套利引擎|套利引擎|实时预期差|信号引擎|买卖信号|信号推送|信号)"
)
# 宣称句式（反向）：术语在前，定性在后（X 是我们的定位 / X 是卖点）
POS_ASSERT_REV = re.compile(
    r"(?:跨域信息套利引擎|套利引擎|实时预期差|信号引擎|买卖信号|信号推送)"
    r"[^。；\n]{0,10}?(?:是我们的|是产品|是卖点|是核心|是定位|服务|产品功能)"
)
# 约束句式：出现任一标记即视为"禁用/退役/否定"语境，本分句放行
POS_CONSTRAINT = re.compile(
    r"不得|禁止|禁用|不采用|不以|不使用|不提供|不输出|不承诺|不做|不是|非|从未|未曾|退役|历史|旧叙事|豁免"
)
# 主语：只有"我们/本产品/平台/产品"这类自述主体才算产品宣称
POS_SUBJECT = re.compile(r"我们|本产品|本工具|本公司|我们的产品|平台|产品")
# 元语言：描述守卫规则本身的句子（拦/白名单/规则…）不算宣称，但同句有主语时仍算
POS_META = re.compile(r"拦|白名单|守卫|正则|规则|匹配")


def pos_violation(clause):
    """按分句判定：约束句式放行；描述规则本身的分句放行；其余看宣称句式。"""
    if POS_CONSTRAINT.search(clause):
        return False
    if POS_META.search(clause) and not POS_SUBJECT.search(clause):
        return False
    return bool(POS_ASSERT.search(clause) or POS_ASSERT_REV.search(clause))


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

        if path.name not in POS_EXEMPT and POS_TERMS.search(line):
            for clause in re.split(r"[。；]", line):
                if POS_TERMS.search(clause) and pos_violation(clause):
                    fail("POS", path, lineno, line, "已退役的套利/实时预期差/信号口径以宣称句式出现")
                    break


if not TARGETS:
    print("跳过：私有设计文档未随本仓库分发（本地不存在）。")
    sys.exit(0)

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

print("\n全部通过：链接完整、无 M3 残留、报告生成器口径一致、无修订考古句、T2 口径有标注、无套利口径回流。")
