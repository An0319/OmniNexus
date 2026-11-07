# 事件时间线 · 基准集与判定下限

> 创建日：2026-11-08 ｜ 依据代际：壳前置能力（phase0/timeline） ｜ 最后实质修订：2026-11-08
> 下限在 §3 写成时确定，**早于任何一次评测运行**。测完照实报，达不到就报达不到。

## 1. 基准集怎么来的（不许编）

- 数据来自 `probe_sources.py` / `timeline.py` 实测抓取的真实快照（`out*/raw_items.json`，不入库），抓取时刻见每个条目的 `fetched_at_utc`。
- 抽样规则写死在 `build_benchmark.py`：只取新闻源、时间窗内、摘要 ≥20 字的条目，按 `(时间, 源, 标题)` 排序后**等间隔**抽取 25 条，从第 1 条开始。规则固定，避免挑样本。
- 标注由人工逐条完成，只依据条目的标题与摘要原文（`benchmark_labels_*.json`），不参考抽取器输出。
- 每条标注四件：`event`（是否为一个具体时点事件）、`subject`、`action`（用 `schema.md` 动作闭集）、`value_kind`。
- 动作标注口径：论文/预印本标题（"Effects of …"、"Phase 2b Trial of …"）记 `publication`；报道试验数据结果记 `trial_result`。两者在标题上常无动词，属标注口径而非抽取错误，评测时照此比对。

## 2. 开发集 / 留出集 / 验证集

| 集合 | 窗口 | 来源 | 用途 | 状态 |
|---|---|---|---|---|
| dev | 2026-10-01 → 2026-11-08 | Google News + Bing News（25 条） | 暴露规则缺口、修词表 | 已标注、已测 |
| test（留出） | 2026-06-01 → 2026-08-31 | Google News 历史窗口（`after:/before:`，24 条） | 冻结规则只测不改 | 已标注、已测 |
| val（第三窗口） | 2026-02-01 → 2026-04-30 | Google News 历史窗口（`after:/before:`，25 条） | 验证 v2 词表，未参与调参 | 已标注、已测 |

纪律：dev 上改规则可以；test 上只测不改。若 test 结果不达标，照实写不达标，并登记"下一轮该补什么"，不改规则后重测同一个 test。

- 读法示例：test 用 `rules_v1` 测过一次即冻结，之后补了 `rules_v2` 词表，**没有**用 v2 回头重测 test——那等于改规则后重测同一留出集，会把留出集变成第二个开发集。v2 只在第三个从未参与调参的窗口（val）上测。
- 词表版本：`rules_v1` = 依据 dev 失败清单扩过的一版；`rules_v2` = 再依据 test 失败清单补的一版（`study finds`、`helped…lose`、`weight loss`、`FDA clearance`、收紧 `first patient`、删裸 `dose`、`not_an_event` 增 `you` / `here's what`）。**v2 的修订依据来自 test**，因此它本身带过拟合风险，必须在未参与调参的窗口上单独验。

## 3. 判定下限（先于评测写定）

| 指标 | 下限 | 为什么是这个数 |
|---|---|---|
| lenient recall | ≥ 0.70 | 人工标为事件的条目，至少七成要进表（字段可能错） |
| strict recall | ≥ 0.45 | 规则抽取器从标题+摘要出发，字段全对的门槛不能定得虚高 |
| lenient precision | ≥ 0.70 | 入表十条最多三条不是事件，否则表就没法用 |
| action accuracy | ≥ 0.60 | 已入表且对上的条目里，动作类别六成以上要对 |
| subject accuracy | ≥ 0.60 | 主体 token 覆盖率 ≥60% 视为合格，六成以上条目要合格 |

未列 strict precision 下限：样本太小，strict 口径留作观察项。

## 4. 指标口径

