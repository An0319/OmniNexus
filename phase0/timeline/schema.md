# 事件时间线 · 事件 schema（v1）

> 创建日：2026-11-08 ｜ 依据代际：壳前置能力（phase0/timeline） ｜ 最后实质修订：2026-11-08
> 本文件是字段的**唯一 owner**。`timeline.py` 与测试按此实现；改字段先改这里。

## 0. 部署依赖（模型抽取器，接手前先看）

| 依赖项 | 现象 | 处理 |
|---|---|---|
| Ollama 服务 | 未启动时 `URLError [WinError 10061]` | 先 `ollama serve`；端点 `http://127.0.0.1:11434` |
| `OLLAMA_NOPRUNE` | 不设环境变量时，服务启动即报 `remove D:\Ollama\models\manifests-v2: Access is denied` | 启动前设 `OLLAMA_NOPRUNE=true` |
| 沙箱只读模型目录 | 沙箱内起服务同样报 `Access is denied`（`D:\Ollama\models` 在只读区） | 服务需在沙箱外启动（`dangerouslyDisableSandbox` 或手工起） |
| `format` 传 JSON Schema | 实测**不强制 `enum`**：给 `enum:["approval","halt"]` 仍返回枚举外字符串（Ollama 0.40.13） | 闭集由提示词全列 + `schema_error()` 校验 + 一次修复重试保证，不依赖解码器 |
| 模型选型 |  | `svjack/Qwen3-4B-Instruct-2507-heretic:latest`（本机 8 个模型里唯一 JSON 3/3 合法且摘要逐字 3/3） |
| 成本 | 单条 1.2–1.8s、0 元（本机推理，无 API 计费） | **可用于在线接口**（见 `benchmark.md` §6.5.3） |

## 1. 设计前提

- 「什么算一个事件」由 [event_definition.md](event_definition.md) 唯一定义，本文件只定义字段。
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
| `extract_method` | string | 是 | 抽取器版本：规则抽取器 `rules_v2`（词表在 `timeline.py` 的 `ACTION_PATTERNS`）；模型抽取器 `model_v1`（提示词与校验在 `extract_model.py`）。同一份 `events.json` 里不混用 |
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

`duplicate` **不是拒绝态**（v1 修订）：重复条目不写进 `rejects`，只计合并次数。理由：`rejects` 的语义是「本次抓到、但没进表」，与已入表事件合并的条目的 URL 仍留在 `events[].sources` 里、内容进了表，把它同时算作「被拒绝」会让同一条既算入表又算拒绝；而且拒绝态要求逐条带 `reason` 与可核锚点，合并项没有这些。合并计数记在 `meta.stats.merged_duplicates`，其 URL 在 `events[].sources[]` 可逐一核到。

模型抽取器（`extract_model.py`）额外产出的两个拒绝理由：

| reason | 判据 |
|---|---|
| `schema_invalid` | 模型输出缺必填字段、字段类型不符，或 `action` / `value_kind` / `reject_reason` 落在枚举外；经一次修复重试仍不合法 |
| `missing_excerpt` | 模型给出的摘要片段不是原文逐字子串，或去空白后 <20 字符 |

两者都属"模型没给出可核结果"，一律不进表；不许用"取最相近动作"之类兜底。

## 5. 输出文件契约

一次运行产出三件：

1. `events.json`：`{status, meta, events[], rejects[]}`；`meta` 含 `query/window_start/window_end/generated_at_utc/sources_stats/extract_method`。
2. `events.md`：按时序排列的人读时间线，每条含日期、主体、动作、数值、原文片段、来源链接。
3. `raw_items.json`：本次抓到的原始条目（含标题/摘要/URL/时间/来源），供离线复跑与基准标注；**第三方原文不入库**，该文件只留在 `out/` 且被 `.gitignore` 排除。

### 5.1 运行状态（`status`，本次新增）

`events.json` 的**顶层**字段 `status`，取值三选一。它回答「这轮抓取是否成立」，与「有没有事件」是两件事：

| 值 | 判据 | 含义 |
|---|---|---|
| `ok` | 所有被请求的源都无 `error`（允许 `fetched == 0`） | 抓取成立；`events` 为空才是真的「这段时间没有事件」 |
| `partial` | 至少一个源有 `error`，至少一个源无 `error` | 抓取部分成立；`events` 只覆盖成功的源，**不可当作全量** |
| `failed` | 所有被请求的源都有 `error`（或一个源都没请求到） | 抓取不成立；`events` 为空**不代表没有事件**，本次结果无证据力 |

- `--replay` 模式不抓取，`status` 恒为 `ok`。
- 逐源失败原因在 `meta.sources_stats[源名].error`，与 `status` 不重复计数、只作明细。

**与既有判据的衔接（不留两套）**：此前文档里的「无数据 = 所有源 `fetched == 0` 且无 `error`」只在 `status == "ok"` 时成立，它是 `ok` 的一个特例，不再单独作为判据。判断一律先看 `status`：`failed` / `partial` 下出现空 `events` 时，禁止解读为「无事件」。

### 5.2 退出码

| 退出码 | 条件 |
|---|---|
| `0` | `status` 为 `ok` 或 `partial`（`partial` 只在 `status` 里体现，不靠退出码） |
| `3` | `status` 为 `failed`（全部源失败） |
| `2` | 参数错误（argparse 既有行为，未改） |

退出码只是给脚本用的快捷判据；**调用方允许只看 `status`**，两者语义一致。`status == "failed"` 时仍会写出 `events.json`（便于排障），但该文件不得被下游当作结果。

## 6. 硬校验（实现必须在写出前逐条检查）

1. `time` 可解析为 `YYYY-MM-DD`；
2. `subject` 非空且 ≤80 字符；
3. `action` 属于 §3 闭集；
4. `source_url` 以 `http://` 或 `https://` 开头；
5. `fetched_at_utc` 可解析且带 UTC 标记；
6. `excerpt` 去空白后 ≥20 字符；
7. `sources` 非空，且每条的 `source_url`、`fetched_at_utc`、`excerpt` 三项同样合格。

任一不满足 → 该条进 `rejects`（reason 写具体项），绝不补默认值。
