# 契约 · 取数层 ↔ 判定层（冻结版 v1）

> 冻结日：2026-11-27 ｜ 适用范围：`phase0/timeline/` 的中英两条线（`rulesets/en.json`、`rulesets/zh.json`）
> 目的：中英两条线现在各跑各的，但**共用接口先冻死**——将来合流时是「通电」，不是「改造」。
> 本轮只写契约，**不改任何实现代码**。

**权威边界（谁 owner 什么）**

| 内容 | 唯一 owner |
|---|---|
| 事件对象的字段、类型、必填、硬校验 | [schema.md](schema.md) |
| 「什么算一个事件」（英文判据） | [event_definition.md](event_definition.md) |
| 「什么算一个事件」（中文判据、A/B/C/D 分类） | [event_definition_zh.md](event_definition_zh.md) |
| **层与层之间的输入/输出边界** | 本文件 |

本文件不复制字段表；与 schema.md 冲突时以 schema.md 为准，并回头改本文件。

## 0. 两层怎么切

- **取数层**：`timeline.py` 的源适配器（`fetch_google_news` 等）→ 产出一条 **raw item**（dict），落盘为 `out/raw_items.json`（不入库）。
- **判定层**：`build_event()` → `validate_event()` → `merge_events()`，产出 `events[]` / `rejects[]`。
- **方向单向**：raw item → event / reject。判定层不回写 raw，也无权改取数层抓到的原文。

## 1. 输入：一条 raw item

判定层只认下列键（`build_event()` 读取处：timeline.py L747–834）。

| 字段 | 类型 | 必填 | 缺失 / 非法时的行为 |
|---|---|---|---|
| `date` | string | 是 | 拒绝，`missing_time` |
| `link` | string | 是 | 不以 http(s) 开头即拒绝，`missing_url` |
| `excerpt` | string | 是 | 去空白后短于 `gates.excerpt_min` 即拒绝，`missing_excerpt` |
| `fetched_at_utc` | string（ISO8601Z） | 是 | 硬校验判 `missing_time`（见 §2 的现状说明） |
| `source_id` | string | 是 | 去重与 `meta.sources_stats` 的键；缺失统计记 `"?"` |
| `title` | string | 观测上必需（无显式校验） | 缺失时不报错，但通常导致后续 `unparsed_action` |
| `source_name` | string | 否 | 缺省 `"unknown"` |
| `url_kind` | `publisher\|official\|aggregator` | 否 | 缺省 `publisher` |
| `excerpt_kind` | `headline\|summary\|abstract` | 否 | 缺省按长度推（`gates.excerpt_kind_min`） |
| `action_hint` / `subject_hint` / `phase_hint` | string | 否 | 缺省走规则抽取；给了就跳过对应抽取步骤 |
| `object` | string \| null | 否 | 直通输出 |

**硬规则（不许含糊）**：raw item 缺字段或字段非法 → 该条进 `rejects` 并带具体 `reason`，
**不抛异常、不补默认值、不猜最接近**。抛错只保留给配置类缺失（§7）。
`schema.md` §6 的硬校验是这条规则的实现清单，逐条对应。

## 2. 时间口径：两个时间，两个字段

| 概念 | 字段 | 谁提供 | 格式 |
|---|---|---|---|
| **事件时刻**（事件发生/发布） | `date` | 取数层（来自源） | 源原样字符串；可带时分，也可只是日期 |
| **抓取时刻**（这一条是什么时候抓到的） | `fetched_at_utc` | 取数层（抓取当场写入） | `YYYY-MM-DDTHH:MM:SSZ` |

- 输出侧：`time` 一律截断为 `YYYY-MM-DD`（UTC 口径），另用 `time_precision ∈ {day, minute}`
  标注源是否给到时分（timeline.py L809）。
- 时区表达：只接受 `Z` 或 `+00:00`；解析后无时区标记的，按 UTC 处理（`parse_date`，L128–130）。
  调用方不得另行假设本地时区，也不得把本地时间伪装成 UTC。