- lenient recall = 人工事件中被入表的比例
- strict recall = 人工事件中「入表 + action 对 + subject 合格 + value_kind 对」的比例
- lenient precision = 入表条目中人工也标为事件的比例
- strict precision = 入表条目中「action 对 + subject 合格」的比例
- subject 合格 = 人工主体 token 至少 60% 出现在抽取主体里（去停用词、忽略大小写）

## 5. 已知局限（写在前头）

- 样本是单主题、单语言区、单次快照，n=24~25；不能外推到"整个新闻抽取都行/不行"。
- 标注由单人所做，没有第二人复核；边界条目（报告更新、会议预告、获奖公告、官方声明）的标签本身可争议，已逐条写了 note。
- 规则抽取器不理解语义，只认词表与位置；反讽、隐喻、否定句（"did not fail"）都会错判。
- val 的历史窗口抓取量很小：3 个月只拿到 26 条，等于抽样几乎全取（间隔 1）。因此 val 的数值更像"这 26 条如此"，不是对三个月新闻总体的估计（R16）。

## 6. 实跑结果（命令 + 输出，逐集合照录）

### 6.1 dev（`rules_v1`）

```
python phase0/timeline/eval_benchmark.py --items phase0/timeline/benchmark_items.json \
  --raw phase0/timeline/out/raw_items.json --labels phase0/timeline/benchmark_labels_dev.json \
  --start 2026-10-01 --end 2026-11-08 --out phase0/timeline/benchmark_dev_result.json
```

| 指标 | 下限 | 实测 | 判定 |
|---|---|---|---|
| lenient recall | 0.70 | 0.882 | 过 |
| strict recall | 0.45 | 0.471 | 过 |
| lenient precision | 0.70 | 0.938 | 过 |
| action accuracy | 0.60 | 0.800 | 过 |
| subject accuracy | 0.60 | 0.800 | 过（strict precision 0.500，观察项） |

dev 是调优集，这里的数字只能说明"规则在这 25 条上够用"，不能当作泛化证据。

### 6.2 test（`rules_v1` 冻结，2026-06-01→08-31）

```
python phase0/timeline/eval_benchmark.py --items phase0/timeline/benchmark_items_test.json \
  --raw phase0/timeline/out_test/raw_items.json --labels phase0/timeline/benchmark_labels_test.json \
  --start 2026-06-01 --end 2026-08-31 --out phase0/timeline/benchmark_test_result.json
```

| 指标 | 下限 | 实测 | 判定 |
|---|---|---|---|
| lenient recall | 0.70 | **0.462** | **未达标** |
| strict recall | 0.45 | **0.154** | **未达标** |
| lenient precision | 0.70 | **0.600** | **未达标** |
| action accuracy | 0.60 | 0.667 | 过 |
| subject accuracy | 0.60 | 0.667 | 过 |

未达标主因（逐条见 `benchmark_test_result.json`）：

- 漏（可归因词表）：`helped people lose`、`study finds`、`advances trial`、`FDA clearance`、`child dies`、`Stock Pops` 类标题在 v1 里没有触发词 → `unparsed_action`。
- 误（可归因词表）：`first patient` 裸词命中患者故事、`dosing` 命中用药解释稿、`Guest Commentary:` 未被 `not_an_event` 拦下。
- 不可归因：论文标题无动词（`Phase 2b Trial of a NaV1.8 Inhibitor`）、主体在标题里根本没出现（`Bundibugyo virus disease trial`）。

### 6.3 val（`rules_v2`，2026-02-01→04-30，未参与调参）

```
python phase0/timeline/timeline.py --topic "clinical trial" --start 2026-02-01 --end 2026-04-30 \
  --sources google_news --max-per-source 100 --out-dir phase0/timeline/out_val
python phase0/timeline/build_benchmark.py --raw phase0/timeline/out_val/raw_items.json \
  --start 2026-02-01 --end 2026-04-30 --out phase0/timeline/benchmark_items_val.json
python phase0/timeline/eval_benchmark.py --items phase0/timeline/benchmark_items_val.json \
  --raw phase0/timeline/out_val/raw_items.json --labels phase0/timeline/benchmark_labels_val.json \
  --start 2026-02-01 --end 2026-04-30 --out phase0/timeline/benchmark_val_result.json
```

