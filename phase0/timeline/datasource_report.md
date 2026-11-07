# 事件时间线 · 数据可得性实证报告

> 创建日：2026-11-08 ｜ 依据代际：壳前置能力（phase0/timeline） ｜ 最后实质修订：2026-11-08
> 证据等级遵循 AGENTS.md R15：A=实跑、B=文件原文、C=推断。本报告只记录抓到的东西，不记录"应该有"。

## 0. 一句话结论

**能拿到真实的事件源，但不是所有源都合格。** 一次探针（`probe_sources.py`，2026-11-07T21:38Z）打 10 个公开源，9 个返回过数据；其中 5 个同时具备「条目级原文 URL + 真实摘要文本 + 可解析时间」，够格进 v1 抽取；3 个只够做时间/标题（无摘要或 URL 是聚合页），2 个需要重试才成功，1 个 URL 已失效。

结论不是"路线成立"，而是：**通用主题检索可做（Google News / Bing News），政策与研究类结构化事件可做（Federal Register / arXiv / ClinicalTrials），财经媒体的"主体"检索只有按标的代码的 Yahoo 一档**。

## 1. 探针方法

- 脚本：`phase0/timeline/probe_sources.py`
- 命令：`python phase0/timeline/probe_sources.py`
- 机器可读结果：`phase0/timeline/probe_sources.json`（只存 URL、抓取时刻、字节数、SHA256、条目数、首末条目时间、样例短引用；不存第三方原文）
- 探针主题：`clinical trial`（英文）/ `临床试验`（中文），时间限定词 `when:30d` 由支持该语法的源使用
- 失败重试：每个源最多重试 1–2 次，间隔 7 秒；每次尝试的状态另存 `attempts` 字段

## 2. 逐源结果（A 级：实跑输出）

| 源 | 状态 | 条目 | 有日期 | 有摘要 | 首→末条目时间（UTC） | URL 性质 | SHA256前12 |
|---|---|---|---|---|---|---|---|
| google_news_rss_en | OK | 89 | 89 | 89 | 2026-10-13T07:00Z → 2026-11-07T21:35Z | 聚合页（news.google.com） | f227177e6791 |
| google_news_rss_zh | OK | 75 | 75 | 74 | 2026-10-12T03:04Z → 2026-11-07T09:33Z | 聚合页（news.google.com） | 22165bf841e7 |
| bing_news_rss | OK | 11 | 11 | 11 | 2018-12-04T08:00Z → 2026-11-07T13:15Z | 跳转后可到出版商原文 | 9453ecf53200 |
| gdelt_doc_api | OK（第2次） | 40 | 40 | **0** | 2026-11-06T09:30Z → 2026-11-07T19:00Z | 出版商原文 | 6464451a5978 |
| clinicaltrials_gov_api_v2 | OK（第3次） | 30 | 30 | 30 | 2015-06-29 → 2026-11-06 | 官方登记页 | 1c0f076354e0 |
| federal_register_api | OK | 30 | 30 | 23 | 2026-10-06 → 2026-11-06 | 官方公报页 | 64c53e1ea209 |
| arxiv_api | OK | 30 | 30 | 30 | 2026-10-09T17:05Z → 2026-11-05T17:55Z | 官方预印本页 | 40b82c64ed5d |
| yahoo_finance_rss | OK | 20 | 20 | 20 | 2026-10-19T03:15Z → 2026-11-07T17:35Z | 出版商原文 | fcaade994bf7 |
| cnbc_rss | OK | 30 | 30 | 30 | 2026-11-06T18:40Z → 2026-11-07T21:17Z | 出版商原文 | 79876d3e7dee |
| sina_finance_rss | FAIL | — | — | — | — | — | 58f9100952a8 |

失败原因（原文照录，A 级）：