- 缺时间的处理：`date` 缺 → `missing_time` 拒绝；`fetched_at_utc` 缺 → 同样落 `missing_time`。
  **现状不对称**：两者共用一个拒绝码，调用方不能据此反推是"事件时刻缺"还是"抓取时刻缺"。
  这是现行行为，本轮只登记不改（见 §9）。

## 3. locale：只由规则集提供，引擎零默认

- 参数位置：`rulesets/<lang>.json` 的 `source_params.<source>.{hl, gl, ceid, source_id}`（如 google_news）。
- 引擎行为：缺任一键 → 抛 `RulesetConfigError`，消息为「语言/地区参数必须由规则集提供，引擎不设默认值」
  （timeline.py L169–179）。**契约固化这条：不许静默兜底**，不许在引擎里写 `if lang == "zh"` 之类分支。
- 调用方责任：共享接口调用必须显式给 `--lang`；CLI 的默认 `zh` 只是命令行便利，不作为接口默认。
- 新增一门语言 = 新增 `rulesets/<lang>.json`（含 §7 的必需键 + 该语言的 `source_params` + `reject_codes`），
  再补该语言的基准样本。引擎代码一行不动。

## 4. 失败与空：写死，两侧都不许伪装

这是 2026-09-30 那个坑的根：**「取不到」和「取到空的」是两种状态。**

- 事件层用顶层 `status` 三态（`schema.md` §5.1）+ 退出码（§5.2）：

| 状态 | 含义 | 空 `events` 的正确读法 |
|---|---|---|
| `ok` | 全部被请求源无 `error`（允许 `fetched == 0`） | 才允许读成「这段时间没有事件」 |
| `partial` | 至少一源成功、至少一源有 `error` | 只覆盖成功源，**不得**读成全量或"无事件" |
| `failed` | 全部源有 `error`（或一个源都没请求到） | **无证据力**，不得读成"无事件" |

- 铁律（对两侧同样有效）：
  1. 任何一侧都不得把 `failed` / `partial` 的空结果当作成功交付；
  2. 任何一侧都不得把"取到空"伪造成"取不到"，反之亦然；
  3. 下游读者必须先看 `status`（或逐源 `error`），再决定能不能用 `events` 长度下结论。
- 日更侧同构：`run_state.status` 与各链 `status/failure_reasons` 承担同一职责；
  任何读者不得只看点数是否为 0 就推断"今天没有变化"。

## 5. 标记字段：谁写、谁读、改名怎么办

| 标记 | 写入方 | 读取方 |
|---|---|---|
| `events.json.status` | `timeline.py` | `eval_*.py`、所有调用方 |
| `meta.extract_method` / `meta.ruleset` | `timeline.py` | 评测脚本、人工复核 |
| `meta.sources_stats[源].error` | `timeline.py` | 排障；不重复计入 `status` |
| `meta.stats.reject_reasons` | `timeline.py` | 质量趋势查看 |
| `snapshot_<链>.lag.degraded` / `.path` | `tools/daily_update.py` | 看板（只读转译）、`tools/daily_sentinel.py` |
| `data/sentinel_report.json`（降级计数、哨兵状态） | `tools/daily_sentinel.py` | 哨兵自身（次日基线） |

**改名/删除 = 契约变更**，必须同一提交内完成三件事：① 改 owner（`schema.md` 或本文件）；
② 同步全部读取方；③ 回归通过。只改写入方、让读方"自己适配"是不允许的。
新增可选字段不算变更（读方必须容忍未知键）。

## 6. 去重与排序：现状归属（先查后写）

- **取数层不做去重**：同一 URL 重复抓到就重复进 `raw_items.json`，原样保留。
- **去重在判定层**：`merge_events()`（timeline.py L894–906），策略参数来自 `ruleset.dedupe`：
  `merge_sources`（只在这些新闻源之间合并；官方记录源每条是独立文书，不合并）、
  `day_tolerance`、`jaccard_min`。
- **排序**：先按 `(time, sources[0].fetched_at_utc)` 升序（L897），再合并；
  合并后的 `sources[]` 按抓取时刻升序，上限 8 条（L900）。
