"""视图层单元测试：引号剥离、主句切分、10 条抽样映射。

用法：
    python tests/run_view_filter_test.py

覆盖 view_filter_definition_zh.md §2 与 §5 的两处高风险：
- 引号剥离必须覆盖《》「」""（）及嵌套；只剥《》会让第 7 条翻成「是」。
- 多动作标题必须取主句（「进展暨…」「…并…」），且不能把并购/合并/并网切开。

只测规则集数据驱动的判定，不重算任何指标，不改标签。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "phase0" / "timeline"))

from timeline import compute_view, load_ruleset, main_clause, strip_quoted  # noqa: E402

RS = load_ruleset("zh")
PAIRS = RS.view["quote_pairs"]
CHECKS = 0


def eq(got, want, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if got != want:
        raise AssertionError(f"{label}\n  want={want!r}\n  got ={got!r}")


def strip(title: str) -> str:
    return strip_quoted(title, PAIRS)


def test_strip_quoted() -> None:
    # 《》——第 1、7 条的动作只在这里面
    eq("收购" in strip("珠免集团：关于《珠海珠免集团股份有限公司收购报告书》之法律意见书"), False, "《》剥除")
    # 嵌套：《…（…）…》
    eq("收购" in strip("甲公司：关于《乙公司（收购）报告书》之意见"), False, "《》内嵌（）")
    # 「」
    eq("收购" in strip("甲公司：「拟收购」事项说明"), False, "「」剥除")
    # 中文双引号
    eq("并购" in strip("“科创板八条”以来并购交易达244单"), True, "“”只剥引号内，引号外保留")
    # 括号里再套引号
    eq(strip("公司（以下简称“公司”）收购A"), "公司收购A", "（）内嵌“”")
    # 未配对的半截引号不吞掉整句外的内容（开头就有闭合符）
    eq("并购" in strip("“科创板八条”以来并购重组"), True, "闭合后继续保留")


def test_main_clause() -> None:
    eq(
        main_clause("关于现金收购A公司50%股权进展暨完成工商变更登记的公告", RS),
        "关于现金收购A公司50%股权进展",
        "「暨」切分",
    )
    eq(main_clause("签署协议并完成交割", RS), "签署协议", "「并」切分")
    eq(main_clause("并购重组活力提升", RS), "并购重组活力提升", "并购不切")
    eq(main_clause("合并报表范围变更", RS), "合并报表范围变更", "合并不切")
    eq(main_clause("光伏电站并网发电", RS), "光伏电站并网发电", "并网不切")
    eq(main_clause("拟收购A并出售B", RS), "拟收购A", "「并」在动作之间切")
    eq(main_clause("完成交割；另行公告", RS), "完成交割", "；切分")


def test_ten_samples() -> None:
    cases = [
        (
            "珠免集团",
            "珠免集团：北京市嘉源律师事务所关于《珠海珠免集团股份有限公司 收购 报告书》之法律意见书",
            ("否", "否", "needs_source_doc"),
        ),
        (
            "建研院",
            "建研院：东莞证券股份有限公司关于江苏瀚启投资有限公司要约 收购 苏州市建筑科学研究院集团股份有限公司之独立财务顾问报告",
            ("是", "是", ""),
        ),
        (
            "建研院",
            "建研院：关于江苏瀚启投资有限公司要约 收购 公司股份的第一次提示性公告",
            ("是", "否", "notice_only"),
        ),
        (
            "银星能源",
            "银星能源：关于现金 收购 宁夏天净神州风力发电有限公司50%股权进展暨完成工商变更登记的公告",
            ("是", "否", "progress_only"),
        ),
        (
            "ABB以26.5亿美元",
            "加码数据中心冷却市场，ABB以26.5亿美元收购德国风机龙头施乐百",
            ("是", "是", ""),
        ),
        (
            "上海誉升要约",
            "艾艾精工：上海誉升要约收购期限届满 股票明起复牌",
            ("是", "是", ""),
        ),
        (
            "山鹰国际",
            "山鹰国际：北京博星证券投资顾问有限公司关于《山鹰国际控股股份公司要约 收购 报告书摘要》之财务顾问意见",
            ("否", "否", "needs_source_doc"),
        ),
        (
            "泽宇智能",
            "泽宇智能：关于现金 收购 智联新能电力科技有限公司51%股权进展暨交易对方完成增持公司股份的公告",
            ("是", "否", "progress_only"),
        ),
        (
            "科创板八条”以来",
            "“科创板八条”以来并购交易达244单 科创板并购重组活力稳步提升",
            ("判不了", "否", "aggregate"),
        ),
        (
            "泉阳泉",
            "泉阳泉：东北证券股份有限公司关于吉林泉阳泉股份有限公司变更部分募集资金投向用于 收购 控股子公司少数股权项目的核查意见",
            ("是", "是", ""),
        ),
    ]
    for i, (subject, title, want) in enumerate(cases, 1):
        v = compute_view(title, subject, RS)
        got = (v["self_contained"], v["increment"], v["reason"])
        eq(got, want, f"抽样第 {i} 条")


def test_explicit_undecidable() -> None:
    # 动作在引号外，但对象只剩体裁尾巴 → 必须显式「判不了」，不许用「否」代替
    v = compute_view("甲公司：关于收购事项的公告", "甲公司", RS)
    eq(v["self_contained"], "判不了", "对象不可指认 → 判不了")
    eq(v["reason"], "needs_source_doc", "判不了落 needs_source_doc")
    # 动作只在引号里 → 自足否，不是判不了
    v = compute_view("甲公司：关于《收购报告书》之法律意见书", "甲公司", RS)
    eq((v["self_contained"], v["increment"]), ("否", "否"), "引号内动作 → 否")


def main() -> int:
    test_strip_quoted()
    test_main_clause()
    test_ten_samples()
    test_explicit_undecidable()
    print(f"[OK] 视图层 {CHECKS} 项断言全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