- `sina_finance_rss`：`HTTP 404`，页面标题为"页面没有找到"。该 RSS 地址已下线，不是网络问题。
- `gdelt_doc_api` 首轮：`HTTP 429`，响应正文写明"Please limit requests to one every 5 seconds"；间隔 7 秒重试后成功。**共享 IP 下限速不稳定，不能作为唯一源。**
- `clinicaltrials_gov_api_v2` 首轮：`SSLError: UNEXPECTED_EOF_WHILE_READING`；同 URL 重试第 2、3 次成功。属于瞬时链路故障，不是接口下线。
- 另有两个在第二批诊断里试过、未进最终表：`fda_press_rss` 返回 404（FDA 改版后原 RSS 路径失效）；`sec_8k_atom` 返回 403（SEC 要求带真实联系方式的 User-Agent，未按该要求配置）。

## 3. URL 可核性分级（决定"能不能进表"）

| 等级 | 含义 | 本批来源 |
|---|---|---|
| P（publisher） | 条目级 URL 直达出版商原文 | bing_news_rss（跳转后）、yahoo_finance_rss、cnbc_rss、gdelt_doc_api |
| O（official） | 条目级 URL 直达官方原始记录 | federal_register_api、clinicaltrials_gov_api_v2、arxiv_api |
| A（aggregator） | URL 是聚合器页面，能打开但不是出版商 canonical | google_news_rss_en / _zh |

硬约束（用户要求 4）：缺来源 URL、抓取时刻、原文片段任一项的事件不许进表。据此：

- **可进 v1**：Bing News（P）、Federal Register（O）、ClinicalTrials（O）、arXiv（O）、Yahoo 财经（P）、CNBC（P）、Google News（A，标注聚合器）
- **不进 v1**：GDELT——条目无摘要文本，凑不齐"原文片段"（要补齐必须逐篇抓原文，40 篇 5 秒限速下不可接受）；Sina（404）；FDA（404）；SEC（403）
- **CNBC / Yahoo 只解"主体=标的"，不解"主题"**：它们没有查询参数，只能拿最新流；主题检索必须走 Google News / Bing News 的 `q=`

## 4. 中途被推翻的判断（按要求保留）

1. **推翻：Google News 的 `<link>` 能解析出出版商原文 URL。**
   - 原判断：抓 RSS 后再跟一次跳转，就能拿到 publishers 的 canonical URL（C 级推断）。
   - 实测（A 级）：完整 276 字符链接 `GET` 返回 200，但 `final_url` 仍停在 `news.google.com/rss/articles/...`，页面里没有 `data-n-au` 原文地址；手工截断的链接直接 400。
   - 结论改写：Google News 的 URL 只能记作**聚合页**，记为 `url_kind=aggregator`；出版商信息只能取 `<source url>` 的站点根域（site-level，非 article-level）。
2. **推翻：探针首版"首末条目时间"可信。**
   - 原实现直接用字符串比较 RFC822 日期，出现 `first_item_date=Fri, 06 Nov 2026`、`last_item_date=Wed, 30 Jan 2019` 的倒挂（2019 比 2026 "大"，因为 `W` > `F`）。
   - 修正：新增 `parse_date()`，统一解析为带时区 datetime 后再取 min/max（`probe_sources.json` 已升到 `probe_version: 2`）。
3. **推翻：ClinicalTrials.gov 当前不可用。**
   - 首轮 `SSLError`，我一度按"接口挂了"记录；重试后同一 URL 连续两次成功，改为**瞬时链路故障**，并保留 `attempts` 数组作为证据。
4. **推翻：GDELT 因为 429 不能进候选池。**
   - 首轮 429 是限速而非封禁；间隔 7 秒后成功拿到 40 条。但摘要字段为空，最终仍被"原文片段"硬约束挡在 v1 之外——理由从"拿不到"改成了"拿得到但不合格"。

## 5. 边界与后续

- 第三方原文与原始响应一律不入库；仓库只保留本报告与 `probe_sources.json` 指纹。
- 可重抓性：`request_url` + `fetched_at_utc` 已够复现该次探针；响应体哈希可比对是否同一份内容。
- 未验证项（如实标注）：中文源只测了 Google News 中文区，未测国内财经站点（新浪 404 之外未再探）；SEC 8-K 仅在未配置合规 UA 的情况下试过，按 SEC 政策补 UA 后可重开（翻案条件：提交带联系方式 UA 并遵守 10 次/秒限速）。
- 下一步：把"能进 v1"的源做成字段映射与抽取规则，见 `schema.md` 与 `timeline.py`。
