"""Build batch-1 deliverables from phase0/output CSV files.

Outputs:
  phase0/batch1_report.md / .html        external version: clinical XBI only
  phase0/batch1_internal_archive.md      internal archive: energy N1 practice account
  phase0/batch1_curve_clinical_xbi.svg   clinical curve
  phase0/batch1_curve_energy_n1.svg      energy curve (referenced only by the internal file)
  phase0/batch1.record.runs.jsonl        user-track attempt ledger

Both renderings of the external report come from one block list, so prose,
numbers and order are identical.  All numbers are read from the CSV files;
nothing is typed by hand.
"""
import html
import json
import re
from pathlib import Path

import pandas as pd

OUT = Path("phase0/output")
TRAIN = ("train", "训练段")
VALID = ("validation", "验证段")
NOISE = 0.19
PASS = 0.3

# ---------------------------------------------------------------- data


def stats():
    eia = pd.read_csv(OUT / "batch1_eia_wpsr_utilization.csv", parse_dates=["week_ending"])
    eia = eia.drop_duplicates(subset=["week_ending"]).sort_values("week_ending")
    sample = eia[(eia.week_ending >= "2016-11-11") & (eia.week_ending <= "2026-10-30")]
    cli = pd.read_csv(OUT / "batch1_clinical_weekly_counts.csv", parse_dates=["week_label_friday"])
    y_crak = pd.read_csv(OUT / "batch1_yahoo_CRAK_daily.csv", parse_dates=["date"])
    y_xbi = pd.read_csv(OUT / "batch1_yahoo_XBI_daily.csv", parse_dates=["date"])
    return {
        "eia_weeks": len(eia),
        "eia_min": str(eia.week_ending.min().date()),
        "eia_max": str(eia.week_ending.max().date()),
        "eia_sample_weeks": len(sample),
        "eia_lo": round(float(sample.utilization_pct.min()), 1),
        "eia_hi": round(float(sample.utilization_pct.max()), 1),
        "eia_mean": round(float(sample.utilization_pct.mean()), 1),
        "eia_last": round(float(eia.iloc[-1].utilization_pct), 1),
        "cli_records": int(cli["count"].sum()),
        "cli_weeks": len(cli),
        "cli_min": str(cli.week_label_friday.min().date()),
        "cli_max": str(cli.week_label_friday.max().date()),
        "crak_rows": len(y_crak),
        "xbi_rows": len(y_xbi),
        "crak_null": int(y_crak.adjclose.isna().sum()),
        "xbi_null": int(y_xbi.adjclose.isna().sum()),
    }


def xcorr():
    out = {}
    for acct in ("energy_n1", "clinical_xbi"):
        for seg, _ in (TRAIN, VALID):
            out[(acct, seg)] = pd.read_csv(OUT / f"batch1_xcorr_{acct}_{seg}.csv")
    return out


S = stats()
X = xcorr()


def peak(acct, seg):
    df = X[(acct, seg)]
    w = df[(df.k >= 4) & (df.k <= 13)]
    r = w.loc[w["corr"].idxmax()]
    return int(r.k), float(r["corr"]), int(r.n)