| 指标 | 下限 | 实测 | 判定 |
|---|---|---|---|
| lenient recall | 0.70 | **0.615** | **未达标** |
| strict recall | 0.45 | **0.154** | **未达标** |
| lenient precision | 0.70 | 0.889 | 过 |
| action accuracy | 0.60 | **0.500** | **未达标** |
| subject accuracy | 0.60 | 0.750 | 过（strict precision 0.222，观察项） |

val 未达标的新增主因（与 test 不同）：

- 动作词表把 `launch/launches` 一律判 `trial_start`，于是"PAHO 启动加速器""Mizzou 上线资源""发布试验改革"三条机构/政策动作全被判成 `trial_start` → 动作准确率 0.5。
- 问句只在**标题末尾**检测，标题中段的问句（`Should My Child Join a Clinical Trial? What Parents Need to Know`）漏过，成为唯一 FP。
- 机构声明（`MHRA statement on Pathways clinical trial`）、政府目标（`Government drives forward its 150-day …`）在词表里没有锚点 → `unparsed_action` 漏掉。

### 6.4 规则抽取器：三个集合放在一起看

| 集合 | 规则 | lenient recall | strict recall | lenient precision | action acc | subject acc |
|---|---|---|---|---|---|---|
| dev | rules_v1 | 0.882 | 0.471 | 0.938 | 0.800 | 0.800 |
| test | rules_v1（冻结） | 0.462 | 0.154 | 0.600 | 0.667 | 0.667 |
| val | rules_v2 | 0.615 | 0.154 | 0.889 | 0.500 | 0.750 |

结论（A 级，来自上表的实跑数字）：**同一个抽取器在调优集上五项达标，在两个未参与调参的窗口上都没有达到下限**。因此当前状态只能宣称"命令能跑通、字段可核、有显式失败态"，**不能宣称"时间线质量达标"**。

### 6.5 模型抽取（`model_v1`，本机 Ollama）

#### 6.5.1 接口可用性（先于效果确认）

| 项 | 实测 |
|---|---|
| 端点 | `http://127.0.0.1:11434`（Ollama 本地 HTTP API，`/api/chat`） |
| 本机模型数 | 8 个（`model_probe.json` 的 `models_available` 全列） |
| 选型 | `svjack/Qwen3-4B-Instruct-2507-heretic:latest`（探针里唯一 3/3 JSON 合法且摘要逐字命中 3/3 的 4B 模型；`mgraffam/qwen3.5-opus4.6` 单条 14.5–15.7s 且摘要逐字 2/3 失败，未采用） |
| 计费 | 无 API key、无调用计费；成本只有电费与占机时间 |
| `format` 传 JSON Schema 是否强制 `enum` | **不强制**。实测（A 级）：给 `enum:["approval","halt"]`，模型仍返回 `{"action":"Trial X halted by sponsor"}`。因此闭集靠提示词全列 + 代码校验兜，不靠解码器 |

探针命令与产物：`python phase0/timeline/probe_model.py` → `phase0/timeline/model_probe.json`（只存延迟、token 数、JSON 合法与否、摘要是否逐字，不存模型输出原文）。

#### 6.5.2 抽取口径（与规则抽取器同一套字段与拒绝态）

- 模型只决定"是不是事件、主体、动作、动作锚点、宾语、定量值、拒绝理由"这 8 项；其余字段由代码补齐。
- 代码侧硬校验：`time` 取源发布时间（不采信模型自报的时间）；`excerpt` 必须是原文逐字子串且 ≥20 字；`subject` 必须在原文出现；`action` 必须落在 `schema.md` 闭集内。
- 不合法先做一次修复重试（把全枚举与失败原因塞回提示词）；仍不合法 → `schema_invalid` 显式拒绝，不猜。
- 抽不出 → 模型返回 `is_event=false` + `reject_reason`（`not_an_event` / `unparsed_action` / `unparsed_subject` 三选一），代码照写进 `rejects`。

