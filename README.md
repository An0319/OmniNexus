# 脉络 · OmniNexus

> **内核极简且稳定的跨域推理操作系统**：数据源 / 计算公式 / 传导链 / 面板 / 通知均为可热插拔插件。
> 它只负责找跨域传导关系；验证由使用者自己的预算完成。

这是一个把「预注册判定」做成工程件的开源实验：**判定线先于数据写死，修订必须留痕，失败必须响亮**。
证伪是正常产出，不是事故。

---

## 当前状态

| 项 | 事实 |
|---|---|
| 工程闭环（T1） | 连续 **30 天**无人值守日更，2026-09-30 → 2026-10-29，30/30，无断更 |
| 运行方式 | GitHub Actions 双 cron（UTC 00:30 / 12:30），任一班次完整成功即当日达标 |
| 预注册判定 | 3 条链、全部未通过（明细见下） |
| 尝试预算 | 3/3 用尽，不再对判定参数做加参调优 |
| 数据快照 | 每次运行写入 `data/`，提交即版本化历史 |

### 三次判定（预注册口径）

| # | 链 | 假设 | 结果 |
|---|---|---|---|
| 1 | chain01 | AI 学术热度（LLM / 推理优化）→ 光模块板块 | ❌ 无传导：收益 ρ −0.108 @7 周 / 成交额 ρ −0.123 @1 周 |
| 2 | chain10 | 人形机器人学术热度 → A 股机器人板块 | 未通过：收益 ρ +0.149 @20 周 ❌ / 成交额 ρ +0.167 @26 周（灰区） |
| 3 | chain20 | 费城半导体指数 → A 股半导体 ETF（隔夜快传导） | 未通过：窗口 [1,2] 内最优 k=1，ρ +0.215，未达判定线 0.3；峰值 k=0，ρ +0.263 属前视诊断，不计入结论 |

判定线 `pass_corr = 0.3`，弱信号带 `noise_band = 0.15`。候选 ≠ 结论：链级结论由作者裁定，指标徽章只表示该指标是否触达判定线。

## 判定怎么读

1. **判定线先于数据**：`chains/*.yaml` 的 `judgement` 段在数据写入前注册，冻结后任何修改都必须新增 `revisions` 条目并消耗尝试额度（工具强制，不靠自觉）。
2. **哈希链**：每次运行核对 `data/streak.json` 记录的上一提交 SHA，账本历史被改写会响亮失败（`rewritten`）。
3. **降级披露**：数据源不可用时按既有降级链兜底（akshare → 东财直连 → 指数代理 → 个股代理），并在看板「数据质量」块披露具体路径——降级不是故障遮掩。
4. **前视诊断**：k=0 同周共动只作诊断披露，不计入可交易结论。

## 仓库结构

```
chains/       链配置（预注册载体）+ 判定留痕 + 运行账本
data/         日更快照（快照即历史）
omninexus/    计算分析层：抓数适配器 / 对齐 / 标准化 / 交叉相关 / 判定引擎
tools/        无人值守日更入口（daily_update.py）与数据源探针
tests/        守卫：依赖方向 / M0 回归 / 纪律测试 / 快照契约 / T1 幂等
phase0/       阶段 0 两次人肉验证的原始脚本与输出（审计现场）
content/      证伪复盘长文
dashboard/    看板（Vite + React + TS，纯静态读快照）
scripts/      画像物化脚本
```

> 设计文档、思考逻辑与内部审计记录**不随公开仓库分发**，仅保留在作者本地。

## 本地复现

```bash
# 1. Python 侧（3.11）
pip install -r requirements.txt
python tools/daily_update.py          # 跑一次完整日更

# 2. 看板
cd dashboard
pnpm install
pnpm dev                              # http://localhost:5173
```

Windows 下可直接双击 `start-dashboard.bat`。

可选环境变量：

| 变量 | 用途 |
|---|---|
| `OPENALEX_API_KEY` | OpenAlex 免费 API key，仅提升配额（不配置会 429，当日失败） |
| `OPENALEX_MAILTO` | OpenAlex 礼貌池邮箱，建议填真实可联系邮箱 |

## 数据源

- 领先面：**OpenAlex**（数据以 CC0 1.0 释放）。
- 滞后面：东方财富 / 新浪财经等，经 **AkShare**（MIT）等开源库抓取。

代码与判定流程遵循本仓库许可；**数据本身的权利不归本项目**，本项目不授予你对第三方数据的任何权利。商用产出物前请自行核验数据源当时的服务条款。

## 免责声明 / Disclaimer

**中文**：本项目仅作方法论演示与公开留痕，**不构成任何投资建议、要约或推荐**。全部结论均为预注册判定的公开结果，历史相关性不代表未来收益；任何依据本仓库内容做出的决策及其后果，由使用者自行承担。

**English**: This project is a methodology demo and a public audit trail. It does **not** constitute investment advice, an offer, or a recommendation of any kind. All results are pre-registered verdicts published as-is; past correlation does not imply future returns. You are solely responsible for any decision you make based on this repository.

## 许可 / License

本仓库以 **[PolyForm Noncommercial License 1.0.0](LICENSE)** 授权：

- **软件本身禁止商业用途**——不得直接拿去做成企业产品；
- **学习、研究、教学、复现完全自由**，无需申请；
- **产出物可商用**：用本仓库的代码、数据与流水线产出的结论 / 图表 / 报告 / 数据集，可用于商业目的，条件是**注明出处**：

```
OmniNexus（脉络）· https://github.com/An0319/OmniNexus
```

详见 [NOTICE](NOTICE)。
