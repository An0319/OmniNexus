"""把功效曲线结果**追加**到 `control_results.md`（探索性沙箱，非预注册）。

读取 `power_summary.json`（由 `run_power.py` 写出），只追加 §7，不改 v1/v2 既有段落。
幂等：文档里已有 `## 7. 功效曲线` 时不再写入。

用法（仓库根目录，需先跑完 run_power.py）：
  python phase0/controls/run_power_report.py
"""
from __future__ import annotations

import json
from pathlib import Path

PHASE0 = Path(__file__).resolve().parent.parent
DOC = PHASE0 / "controls" / "control_results.md"
SUMMARY = PHASE0 / "controls" / "power_summary.json"
MARK = "## 7. 功效曲线"

# 只读引用，不参与判定：批次一临床两段的固定线，用于「排除了多大」的对照
CLINICAL_VAL_PEAK = 0.2035


def _line(name: str, obj: dict) -> str:
    if obj["value"] is None:
        return f"- {name}：{obj['note']}"
    return f"- {name}：`r = {obj['value']:.2f}`（{obj['note']}）"


def _v(obj: dict) -> str:
    return f"{obj['value']:.4f}" if obj.get("value") is not None else "网格外（高于 0.50）"


def main() -> int:
    text = DOC.read_text(encoding="utf-8")
    if MARK in text:
        print("功效曲线已追加过，未重复写入")
        return 0
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    reps = s["reps"]
    curve = s["curve"]

    se = 100 * 0.5 / (reps ** 0.5)  # 每格检出率的二项标准误上界（p=0.5）
    lines = [
        "",
        MARK + "（2026-11-07 追加）",
        "",
        "### 7.1 口径",
        "",
        "- **注入式模拟，不是解析近似**：领先序列取真实 WTI 原油周收益率连续块，噪声取真实",
        "  零售汽油周收益率圆周远平移（距离 ≥ 26 周）后的同长片段，按"
        " `lag = r·lead[t-3] + sqrt(1-r²)·noise·(sd_lead/sd_noise)` 混合；"
        "注入滞后 `k0 = 3`（窗口 `[1,8]` 与先验带 `[2,6]` 之内）。",
        "- 每段仍走同一处理链与同一把尺子（`ruler.measure`：52 周滚动 z、段内配对、"
        "循环平移零分布、块自助 95% 区间），判定按 v2 每段 `2.5%`。",
        "- 模拟段量级对齐批次一：段跨度取 296/104 周，峰值处的实际配对行数约 `n≈293` / `n≈101`"
        "（批次一在 `k=11/13` 处是 `285/91`，同量级）；`r` 网格 "
        "`0.10..0.50` 步长 `0.05`，每格 `{}` 次重复。".format(reps),
        "- 两种口径并列：主口径按跑前写定的远平移（7.3 前三组数）；同时列出 v2 部署判据的"
        "严格双版（全+远同时 `≤ 2.5%`）。设计 §2.3 曾在开跑前判断「全平移版在短块上结构上"
        "不可达」（当时单块实测 `13/363 ≈ 3.6%`）；全网格跑完后该判断不成立——随机化块起点后，"
        "部分实现的 `p_all` 可 `≤ 2.5%`，训练段严格双版检出率与远平移版几乎相同，验证段约为其一半。"
        "真实对照序列长 1450–2129 周，近平移占比 < 1%，部署口径在真实数据上更接近远平移版。",
        "- 每次重复是一个独立实现：领先块起点在可用历史内随机、汽油噪声的圆周平移量随机"
        "（均落在 `dist ≥ 26` 的远平移区），二者随 `(r, rep)` 变化。首轮实现把这两样都固定、"
        "只换自助种子，60 次重复实为同一实现（检出率退化成 0/100 阶跃），作废并修正后重跑；"
        "这是实现与「60 次重复」口径不符的修正，不涉及判定条件。",
        "- 每格 `{}` 次重复，检出率的二项标准误最大约 ±{:.1f} 个百分点；"
        "检出线由 9 点网格线性内插，网格外交代的就地注明，不外推。".format(reps, se),
        "",
        "### 7.2 曲线（远平移口径为主；严格双版并列）",
        "",
        "| `r` | 训练 `n`（中位） | 训练实测 `k0` | 训练检出率 | 验证 `n`（中位） | 验证实测 `k0` | 验证检出率 | 两段同向并存 | 训练（严格双版） | 验证（严格双版） |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in curve:
        lines.append(
            f"| {c['r']:.2f} | {c['peak_n_train']:.0f} | {c['realized_k0_train']:+.3f} "
            f"| {c['train']*100:.0f}% "
            f"| {c['peak_n_valid']:.0f} | {c['realized_k0_valid']:+.3f} "
            f"| {c['validation']*100:.0f}% "
            f"| {c['both_same_dir']*100:.0f}% "
            f"| {c['train_strict']*100:.0f}% | {c['validation_strict']*100:.0f}% |")
    lines += [
        "",
        f"注入是否生效：每格在 `k0=3` 处的实测相关中位数见 7.2 表（全体 `realized_k0_median = "
        f"{s['realized_k0_median']:+.3f}`）。逐格值应接近名义 `r`；偏离说明该段的噪声与领先序列"
        "仍有残余相关（真实原油与汽油共享宏观因子），此时实际注入强度高于名义值，读表时应以"
        "「实测 `k0`」列为准，而不是把 `r` 当作已实现的强度。",
        "",
        "### 7.3 检出线（四个数，远平移口径为跑前主口径）",
        "",
        _line("训练段（`n≈293`，批次一 285）的 80% 检出线", s["r80_train"]),
        _line("训练段（`n≈293`，批次一 285）的 50% 检出线", s["r50_train"]),
        _line("验证段（`n≈101`，批次一 91）的 80% 检出线", s["r80_validation"]),
        _line("验证段（`n≈101`，批次一 91）的 50% 检出线", s["r50_validation"]),
        "",
        "同一网格、按 v2 部署判据（全+远同时 `≤ 2.5%` 且区间不含 0）的对应线：",
        _line("训练段（`n≈293`）的 80% 检出线（严格）", s["r80_train_strict"]),
        _line("训练段（`n≈293`）的 50% 检出线（严格）", s["r50_train_strict"]),
        _line("验证段（`n≈101`）的 80% 检出线（严格）", s["r80_validation_strict"]),
        _line("验证段（`n≈101`）的 50% 检出线（严格）", s["r50_validation_strict"]),
        "",
        "### 7.4 用途与边界",
        "",
        "今天临床验证段峰值为 `0.2035`（批次一固定线，未重算、未改动）。把本曲线的"
        f"验证段检出线与它并排：远平移 80% 线 `{_v(s['r80_validation'])}`、50% 线 "
        f"`{_v(s['r50_validation'])}`；严格双版 80% 线 `{_v(s['r80_validation_strict'])}`、"
        f"50% 线 `{_v(s['r50_validation_strict'])}`。`0.2035` 低于全部四条线：本批「看不见」"
        "能翻译出的排除上限很弱——在本批尺寸下，`0.20` 量级的真实关系被检出的概率不到五成"
        "（7.2 表 `r=0.20` 一行可读具体值）。因此未检出既不等价于 `0.2035` 不存在，"
        "也不足以排除它；要把「排除 ≥ r」说成强结论，`r` 至少要到上述 80% 线。",
        "",
        "本条只给模拟边界，不改批次一的判定线，也不把否定结论升级成「不存在」。",
        "",
        "### 7.5 局限（必须与数字一起读）",
        "",
        "- 混合后序列的边际不再逐点等于原汽油收益率（两条近似正态序列的线性组合）；"
        "不用分位重排是因为重排会毁掉零分布赖以成立的序列自相关。曲线是**近似但自洽**"
        "的注入式模拟。",
        "- 模拟块短，全/远两版的差别在本网格里比开跑前的预估小（见 7.1）：严格双版的代价主要"
        "落在验证段（检出率约为远平移版的一半），真实长序列上这一差距会进一步缩小。",
        f"- 每格 `{reps}` 次重复，曲线在两条相邻网格点之间可能有 ±{se:.1f} 个百分点量级的抖动；"
        "检出线用线性内插，不宣称精度高于网格步长 `0.05`。",
        "- 逐次重复的原始记录 `power_raw.jsonl` 仅本地留存，不作为对外证据；"
        "仓库内保留 `power_summary.json` 与本脚本。",
        "",
    ]
    with DOC.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("§7 已追加")
    for key in ("realized_k0_median", "r80_train", "r50_train", "r80_validation",
                "r50_validation", "r80_train_strict", "r80_validation_strict"):
        print(key, s[key])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
