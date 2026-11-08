# 接口层 · 可依赖接口文档（v1）

> 创建日：2026-11-08 ｜ 依据代际：壳前置能力（`phase0/timeline` + `phase0/registry`）｜ 最后实质修订：2026-11-08
>
> 本文只写**现有代码真实撑得住**的接口。凡是"希望它长成这样"的设计，一律不写进来；撑不住的地方集中列在
> [§5](#5-现有代码撑不起这份文档的地方建议不改代码)，不动 `phase0/timeline/` 与 `phase0/registry/` 一行代码。

## 0. 一分钟结论

| 能力 | 入口 | 能给出什么 | 一句话边界 |
|---|---|---|---|
| 事件时间线 | `phase0/timeline/timeline.py` | 结构化事件表（`events.json`：meta + events + rejects）+ 人读稿 | **条件性可用**：只有标题输入时 recall 0.875 / precision 0.778、26.1% 判不了；补到「标题 + 正文首段」后 recall 0.833 / precision 0.833、判不了 4.3%——按输入条件两行分开看（详见 §2.6） |
| 事件注册闭环 | `phase0/registry/cli.py` | 注册 / 到期核验 / 对账；append-only 哈希链账本 | 判据必须写成结构化字段；三种状态 `hit` / `miss` / `undetermined`，判据之外的话不参与判定 |

两者都是**本机进程内调用**，不常驻、无服务端、无账号。壳（Tauri 或任何前端）只要能把 Python 子进程拉起来就能用；
不要指望它们提供 HTTP 服务——现有代码没有任何 server 入口。

---

## 1. 通用约定（两条能力都适用）

| 项 | 事实 | 依据 |
|---|---|---|
| 调用形态 | 命令行进程 / Python 函数调用，**非 HTTP** | `timeline.py` 只有 `argparse` 入口；`registry` 只有 `cli.py` 与模块函数 |
| 时刻口径 | 所有写入时刻由调用方显式传入，脚本**不读系统时钟** | `registry/timeutil.py`、`registry/ledger.py` `append(at=...)` |
| 落盘位置 | timeline 写 `--out-dir` 三件；registry 写 append-only `.jsonl` 账本 | `timeline.py` `write_outputs`；`registry/ledger.py` |
| 第三方原文 | `raw_items.json` 与 `out*/` 目录不入库，只有指纹与派生字段对外 | `.gitignore`、`phase0/timeline/out/.gitignore` |

**时区提醒（真实存在的坑）**：`timeutil.parse_iso_utc` 接受任意带时区的 ISO 串并换算成 UTC 日期用于判定，
但账本里 `at` 字段是**原样字符串**，不归一。传 `2026-11-07T23:40:00+09:00` 也能跑通并落账。
调用方**只应传 `...Z`**，否则账本上看到的时刻与判定用的 UTC 日期会在字面上不一致。

---

## 2. 能力一：事件时间线

### 2.1 签名（以现有实现为准）

**进程入口**

```
python phase0/timeline/timeline.py \
  --topic "<主题词>" | --entity "<主体词>" \
  --start YYYY-MM-DD --end YYYY-MM-DD \
  [--sources google_news,bing_news,clinicaltrials,federal_register,arxiv,yahoo_finance,cnbc] \
  [--max-per-source 60] [--out-dir phase0/timeline/out] \
  [--replay <raw_items.json>]
```

**库入口（可直接 import，但形状受限）**

```python
import argparse, sys
sys.path.insert(0, "phase0/timeline")
import timeline

ns = argparse.Namespace(
    topic="clinical trial", entity=None,
    start="2026-10-20", end="2026-11-08",
    sources="google_news,bing_news,clinicaltrials,federal_register",
    max_per_source=60, out_dir="phase0/api/demo/out_replay",
    replay=None,          # 有值则离线复跑，不联网
)
rc = timeline.run(ns)     # -> int，退出码；结果写在 out_dir 的文件里，不 return 数据
```

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `topic` / `entity` | str / None | 二者其一 | `topic` 走主题默认源组合；`entity` 走股价新闻默认源组合，并对文本做「主体必须出现」过滤 |
| `start` / `end` | `YYYY-MM-DD` | 是 | 闭区间；`start > end` 直接返回 2 |
| `sources` | 逗号分隔 | 否 | CLI 的 `main()` 会补默认值；**直接调 `run()` 时必须自己填**，填 `None` 会在 `args.sources.split` 处炸掉 |
| `out_dir` | 路径 | 否 | CLI 默认 `phase0/timeline/out`；直接调 `run()` 必须自己填 |
| `replay` | 路径 | 否 | 读既有 `raw_items.json` 离线复跑，不联网；本次实测与联网跑**逐项计数完全一致**（145/55/87/3） |

**返回结构**：`run()` 只返回退出码（`0` / `2` / `3`，`3` = 全部源失败）；真实产出是 `out_dir` 下三个文件。

```jsonc
// events.json
{
  "status": "ok",                  // ok / partial / failed；判定规则见 §2.2
  "meta": {
    "query": "...", "mode": "topic|entity",
    "window_start": "YYYY-MM-DD", "window_end": "YYYY-MM-DD",
    "generated_at_utc": "YYYY-MM-DDTHH:MM:SSZ",     // 本次运行时刻
    "extract_method": "rules_v2",
    "sources": ["google_news", "..."],
    "sources_stats": {                              // 逐源：抓了多少、入表几、拒几、有没有报错
      "google_news": {"fetched": 60, "accepted": 0, "rejected": 0},
      "bing_news":   {"fetched": 11, "accepted": 0, "rejected": 0,
                      "error": "ProxyError: ..."}    // 只有失败时才有 error 键
    },
    "stats": {"raw_items": 145, "events": 55, "rejects": 87,
              "merged_duplicates": 3, "reject_reasons": {"unparsed_action": 30}}
  },
  "events": [ /* 见 schema.md §2：event_id/time/subject/action/... /sources[] */ ],
  "rejects": [ {"source_id","title","url","date","reason"} ]
}
```

事件对象的字段 owner 是 [schema.md](file:///c:/Users/24063/Desktop/Trae-CN-Project/OmniNexus/phase0/timeline/schema.md)，本文不复述、不改写。
`events.md` 是人读稿（按日分组），`raw_items.json` 是抓取原始条目（**含第三方原文，不入库**）。

### 2.2 三种失败态（各自对应真实产生的状态）

失败态由**顶层 `status`**（`ok / partial / failed`）与 `sources_stats` / `rejects` 一起表达。
只看 `events.length == 0` 会把三种情况混成一种；`--replay` 恒为 `status == "ok"`。

| 失败态 | 进程表现 | 判定依据（真实字段） | 退出码 |
|---|---|---|---|
| **① 无数据** | 跑完了，什么都没抓到 | `status == "ok"` 且所有被请求源 `fetched == 0`、**没有 `error` 键**；`stats.raw_items == 0`。此时 `events` 为空才是真"没有事件" | `0` |
| **② 数据不可达 / 部分失败** | 部分源失败，结果只覆盖成功的源 | `status == "partial"`：至少一个源有 `error`、至少一个没有 | `0` |
| **② 数据不可达 / 全部失败** | 全部源失败，仍写出三个文件供排障 | `status == "failed"`：所有被请求源都有 `error` | **`3`** |
| **③ 判不了** | 抓到了，但没进表 | `rejects[].reason` 属于 §2.3 的闭集 | `0` |

**退出码 `2` 只用于调用方式错误**：`--start > --end`、既无 `--topic` 也无 `--entity`、`--sources` 里写了未知源名。
**`status == "partial"` 时退出码仍是 `0`**，且结果只覆盖成功的源——这个坑没消失，只是变得可识别，壳必须读 `status`（见 §5.0-A）。

### 2.3 拒绝态闭集（真实产出对照）

`schema.md §4` 现在是 **8 种**（规则抽取器）+ **2 种**（模型抽取器 `extract_model.py`）。逐条对照代码后：

| reason | 出现在哪 | 本次实跑是否观察到 |
|---|---|---|
| `out_of_window` | 事件时间不在窗口 | ✅ 50 条 |
| `unparsed_action` | 全文无任何动作词 | ✅ 30 条 |
| `not_an_event` | 标题以 Why/How/Opinion 开头或以问号结尾 | ✅ 4 条 |
| `missing_excerpt` | 摘要去空白后 < 20 字符 | ✅ 2 条 |
| `unparsed_subject` | 动作词前取不出主体 | ✅ 1 条 |
| `missing_time` | 时间缺失或不可解析 | 代码可达，本轮 0 条 |
| `missing_url` | URL 缺失或不是 http(s) | 代码可达，本轮 0 条 |
| `subject_not_in_text` | 指定 `--entity` 但文本里没出现 | 仅 `--entity` 模式可达 |
| `schema_invalid` | 仅模型路线 `extract_model.py` | 本轮未跑模型路线 |
| `missing_excerpt`（模型版） | 片段非原文逐字子串 | 同上 |

`duplicate` **不在这张表里**：合并项的内容已入表、URL 仍在 `sources[]`，只计入 `meta.stats.merged_duplicates`；
同一条不该既算入表又算拒绝，所以 `rejects` 的语义是"抓到了但没进表"。

### 2.4 成本与延迟（实测）

| 项 | 值 | 来源 |
|---|---|---|
| 金额 | **0 元**（全部公开源无 key、无边车；模型路线为本机 Ollama） | 本次实跑，无任何计费接口 |
| 联网模式总耗时 | **18.3 s**（4 源 / 145 条原始条目 / 3 周窗口）；冷启动首轮明显更慢（量级 2–3 倍，未单独留存计时文件，标 C 级） | 本次实测 `timeline.py --topic "clinical trial"` |
| 离线复跑（`--replay`） | **0.79 s**，无网络 | 本次实测 replay 运行 |
| 模型抽取（可选路线） | **1.2–1.8 s/条、0 元/条**；首条有一次性加载开销（探针首条 74.45 s） | [benchmark.md §6.5.3](file:///c:/Users/24063/Desktop/Trae-CN-Project/OmniNexus/phase0/timeline/benchmark.md) |
| 部署依赖 | 模型路线需本机 `ollama serve`（`http://127.0.0.1:11434`）且已拉取 `svjack/Qwen3-4B-Instruct-2507-heretic:latest`；规则路线无此依赖 | 本次探针：`models=8`、目标模型在位 |

延迟随窗口长度、源数量、`--max-per-source` 线性变化，源间有 1.2 s 固定间隔（`time.sleep(1.2)`）。
**不要按"每条固定耗时"做容量估算**——耗时主要在抓取，不在抽取。

### 2.5 输出可信度（哪些字段能当依据）

| 字段 | 能依赖吗 |
|---|---|
| `source_url` + `fetched_at_utc` + `excerpt` | 能：三条齐备才入表，缺一即拒绝 |
| `event_id` | 能：`subject+action+time+首条url` 的 sha256 前 16 位，同输入同 id |
| `action` | **半能**：动作准确率 0.857（只有标题 6/7）、0.700（标题 + 正文首段 7/10）；机构类标题易被判成 `trial_start` |
| `subject` | **半能**：准确率 1.000（只有标题 7/7）、0.900（标题 + 正文首段 9/10），但会把"类别"当主体误入表（B05/B16，两轮都在） |
| `value.number` | 谨慎：规则路线取"最早出现的数值片段"，不保证绑定到该动作 |
| `sources[]` | 谨慎：去重只在新闻源之间做，Jaccard 0.55 是拍的阈值（阈值合理性属未核实项） |

### 2.6 质量边界（原样写，不许美化）

**这一节就是"条件性可用"的全部内容，壳做产品决定时必须照这段来。**

第四套样本 `def`（2025-11-01 → 2026-01-31，**n=23**，测前先定定义）。同一批 23 条、同一套定义、同一个模型，
**只换输入**，两轮各自只测一次；结果文件分别是 `benchmark_def_model_result.json` 与 `benchmark_def_body_model_result.json`。

| 输入条件 | 判不了占比 | 召回（主口径 / 备查口径） | 精确（主口径） |
|---|---|---|---|
| 只有标题 | 26.1%（6/23） | 0.875（7/8）/ 0.500（7/14） | 0.778（7/9） |
| 标题 + 正文首段 | 4.3%（1/23） | 0.833（10/12）/ 0.769（10/13） | 0.833（10/12） |

**两行都要留，因为输入条件是产品必须做的选择**：能拿到正文按第二行，只能拿到标题按第一行。
只写第二行会让人以为随便抓点什么都行——第二行成立的前提是"每条都取到发布方正文首段"，这需要额外的抓取与清洗。

可计条目（主口径 / 备查口径）：只有标题轮 **8 / 14**，标题 + 正文首段轮 **12 / 13**；两轮都只有 23 条样本，**不外推**。

其余指标按同一口径分列（下限沿用 0.70 / 0.45 / 0.70 / 0.60 / 0.60）：

| 输入条件 | strict recall（主 / 备查） | action accuracy | subject accuracy |
|---|---|---|---|
| 只有标题 | 0.750（6/8）/ 0.429（6/14） | 0.857（6/7） | 1.000（7/7） |
| 标题 + 正文首段 | 0.583（7/12）/ 0.538（7/13） | 0.700（7/10） | 0.900（9/10） |

**口径差异照实说**：

- **只有标题轮**：主口径五项过线，但分母只剩 8 条事件；备查口径 recall 两项未达标（0.500 / 0.429）。
- **标题 + 正文首段轮**：主口径与备查口径**五项都过线**（`benchmark.md §6.7.2`），但这一轮是重测量、不是第二次机会。

**判不了的两档**：

- 只有标题：23 条里 6 条落"判不了"（6/23 = 26.1%），全部卡在"能不能算事件"这一层，而不是抽取算法。
- 标题 + 正文首段：只补了这 6 条的 `excerpt`，其中 5 条变为可判、1 条仍判不了（B10，正文里也没有可用的载体线索），降到 1/23 = 4.3%。

换成一句可交付的话：

> 只有标题时，它能把 8 条里的 7 条抓出来，但会**漏掉「机构声明」这一类**，并在**「类别被当成主体」时误入表**；
> 对只有标题且无动作的条目，它**偏向拒绝**。
> 能补到正文首段时，判不了降到 1/23、精确升到 0.833，但**仍会漏机构声明、仍会把类别当主体**。

具体失效类型（逐条可查两份结果文件的 `rows`）：

| 失效类型 | 只有标题 | 标题 + 正文首段 |
|---|---|---|
| 漏机构声明 | B07（`…, says ABPI`，人工标 `policy`）被判 `not_an_event` | B07 仍被判 `not_an_event`（漏） |
| 把类别当主体 | B05（`Private equity` 是类别不是具名主体）、B16（`Alzheimer's drug developers` 未具名）误入表 | B05、B16 仍误入表 |
| 无动作标题偏向拒绝 | 论文题、声明题、指引题一律按 `not_an_event` 拒绝 | B22（评选结果）仍被判 `not_an_event`；B10 仍判不了 |
| 动作错判 | 机构/资源类标题的 `launch` 被判成 `trial_start`（val 集 3 条同形） | B13（`funding`→`partnership`）、B14、B20 三条动作错（7/10） |

**规则路线也别指望**：`rules_v1` 在 test 集 0.462 / 0.154 / 0.600、`rules_v2` 在 val 集 0.615 / 0.154 / 0.889，
两个未参与调参的窗口都不达标。**模型路线 `model_v1` 在 val 集三项未达标**（recall 0.538 / 0.308、action 0.571）。
调优集达标只能当"能跑"，不能当"能用"——这是本项目已经踩过的坑。

**根因（已定位，不在本层能修）**：只有标题轮的瓶颈在输入——def 窗口 23/23 条 `excerpt == title`，
Google News 历史检索不回摘要，所以 26.1% 的条目缺"动作/载体线索"。补正文首段的第二轮证明：
要提升可判定率，得先解决"每条都带正文首段"，不是换模型、不是补词表；但那一步的抓取覆盖与入库口径尚未产品化。

**补正文那轮的已知污染（照实登记，不隐去）**：标注者同时是上一轮模型输出的读者，这层污染无法用时间戳封住；
6 条正文段的来源页面由标注者挑选，属测量条件的人为选择。时序只能保证"标注与指纹先落盘、模型后运行"。
正文段落按预注册条款**不入库**，仓库内可核的是逐条来源与指纹（`benchmark.md §6.7.1` 的表格与 `def_body_sources.json`）。

**因此"条件性可用"的准确读法**：
- 可依赖：**"给出带来源的事件候选表"**，用于人工复核、作为线索而非结论；
- 不可依赖：**"自动判断某事件一定发生过 / 一定没发生"**，也**不可依赖**"没抓到 = 没发生"。

---

## 3. 能力二：事件注册闭环

### 3.1 签名（以现有实现为准）

**进程入口**

```
python phase0/registry/cli.py [--ledger <path>] <command> ...

  register   --payload '<json>' | --payload-file <path>   --at <ISO8601 带时区>   # 必填
  verify     --at <ISO8601 带时区>  [--id <id>]
  reconcile  [--json] [--point-min 20]
  list
  chain-check
```

**库入口（四件事都有对应函数）**

```python
sys.path.insert(0, "phase0/registry")
import ops, ledger, reconcile

record = ops.build_registration(payload: dict, at: str, ledger_path) -> dict
    # 拒绝时抛 ops.RegistrationRejected，异常带 .code / .message

results = ops.verify_all(at: str, ledger_path, only_id: str | None = None) -> list[dict]

summary = ops.reconcile(ledger_path, point_min=20) -> dict

report  = ledger.verify_chain(ledger_path) -> {"ok","count","problems","head_sha256"}
```

`payload` 的字段（多一个都拒，少一个也拒）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | `^[A-Za-z0-9][A-Za-z0-9._:-]{2,63}$` | 唯一；重复即 `DUPLICATE_ID` |
| `claim` | str ≥4 字符 | **只给人看，不参与判定**；命中含糊词表即拒 |
| `registered_at` | ISO8601 带时区 | 申报时刻 |
| `expires_on` | `YYYY-MM-DD` | 到期日 |
| `criterion` | object | 判定全部读它，字段表见 [syntax.md](file:///c:/Users/24063/Desktop/Trae-CN-Project/OmniNexus/phase0/registry/syntax.md) §2 |
| `provenance` | object，可选 | `{kind: live\|backfill_selftest, note}`，只允许这两个键 |

**返回结构**

```jsonc
// register 成功（stdout，exit 0）
{"status":"registered",
 "record":{"at","kind":"registration","id","claim","claim_canonical","registered_at","expires_on",
           "criterion","criterion_sha256",
           "source_probe":{"provider","id","field","url","fetched_at_utc","sha256","rows","first","last","from_process_cache"},
           "provenance","prev_record_sha256"},
 "ledger":"..."}

// verify（stdout，exit 0）—— not_due 与 frozen 也占 counts 的位置
{"at":"2026-11-07T23:20:00Z",
 "counts":{"not_due":1,"hit":1,"undetermined":1},
 "results":[
   {"id":"REG-API-DEMO-01","status":"not_due","verdict":null,"reason_code":null,
    "detail":"REG-API-DEMO-01 未到期：2026-11-07 早于结算日 2026-12-03"},
   {"id":"REG-API-DEMO-02","status":"hit","verdict":"hit","reason_code":null,"value":5.31},
   {"id":"REG-API-DEMO-03","status":"undetermined","verdict":"undetermined",
    "reason_code":"WINDOW_NOT_COVERED","value":null}]}
```

`status` 有 5 个值，**其中两个不是判定**：
- `not_due`：还没到 `expires_on + settlement_lag_days`，不落账；
- `frozen`：该 id 已有 `hit`/`miss`，判定冻结，重跑被拒（防"重复跑到命中"）。

判定记录落账时还带 `observed`（窗口、n、首末观测日、聚合值）与 `source_fingerprint`（URL/sha256/行数/首末日）。

### 3.2 三种失败态

**registry 把"无数据 / 不可达 / 判不了"统一收敛到一个状态 `undetermined`**，靠 `reason_code` 分桶。
这是真实存在的收敛，不是文档美化——所以壳层必须读 `reason_code`，不能只看 `status`。

| 失败态 | registry 状态 | 真实原因码 | 观察点 |
|---|---|---|---|
| **① 无数据** | `undetermined` | `NO_OBSERVATIONS_IN_WINDOW`（窗口内一条都没有）、`SOURCE_EMPTY`（清洗后为空）、`INSUFFICIENT_OBSERVATIONS`（少于 `min_observations`）、`WINDOW_NOT_COVERED`（窗口末与最后观测间隔超 `coverage_slack_days`） | 取到数了，但窗口没被数据覆盖 |
| **② 数据过期 / 不可达** | `undetermined` | `SOURCE_UNREACHABLE` / `SOURCE_HTTP` / `SOURCE_PARSE` / `SOURCE_FIELD_MISSING` | 根本没拿到可用响应 |
| **③ 判不了** | `undetermined` | `AGGREGATE_UNDEFINED`（`pct_change` 首条观测为 0） | 数据齐了，但在数学/口径上无定义 |

**注册那一刻的失败态（更严格）**：不能判的预测**根本进不了账本**，stdout 无输出、stderr 打 `rejected [CODE]: message`、退出码 `2`。
错误码清单（A1–A21）见 [syntax.md](file:///c:/Users/24063/Desktop/Trae-CN-Project/OmniNexus/phase0/registry/syntax.md) §3，本次实跑验证的四个：

| 场景 | 错误码 | 实测输出 |
|---|---|---|
| 含糊句子 | `VAGUE_CLAIM` | `claim 含含糊表述 ['大概率', '大概率上涨']` |
| 数据源当下取不到 | `SOURCE_HTTP` | `数据源当下取不到，拒绝注册：HTTP 404（…id=NOSUCHSERIES）` |
| live 注册晚于到期日 | `REGISTRATION_AFTER_EXPIRY` | `live 注册在到期日 2026-11-05 之后才写入（2026-11-07）` |
| 查一个不存在的 id | `ID_NOT_FOUND` | `账本里没有 id NOPE` |

`undetermined` 的纪律：**不进命中率分母，也不许在报告里折算成 `miss`**。

### 3.3 成本与延迟（实测，不是估算）

| 项 | 实测 | 方法 |
|---|---|---|
| 金额 | **0 元**（FRED / Yahoo 公开接口，无 key） | — |
| 单次 FRED 取数（大序列 DGS10，16197 行） | **0.24–0.48 s**（3 次：0.479 / 0.240 / 0.321） | `sources.probe` 3 次，每次先 `reset_cache()` |
| 单次 FRED 取数（小序列 GASREGW，1884 行） | **0.13–0.15 s**（3 次：0.135 / 0.150 / 0.133） | 同上 |
| 单次 Yahoo 取数（XBI，5222 行） | **0.90–1.04 s**（3 次：1.042 / 0.905 / 1.042） | 同上 |
| 进程级 `verify`（3 条：1 条真取数 + 1 条落账 + 1 条 not_due） | **2.03 / 3.00 s**（两次实测，同一账本重建后复跑，结果逐字段一致） | 端到端计时 |
| 进程级 `verify --id`（命中冻结，无网络） | **1.95 / 2.24 s**（两次实测） | 端到端计时 |
| 进程级 `verify --id`（网络掐死，走失败分支） | **3.98 s** | 端到端计时 |
| 单次取数超时 | `TIMEOUT = 90 s`，**无重试** | `sources.py` |

**由此推得的容量口径**：`verify` 的耗时 ≈ 2 s 固定开销 + 逐条取数（同进程内同一序列只抓一次，有进程内缓存；
跨进程不缓存）。**不要按"每条 0.2 s"估算**——每个注册条目至少要一次真实网络往返。

### 3.4 质量边界

| 能保证 | 不能保证（原样承认） |
|---|---|
| 判据可执行、结论可复算（`criterion_sha256` 校验，判据被改即 `CRITERION_TAMPERED`） | **句子与判据的语义错配机器查不出**：`claim` 说"上涨"而判据写成 `lte` 也照样落账 |
| `hit`/`miss` 一旦落账即冻结 | 累计命中率是**描述性统计**，不做显著性检验、不做多重比较校正；n < 20 只报 Wilson 区间、不报点估计 |
| 注册时校验"当下能抓、字段在" | **"可获得" ≠ "数据新鲜"**。新鲜度只在核验阶段靠 `WINDOW_NOT_COVERED` 兜底（月度序列天然滞后一个月以上） |
| 含糊词表拦截典型写法 | 词表是**启发式**，挡不住故意绕开的表述；真正的防线是"判据必须结构化" |
| `chain-check` 能证明账本行未被改动 | **哈希锁的是原始行文本**：把账本读进来重新 `json.dumps` 再写回（哪怕内容等价）→ `ok=false`（本层实测过，重排后立即失效）。壳层展示账本时**只读不重写** |

**只支持 FRED 与 Yahoo 两类源**。新增源不是"加个字符串"——要在 `sources.py` 的 `PROVIDERS` 登记并实现解析与字段约定。

**对账口径**：`hit_rate` 的 `n` 只含 `hit+miss`；`undetermined` 单列；`no_verdict`（注册了但没核验过）单列。三者混算就错。

---

## 4. 三个真跑通的调用（原始输出，长行截断处已标）

> 全部在仓库根目录执行，时刻为 2026-11-07（UTC）。数据随时变化，**重跑数字会不同**，重跑一致性由 `--replay` 离线模式保证。

### 调用 1 · 给定主题出时间线

```
$ python phase0/timeline/timeline.py --topic "clinical trial" --start 2026-10-20 --end 2026-11-08 \
    --out-dir phase0/api/demo/out_timeline
[fetch] google_news: 60 条
[fetch] bing_news: 11 条
[fetch] clinicaltrials: 60 条
[fetch] federal_register: 14 条

[result] raw=145 events=55 rejects=87 merged=3 reasons={'unparsed_action': 30, 'out_of_window': 50,
         'not_an_event': 4, 'unparsed_subject': 1, 'missing_excerpt': 2}
[write] phase0\api\demo\out_timeline\events.json
[write] phase0\api\demo\out_timeline\events.md
[write] phase0\api\demo\out_timeline\raw_items.json
# 退出码 0，总耗时 18.3 s
```

入表事件的关键字段（`excerpt` 与 `source_url` 只示形状，不贴原文）：

```jsonc
{"event_id":"8c5a50f98821…","time":"2026-10-20","time_precision":"minute",
 "subject":"AstraZeneca","action":"trial_start","action_text":"launch","object":null,
 "value":{"kind":"none","raw":null,"number":null,"unit":null},
 "source_url":"https://news…","url_kind":"aggregator","source_name":"AstraZeneca",
 "fetched_at_utc":"2026-11-07T2…","excerpt":"AstraZeneca …","excerpt_kind":"summary",
 "extract_method":"rules_v2","sources":[{…}]}
```

**同一份 `raw_items.json` 离线复跑，计数逐项一致**（这是可复算的证据，不是印象）：

```
$ python -c "…timeline.run(Namespace(replay='phase0/api/demo/out_timeline/raw_items.json', …))"
[replay] 读取 145 条：phase0/api/demo/out_timeline/raw_items.json

[result] raw=145 events=55 rejects=87 merged=3 reasons={'unparsed_action': 30, 'out_of_window': 50,
         'not_an_event': 4, 'unparsed_subject': 1, 'missing_excerpt': 2}
[write] phase0\api\demo\out_replay\events.json
return code = 0 function
# 耗时 0.79 s，无网络
```

**失败态 ①（无数据）——喂一个拿不到数据的主题：**

```
$ python phase0/timeline/timeline.py --topic "zzqxvbn nonexistent topic 9000" \
    --start 2026-10-20 --end 2026-11-08 --out-dir phase0/api/demo/out_empty
[fetch] google_news: 0 条
[fetch] bing_news: 0 条
[fetch] clinicaltrials: 0 条
[fetch] federal_register: 0 条

[result] raw=0 events=0 rejects=0 merged=0 reasons={}
# 退出码 0
```

返回的**不是空结果而已**：`sources_stats` 四个源全是 `{"fetched":0,"accepted":0,"rejected":0}` 且**没有 `error` 键**
→ 这是"源可达但确实没有匹配条目"，即 **①无数据**。

**失败态 ②（数据不可达 / 全部失败）——把出口网络掐死：**

```
$ $env:HTTPS_PROXY="http://127.0.0.1:9"; python phase0/timeline/timeline.py --topic "clinical trial" \
    --start 2026-10-20 --end 2026-11-08 --sources google_news,federal_register \
    --out-dir phase0/api/demo/out_unreachable
[fetch] google_news: FAIL ProxyError: HTTPSConnectionPool(host='news.google.com', port=443): Max retries exceeded…
[fetch] federal_register: FAIL ProxyError: HTTPSConnectionPool(host='www.federalregister.gov', port=443): Max retries …

[result] raw=0 events=0 rejects=0 merged=0 reasons={}
[status] failed  sources={"google_news": {…,"error":"ProxyError: …"}, "federal_register": {…,"error":"ProxyError: …"}}
[status] FAILED: 全部源抓取失败，本次结果无证据力（退出码 3）
# 退出码 3  ← 全部源失败：status=failed，退出码 3
```

```jsonc
"sources_stats": {
  "google_news":      {"fetched":0,"accepted":0,"rejected":0,"error":"ProxyError: HTTPSConnectionPool(host='news.google.com', port=443): Max retries exceeded…"},
  "federal_register": {"fetched":0,"accepted":0,"rejected":0,"error":"ProxyError: HTTPSConnectionPool(host='www.federalregister.gov', port=443): Max retries …"}
}
```

**同样的 `events: []`，三种情况现在由顶层 `status` 区分：`ok`（真无数据）、`partial`（部分源失败，只覆盖成功源）、`failed`（全部失败，退出码 3）。壳若只看 `events.length` 仍会误报"没新闻"。**

**失败态 ③（判不了）**：见调用 1 主输出里的 `rejects=87` 与 `reject_reasons`——抓到了、但 30 条无动作词、
50 条超窗口、4 条是评论稿、1 条取不出主体、2 条摘要太短。逐条带 `reason` 落盘，不进 `events`。

**失败态 ①/② 在 `--entity` 模式下同形，且更隐蔽**（这是 §5-⑤ 那条硬伤的直接证据）：

```
$ python phase0/timeline/timeline.py --entity "NOTAREALTICKER123" --sources yahoo_finance \
    --start 2026-10-20 --end 2026-11-08 --out-dir phase0/api/demo/out_badsrc_entity
[fetch] yahoo_finance: 0 条
[result] raw=0 events=0 rejects=0 merged=0 reasons={}
[status] ok  sources={"yahoo_finance": {"fetched": 0, "accepted": 0, "rejected": 0}}
# 退出码 0，status=ok、没有 error 键 —— 与"这个主体确实没新闻"仍无法区分
```

### 调用 2 · 注册一条机器可判的预测

```
$ python phase0/registry/cli.py --ledger phase0/api/demo/demo.ledger.jsonl register \
    --payload-file phase0/api/demo/payload_register.json --at 2026-11-07T23:00:00Z
{
  "status": "registered",
  "record": {
    "at": "2026-11-07T23:00:00Z",
    "kind": "registration",
    "id": "REG-API-DEMO-01",
    "claim": "10 年期美债收益率在 2026 年 10 月整月内出现过不低于 4.0% 的读数",
    "claim_canonical": "FRED:DGS10 在 2026-10-01 至 2026-10-31 窗口内，窗口内最大观测值 ≥ 4 percent（至少 15 个观测）",
    "registered_at": "2026-11-07T23:00:00Z",
    "expires_on": "2026-11-30",
    "criterion": { … },                      // 与 payload 一致，逐字段归一化后的深拷贝
    "criterion_sha256": "ba28dea40748eac7157ccbea14e9493e978adb09689dbcf6fde7fc1e5be60ad0",
    "source_probe": {
      "provider": "fred", "id": "DGS10", "field": "value",
      "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
      "fetched_at_utc": "2026-11-07T23:00:00Z",
      "sha256": "b475ba7f607331389c112cdf0f3bfea981eaab609de34645b49dfd02e9797ea4",
      "rows": 16197, "first": "1962-01-02", "last": "2026-11-05", "from_process_cache": false
    },
    "provenance": {"kind": "live", "note": "接口层演示调用"},
    "prev_record_sha256": null
  },
  "ledger": "phase0/api/demo/demo.ledger.jsonl"
}
# 退出码 0
```

**失败态 ③（判不了）在注册口就被挡下** —— 含糊句子进不了账本：

```
$ … register --payload-file phase0/api/demo/payload_reject_vague.json --at 2026-11-07T23:05:00Z
rejected [VAGUE_CLAIM]: claim 含含糊表述 ['大概率', '大概率上涨']；判据必须机器可判，含糊句子在注册这一刻就拒绝
# 退出码 2，账本零新增字节
```

**失败态 ②（数据不可达）在注册口就被挡下** —— 用一个不存在的美联储序列：

```
$ … register --payload-file phase0/api/demo/payload_reject_source.json --at 2026-11-07T23:06:00Z
rejected [SOURCE_HTTP]: 数据源当下取不到，拒绝注册：HTTP 404（https://fred.stlouisfed.org/graph/fredgraph.csv?id=NOSUCHSERIES）
# 退出码 2
```

**第四个拒绝（时间线自相矛盾）** —— 拿一条已过期的判据当 `live` 注册：

```
$ … register --payload-file phase0/api/demo/payload_reject_late.json --at 2026-11-07T23:07:00Z
rejected [REGISTRATION_AFTER_EXPIRY]: live 注册在到期日 2026-11-05 之后才写入（2026-11-07）；
         历史补录必须标 provenance.kind=backfill_selftest
# 退出码 2
```

### 调用 3 · 对已到期的一条做核验与对账

演示账本按纪律先落一条 `backfill_notice`（写明补录时刻、覆盖范围、"原始实时注册时刻不可考"），
再放两条**已到期**的回填记录（`provenance.kind=backfill_selftest`）。

```
$ python phase0/registry/cli.py --ledger phase0/api/demo/demo.ledger.jsonl verify --at 2026-11-07T23:20:00Z
{
  "at": "2026-11-07T23:20:00Z",
  "counts": {"not_due": 1, "hit": 1, "undetermined": 1},
  "results": [
    {"id": "REG-API-DEMO-01", "status": "not_due", "verdict": null, "reason_code": null,
     "detail": "REG-API-DEMO-01 未到期：2026-11-07 早于结算日 2026-12-03"},
    {"id": "REG-API-DEMO-02", "status": "hit", "verdict": "hit", "reason_code": null, "value": 5.31},
    {"id": "REG-API-DEMO-03", "status": "undetermined", "verdict": "undetermined",
     "reason_code": "WINDOW_NOT_COVERED", "value": null}
  ]
}
# 退出码 0，耗时 2.03 s
```

三条走完三条路：`REG-API-DEMO-01` 还没到结算日（`not_due`，不落账）；`REG-API-DEMO-02` 的 DGS10 窗口被数据覆盖，
`observed` 为窗口 2026-10-01～10-30、n=21、首末观测 10-01/10-30，聚合 `max` = 5.31 ≥ 4.0 → `hit`；
`REG-API-DEMO-03` 的 GASREGW 周度序列 `observed` 只有 n=4、最后观测 2026-10-26，而窗口末是 2026-10-30，
间隔 4 天 > `coverage_slack_days=0` → **失败态 ①（窗口没被数据覆盖）**，`WINDOW_NOT_COVERED`。

对账（**只读，不核验**）：

```
$ python phase0/registry/cli.py --ledger phase0/api/demo/demo.ledger.jsonl reconcile
| 指标 | 数值 |
|---|---|
| 注册数 | 3 |
| 已判定 | 1 |
| 命中 hit | 1 |
| 未命中 miss | 0 |
| 无法判定 undetermined | 1 |
| 尚无判定 | 1 |

命中率：1 条可判中 1 条命中；按 Wilson 方法 95% 区间 21%–100%；样本不足以给点估计

| 事件 | 来源 | 判定 | 原因码 |
|---|---|---|---|
| REG-API-DEMO-01 | fred:DGS10 | — | — |
| REG-API-DEMO-02 | fred:DGS10 | hit | — |
| REG-API-DEMO-03 | fred:GASREGW | undetermined | WINDOW_NOT_COVERED |
```

注意 `reconcile` 自己也会说"样本不足以给点估计"（n=1）——这不是我加的修饰，是现有代码的输出。

**判定冻结**（对已 `hit` 的条目重跑）：

```
$ … verify --id REG-API-DEMO-02 --at 2026-11-07T23:25:00Z
{"at":"2026-11-07T23:25:00Z","counts":{"frozen":1},
 "results":[{"id":"REG-API-DEMO-02","status":"frozen","verdict":"hit","reason_code":null}]}
# 退出码 0；耗时 2.24 s（无网络，命中冻结）
```

**失败态 ②（不可达）在核验阶段** —— 对 `undetermined` 条目补跑，且掐死网络：

```
$ $env:HTTPS_PROXY="http://127.0.0.1:9"; … verify --id REG-API-DEMO-03 --at 2026-11-07T23:30:00Z
{"at":"2026-11-07T23:30:00Z","counts":{"undetermined":1},
 "results":[{"id":"REG-API-DEMO-03","status":"undetermined","verdict":"undetermined",
             "reason_code":"SOURCE_UNREACHABLE","value":null}]}
```

同一个 `undetermined`，原因码从 `WINDOW_NOT_COVERED` 变成 `SOURCE_UNREACHABLE` —— 两种失败态在 registry 里
**共用同一个状态**，只能靠 `reason_code` 区分。补跑耗时 3.98 s（含启动、pandas 导入与失败的连接尝试）。

**账本完整性只读校验**：

```
$ … chain-check
{"ok": true, "count": 6, "problems": [], "head_sha256": "1bc752cc6ad78d70ad6bc37f6e7969d25714c27e4eb81516c1f2d91ced04e963"}
# 退出码 0
```

### 覆盖对照表

| 要求 | 调用 | 展示的失败态 |
|---|---|---|
| 给定主题出时间线 | 调用 1 | —（成功）+ **①无数据** + **②不可达** + **③判不了（87 条 rejects）** |
| 注册一条机器可判的预测 | 调用 2 | **③判不了（VAGUE_CLAIM）** + **②不可达（SOURCE_HTTP 404）** + 时间线矛盾拒绝 |
| 对已到期的一条核验对账 | 调用 3 | **①数据没覆盖窗口（WINDOW_NOT_COVERED）** + **②不可达（SOURCE_UNREACHABLE）** + 判定冻结 |

---

## 5. 现有代码撑不起这份文档的地方（建议，不改代码）

**这些是硬伤，不在本层修，按约定只登记。** 每条形如「现在什么样 / 为什么会误导 / 最小修法」。

### 5.0 已修复缺陷的残留约束（调用方仍必须遵守）

**A. 源全挂退出 0 —— 已修复（`99c84eb`）**：`events.json` 顶层新增 `status`（`ok / partial / failed`），
全部被请求源失败时返回 `3`，三个文件照写供排障；`--replay` 恒为 `ok`。
但 **`partial` 的退出码仍是 `0`**，且结果只覆盖成功的源——这个坑没消失，只是变得可识别了。
**所以任何调用方仍必须看 `status`，不能只看退出码与 `events` 数量**：
`ok` → `events` 为空才是真"没有事件"；`partial` → 标注"只覆盖部分源"；`failed` → 不得当作结果。

| # | 现象（现状） | 为什么会误导下游 | 最小修法（待作者裁决） |
|---|---|---|---|
| ① | timeline **没有库级 API**：`run(args: Namespace) -> int`，返回退出码，结果只能读文件；`args.sources` / `args.out_dir` 为 `None` 时直接崩 | 调用方必须伪造 `argparse.Namespace` 8 个字段并知道 CLI 的默认值逻辑；壳层容易被"函数返回 0 = 成功"骗到 | 加一层 `run_topic(topic, start, end, sources=None) -> (meta, events, rejects)` 薄包装，内部仍调 `run()` |
| ② | registry 把"无数据 / 不可达 / 判不了"**统一收敛到 `undetermined`** | 壳层必须自己维护 `reason_code` 分桶表，否则界面上三种完全不同的事会显示成同一句"无法判定" | 在 `evaluate.py` 输出里加 `reason_class: "no_data"\|"unreachable"\|"undefined"`（不新增状态，只加分类字段） |
| ③ | `syntax.md §五` 写"`undetermined` 允许补跑**一次**"，但 `ops.verify_one` 只拦 `hit`/`miss`，对 `undetermined` **可无限次补跑** | 文档的"一次"是纪律承诺，代码没兑现；下游可能据此假设"最多两条记录" | 在 `verify_one` 里查 `retry_of_undetermined` 是否已存在，存在即拒；或把文档改成"可多次补跑，每次带 supersedes" |
| ④ | 账本 `at` 字段**原样写入**，不归一 UTC（`2026-11-07T23:40:00+09:00` 实测可跑通并落账） | 账本上看到的时刻与判定用的 UTC 日期字面不一致；哈希链锁的是非归一字符串 | `ledger.append` 里对 `at` 做 `parse_iso_utc(at).isoformat()` 归一后再写；或在 `timeutil` 拒收非 `Z` 结尾 |
| ⑤ | timeline 的 `--entity` 模式默认源是 `yahoo_finance,google_news,cnbc`，对不存在的标的**静默返回 0 条**（实测 `NOTAREALTICKER123` → 0 条、无 error） | 与"这个标的没新闻"无法区分；下游会误判为"该主体无事件" | 参考 §5.0-A 的思路：把"查询词毫无命中"与"源正常但无匹配"分开标注 |
| ⑥ | `sources.py` `TIMEOUT=90`、**无重试**、无退避 | 单条核验最坏要等 90 s×条数；批量 `verify_all` 在源半死时会长时间卡住 | 加 `retries=1` + 指数退避，或把 timeout 收到 15–20 s 并按条计失败 |

**另有一条不是硬伤但必须知道**：`timeline.py` 的动作判定是"全局最早命中"，`launch` 出现在机构类标题里会被判成
`trial_start`（val 集 3 条同形）。这是**已登记的方法层缺口**（`benchmark.md §8`），不属于接口问题，
但它决定了 §2.6 里 `action` 只能"半依赖"。

---

## 6. 本次实跑的证据与不可复核项

| 项 | 位置 | 可复核性 |
|---|---|---|
| 三个调用的命令与原始输出 | 本文 §4 | B 级（文档原文）；数字为当次真实运行，源数据随时间变化 |
| 演示账本（注册 + 判定 + 哈希链） | `phase0/api/demo/demo.ledger.jsonl` | A 级，可 `chain-check` 复核 |
| 三条拒绝用的 payload | `phase0/api/demo/payload_reject_*.json` | B 级，可原样重跑 |
| 取数耗时（FRED / Yahoo） | 本文 §3.3 | A 级，脚本可重跑（见下） |
| 模型路线 1.2–1.8 s/条、0 元 | `phase0/timeline/benchmark.md §6.5.3` | A 级，原始结果文件在 `phase0/timeline/benchmark_*_model_result.json` |
| 质量数字（两轮：只有标题 0.875 / 0.778 / 26.1%；标题 + 正文首段 0.833 / 0.833 / 4.3%） | `phase0/timeline/benchmark.md §6.6.1`（只有标题）+ `§6.6.2`（结论）+ `§6.7.1`（预注册与污染登记）+ `§6.7.2`（补正文结果） | A 级，原始结果 `benchmark_def_model_result.json` / `benchmark_def_body_model_result.json`，标注 `benchmark_labels_def.json` / `benchmark_labels_def_body.json`；补正文段落本身不入库，仅有来源与指纹 |
| 运行状态 `status` 与退出码（`failed` → 3、`ok` → 0） | `phase0/timeline/timeline.py` L716-727 / L789-791 | A 级，`failed` 与 `ok` 各一次实跑已复核；`partial → 0` 未单独实跑，为 B 级（代码原文） |
| timeline 的 `out*/` 产物与 `raw_items.json` | 本地 `phase0/api/demo/out_*/` | **不入库、不作为对外证据**（含第三方原文片段）；只有计数进本文 |

重测取数耗时的最小脚本（不改任何现有代码）：

```python
import sys, time
sys.path.insert(0, "phase0/registry")
import sources as S
for prov, sid, fld in [("fred","DGS10","value"), ("yahoo","XBI","adjclose")]:
    S.reset_cache(); t0 = time.perf_counter()
    series, fp = S.probe(prov, sid, fld, "2026-11-07T22:50:00Z")
    print(prov, sid, round(time.perf_counter() - t0, 2), "s", fp["rows"], fp["last"])
```