#### 6.5.3 命令与成本

```
python phase0/timeline/eval_benchmark.py --items phase0/timeline/benchmark_items_dev.json \
  --raw phase0/timeline/out/raw_items.json --labels phase0/timeline/benchmark_labels_dev.json \
  --start 2026-10-01 --end 2026-11-08 --extractor model \
  --cache phase0/timeline/out_model/model_cache_dev2.json \
  --out phase0/timeline/benchmark_dev_model_result.json

python phase0/timeline/eval_benchmark.py --items phase0/timeline/benchmark_items_val.json \
  --raw phase0/timeline/out_val/raw_items.json --labels phase0/timeline/benchmark_labels_val.json \
  --start 2026-02-01 --end 2026-04-30 --extractor model \
  --cache phase0/timeline/out_model/model_cache_val.json \
  --out phase0/timeline/benchmark_val_model_result.json
```

| 成本项 | dev（25 条） | val（25 条） |
|---|---|---|
| 单条耗时均值 | 1.27s | 1.15s |
| 单条耗时最大 | 1.85s | 1.86s |
| 输出 token 均值 | 78.1 | 70.6 |
| 每条费用 | 0 元（本机推理，无计费） | 0 元 |
| **可用于在线接口** | **可用**：1.2–1.8s/条、0 元/条，无网络依赖（本机 Ollama） | **可用**：1.2–1.8s/条、0 元/条 |

模型首次调用有一次性加载开销（探针首条 74.45s）；`warm_up()` 已单列，不计入单条耗时。

#### 6.5.4 dev 结果（调优集，可改口径）

```
{"n_items": 25, "n_labeled_events": 17, "n_emitted": 14,
 "lenient_recall": 0.765, "strict_recall": 0.529, "lenient_precision": 0.929,
 "strict_precision": 0.643, "action_accuracy": 0.846, "subject_accuracy": 0.769}
```

五项下限全部达标（A 级，`benchmark_dev_model_result.json`）。达成路径是三版迭代：v1 只靠 `format` 传 schema → `action` 出枚举外、`action_text` 出数组、缺字段，0 条入表；v2 改提示词全列闭集 + 代码校验 + 一次修复重试 → lenient recall 0.706 / strict 0.353 / action 0.500；v3 加动作逐值释义、冲突消解规则、两条 few-shot → 上表数字。

#### 6.5.5 val 结果（未参与调参，只测一次）

```
{"n_items": 25, "n_labeled_events": 13, "n_emitted": 7,
 "lenient_recall": 0.538, "strict_recall": 0.308, "lenient_precision": 1.000,
 "strict_precision": 0.571, "action_accuracy": 0.571, "subject_accuracy": 1.000}
```

| 指标 | 下限 | 实测 | 判定 |
|---|---|---|---|
| lenient recall | 0.70 | **0.538** | **未达标** |
| strict recall | 0.45 | **0.308** | **未达标** |
| lenient precision | 0.70 | 1.000 | 过 |
| action accuracy | 0.60 | **0.571** | **未达标** |
| subject accuracy | 0.60 | 1.000 | 过 |

val 未达标的主因（A 级，逐条见结果文件 `rows`）：13 条人工事件里有 6 条被模型自己判成 `not_an_event`（B02 NIH 重新定义临床试验、B06 MHRA 声明、B11 公共卫生期间试验指引、B12 论文标题、B20 FDA 要求上报结果）、1 条 `unparsed_subject`（B01 论文标题）。模型对"论文题/声明题/指引题"一律按 `is_event=false` 拒绝：precision 满分（7 条入表全对）、subject 满分，但 recall 掉到 0.538。动作偏差与规则路线同形：7 条入表里 B19（PAHO 启动加速器）、B21（Mizzou 上线资源）、B22（Government drives forward…）三条机构/资源类动作被判成 `trial_start`，只有 B04/B23/B24/B25 动作对（0.571）。

