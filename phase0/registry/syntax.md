# 判据语法 criterion/v1 与注册拒绝规则

> 创建日：2026-11-08 ｜ 依据代际：2026-11 事件注册闭环（D11 定位下的新能力，不改定位主句） ｜ 最后实质修订：2026-11-08

本文只回答三件事：一条预测由什么组成、判据怎么写、什么样的预测在注册那一刻就被拒绝。

---

## 一、一条预测的组成

```
预测 = claim（一句话）+ expires_on（到期日）+ criterion（结构化判据）
```

- `claim`：给人看的一句话，**不参与判定**。它唯一的作用是让人类读懂这条预测。
- `expires_on`：`YYYY-MM-DD`。到此日为止，这条预测要么成立、要么不成立、要么判不了。
- `criterion`：机器执行的全部语义。判定只读它，不读 `claim`。

另有两个记账字段：`registered_at`（申报时刻）与 `id`（唯一标识）。真实写入时刻由命令行
`--at` 传入，不写在请求里；两者不是一回事，见第四节。

### 为什么不允许「先收下再人工判」

含糊句子一旦被收下，后面每一步都会自动变成人工判断：取什么数、算哪个区间、阈值算不算达到，
全靠事后解释。事后解释无法与「看到结果再定口径」区分开。所以拒绝点必须前移到注册那一刻：
**写不出机器可执行的判据，就是还不能注册，而不是「待人工确认」。**

---

## 二、criterion 字段表

所有字段必填，没有隐藏默认值。多一个字段也会被拒绝（未声明的语义不实现）。

| 字段 | 类型 | 含义 |
|---|---|---|
| `syntax_version` | 字符串 | 固定 `criterion/v1` |
| `source.provider` | 字符串 | `fred` 或 `yahoo` |
| `source.id` | 字符串 | FRED 序列号（大写字母/数字/下划线）或 Yahoo 代码 |
| `source.field` | 字符串 | `fred` 固定 `value`；`yahoo` 固定 `adjclose` |
| `window.start` / `window.end` | `YYYY-MM-DD` | 观测窗口，**闭区间**，按观测日期筛选 |
| `aggregate` | 枚举 | `min` / `max` / `last` / `mean` / `pct_change` |
| `comparator` | 枚举 | `gte`（≥）/ `lte`（≤），含等号 |
| `threshold` | 有限数值 | 阈值；`pct_change` 时单位为百分比 |
| `unit` | 非空字符串 | 阈值单位，只用于人读，不参与计算 |
| `min_observations` | 整数 ≥1 | 窗口内至少要有多少条观测才允许判定 |
| `coverage_slack_days` | 整数 ≥0 | 窗口末日与「窗口内最后一个观测」之间允许的最大间隔天数 |
| `settlement_lag_days` | 整数 ≥0 | 到期日之后再过几天才允许核验（给数据发布留时间） |

### 判定语义（必须与 `evaluate.py` 逐条对得上）

1. **窗口**：取观测日期落在 `[start, end]` 闭区间内的全部观测。
2. **聚合**：
   - `min` / `max`：窗口内最小 / 最大观测值；
   - `last`：窗口内**最后一条**观测（不保证正好是窗口末日，节假日与数据滞后都会让日期提前）；
   - `mean`：窗口内观测算术平均；
   - `pct_change`：`(最后一条 / 第一条 - 1) × 100`，单位是百分比。
3. **比较**：`gte` 为 `值 ≥ 阈值`，`lte` 为 `值 ≤ 阈值`，均为闭区间。
4. **覆盖检查**：记 `gap = window.end − 窗口内最后一观测日期`。`gap > coverage_slack_days`
   即认为窗口没有被数据覆盖，判「无法判定」，不给结论。
5. **充分性检查**：窗口内观测数少于 `min_observations` 即判「无法判定」。
6. **检查顺序**：到期 → 取数 → 窗口是否为空 → 覆盖是否够 → 观测数是否够 → 聚合是否可算
   （`pct_change` 首条观测为 0 时比值为无穷，记 `AGGREGATE_UNDEFINED`） → 比较。
   顺序固定，避免同一份数据在不同实现里落到不同的原因码。

---

## 三、注册拒绝规则（写不出可执行判据就当场拒）

拒绝发生在写账本之前；被拒绝的请求不会在账本里留下任何字节。

