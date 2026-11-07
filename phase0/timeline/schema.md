# 事件时间线 · 事件 schema（v1）

> 创建日：2026-11-08 ｜ 依据代际：壳前置能力（phase0/timeline） ｜ 最后实质修订：2026-11-08
> 本文件是字段的**唯一 owner**。`timeline.py` 与测试按此实现；改字段先改这里。

## 1. 设计前提

- 输出不是自由文本：每条事件落成固定字段，缺字段即拒绝入表。
- 字段值可回溯到原始抓取：`source_url` + `fetched_at_utc` + `excerpt` 三件齐备才成立。
- 抽取失败是显式状态（`reject` 记录原因），不是"猜一个填上去"。

## 2. 事件对象

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `event_id` | string | 是 | 由 `subject + action + time + 首条 source_url` 计算的 sha256 前 16 位；同样输入得同样 id |
| `time` | string `YYYY-MM-DD` | 是 | 事件发生日（UTC 口径）。带时分秒的源截断到日，`time_precision` 标注 |
| `time_precision` | `day` \| `minute` | 是 | 源只给日期 → `day`；给到时分 → `minute` |
| `subject` | string | 是 | 事件主体（公司/机构/药物/政策名），≤80 字符，去首尾标点 |
| `action` | enum（见 §3） | 是 | 动作类别，闭集 |
| `action_text` | string | 是 | 触发该动作的**原文锚点**（逐字片段，≤60 字符），用于人工复核为何判成该动作 |
| `object` | string \| null | 否 | 动作对象（药名、试验名、标的、政策文号） |
| `value` | object | 是 | `{kind, raw, number, unit}`；无定量值时 `kind="none"`，其余为 null |
| `source_url` | string | 是 | 条目级 URL，必须 `http(s)` 开头；分级见 `url_kind` |
| `url_kind` | `publisher` \| `official` \| `aggregator` | 是 | 出版商原文 / 官方记录 / 聚合器页面 |
| `source_name` | string | 是 | 发布方名称（媒体名或机构名） |
| `fetched_at_utc` | string ISO8601Z | 是 | 抓到该条目的时刻（UTC），不是事件发生时间 |
| `excerpt` | string | 是 | 原文片段（≥20 字符），逐字取自源文本，不做改写 |
| `excerpt_kind` | `headline` \| `summary` \| `abstract` | 是 | 片段类型；只有标题可用的条目标 `headline` |
| `extract_method` | string | 是 | 抽取器版本，当前固定 `rules_v2`（词表版本号，规则表在 `timeline.py` 的 `ACTION_PATTERNS`） |
| `sources` | array | 是 | 去重合并后的全部报道：`[{source_url, source_name, url_kind, fetched_at_utc, excerpt}]`，至少 1 条，按抓取时刻升序 |

## 3. 动作闭集（`action`）

| 值 | 含义 | 典型触发词（原文锚点） |
|---|---|---|
| `trial_start` | 启动/开试/首例给药 | initiated, launched, first patient dosed, enrollment open |
| `trial_result` | 结果/数据读出/达标与否 | results, topline, met primary endpoint, failed, missed |
| `approval` | 获批/授权/绿灯 | approved, authorized, cleared, green light |
| `rejection` | 拒批/否决 | rejected, declined, complete response letter |
| `halt` | 暂停/终止/叫停 | halted, suspended, paused, terminated |
| `designation` | 监管资格认定 | orphan, breakthrough, fast track, priority review |
| `deal` | 收购/合并/授权交易 | acquire, merger, takeover, licensing deal |
| `partnership` | 合作/联研 | partner, collaborate, team up, joint venture |
| `funding` | 融资/投资 | raised, funding round, investment |
| `policy` | 规则/公报/征求意见 | final rule, proposed rule, notice, guidance |
| `registration` | 登记类事件 | registered, new trial posted |
| `publication` | 论文/预印本发布 | preprint, study published, researchers find |
| `personnel` | 人事变动 | appointed, named, resigned, steps down |
| `other` | 预留：人工标注用它表示「确实是事件但不属上面任一动作」 | 当前规则抽取器**不产出**该值（`ACTION_PATTERNS` 无该项） |

## 4. 拒绝态（不进表，写进 `rejects`）

| reason | 判据 |
|---|---|
| `out_of_window` | 事件时间不在 `[start, end]` |
| `missing_time` | 时间缺失或不可解析 |
| `missing_url` | URL 缺失或不是 http(s) |
| `missing_excerpt` | 摘要缺失或去空白后 <20 字符 |
| `unparsed_action` | 全文（标题+摘要）里没有任何动作词 |
| `unparsed_subject` | 动作词前取不出主体短语（动词在标题开头、或主体为空） |
| `subject_not_in_text` | 指定了 `--entity`，但文本里没出现该主体 |
| `not_an_event` | 标题以 Why/How/Opinion/Analysis 等开头或以问号结尾，判为评论/解释稿而非事件 |
| `duplicate` | 与已入表事件合并（并入 `sources`，不单独成行）。**只在新闻源之间合并**：Federal Register / ClinicalTrials / arXiv 每条是独立文书，标题相近不等于同一事件 |

## 5. 输出文件契约

一次运行产出三件：

1. `events.json`：`{meta, events[], rejects[]}`；`meta` 含 `query/window_start/window_end/generated_at_utc/sources_stats/extract_method`。
2. `events.md`：按时序排列的人读时间线，每条含日期、主体、动作、数值、原文片段、来源链接。
3. `raw_items.json`：本次抓到的原始条目（含标题/摘要/URL/时间/来源），供离线复跑与基准标注；**第三方原文不入库**，该文件只留在 `out/` 且被 `.gitignore` 排除。

## 6. 硬校验（实现必须在写出前逐条检查）

1. `time` 可解析为 `YYYY-MM-DD`；
2. `subject` 非空且 ≤80 字符；
3. `action` 属于 §3 闭集；
4. `source_url` 以 `http://` 或 `https://` 开头；
5. `fetched_at_utc` 可解析且带 UTC 标记；
6. `excerpt` 去空白后 ≥20 字符；
7. `sources` 非空，且每条的 `source_url`、`fetched_at_utc`、`excerpt` 三项同样合格。

任一不满足 → 该条进 `rejects`（reason 写具体项），绝不补默认值。