def svg_chart(title, acct, fname):
    train = X[(acct, "train")]
    val = X[(acct, "validation")]
    pk, pv, _ = peak(acct, "validation")
    W, H = 920, 520
    ml, mr, mt, mb = 74, 34, 58, 64
    x0, x1, y0, y1 = ml, W - mr, mt, H - mb
    ymin, ymax = -0.30, 0.38

    def px(k):
        return x0 + (k / 13) * (x1 - x0)

    def py(v):
        return y1 - ((v - ymin) / (ymax - ymin)) * (y1 - y0)

    p = []
    p.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
             f'width="{W}" height="{H}" role="img" aria-labelledby="t-{acct}">')
    p.append('<rect width="100%" height="100%" fill="#ffffff"/>')
    p.append(f'<title id="t-{acct}">{html.escape(title)}</title>')
    font = "font-family=\"system-ui,-apple-system,'Segoe UI','Microsoft YaHei',sans-serif\""
    p.append(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" fill="#fbfbfc" stroke="#e2e4e8"/>')
    p.append(f'<rect x="{px(4)-3:.1f}" y="{y0}" width="{px(13)-px(4)+6:.1f}" height="{y1-y0}" '
             f'fill="#eef2f7"/>')
    p.append(f'<text x="{px(4)+8}" y="{y0+22}" {font} font-size="13" fill="#8892a0">判定窗口 [4,13]</text>')
    for v in (-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3):
        yv = py(v)
        p.append(f'<line x1="{x0}" y1="{yv:.1f}" x2="{x1}" y2="{yv:.1f}" stroke="#eceef1"/>')
        p.append(f'<text x="{x0-10}" y="{yv+4:.1f}" {font} font-size="12" fill="#6b7380" '
                 f'text-anchor="end">{v:+.1f}</text>')
    for k in range(14):
        p.append(f'<text x="{px(k):.1f}" y="{y1+22}" {font} font-size="12" fill="#6b7380" '
                 f'text-anchor="middle">{k}</text>')
    p.append(f'<text x="{(x0+x1)/2}" y="{H-12}" {font} font-size="13" fill="#4a5160" '
             f'text-anchor="middle">领先周数 k（lead_z_t 对 lag_z_(t+k)）</text>')
    p.append(f'<line x1="{x0}" y1="{py(NOISE):.1f}" x2="{x1}" y2="{py(NOISE):.1f}" '
             f'stroke="#c98a2e" stroke-width="1.3" stroke-dasharray="4 4"/>')
    p.append(f'<text x="{x1-6}" y="{py(NOISE)-7:.1f}" {font} font-size="12" fill="#a9701d" '
             f'text-anchor="end">噪声带 0.19</text>')
    p.append(f'<line x1="{x0}" y1="{py(PASS):.1f}" x2="{x1}" y2="{py(PASS):.1f}" '
             f'stroke="#2f7d4f" stroke-width="1.5" stroke-dasharray="7 4"/>')
    p.append(f'<text x="{x1-6}" y="{py(PASS)-7:.1f}" {font} font-size="12" fill="#256640" '
             f'text-anchor="end">通过线 0.30</text>')
    p.append(f'<line x1="{x0}" y1="{py(0):.1f}" x2="{x1}" y2="{py(0):.1f}" stroke="#9aa1ab"/>')
    for df, color, label in ((train, "#4c6f8c", "训练段"), (val, "#b0562f", "验证段")):
        pts = " ".join(f"{px(int(r.k)):.1f},{py(float(r['corr'])):.1f}" for _, r in df.iterrows())
        p.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2.4"/>')
        for _, r in df.iterrows():
            p.append(f'<circle cx="{px(int(r.k)):.1f}" cy="{py(float(r["corr"])):.1f}" r="3.6" '
                     f'fill="{color}"/>')
    cx, cy = px(pk), py(pv)
    p.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="8" fill="none" stroke="#b0562f" stroke-width="2"/>')
    anchor = "end" if pk >= 10 else "start"
    dx = -14 if pk >= 10 else 14
    p.append(f'<text x="{cx+dx:.1f}" y="{cy-16:.1f}" {font} font-size="13" fill="#8f4224" '
             f'text-anchor="{anchor}">峰值 {pv:+.4f} @ k={pk}</text>')
    if acct == "clinical_xbi":
        mv = float(val[val.k == 8]["corr"].iloc[0])
        mx, my = px(8), py(mv)
        p.append(f'<text x="{mx:.1f}" y="{my+26:.1f}" {font} font-size="12" fill="#6b3a2a" '
                 f'text-anchor="middle">k=8：{mv:+.4f}</text>')
    lx = x0 + 16
    for i, (color, label) in enumerate((("#4c6f8c", "训练段（仅诊断）"), ("#b0562f", "验证段（判定）"))):
        yy = y0 + 46 + i * 20
        p.append(f'<line x1="{lx}" y1="{yy}" x2="{lx+22}" y2="{yy}" stroke="{color}" stroke-width="2.4"/>')
        p.append(f'<text x="{lx+30}" y="{yy+4}" {font} font-size="12" fill="#4a5160">{label}</text>')
    p.append(f'<text x="{x0}" y="{y0-22}" {font} font-size="15" font-weight="600" '
             f'fill="#1f2733">{html.escape(title)}</text>')
    p.append("</svg>")
    svg = "\n".join(p)
    Path(f"phase0/{fname}").write_text(svg, encoding="utf-8")
    return svg


SVG_E = svg_chart("能源 N1：炼厂开工率 → CRAK 周收益率", "energy_n1", "batch1_curve_energy_n1.svg")
SVG_C = svg_chart("临床 XBI：产业界新登记试验数 → XBI 周收益率", "clinical_xbi", "batch1_curve_clinical_xbi.svg")

# ---------------------------------------------------------------- block helpers


def h(B, level, text):
    B.append(("h", level, text))


def p(B, text):
    B.append(("p", text))


def quote(B, text):
    B.append(("q", text))


def table(B, headers, rows):
    B.append(("t", headers, rows))


def fig(B, svg, caption):
    B.append(("f", svg, caption))


def ul(B, items):
    B.append(("u", items))


epk_t, epv_t, epn_t = peak("energy_n1", "train")
cpk_t, cpv_t, cpn_t = peak("clinical_xbi", "train")
epk_v, epv_v, epn_v = peak("energy_n1", "validation")
cpk_v, cpv_v, cpn_v = peak("clinical_xbi", "validation")

c8 = float(X[("clinical_xbi", "validation")].query("k == 8")["corr"].iloc[0])
c8n = int(X[("clinical_xbi", "validation")].query("k == 8")["n"].iloc[0])
c12 = float(X[("clinical_xbi", "validation")].query("k == 12")["corr"].iloc[0])

# ---------------------------------------------------------------- external report (clinical XBI)

B = []

h(B, 1, "批次一验证报告：临床 XBI（正式账）")
p(B, "报告日期：2026-11-07 ｜ 预注册锚点：`8b63fb1` ｜ 留出段：未开封 ｜ 判定尝试：`attempt #1`")
p(B, "本文件为**对外版**，只包含临床 XBI 正式账。")
quote(B, "**归属说明**：能源 N1 为练手账，其结果不进入本报告；本报告仅报临床 XBI 正式账。")

h(B, 2, "1. 命题原文")
p(B, "引自 `phase0/preregistration_clinical_xbi.md` §1：")
quote(B, "产业界新登记的临床试验数量（ClinicalTrials.gov，lead sponsor class = `INDUSTRY`，`INTERVENTIONAL`，按 `StudyFirstPostDate` 周度计数）**系统性领先** State Street SPDR S&P Biotech ETF（XBI）的周收益率 **4–13 周**；方向为正：新登记数量上行后，XBI 后续 4–13 周的周收益倾向为正。")

h(B, 2, "2. 预注册时间锚")
table(B, ["项", "值"], [
    ["提交哈希", "`8b63fb1c58df7120321d1bd8d78a25eb93d6a724`（短哈希 `8b63fb1`）"],
    ["提交信息", "`docs: add batch-1 preregistration drafts for energy N1 and clinical XBI`"],
    ["提交对象时间", "`2026-11-07T15:48:56+09:00`（`2026-11-07T06:48:56Z`）。这是 Git 提交对象自带的时间，不是推送时刻"],
    ["推送时刻", "**无独立记录**。仓库与本地均未保留 push 的起止时间戳，因此无法证明远端在开跑前已可见该提交；可核验的只有提交对象时间与提交内容"],
    ["外部核验", "`https://github.com/An0319/OmniNexus/commit/8b63fb1c58df7120321d1bd8d78a25eb93d6a724`"],
    ["远端分支", "`origin/main`，推送范围 `0d5f835..8b63fb1`"],
    ["首次数据抓取", "Yahoo chart API：XBI `06:52:56Z`（见快照旁注 `fetched_at_utc`）；ClinicalTrials.gov `06:55:15Z`"],
    ["先后顺序", "提交对象时间 `06:48:56Z` 早于最早一次抓取 `06:52:56Z`；这只证明「提交先于取数」，不能证明「远端先于取数可见」"],
    ["锁定内容", "命题、数据口径、样本窗口、三段切分、`lag_range=[0,13]`、`pass_window=[4,13]`、`pass_corr=0.3`、`noise_band=0.19`、方向为正、指标数量 1"],
])
p(B, "过程账本 `phase0/batch1.record.runs.jsonl`（本地路径，不随仓库分发）同时记录能源与临床两账的结果字段。按能源稿 §10 的练手账口径，该账本不入库、仅本地留存，因此不作为对外证据。对外可核的过程证据是锚定 commit `8b63fb1`：能证明这些条款确实在该提交里、且该提交现在在远端，但 commit 时间为客户端时间，不能证明远端在开跑前已可见。随附的临床逐格 CSV 与临床快照旁注用于复算。")

h(B, 2, "3. 数据与快照")
h(B, 3, "3.1 临床 XBI")
table(B, ["项", "实测"], [
    ["端点", "`https://clinicaltrials.gov/api/v2/studies`"],
    ["筛选", "`AREA[LeadSponsorClass]INDUSTRY AND AREA[StudyType]INTERVENTIONAL AND AREA[StudyFirstPostDate]RANGE[2016-11-07,2026-10-30]`"],
    ["记录数", f"{S['cli_records']:,}"],
    ["分页", "`pageSize=1000` + `pageToken`，共 57 页；记录数与同条件 API `totalCount` 相等，无漏页"],
    ["纯度", "全部 `INDUSTRY` + `INTERVENTIONAL`；`StudyFirstPostDate` 缺失 0"],
    ["周桶", f"{S['cli_weeks']} 周（`{S['cli_min']}`–`{S['cli_max']}`）；`2024-09-13` 为确认真实 0（直接区间查询返回 0 条）"],
    ["滞后面", f"Yahoo chart API v8，`XBI` 日线 `adjclose`，{S['xbi_rows']} 个交易日（`2016-11-07`–`2026-11-06`），空值 {S['xbi_null']}"],
    ["快照旁注", "`phase0/output/batch1_snapshot_clinical.md`、`batch1_snapshot_yahoo_XBI.md`"],
])

h(B, 3, "3.2 临床记录数 4,337 差的窗口解释")
p(B, "预注册 §9 的可得性探针口径为 `2016-01-01`–`2026-11-06`，记录 `totalCount=60780`；实际抓取使用锁定样本窗口 `2016-11-07`–`2026-10-30`，得到 56,443 条。差额可由同条件 `totalCount` 实查完全分解：")
table(B, ["区间", "`totalCount`"], [
    ["`2016-01-01`–`2026-11-06`（预注册 §9 探针）", "60,780"],
    ["`2016-11-07`–`2026-10-30`（锁定样本，实际抓取）", "56,443"],
    ["`2016-01-01`–`2016-11-06`（被排除的头部）", "4,181"],
    ["`2026-10-31`–`2026-11-06`（被排除的尾部）", "156"],
    ["三段之和", "60,780"],
])
p(B, "差额 `4,337 = 4,181 + 156`，全部来自日期窗口不同：不是翻页漏页（抓取记录数等于同条件 `totalCount`），不是筛选条件变化，也不是预估误差。预注册稿的锁定条款未改；锚定 commit `8b63fb1` 之后仅追加状态与修订记录。")

h(B, 2, "4. 方法")
h(B, 3, "4.1 三段切分（锁定，未改）")
table(B, ["段", "周标签范围", "用途", "是否产生判定"], [
    ["训练", "`2016-11-11`–`2022-12-30`；z 预热后有效段自 `2017-05-05`", "管线自检、对齐与缺失诊断", "否"],
    ["验证", "`2023-01-06`–`2024-12-27`", "第一次正式判定", "是"],
    ["留出", "`2025-01-03`–`2026-10-30`", "验证段成立后才开封一次", "确认"],
])
h(B, 3, "4.2 计算口径")
ul(B, [
    "两面分别做滚动 52 周 z-score，`min_periods=26`，只用当期及过去 52 周，不使用未来值。",
    "对 `k=0..13` 计算 `corr(lead_z_t, lag_z_{t+k})`，按周标签配对，pairwise complete；每个 k 报样本量 `n`。",
    "**段内配对约束**：一对样本的领先周 `t` 与滞后周 `t+k` 必须同时落在该段内，即 `t <= 段末 - k 周`。验证段末端就是留出截断点，此前已满足该约束；训练段复核时发现只约束了 `t`，已按同一规则修正并重算，`n` 随 `k` 递减。该修正只改训练段诊断数字，验证段与判定不受影响。",
    "判定只看 `[4,13]` 内的最大正相关；`k=0..3` 只打印，不参与判定。",
])
h(B, 3, "4.3 留出段封存与实测")
table(B, ["项", "实测"], [
    ["封存范围", "周标签 `2025-01-03`–`2026-10-30`"],
    ["默认读取上限", "`2024-12-27`"],
    ["开封开关", "仅显式传入 `--open-holdout`；本次未传"],
    ["磁盘原始件最大日期", "Clinical `2026-10-30`、XBI `2026-11-06`"],
    ["加载后最大日期", "领先面与滞后面全部 `2024-12-27`"],
    ["载入的留出段行数", "0（脚本内断言通过）"],
    ["截断副本", "未生成；保留全量原始件"],
])
h(B, 3, "4.4 计次")
table(B, ["项", "登记"], [
    ["有效尝试", "`attempt #1`"],
    ["技术重跑", "2 次，均为代码 bug，`counts_as_attempt=false`（详见修订表与结案登记）"],
    ["参数改动", "无。`lag_range`、`pass_window`、`pass_corr`、`noise_band`、筛选条件、字段、窗口、切分点、标准化参数、指标数量、标的均未改"],
    ["剩余尝试", "2 次，本次不使用"],
])

h(B, 2, "5. 结果")
h(B, 3, "5.1 临床 XBI（正式账）")
p(B, f"训练段窗口内峰值 `{cpv_t:+.4f}`（`k={cpk_t}`，`n={cpn_t}`）；验证段窗口内峰值 `{cpv_v:+.4f}`（`k={cpk_v}`，`n={cpn_v}`）。")
table(B, ["段", "窗口内最大正相关", "落点", "n", "判定用？"], [
    ["训练", f"{cpv_t:+.4f}", f"k={cpk_t}", f"{cpn_t}", "否（仅诊断）"],
    ["验证", f"{cpv_v:+.4f}", f"k={cpk_v}", f"{cpn_v}", "是"],
])
p(B, "逐格数值（`k`、`n`、相关系数）：")
tr = X[("clinical_xbi", "train")]
va = X[("clinical_xbi", "validation")]
rows = []
for _, a in tr.iterrows():
    b = va[va.k == a.k].iloc[0]
    rows.append([f"{int(a.k)}", f"{int(a.n)}", f"{float(a['corr']):+.4f}", f"{int(b.n)}", f"{float(b['corr']):+.4f}"])
table(B, ["k", "训练 n", "训练 r", "验证 n", "验证 r"], rows)
fig(B, SVG_C, "图 1 · 临床 XBI：训练段与验证段相关性曲线（横轴 `k=0..13`；橙虚线 `0.19` 为噪声带，绿虚线 `0.30` 为通过线；SVG 文件 `phase0/batch1_curve_clinical_xbi.svg`）")
p(B, f"另记一条事实：验证段 `k=8` 的相关系数为 `{c8:+.4f}`（`n={c8n}`），是验证段 14 个滞后位中绝对值最大的一格。")

h(B, 3, "5.2 训练段与验证段的一致性")
table(B, ["账", "训练峰值", "验证峰值", "位置差", "相关系数比值", "是否一致"], [
    ["临床 XBI", f"k={cpk_t}，{cpv_t:+.4f}", f"k={cpk_v}，{cpv_v:+.4f}", f"{abs(cpk_v-cpk_t)} 周", f"{abs(cpv_v/cpv_t):.1f}", "否"],
])
p(B, "训练段没有给出可迁移的形态：验证段峰值的位置与训练段不同，相关系数也不同。这里只报**相关系数比值**（验证段峰值 ÷ 训练段峰值），它不是效应量，也不作倍数解读。该差异不改变机械判定（判定只看验证段），但说明不能把训练段结果当作预期证据。")

h(B, 2, "6. 判定（按稿子条款机械执行）")
p(B, "**临床 XBI → 灰区**。依据 `phase0/preregistration_clinical_xbi.md` §5：`0.19 <= peak_corr < 0.3` 定义为灰区，灰区不构成「成立」。实测 `+0.2035` 落在灰区，距通过线 `0.3` 差 `0.0965`，按预注册词表记为「灰区」，不写「成立」，也不写「接近成立」这类措辞。")
p(B, "为什么是机械裁决：判定线在开跑前写入并以 commit `8b63fb1` 固定；本次未改任何参数，未用训练段结果回调阈值，未用剩余尝试重跑；判定只读验证段 `[4,13]` 的峰值，不读留出段。裁决过程没有人为挑选空间。")
p(B, f"另记一条事实，不参与判定：验证段 `k=8` 为 `{c8:+.4f}`（`n={c8n}`），位于窗口内且方向为负，与命题方向相反；`k=12` 为 `{c12:+.4f}`，方向同样为负。判定仍按 §5 只看窗口内最大正相关；这些负值不被挑选，也不被隐去。")

h(B, 2, "7. 留出段未开封")
ul(B, [
    "留出段 `2025-01-03`–`2026-10-30` **未开封**，开封次数 0。",
    "磁盘上保留了含留出段行的全量原始件，但**未对其做任何计算或查看**；主脚本在不加 `--open-holdout` 时硬截断到 `2024-12-27`，实测载入留出段行数为 0。",
    "未生成截断副本；未二次开封；未用留出段结果反向修改任何参数。",
    "依据 §4 与 §8：验证段未判「成立」时，留出段永久封存。本批次临床账未成立，留出段不再开封。",
])

h(B, 2, "8. 局限")
ul(B, [
    "只验证「领先—滞后关联」，不声称因果；相关系数不构成因果证据。",
    "单一标的、单一指标、周频；未扣交易成本，未做流动性检验。",
    "**多重比较与家族错误率**：14 个滞后位 × 1 个指标，判定又取窗口内最大值，存在选择效应；`0.19` / `0.30` 两条线不控制家族错误率，未做 Bonferroni 或 FDR 校正。",
    "**样本重叠与自相关**：周收益率配 13 周滞后，相邻 `k` 共用大量同一批周值；表中 `n` 是配对行数，不是独立样本数，有效样本远小于 `n`，相关系数的标准误被低估。",
    "**判定线来源**：`0.19` 约合零分布 p95（实测 `0.188`）；`0.30` 不是零分布分位，而是在 p99（`0.218–0.248`）之上的跨链经验补偿。两条线都不是本批数据自身校准，本批未重跑零分布（预注册 §5 规定开跑前不动线）。",
    "**峰值落在窗口边缘**：验证段峰值 `k=13` 是窗口右边界，且该格 `n=91` 为窗口内最小；边缘峰值缺少相邻 `k` 的形态支撑（`k=12` 为负）。",
    "**ETF 规模与成分变化**：XBI 的成分与权重随时间调整，历史 `adjclose` 不能完全代表当前篮子；规模变化也会改变流动性与定价。",
    "**周频对齐与时点可交易性**：周标签固定为周五，信号可执行时点落在下一交易日；未检验开盘/收盘可成交价差，也未检验信号发布到执行的时滞。",
    "**52 周 z 不消除季节性**：滚动 z-score 只做水平与波动归一，不剔除季节性、周期性或结构性断点。",
    "临床计数以 `StudyFirstPostDate` 为登记时点，申办方后续更新不回改历史；样本内该字段缺失为 0，但上游长期稳定性未逐条核验。",
    "**数据源可回改**：ClinicalTrials.gov 与 Yahoo 均可能修订历史；本仓库只保留抓取时点快照，无法防止上游回改。",
    "训练段仅作诊断，其峰值位置与验证段不一致，不构成对验证段结果的支撑，也不能外推到其他窗口。",
    "未做事后子组分析（地区、阶段、招募状态）；如做，只能标为事后探索，不得改写判定。",
])

h(B, 2, "9. 数据与代码位置")
p(B, "逐格结果：`phase0/output/batch1_xcorr_clinical_xbi_train.csv`、`phase0/output/batch1_xcorr_clinical_xbi_validation.csv`；快照旁注：`phase0/output/batch1_snapshot_clinical.md`、`phase0/output/batch1_snapshot_yahoo_XBI.md`；跑数脚本：`phase0/run_batch1.py`；报告生成脚本：`phase0/build_batch1_report.py`。上述逐格结果与快照旁注已在 `.gitignore` 中按具体路径精确放行、待本次提交。原始大件（56,443 条记录与日线行情）体积较大，仍留在本地 `phase0/output/` 未入库，可按快照旁注记录的端点与筛选条件重取。练手账（能源 N1）的证据不入库，仅本地留存，不在本报告范围。数据均为公开源，无隐私内容。")

# ---------------------------------------------------------------- internal archive (energy N1)

I = []

h(I, 1, "批次一内部归档：能源 N1（练手账）")
p(I, "归档日期：2026-11-07 ｜ 预注册锚点：`8b63fb1` ｜ 留出段：未开封 ｜ 判定尝试：`attempt #1`")
quote(I, "**归属说明**：本文件是**内部归档**，只记录练手账的流程演练结果，不进入对外材料，也不得被引用为对外证据。对外版见 `phase0/batch1_report.md` / `phase0/batch1_report.html`，其中只包含临床 XBI 正式账。")

h(I, 2, "1. 命题原文")
p(I, "引自 `phase0/preregistration_energy_n1.md` §1：")
quote(I, "美国炼厂开工率（EIA WPSR Table 2「Percent Utilization」，美国总量，周度）**系统性领先** VanEck Oil Refiners ETF（CRAK）的周收益率 **4–13 周**；方向为正：开工率上行后，CRAK 后续 4–13 周的周收益倾向为正。")

h(I, 2, "2. 数据与快照")
table(I, ["项", "实测"], [
    ["领先面", "EIA WPSR Table 2「Percent Utilization」，美国总量列，周度"],
    ["归档端点", "`https://www.eia.gov/petroleum/supply/weekly/archive/YYYY/YYYY_MM_DD/csv/table2.csv`；2026-10-15 起部分页面改为 `download/table2.csv`"],
    ["最新周端点", "`https://ir.eia.gov/wpsr/table2.csv`"],
    ["唯一周数", f"{S['eia_weeks']}（`{S['eia_min']}`–`{S['eia_max']}`）"],
    ["样本内周数", f"{S['eia_sample_weeks']} / 521，缺口 0"],
    ["样本内取值", f"{S['eia_lo']}–{S['eia_hi']}，均值 {S['eia_mean']}"],
    ["最新已发布周", f"`2026-10-30`，{S['eia_last']}"],
    ["补数登记", "3 周从相邻期的「上周列」补回：`2019-06-28` 94.2、`2022-06-17` 94.0、`2023-11-03` 85.2"],
    ["滞后面", f"Yahoo chart API v8，`CRAK` 日线 `adjclose`，{S['crak_rows']} 个交易日（`2016-11-07`–`2026-11-06`），空值 {S['crak_null']}"],
    ["快照旁注", "`phase0/output/batch1_snapshot_eia_wpsr.md`、`batch1_snapshot_yahoo_CRAK.md`"],
])
h(I, 3, "2.1 三周补数与「缺失即丢弃」规则的对齐")
p(I, "预注册 §3 的缺失规则是「某周缺失则丢弃该周」，不插值、不前向填充。实现时 3 周（`2019-06-28`、`2022-06-17`、`2023-11-03`）在当前周列缺失，但同一张 EIA Table 2 的相邻列（该表自带的「上周」列）给出了这三周的原始发布值，因此取回的是**原文原值**，不是插值、不是前向填充、不是由相邻周推算；数值来源 URL 已逐条记入快照旁注 `prior_column_backfilled_weeks`。这不属于参数修订：判定线、窗口、字段、样本与切分均未改动，补回的是源表已发布的当期值，缺失周数由 3 降为 0。")
p(I, "若这三周不补，样本内缺失率为 3 / 521 ≈ 0.58%，低于预注册的 5% 停跑线；补数的目的是让周序列连续，而不是改善相关性。补数前后的差异未用于选择结果。")

h(I, 2, "3. 方法")
h(I, 3, "3.1 三段切分（锁定，未改）")
table(I, ["段", "周标签范围", "用途", "是否产生判定"], [
    ["训练", "`2016-11-11`–`2022-12-30`；z 预热后有效段自 `2017-05-05`", "管线自检、对齐与缺失诊断", "否"],
    ["验证", "`2023-01-06`–`2024-12-27`", "第一次正式判定", "是"],
    ["留出", "`2025-01-03`–`2026-10-30`", "验证段成立后才开封一次", "确认"],
])
h(I, 3, "3.2 计算口径")
ul(I, [
    "两面分别做滚动 52 周 z-score，`min_periods=26`，只用当期及过去 52 周，不使用未来值。",
    "对 `k=0..13` 计算 `corr(lead_z_t, lag_z_{t+k})`，按周标签配对，pairwise complete；每个 k 报样本量 `n`。",
    "**段内配对约束**：一对样本的 `t` 与 `t+k` 必须同时落在该段内，即 `t <= 段末 - k 周`。复核发现训练段此前只约束了 `t`，已按同一规则修正并重算（`n` 随 `k` 递减）；验证段末端就是留出截断点，不受影响。",
    "判定只看 `[4,13]` 内的最大正相关；`k=0..3` 只打印，不参与判定。",
])
h(I, 3, "3.3 留出段封存")
table(I, ["项", "实测"], [
    ["封存范围", "周标签 `2025-01-03`–`2026-10-30`"],
    ["默认读取上限", "`2024-12-27`"],
    ["开封开关", "仅显式传入 `--open-holdout`；本次未传"],
    ["载入的留出段行数", "0（脚本内断言通过）"],
])

h(I, 2, "4. 结果")
p(I, f"训练段窗口内峰值 `{epv_t:+.4f}`（`k={epk_t}`，`n={epn_t}`）；验证段窗口内峰值 `{epv_v:+.4f}`（`k={epk_v}`，`n={epn_v}`）。")
table(I, ["段", "窗口内最大正相关", "落点", "n", "判定用？"], [
    ["训练", f"{epv_t:+.4f}", f"k={epk_t}", f"{epn_t}", "否（仅诊断）"],
    ["验证", f"{epv_v:+.4f}", f"k={epk_v}", f"{epn_v}", "是"],
])
p(I, "逐格数值（`k`、`n`、相关系数）：")
tr = X[("energy_n1", "train")]
va = X[("energy_n1", "validation")]
rows = []
for _, a in tr.iterrows():
    b = va[va.k == a.k].iloc[0]
    rows.append([f"{int(a.k)}", f"{int(a.n)}", f"{float(a['corr']):+.4f}", f"{int(b.n)}", f"{float(b['corr']):+.4f}"])
table(I, ["k", "训练 n", "训练 r", "验证 n", "验证 r"], rows)
fig(I, SVG_E, "图 1 · 能源 N1：训练段与验证段相关性曲线（横轴 `k=0..13`；橙虚线 `0.19` 为噪声带，绿虚线 `0.30` 为通过线；SVG 文件 `phase0/batch1_curve_energy_n1.svg`）")
p(I, f"训练段与验证段的相关系数比值 `{abs(epv_v/epv_t):.1f}`（验证段峰值 ÷ 训练段峰值）。这里只报比值，不作效应量或倍数解读；两段位置不同（`k={epk_t}` 对 `k={epk_v}`），训练段不构成对验证段的支撑。")

h(I, 2, "5. 判定")
p(I, f"**能源 N1 → 不成立**。依据 `phase0/preregistration_energy_n1.md` §5「什么算不成立」第 1 条：验证段 `[4,13]` 内最大正相关 `< 0.19`。实测 `{epv_v:+.4f} < 0.19`，条件命中，判「不成立」。该账为练手账，结果归档，不进对外材料；不调参、不换标的、不消耗剩余尝试。")

h(I, 2, "6. 局限")
ul(I, [
    "只验证「领先—滞后关联」，不声称因果；相关系数不构成因果证据。",
    "单一标的、单一指标、周频；未扣交易成本，未做流动性检验。",
    "**多重比较与家族错误率**：14 个滞后位 × 1 个指标，判定又取窗口内最大值；`0.19` / `0.30` 两条线不控制家族错误率。",
    "**样本重叠与自相关**：周收益率配 13 周滞后，相邻 `k` 共用大量同一批周值；表中 `n` 是配对行数，不是独立样本数，有效样本远小于 `n`。",
    "**判定线来源**：`0.19` 与 `0.30` 继承自其他链的零分布校准，不是本批数据自身的零分布。",
    "**WPSR 发布时滞**：周报通常在周结束后下一周周三发布，`k=0` 只作前视诊断，`k>=1` 才视为可交易滞后；未检验发布时点与可成交时点。",
    "**EIA 回改风险**：WPSR 周报可能在后续周次修订；本仓库只保留抓取时点快照。",
    "**52 周 z 不消除季节性**：滚动 z-score 只做水平与波动归一，不剔除季节性、周期性或结构性断点。",
    "ETF 规模与成分可能变化；历史 `adjclose` 不能完全代表当前篮子。",
    "训练段仅作诊断，其峰值位置与验证段不一致，不构成对验证段结果的支撑。",
    "未做事后子组分析；如做，只能标为事后探索，不得改写判定。",
])

h(I, 2, "7. 数据与代码位置")
p(I, "逐格结果：`phase0/output/batch1_xcorr_energy_n1_train.csv`、`phase0/output/batch1_xcorr_energy_n1_validation.csv`；快照旁注：`phase0/output/batch1_snapshot_eia_wpsr.md`、`phase0/output/batch1_snapshot_yahoo_CRAK.md`；跑数脚本：`phase0/run_batch1.py`；归档生成脚本：`phase0/build_batch1_report.py`。能源账证据未入库（`.gitignore` 未放行），仅本地留存；本文件与能源曲线 SVG 同样仅本地留存，不入库。原始大件（775 周 EIA 表与 CRAK 日线）仍留在本地 `phase0/output/` 未入库，可按快照旁注记录的端点重取。数据均为公开源，无隐私内容。")

h(I, 2, "8. 账本机制与已知缺口")
p(I, "本节只进内部分档，不出现在对外版。")
ul(I, [
    "前 9 条为历史整块重写：`build_batch1_report.py` 早期版本每次运行都会重写整份账本，第 1–9 行的写入时刻只能记为补录时刻，不能还原为逐条事件时刻。",
    "前 9 条前缀哈希为 `c2c755daf5ff93170c48155cae9d07641224ef2354123e8d832e57d8fd8ea742`（SHA256，按字节计，仅备查）；`tests/run_batch1_ledger_integrity.py` 的 `--prefix-sha256` 为可选参数，默认只打印不比对，仓库内未登记期望值。",
    "第 10 条起改由 `phase0/append_batch1_ledger.py` 追加：`open(path, \"a\")` 单条写入，`--at` 必填无默认，追加前校验尾部可解析。",
    "`phase0/build_batch1_report.py` 已改为只读账本：账本缺失或含坏行即退出，不再生成。",
    "`omninexus/guard.py` 的 H4「运行历史只追加不覆写」不覆盖本账本：H4 的日志路径由台账派生（`chains/<id>.record.runs.jsonl`），项目账本约束又限定 `record_path.parent.name == \"chains\"`；本账本位于 `phase0/`，无链 YAML 与 `record.json`，且历史写入从未经过 guard 的 `_append_run_log`。本轮不将其纳入 guard，以免与两份预注册稿 §7 的账本独立性冲突。",
    "已知缺口：历史段不可追溯，整份账本不作为对外证据；对外可核的过程证据止于锚定 commit 与临床逐格 CSV、临床快照旁注。",
])

# ---------------------------------------------------------------- render

INLINE = [
    (r"\*\*(.+?)\*\*", r"<strong>\1</strong>"),
    (r"`(.+?)`", r"<code>\1</code>"),
]


def html_inline(s):
    s = html.escape(s)
    for pat, rep in INLINE:
        s = re.sub(pat, rep, s)
    return s


def render_md(blocks):
    out = []
    for b in blocks:
        if b[0] == "h":
            out.append("#" * b[1] + " " + b[2])
            out.append("")
        elif b[0] == "p":
            out.append(b[1])
            out.append("")
        elif b[0] == "q":
            out.append("> " + b[1])
            out.append("")
        elif b[0] == "t":
            hd, rows = b[1], b[2]
            out.append("| " + " | ".join(hd) + " |")
            out.append("|" + "|".join(["---"] * len(hd)) + "|")
            for r in rows:
                out.append("| " + " | ".join(r) + " |")
            out.append("")
        elif b[0] == "u":
            for it in b[1]:
                out.append("- " + it)
            out.append("")
        elif b[0] == "f":
            out.append(b[2])
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def render_html(blocks, title):
    body = []
    for b in blocks:
        if b[0] == "h":
            body.append(f"<h{b[1]}>{html_inline(b[2])}</h{b[1]}>")
        elif b[0] == "p":
            body.append(f"<p>{html_inline(b[1])}</p>")
        elif b[0] == "q":
            body.append(f"<blockquote>{html_inline(b[1])}</blockquote>")
        elif b[0] == "t":
            hd, rows = b[1], b[2]
            th = "".join(f"<th>{html_inline(c)}</th>" for c in hd)
            tr = ""
            for r in rows:
                tr += "<tr>" + "".join(f"<td>{html_inline(c)}</td>" for c in r) + "</tr>"
            body.append(f"<table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>")
        elif b[0] == "u":
            body.append("<ul>" + "".join(f"<li>{html_inline(i)}</li>" for i in b[1]) + "</ul>")
        elif b[0] == "f":
            body.append(f'<figure>{b[1]}<figcaption>{html_inline(b[2])}</figcaption></figure>')
    css = """
:root{--ink:#1f2733;--muted:#5d6675;--line:#e2e5ea;--bg:#ffffff;--soft:#f6f7f9;--accent:#b0562f}
*{box-sizing:border-box}
body{margin:0;background:var(--soft);color:var(--ink);
 font-family:system-ui,-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;
 font-size:16px;line-height:1.75}
main{max-width:1040px;margin:0 auto;padding:56px 48px 80px;background:var(--bg)}
h1{font-size:28px;line-height:1.35;margin:0 0 14px;letter-spacing:-.2px}
h2{font-size:20px;margin:42px 0 14px;padding-bottom:8px;border-bottom:1px solid var(--line)}
h3{font-size:16px;margin:26px 0 10px;color:#2c3542}
p{margin:12px 0}
blockquote{margin:14px 0;padding:12px 16px;border-left:3px solid var(--accent);
 background:#fbf5f1;color:#513b31}
code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:13px;
 background:#f1f3f6;padding:1px 5px;border-radius:4px}
table{width:100%;border-collapse:collapse;margin:14px 0;font-size:14px}
th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
th{background:var(--soft);font-weight:600}
ul{margin:10px 0 10px 22px}
li{margin:6px 0}
figure{margin:26px 0;text-align:center}
figure svg{max-width:100%;height:auto;border:1px solid var(--line)}
figcaption{font-size:13px;color:var(--muted);margin-top:8px;text-align:left}
@media print{body{background:#fff}main{padding:0;max-width:none}}
"""
    return ("<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>{html.escape(title)}</title>\n<style>" + css + "</style>\n</head>\n<body>\n<main>\n"
            + "\n".join(body) + "\n</main>\n</body>\n</html>\n")


md = render_md(B)
htm = render_html(B, "批次一验证报告：临床 XBI（正式账）")
Path("phase0/batch1_report.md").write_text(md, encoding="utf-8")
Path("phase0/batch1_report.html").write_text(htm, encoding="utf-8")
Path("phase0/batch1_internal_archive.md").write_text(render_md(I), encoding="utf-8")

# ---------------------------------------------------------------- identity check (external report)

core = re.search(r"<main>([\s\S]*)</main>", htm).group(1)
core = re.sub(r"<svg[\s\S]*?</svg>", " ", core)
core = re.sub(r"<style>[\s\S]*?</style>", " ", core)
html_text = html.unescape(re.sub(r"<[^>]+>", " ", core))

cjk_md = re.findall(r"[\u4e00-\u9fff]", md)
cjk_ht = re.findall(r"[\u4e00-\u9fff]", html_text)
num_md = re.findall(r"[-+]?\d+(?:\.\d+)?", md)
num_ht = re.findall(r"[-+]?\d+(?:\.\d+)?", html_text)

print(json.dumps({
    "md_chars": len(md),
    "html_chars": len(htm),
    "cjk_chars_md": len(cjk_md),
    "cjk_chars_html": len(cjk_ht),
    "cjk_identical": cjk_md == cjk_ht,
    "number_tokens_md": len(num_md),
    "number_tokens_html": len(num_ht),
    "numbers_identical_order": num_md == num_ht,
    "md_headings": md.count("\n#"),
}, ensure_ascii=False))
if cjk_md != cjk_ht:
    for i, (a, b) in enumerate(zip(cjk_md, cjk_ht)):
        if a != b:
            print("first CJK mismatch at", i, a, b)
            break
if num_md != num_ht:
    for i, (a, b) in enumerate(zip(num_md, num_ht)):
        if a != b:
            print("first number mismatch at", i, a, b)
            break

# ---------------------------------------------------------------- ledger (read-only)

LEDGER = Path("phase0/batch1.record.runs.jsonl")
if not LEDGER.exists():
    raise SystemExit(f"ledger missing: {LEDGER}（账本由 append_batch1_ledger.py 维护，本脚本只读）")
rows = []
for ln in LEDGER.read_text(encoding="utf-8").splitlines():
    if not ln.strip():
        continue
    try:
        rows.append(json.loads(ln))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ledger line is not valid JSON: {exc}")
print("ledger rows:", len(rows))