结论（照实报，未下调门槛）：**`model_v1` 在 val 上五项中三项未达标，模型路线以当前口径判定为未通过**。dev 与 val 的落差与规则路线同形——调优集达标、留出窗口不达标。本集合已用掉唯一一次验证机会，不得再以调参后的 `model_v1.x` 回测 val。

### 6.6 定义先定、再抽第四套样本（预注册块）

> 本块写于抽样之前、结果为空时。写入时刻 UTC `2026-11-07T22:38:34Z`。
> 事件定义文件：`phase0/timeline/event_definition.md`，SHA256 `caa8bf7f609aa1249caa2954cbfec14a13dafce1dfb0118409376524a321c8d9`（5251 bytes）。该文件在本块写定后、抽样本前不再修改。

**为什么重开一套**：dev / test / val 三套的标注口径在本轮被证明存在未裁决分歧——被模型拒绝的条目集中在「论文题 / 机构声明 / 指引文件 / 监管条款」四类，这四类算不算事件在旧口径里从来没有机械判据。用旧标签再测，测到的是标注者口语习惯，不是抽取质量。

**第四套样本（`def`）**：

- 时间窗：`2025-11-01 → 2026-01-31`（与 dev / test / val 三个月度窗口完全不重叠，且未被任何一轮抽取或标注碰过）。
- 抽样：`build_benchmark.py` 的固定规则（只取新闻源、等间隔 25 条），不自选。
- 标注：只依据条目自带的 `title` + 摘要片段，按 `event_definition.md` §3 的三步流程；**不参考任何模型输出**（模型输出在标注完成后才生成）。
- 三态标注：`event=true`（算）/ `event=false`（不算）/ `event=null`（判不了，写 `note` 说明卡在 S 还是 A）。

**计分（先写死，不改）**：

- 下限沿用 §3 的五个数：lenient recall 0.70 / strict recall 0.45 / lenient precision 0.70 / action accuracy 0.60 / subject accuracy 0.60。
- 主口径：`判不了` 条目不进 recall / precision 任一方向的分母，单报 `n_undecidable`。
- 备查口径：`判不了` 按"不算"计，一并报 `alt_*` 五个数。
- 只测一次。测完 `def` 冻结，不论过没过；结果不回填、不重打分、不据以下调门槛。

**标注完成记录**：`2026-11-07T22:40:41Z` 完成 23 条标注（`benchmark_labels_def.json`，SHA256 前 16 位 `af41d14761946da1`），**此时模型尚未在新样本上跑过一次**。

**被测对象**：`extract_model.py` 的 `model_v1`，口径不动（提示词、闭集、修复重试、拒绝态一律不改）。若未过，结论写成"在现有定义与现有模型下，本能力上限是多少"，不再出第三版。

#### 6.6.1 结果（只测这一次）

命令（结果文件 `benchmark_def_model_result.json`）：

```
python phase0/timeline/eval_benchmark.py --items phase0/timeline/benchmark_items_def.json \
  --raw phase0/timeline/out_def/raw_items.json --labels phase0/timeline/benchmark_labels_def.json \
  --start 2025-11-01 --end 2026-01-31 --extractor model \
  --cache phase0/timeline/out_model/model_cache_def.json \
  --out phase0/timeline/benchmark_def_model_result.json
```

| 指标 | 下限 | 主口径（判不了不计入分母） | 判定 | 备查口径（判不了按不算） | 判定 |
|---|---|---|---|---|---|
| lenient recall | 0.70 | 0.875（7/8） | 过 | **0.500**（7/14） | **未达标** |
| strict recall | 0.45 | 0.750（6/8） | 过 | **0.429**（6/14） | **未达标** |
| lenient precision | 0.70 | 0.778（7/9） | 过 | 0.700（7/10） | 过（贴线） |
| strict precision | — | 0.667（6/9） | — | 0.600（6/10） | — |
| action accuracy | 0.60 | 0.857（6/7） | 过 | 0.857 | 过 |
| subject accuracy | 0.60 | 1.000（7/7） | 过 | 1.000 | 过 |

