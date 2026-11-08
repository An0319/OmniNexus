# 结构化事件源侦察（只侦察，未接入）

> 创建日：2026-11-08 ｜ 依据代际：壳前置能力（phase0/timeline） ｜ 最后实质修订：2026-11-08
> 边界：不用于抽样、不替代现有源、未写集成代码。用途只有一条——将来当「答案本来就摆在那儿」的锚，用来量判据准不准。下表只写**实测**结果，没调过就写没调过。

| 源 | 入口 | 返回形态 | 有公开判定口径 | 门槛 | 实测结果 |
|---|---|---|---|---|---|
| 巨潮资讯 | `POST http://www.cninfo.com.cn/new/hisAnnouncement/query` | 公告条目：`secName`、`announcementTitle`、`announcementTime`、`adjunctUrl`（PDF 相对路径） | 无 | 免费无密钥，需 `Referer`/`Origin`/`X-Requested-With` | **成功**：3→6 页 × 2 板块共 360 条；PDF **未打开** |
| 东方财富快讯 | `https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_50_{page}_.html` | 快讯，含 `digest` | 无 | 免费无密钥 | **成功**：150 条 |
| 新浪财经滚动 | `https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516` | 文章，含 `intro`、`ctime` | 无 | 免费无密钥 | **成功**：100 条 |
| 华尔街见闻快讯 | `https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel` | 快讯，含 `content_text` | 无 | 免费无密钥 | 首轮 HTTP 200（60 条）；**随后两次读超时 / SSL 握手超时，语料不含此源** |
| 36 氪 | `https://36kr.com/feed` | 期望 RSS，实际返回 HTML | 无 | 免费 | **未获得条目** |
| 财新 | `https://www.caixin.com/rss/all.xml` | 期望 RSS，实际返回重定向 HTML | 无 | 站点有付费墙（条目级未验证） | **未获得条目** |
| 第一财经 | `https://www.yicai.com/rss/news.xml` | — | — | — | **HTTP 404，未获得条目** |

**结论**

- 本轮真正调通的「非文章型」源只有巨潮公告检索：给的是公告条目（标题＋时间＋PDF），仍要自己判「算不算事件」；PDF 是文件级锚的好材料。
- **没有任何源直接返回「已判定事件 + 公开判定口径」**；声称有事件库的商用库口径不公开且付费，未验证。
- 交易所公告接口、企业信息库、专利库、临床试验注册库四类未调过，清单里只写「预期」，**不能写「可用」**。
