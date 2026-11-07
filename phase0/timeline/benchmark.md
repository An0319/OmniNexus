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

### 6.4 三个集合放在一起看

| 集合 | 规则 | lenient recall | strict recall | lenient precision | action acc | subject acc |
|---|---|---|---|---|---|---|
| dev | rules_v1 | 0.882 | 0.471 | 0.938 | 0.800 | 0.800 |
| test | rules_v1（冻结） | 0.462 | 0.154 | 0.600 | 0.667 | 0.667 |
| val | rules_v2 | 0.615 | 0.154 | 0.889 | 0.500 | 0.750 |

结论（A 级，来自上表的实跑数字）：**同一个抽取器在调优集上五项达标，在两个未参与调参的窗口上都没有达到下限**。因此当前状态只能宣称"命令能跑通、字段可核、有显式失败态"，**不能宣称"时间线质量达标"**。

## 7. 中途被推翻的判断（保留被推翻版本与理由）

1. **"dev 五项达标说明规则可用"**（原判断）→ 推翻。理由：dev 是调优集，词表就是照着它的失败清单补的；换到 test 立刻跌到 0.462 / 0.154 / 0.600。教训：调优集上的达标只能当"能跑"，不能当"能用"。
2. **"补上 test 失败清单里的词（v2）就能把 recall 拉回下限"**（原判断）→ 推翻。理由：val 上 recall 只到 0.615。词表补丁解决的是"漏了这个词"，解决不了"这条标题压根没有动作动词/主体"（论文题、声明题、目标题）。这属于方法层缺口，不是词表层缺口。
3. **"命中最早的动作词就是该事件的正确动作"**（`detect_action` 原设计）→ 部分推翻。理由：val 中 `launches` 出现在机构类标题里，最早命中即判 `trial_start`，但人工标为 policy/other；同一现象在 dev 被掩盖，因为 dev 的 `launch` 恰好都用在真试验上。改为"词+主语距离/宾语约束"需要新一轮设计，不在本批做。
4. **"去重能自动把同一事件的多家报道合成一条"**（原判断）→ 部分推翻。理由：dev 快照 165 条只合并了 2 条；WHO 埃博拉疫苗在 dev 内有 B14/B16 两条近重复未合并，因为标题 Jaccard 未达 0.55 且 Google News 每条 link 是不同聚合页 URL。阈值 0.55 是拍的，没有独立调过；它是否合适属未核实项。
5. **"另建 `other` 动作词表（death/award/earnings）就能提 recall"**（计划过、未采纳，C 级推演）→ 暂不采纳。理由：`other` 若与 `halt` 争最早命中位置，会把手上的 dev B11（"两例死亡后 Artiva 关停"，人工标 halt）判成 `other`；当前没有第二条证据说明该换。登记为下一轮待验证项，未实跑，故只算推断。
6. **"Google News 能把聚合链接解析回出版商原文"**（原判断，最早做可核性时）→ 推翻，见 `datasource_report.md`：完整链接 GET 后 final_url 仍是 `news.google.com`，页面无 `na-u` 标记；只能标 `url_kind=aggregator`。

## 8. 下一轮该补什么（登记，不在本批做）

- 动作判定加距离约束（动作词必须与主语同段且宾语匹配），替代"全局最早命中"。触发条件：要提升 action accuracy 到 0.6 以上。
- `other` 词表（death / award / earnings / guidance 之外的机构动作）单独建，并用 dev+val 双窗口回归确认不与 `halt`/`policy` 抢位。
- 问句/评论稿识别从"标题末尾问号"扩到"标题内任意问号 + 首词表"，覆盖标题中段问句。
- 学习式抽取（模型参与）时，输出必须受 schema 约束解码，抽不出返回显式失败态；本批只做了规则基线，未接模型。
- 历史窗口检索量偏小（3 个月 26 条）：时间线要真正可用需多源补齐（Bing News / GDELT / 官方源已实测可用，GDELT 缺摘要不能进表）。