样本构成：23 条抽样，`算` 8 条 / `不算` 9 条 / `判不了` 6 条。

**输入质量事实（A 级）**：23 条的摘要片段与标题**逐字相同**（`excerpt == title`，23/23）。本窗口的 Google News 历史检索只回标题、不回摘要，所以定义表里"动作/载体线索"能检的东西变少——6 条判不了全部卡在 A（论文题、趋势分析、中心公告、`new initiative`、评选榜）。

逐条要点：

- 8 条 `算` 里 7 条入表且动作/主体对（B01、B02、B11、B18、B19、B21 全对；B13 入表但动作判 `partnership`、人工标 `funding`）。
- 漏 1 条：B07（`…, says ABPI`，人工按 §4 落 `policy`），模型判 `not_an_event`。
- 2 条误入表：B05（`Private equity` 是类别不是具名主体）、B16（`Alzheimer's drug developers` 未具名）。
- 6 条 `判不了` 里模型拒 5 条、误入 1 条（B14）。

#### 6.6.2 结论（不宣称达标，两个口径都报）

主口径五项过线，但**这是"排除判不了"后的窄口径**：分母只有 8 条事件，其中 6 条 `判不了` 被剔除（占抽样的 26%）。备查口径下 recall 两项未达标（0.500 / 0.429）。

因此本轮的准确结论是两句，不是一句：

1. **在"能判定"的条目上，`model_v1` 的表现是：recall 0.875、precision 0.778、动作准确率 0.857、主体准确率 1.000。**
2. **在现有定义 + 现有模型 + 只有标题的输入下，本能力上限是：26% 的条目判不了、可判定条目里约每 4 条有 1 条该入表却没入（或误入）。** 换成一句可交付的话：**它能把 8 条里的 7 条抓出来，但会漏掉"机构声明"这一类，并在"类别被当成主体"时误入表；对只有标题且无动作的条目，它偏向拒绝，与规则路线同一失效模式。**

按预注册，`def` 现在冻结：不重打分、不据此调口径、不出第三版。

### 6.7 换输入重测（`def_body`）：预注册块

§6.6 的结论把瓶颈指到输入：23/23 条 `excerpt == title`，6 条判不了全卡在 A（既看不出动作，也看不出发布载体）。本轮**只换输入**，其余全部冻结。

#### 6.7.1 预注册（先于模型运行）

**冻结项（本轮一个字没动）**

- `event_definition.md`：SHA256 `caa8bf7f609aa1249caa2954cbfec14a13dafce1dfb0118409376524a321c8d9`（与 §6.6 登记值相同）。
- `extract_model.py` 的 `model_v1` 提示词与闭集校验；模型 `svjack/Qwen3-4B-Instruct-2507-heretic:latest`，`temperature 0`。
- §3 的五个下限（0.70 / 0.45 / 0.70 / 0.60 / 0.60）。

**唯一改动：补 6 条判不了条目的 `excerpt`**

- 补全规则：取发布方页面正文首段——连续原文，上限 2000 字符，不拼接、不改写、不翻译；抓不到正文的如实记「该源不可补」。
- 抽样不变：仍是 §6.6 的同一套 23 条，`id` / 标题 / URL / 日期 / 来源字段一律不动，只替换这 6 条的 `excerpt`。
- 正文段按预注册条款**不入库**。仓库内可核的是逐条来源与指纹（`def_body_sources.json`，SHA256 前 16 位 `0edfbeebd60087b4`）：

