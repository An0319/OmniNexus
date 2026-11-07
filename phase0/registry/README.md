# 事件注册闭环（phase0/registry）

> 创建日：2026-11-08 ｜ 依据代际：2026-11 事件注册闭环（D11 定位下的新能力，不改定位主句） ｜ 最后实质修订：2026-11-08

本目录实现一件事：**一条预测在写下的时候就必须能判，到期之后必须能对账。**

它有三个动作：

1. **注册**——预测 = 一句话 + 到期日 + 结构化判据。判据写不成机器能执行的形状，当场拒绝。
2. **到期核验**——按判据取数、按窗口聚合、按阈值比较，落 `hit` / `miss` / `undetermined`。
3. **对账**——累计命中率只报区间，不报点估计；`undetermined` 单列，不进分母。

本目录与既有代码互不侵入：不改 `ruler.py`、不改 `phase0/controls/`、不碰批次一账本
`phase0/batch1.record.runs.jsonl`、不动已发布报告与留出段。

## 目录结构

| 文件 | 作用 |
|---|---|
| `syntax.md` | 判据语法与拒绝规则（先读这个） |
| `criterion.py` | 判据校验、规范句式渲染、判据哈希、含糊句拒绝 |
| `sources.py` | 数据源接入（FRED / Yahoo），只出指纹，不落原始数据 |
| `ledger.py` | append-only 账本：单条追加、显式时刻、哈希链校验 |
| `evaluate.py` | 到期核验：三态判定与原因码 |
| `reconcile.py` | 对账：Wilson 区间、分母口径 |
| `ops.py` | 注册 / 核验 / 对账的操作实现（CLI 与自检共用） |
| `cli.py` | 命令行入口 |
| `backfill_events.json` | 9 条已发生事实构造的回填事件 |
| `selftest.py` | 闭环自检（注册→到期→核验→对账，含拒绝用例） |
| `backfill.ledger.jsonl` | 回填测试账本（独立文件，**不是**真实业务账本） |
| `selftest_result.json` | 最近一次自检的结构化证据 |
| `self_review.md` | 自审记录：被推翻的判断与自检抓到的缺陷 |

真实业务账本是 `registry.ledger.jsonl`，首次真实注册时才会生成；当前不存在，也不该拿回填数据填充它。

## 用法

`--ledger` 是全局参数，要写在子命令之前。

```bash
# 注册（--at 必填，脚本不读系统时钟）
python phase0/registry/cli.py --ledger phase0/registry/registry.ledger.jsonl \
  register --payload-file my_prediction.json --at 2026-11-08T09:00:00Z

# 到期核验（未到期的事件会被跳过，不落判定）
python phase0/registry/cli.py --ledger phase0/registry/registry.ledger.jsonl \
  verify --at 2026-12-31T09:00:00Z

# 对账（默认输出人读表格，加 --json 输出机器可读）
python phase0/registry/cli.py --ledger phase0/registry/registry.ledger.jsonl reconcile

# 列表与哈希链校验
python phase0/registry/cli.py --ledger phase0/registry/registry.ledger.jsonl list
python phase0/registry/cli.py --ledger phase0/registry/registry.ledger.jsonl chain-check
```

注册请求示例（字段含义见 `syntax.md`）：

```json
{
  "id": "REG-2026-0001",
  "claim": "WTI 会在 2026 年 12 月内触及 90 美元/桶",
  "registered_at": "2026-11-08T09:00:00Z",
  "expires_on": "2026-12-31",
  "criterion": {
    "syntax_version": "criterion/v1",
    "source": {"provider": "fred", "id": "DCOILWTICO", "field": "value"},
    "window": {"start": "2026-12-01", "end": "2026-12-31"},
    "aggregate": "max",
    "comparator": "gte",
    "threshold": 90,
    "unit": "USD/barrel",
    "min_observations": 15,
    "coverage_slack_days": 7,
    "settlement_lag_days": 3
  }
}
```

## 自检怎么跑

```bash
python phase0/registry/selftest.py --at 2026-11-08T12:00:00Z --reset
```

- `--at` 必填；`--reset` 用于重建回填账本（账本已存在时默认拒绝覆盖）。
- 自检需要联网（FRED / Yahoo）。它会把 9 条回填事件注册、核验、对账，并逐条断言
  「三态齐活 / undetermined 不进分母 / 删掉 claim 后结论不变 / 命中即冻结 /
  判据被改会被发现 / 未到期不落判定 / 12 类不合规注册被拒且账本不动 /
  账本只在前缀后增长 / 无系统时钟调用」。

最近一次结果（`--at 2026-11-08T12:00:00Z`）：9 条注册，`hit` 4、`miss` 3、
`undetermined` 2；7 条可判中 4 条命中，按 Wilson 方法 95% 区间 25%–84%，
样本不足以给点估计；32 条断言全部通过。逐条证据见 `selftest_result.json`。

## 账本纪律

- **append-only**：按行追加，既有字节不重写；追加前先确认文件尾部可解析。
- **写入时刻显式传入**：`--at` 必填，代码里不读系统时钟（自检会静态扫描确认）。
- **哈希链**：每条记录带 `prev_record_sha256`，`chain-check` 可只读校验中间是否被改过。
- **回填必须自报**：回填记录必须带 `provenance.kind=backfill_selftest`，并由一条
  `backfill_notice` 写明补录时刻、覆盖范围，以及「原始实时注册时刻不可考」。
- **本目录账本独立**：与 `phase0/batch1.record.runs.jsonl` 没有任何读写关系。

## 第三方数据

原始响应只在内存里参与计算，**不入库**。账本里只留指纹：URL、SHA256、行数、首末日期、
抓取时刻。外部复算只能靠公开源重新抓取，不能靠仓库内的数据副本。

## 明确不做

- 不做人工裁定入口：判定只读判据，不读 `claim` 文本，也不接受「事后人工改判」。
- 不做自动开新预测、不做择时、不做组合：本目录只负责「注册—到期—对账」这一条链。
- 不在注册阶段判断预测对不对：注册只校验「可判」与「数据源可用」。