- **重复不写进 `rejects`**，只记 `meta.stats.merged_duplicates`（`schema.md` §4 的 v1 修订）。
- 两侧现状一致：没有"取数层也去重一遍"的第二套逻辑。将来若加，必须先改本节。

## 7. 规则集与引擎的契约（原先没有成文，本节补齐）

实现位置：`Ruleset.__init__`（timeline.py L38–89）、`load_ruleset`（L92–97）。

- **必需键**（引擎直接索引，缺则 `KeyError`）：
  `lang`、`actions`、`action_patterns`、`value_patterns`、`subject`、`gates`、`tokenize`、`dedupe`、`reject_codes`
- **可选键**：`version`、`extract_method`、`source_params`、`default_sources`、`filters`、`samples`、
  `vocab_provenance`、`_comment`
- **缺键行为分两级（现状，不是理想态）**：
  - 结构键缺 → `KeyError`（未包装成 `RulesetConfigError`）；
  - `source_params.<源>.<语言键>` 缺 → `RulesetConfigError`。
  两级并存是当前实现，本轮只登记；要统一须改代码，届时单独提。
- **`reject_codes` 的最低集**：必须含 `missing_time / out_of_window / missing_url / missing_excerpt /
  unparsed_action / unparsed_subject / subject_not_in_text / not_an_event`（en 即这 8 个）；
  `filters` 里用到的每个 `key` 也必须能在 `reject_codes` 里取到（zh 另扩 13 个 `zh_*` 码）。
- **新增语言要新增什么**：一个 `rulesets/<lang>.json`（上列必需键）、该语言的 `source_params`、
  `extract_method` 标识，以及该语言的基准样本；引擎不加语言分支。
- **已有成文材料（就地引用，不复制）**：
  - 中文判据与样本分类：[event_definition_zh.md](event_definition_zh.md)（§ 复算段给出 `rulesets/zh.json` 与 `rules_v2-zh.1` 的口径）；
  - 英文回归锁：[tests/run_ruleset_regression.py](../../tests/run_ruleset_regression.py)（97 条逐条一致）；
  - 中文规则评测：[eval_zh_rules.py](eval_zh_rules.py)。

## 8. 我认为**不该**定死的条目（附理由）

1. **去重阈值数值**（`jaccard_min`、`day_tolerance`）：与语言/语料相关，是调参对象。
   只定"阈值必须来自规则集"，不定具体值。
2. **源清单与 `source_id` 命名**：接源会持续变化。只定"每条 raw 必须带稳定 `source_id`"，
   不定有哪些源。
3. **`value.kind` 的具体枚举**：量化类型会扩。只定"新 kind 必须先在 `schema.md` 登记"。
4. **抽取器实现**（`rules_v2` / `model_v1`）：已在 `extract_method` 里标注。
   只定"同一份 `events.json` 不混用"，不锁死用哪种。
5. **拒绝原因的完整清单**：模型抽取器已经加了 `schema_invalid` 等。
   只定"新 reason 必须登记到 `schema.md` §4，且不得用于给含糊条目找台阶"。
6. **`raw_items.json` 的字段全集**：它是诊断/复跑产物、不入库。
   只定最小集：`title / date / link / excerpt / fetched_at_utc / source_id`。

## 9. 与现有实现的偏差登记（只登记，不修改）

| 偏差 | 位置 | 影响 | 本轮处理 |
|---|---|---|---|
| 抓取时刻缺失与事件时刻缺失共用 `missing_time` | `build_event` L755–757、`validate_event` L848–849 | 调用方无法从拒绝码区分缺的是哪一个 | 按现状写入 §2，不改代码 |
| 规则集结构键缺失抛 `KeyError`，语言键缺失抛 `RulesetConfigError` | `Ruleset.__init__` L45–82、`_need` L173–179 | 错误类型不统一，捕获方要两种都接 | 按现状写入 §7，不改代码 |

本轮**未发现**"契约与现有代码根本对不上、必须改代码才能成立"的条目。
若后续出现，先上报再动，不在契约文档里假装成立。