| # | 触发条件 | 错误码 | 代码位置 |
|---|---|---|---|
| A1 | 没有 `criterion`，或它不是对象 | `CRITERION_MISSING` | `criterion.py` `validate` |
| A2 | 判据缺少任一必填字段 | `MISSING_FIELD` | 同上 |
| A3 | 判据含未声明字段 | `UNKNOWN_FIELD` | 同上 |
| A4 | `syntax_version` 不是 `criterion/v1` | `SYNTAX_VERSION` | 同上 |
| A5 | 数据源未登记 | `SOURCE_PROVIDER` | 同上 |
| A6 | 序列号/代码不符合该源格式 | `SOURCE_ID` | 同上 |
| A7 | `field` 与数据源不匹配 | `SOURCE_FIELD` | 同上 |
| A8 | 日期格式不对 / 窗口结构不对 / 窗口起晚于止 | `DATE_FORMAT` / `WINDOW_INVALID` / `WINDOW_INVERTED` | 同上 |
| A9 | 聚合方式不在白名单 | `AGGREGATE_UNKNOWN` | 同上 |
| A10 | 比较符不在白名单（「大约」「接近」「大概率」之类都进不来） | `COMPARATOR_UNKNOWN` | 同上 |
| A11 | 阈值不是有限数值（字符串、`NaN`、`Inf` 一律拒） | `THRESHOLD_INVALID` | 同上 |
| A12 | 单位为空 | `UNIT_INVALID` | 同上 |
| A13 | `min_observations < 1`；或 `pct_change` 却小于 2 | `FIELD_RANGE` / `MIN_OBS_TOO_SMALL` | 同上 |
| A14 | `claim` 含含糊表述 | `VAGUE_CLAIM` | `criterion.py` `lint_claim` |
| A15 | `claim` 少于 4 个字符 | `CLAIM_INVALID` | 同上 |
| A16 | 申报时刻晚于到期日 | `REGISTERED_AFTER_EXPIRY` | `ops.py` `build_registration` |
| A17 | 判据窗口末晚于到期日（判据越过了自己的到期日） | `WINDOW_AFTER_EXPIRY` | 同上 |
| A18 | `live` 注册在到期日之后才写入 | `REGISTRATION_AFTER_EXPIRY` | 同上 |
| A19 | 写入时刻早于申报时刻 | `WRITE_BEFORE_REGISTRATION` | 同上 |
| A20 | `id` 重复 | `DUPLICATE_ID` | 同上 |
| A21 | 数据源当下取不到 / 字段缺失 / 解析为空 | `SOURCE_HTTP` / `SOURCE_UNREACHABLE` / `SOURCE_PARSE` / `SOURCE_FIELD_MISSING` / `SOURCE_EMPTY` | `sources.py` `probe` |

### 含糊词表（A14 的实际判据）

中文：大概率、很可能、可能、或许、也许、有望、或将、走强、走弱、看好、看空、偏多、偏空、
估计、差不多、显著、趋势、方向性、应该会、大概率上涨、上涨概率、下跌概率。
英文（按词边界匹配，避免误伤月份等）：likely、probably、maybe、might、roughly、seems、
arguably、tends。

这张表是**启发式**，不是语义理解。它挡得住「大概率上涨」这类典型写法，挡不住故意绕开的表述。
真正的防线是第二节：判据必须写成结构化字段，句子再含糊也不会进入判定。

---

## 四、时间口径

| 时刻 | 来源 | 说明 |
|---|---|---|
| 写入时刻 | 命令行 `--at` | 必填。脚本不读系统时钟；缺失即报错退出。 |
| 申报时刻 | 请求里的 `registered_at` | 这条预测「声称」是什么时候写下的。 |
| 到期日 | `expires_on` | `YYYY-MM-DD`；核验在 `expires_on + settlement_lag_days` 之后才允许。 |
| 抓取时刻 | 账本指纹里的 `fetched_at_utc` | 取自当次 `--at`，不用系统时钟。 |

历史补录必须同时满足：`provenance.kind=backfill_selftest`、写入时刻晚于申报时刻、并且账本里
单开一条 `backfill_notice` 写明补录时刻、覆盖范围与「原始实时注册时刻不可考」。
只写一句「回填」不算交代。

---

## 五、判定状态

| 状态 | 含义 | 是否进命中率分母 |
|---|---|---|
| `hit` | 按判据算出「达到」 | 是 |
| `miss` | 按判据算出「没达到」 | 是 |
| `undetermined` | 判不了，附原因码 | **否** |
| `not_due` | 还没到可核验的时点，是流程状态而不是判定 | 否（不落账） |

`undetermined` 的原因码：

| 原因码 | 触发条件 |
|---|---|
| `SOURCE_UNREACHABLE` / `SOURCE_HTTP` | 网络失败或 HTTP 错误 |
| `SOURCE_PARSE` / `SOURCE_EMPTY` | 响应不可解析 / 清洗后无数据 |
| `SOURCE_FIELD_MISSING` | 响应里没有约定字段 |
| `NO_OBSERVATIONS_IN_WINDOW` | 窗口内一条观测都没有 |
| `WINDOW_NOT_COVERED` | 窗口末与最后一条观测的间隔超过 `coverage_slack_days` |
| `INSUFFICIENT_OBSERVATIONS` | 观测数少于 `min_observations` |
| `AGGREGATE_UNDEFINED` | 聚合在数学上无定义（目前只有 `pct_change` 首条观测为 0） |

规则：`undetermined` 不是「倾向于不成立」。它不参与命中率计算，也不允许在报告里折算成 `miss`。
只有 `undetermined` 允许补跑一次；补跑记录带 `supersedes` 与 `retry_of_undetermined`。
`hit` / `miss` 一旦落账即冻结，重跑会被拒绝——否则就成了「重复跑到命中」。

---

## 六、已知局限（写清楚，不藏）

1. **句子与判据的语义错配机器查不出**。例如 `claim` 说「上涨」而判据写成 `lte`。系统只保证
   判据可执行、结论可复算；它不承诺这句话和这个判据在语义上一致。缓解手段是：账本同时存
   `claim_canonical`（由判据自动渲染的规范句），以它为准读判据；自由文本只作注记。
2. **含糊词表是启发式**，见第三节说明。
3. **注册时的「可获得」只等于「当下能抓、字段在」**，不等于「数据新鲜」。新鲜度由核验阶段的
   `WINDOW_NOT_COVERED` 兜底，因为不同频率的序列发布节奏不同（月度序列天然滞后一个月以上）。
4. **目前只支持 FRED 与 Yahoo 两类源**。新增数据源要在 `sources.py` 的 `PROVIDERS` 登记并实现
   解析与字段约定，不是加一个字符串就能用。
5. **累计命中率是描述性统计**，不做显著性检验，也不做多重比较校正。它回答「到目前为止判了几条、
   对了几条」，不回答「这套判据是否优于随机」。