| id | 来源 | 取用方式 | 字符数 | excerpt SHA256 前 16 位 |
|---|---|---|---|---|
| B06 | `https://www.nature.com/articles/s41591-025-04106-7` | requests 取正文段落（选择器） | 1708 | `b0ae7148d1a3edd1` |
| B10 | `https://pmc.ncbi.nlm.nih.gov/articles/PMC12680696/` | requests 取整页文本（关键词处连续切片） | 2000 | `d1da6e33275ca4a7` |
| B12 | `https://www.nature.com/articles/d41573-025-00208-6` | requests 取整页文本（关键词处连续切片） | 2000 | `741b70a537fdf720` |
| B14 | `https://www.ucl.ac.uk/population-health-sciences/clinical-trials-and-methodology/about/mrc-centre-research-excellence-clinical-trial-innovation-partnership-nihr` | WebFetch（本机请求被 403） | 494 | `35063469c272fb28` |
| B20 | `https://www.thebraintumourcharity.org/brain-tumour-diagnosis-treatment/treating-brain-tumours/clinical-trials/act-bt/` | requests 取正文首段 | 165 | `367cf5c84b7cd1a0` |
| B22 | `https://www.pennmedicine.org/news/four-penn-studies-named-among-nations-top-clinical-research-advances` | WebFetch（本机请求被拦截页挡住） | 216 | `df457b3c4461ed9b` |

- 取回结果与上表指纹不一致，即视为不可复算。
- 输入噪声照实登记：B12 的 2000 字符切片含登录墙文案与页面招聘位（属页面上连续原文，未裁剪），这既是它能拿到 DOI 题录的原因，也是它的噪声来源；B10 的切片在摘要之后延续到 `Subject terms` 与通俗摘要。

**重标规则（只重判被补全的 6 条，其余 17 条标注不变——它们的 `excerpt` 未变）**

- 判据仍是 `event_definition.md` §2 / §3 / §4，逐条机械应用。
- S 是硬闸（§3 第 2 步先于 A）：**期刊名本身不作具名承担者**，判例是 §6.6 的 B04（`A2 有载体线索但 S 不过 → 不算`）。
- A2 成立需同时满足两件：文本里有载体线索（期刊名 / `published in` / DOI / 预印本库名 / 官方发布页域名）**且**条目 URL 指向该载体。本批条目 URL 是 Google News 聚合页，因此「只在标题尾部出现刊名」不构成 A2。

**重标结果（先落盘，后跑模型）**

- `benchmark_labels_def_body.json`，SHA256 前 16 位 `406e21aecda8729d`；标注完成时刻 **2026-11-07T23:02:05Z**。
- 构成：`算` 12 条 / `不算` 10 条 / `判不了` 1 条（B10）。
- 6 条逐条落格：B06 → `算`（`trial_result`）；B14 / B20 / B22 → `算`（`other`）；B12 → `不算`（S 不过，A2 的两个条件也不成立）；B10 → 仍 `判不了`。
- **上述标注写入时，模型尚未在本批输入上运行过一次。** 结果见 §6.7.2。

**本轮纪律**：这是重测量，不是第二次机会。测完即冻结——不据此改提示词、不换模型、不动门槛；若仍不过，直接写上限，不出第四版。

**已知污染（照实登记，不隐去）**：本轮标注者同时是上一轮模型输出的读者，这层污染无法用时间戳封住；时序只能保证「标注与指纹先落盘、模型后运行」。另外这 6 条正文段的来源页面由标注者挑选，属测量条件的人为选择。

## 7. 中途被推翻的判断（保留被推翻版本与理由）

1. **"dev 五项达标说明规则可用"**（原判断）→ 推翻。理由：dev 是调优集，词表就是照着它的失败清单补的；换到 test 立刻跌到 0.462 / 0.154 / 0.600。教训：调优集上的达标只能当"能跑"，不能当"能用"。
2. **"补上 test 失败清单里的词（v2）就能把 recall 拉回下限"**（原判断）→ 推翻。理由：val 上 recall 只到 0.615。词表补丁解决的是"漏了这个词"，解决不了"这条标题压根没有动作动词/主体"（论文题、声明题、目标题）。这属于方法层缺口，不是词表层缺口。
3. **"命中最早的动作词就是该事件的正确动作"**（`detect_action` 原设计）→ 部分推翻。理由：val 中 `launches` 出现在机构类标题里，最早命中即判 `trial_start`，但人工标为 policy/other；同一现象在 dev 被掩盖，因为 dev 的 `launch` 恰好都用在真试验上。改为"词+主语距离/宾语约束"需要新一轮设计，不在本批做。
4. **"去重能自动把同一事件的多家报道合成一条"**（原判断）→ 部分推翻。理由：dev 快照 165 条只合并了 2 条；WHO 埃博拉疫苗在 dev 内有 B14/B16 两条近重复未合并，因为标题 Jaccard 未达 0.55 且 Google News 每条 link 是不同聚合页 URL。阈值 0.55 是拍的，没有独立调过；它是否合适属未核实项。
5. **"另建 `other` 动作词表（death/award/earnings）就能提 recall"**（计划过、未采纳，C 级推演）→ 暂不采纳。理由：`other` 若与 `halt` 争最早命中位置，会把手上的 dev B11（"两例死亡后 Artiva 关停"，人工标 halt）判成 `other`；当前没有第二条证据说明该换。登记为下一轮待验证项，未实跑，故只算推断。
6. **"Google News 能把聚合链接解析回出版商原文"**（原判断，最早做可核性时）→ 推翻，见 `datasource_report.md`：完整链接 GET 后 final_url 仍是 `news.google.com`，页面无 `na-u` 标记；只能标 `url_kind=aggregator`。
7. **"词表补丁到头了，换模型就能过线"**（原判断，本批动手前）→ 推翻。理由：`model_v1` 在 dev 五项全过（0.765 / 0.529 / 0.929 / 0.846 / 0.769），换到未参与调参的 val 掉到 0.538 / 0.308 / 1.000 / 0.571 / 1.000，三项未达标。模型解决的是"论文题没有动词"这类语义缺口的一半（它能识别是论文，但按规则判 `not_an_event` 拒绝），没解决"声明题/指引题该不该算事件"的标注口径问题。换模型不等于换掉方法层缺口。
8. **"Ollama 的 `format` 传 JSON Schema 能强制枚举"**（原设计依赖）→ 推翻。理由：实测传 `enum:["approval","halt"]` 仍返回枚举外字符串；模型路线因此改为"提示词全列闭集 + 代码校验 + 一次修复重试"，闭集由代码而非解码器保证。
9. **"dev/test/val 的标签就是真实事件边界"**（原判断）→ 推翻。理由：被拒条目集中在论文题/机构声明/指引文件/监管条款四类，而整套资料里从未有过判定这四类的机械规则；用旧标签再测，测到的是标注者口径。故先写 `event_definition.md`（写入时刻与 SHA256 记在 §6.6），再抽第四套样本。

## 8. 下一轮该补什么（登记，不在本批做）

- 动作判定加距离约束（动作词必须与主语同段且宾语匹配），替代"全局最早命中"。触发条件：要提升 action accuracy 到 0.6 以上。
- `other` 词表（death / award / earnings / guidance 之外的机构动作）单独建，并用 dev+val 双窗口回归确认不与 `halt`/`policy` 抢位。
- 问句/评论稿识别从"标题末尾问号"扩到"标题内任意问号 + 首词表"，覆盖标题中段问句。
- 事件定义已落盘（`event_definition.md`），第四套样本 `def` 只测一次并冻结：主口径五项过线、备查口径 recall 两项未过；结论按 §6.6.2 的两句，不宣称达标。
- 下一步的瓶颈不在模型措辞，而在**输入只有标题**：本窗口 23/23 条无摘要，26% 落"判不了"。要提升可判定率，先解决"每条都带摘要"（换源或补抓正文单段），再谈模型。
- 历史窗口检索量偏小（3 个月 34 条、窗口内 23 条）：时间线要真正可用需多源补齐（Bing News / GDELT / 官方源已实测可用，GDELT 缺摘要不能进表）。
