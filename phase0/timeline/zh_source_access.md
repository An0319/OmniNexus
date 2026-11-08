# 中文源取件路径调查

> 创建日：2026-11-08 ｜ 依据代际：壳前置能力（phase0/timeline） ｜ 最后实质修订：2026-11-08
> 范围：只回答「每一类中文源到底怎么取得到」——入口、形态、是否要登录/签名、有无反爬、实测结果、卡在哪一步。**不写「预期可用」**，没测过的写没测过。
> 证据等级：下表全部为 **A 级实跑**（本机直连，HTTP 状态码 + 响应字节 + 字段名均来自当次响应）。时刻：2026-11-08 21:55–22:05 CST（新浪接口回传 `timestamp: Sun Nov 08 21:55:25 +0800 2026` 可作锚）。换网络、换时间可能不同，下表只对当次有效。

## 0. 一句话结论

**「换个站就行」不成立。** 四家此前失败的源，失败原因各不相同，且只有一家（华尔街见闻）是瞬时故障、现在已恢复；36 氪不是格式问题而是 **RSS 根本不存在**，真正的入口是一个未公开的 JSON 接口（`gateway.36kr.com`，POST，无需登录）；财新与第一财经的 RSS 已下线，只剩 HTML；财联社要签名；澎湃 403；证券时报 TLS 握手超时。

真正能稳定取到结构化列表的路径只有两条半：**JSON 接口**（东财、新浪、华尔街见闻、36 氪 gateway、东财研报）和 **JSONP**（东财快讯），外加一个 RSS（Google News）。

## 0.5 抓取边界（官方口径，写死在代码与文档里）

1. **官方实现只走公开能直接打开的路径**：RSS、公开网页、公告页。需要登录、付费、关注公众号、扫码授权才能看到的内容，官方路径都不进入。
2. **公众号、付费墙：官方不抓、不主动碰、不提供实现。**
3. **插件扩展点留给用户自行接入、自行承担后果。官方不提供、不审核、不背书任何绕过付费墙或登录墙的实现。**

第 3 条必须与第 2 条同时出现：只留口子不写清，出事时「官方留了口子」会被读成默许。口子照留，责任写清。

落到本调查：36 氪 `gateway.36kr.com` 属于**公开网页自己调用的接口**，不是绕过技术措施，可以接，但随前端改版可能失效；财新 / 一财 / 澎湃的**公开 HTML 解析可以做，绕过付费墙或登录墙不可以**；财新的付费墙部分**未验证，且按边界不实现**。

## 1. 逐源实测表

| 源 | 类别 | 入口（当次实测） | 形态 | 登录/密钥 | 反爬 | 实测结果 | 卡点 |
|---|---|---|---|---|---|---|---|
| 巨潮资讯 | 上市公司公告 | `POST http://www.cninfo.com.cn/new/hisAnnouncement/query` | JSON | 否 | 需 `Referer`＋`Origin`＋`X-Requested-With` | **200**，21,422B，0.9s，`totalAnnouncement=2199`，`announcements[]` 含 `secName` / `announcementTitle` / `announcementTime` / `adjunctUrl`（PDF 相对路径） | 无（PDF 正文未打开） |
| 东方财富快讯 | 财经快讯 | `https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_50_1_.html` | **JSONP**（`var ajaxResult=` 前缀） | 否 | 无 | **200**，65,103B，6.2–8.6s，`LivesList` 50 条，字段 `title` / `digest` / `showtime` / `url_unique` | 需剥前缀；响应慢 |
| 新浪财经滚动 | 财经快讯 | `https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&num=20` | JSON | 否 | 无 | **200**，42,364B，0.7s，`result.pdps[]` | 无 |
| 华尔街见闻·快讯 | 财经快讯 | `https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=20` | JSON | 否 | 无 | **连跑 3 次全 200**，各 20 条，1.0/1.5/1.8s，字段 `title` / `content_text` / `display_time`（epoch 秒） | **无**；上一轮两次超时属瞬时故障，不是接口不可用 |
| 华尔街见闻·文章 | 财经深度 | `https://api-one.wallstcn.com/apiv1/content/articles?channel=global-channel&limit=20` | JSON | 否 | 无 | **200**，26,641B，0.4s，`data.items[]` | 无 |
| 36 氪·快讯 | 财经快讯 | `POST https://gateway.36kr.com/api/mis/nav/newsflash/flow`，body 见 §2 | JSON | 否 | 无 | **200**，15,673B，0.5–1.7s，`data.itemList` 20 条，`hasNextPage=1`；字段 `templateMaterial.widgetTitle` / `publishTime`（epoch 毫秒）/ `widgetContent` | `/feed` 与 `/newsflashes` 返回**同一份 25,361B SPA 空壳**，里面没有条目；该接口无文档，**随前端改版可能失效** |
| 36 氪·文章流 | 财经深度 | `POST https://gateway.36kr.com/api/mis/nav/ifm/subNav/flow` | JSON | 否 | 无 | **200**，15,357B，1.0s，`data.itemList` 20 条 | 同上：只能走接口 |
| 财联社 | 财经快讯 | `https://www.cls.cn/v1/roll/get_roll_list?app=CailianpressWeb&os=web&sv=7.7.5&rn=20` | 错误 JSON | — | 有（请求签名） | **200 但 `errno=10012`「签名错误」**；`/nodeapi/telegraphList` → **404** | 卡在签名算法（`sign` 参数），未破解 |
| 财新 | 财经深度 | `https://www.caixin.com/rss/all.xml`（另试 `/rss/`、`/rss/0.xml`、http 版） | — | 正文付费墙（未验证） | 有（RSS 重写） | 四个入口**全部重写到 `other.caixin.com/404/index.html`**（HTTP 200，但内容是 404 页，18,099B）；首页 HTML 可取（96,395B） | 卡在「**无公开 RSS**」，只能解析首页 HTML；付费墙部分**未验证，且按边界不实现** |
| 第一财经 | 财经深度/快讯 | `https://www.yicai.com/rss/news.xml` → **404**；`https://www.yicai.com/news/` → **200** HTML 390,195B；`https://www.yicai.com/api/ajax/getlistbycid?cid=115\|110` → **200 空数组 `[]`** | HTML | 否 | 前端有 `yc_autologin.js` | 首页可取；按 `/news/\d+.html` 正则抓标题链接 **0 命中**；两个 cid 的列表接口都返回 `[]` | 卡在「不知道正确的列表接口与 cid，首页链接结构需逆向」 |
| 澎湃新闻 | 财经深度 | `https://www.thepaper.cn/` | — | 否 | 有（403） | 裸请求 **403**；带本站 Referer **403**；带百度 Referer **403** | 卡在 403；最小路径＝带完整浏览器指纹/Cookie，翻案条件＝风控放宽 |
| 界面新闻 | 财经深度 | `https://www.jiemian.com/` → **200** HTML 153,258B；`https://a.jiemian.com/index.php?m=article&a=indexajax&cid=1&page=1` → **404** | HTML | 否 | 未测到 | 首页可取；旧 ajax 接口 404 | 卡在「无公开 JSON 列表口，只能解析首页 HTML」 |
| 每日经济新闻 | 财经深度 | `https://www.nbd.com.cn/` | HTML | 否 | 未测到 | **200**，183,110B | 首页可取；**条目结构未验证** |
| 证券时报 | 财经深度 | `https://www.stcn.com/` | — | — | 不确定 | 两次 **TLS 握手超时**（`_ssl.c:993`），无状态码 | 卡在网络层（TLS 握手），非 4xx |
| 东方财富研报 | 研报 | `https://reportapi.eastmoney.com/report/list?cb=datatable&pageSize=20&pageNo=1&beginTime=2026-10-01&endTime=2026-11-08&qType=0&code=*` | **JSONP**（`datatable(...)`） | 否 | 无 | **200**，28,304B，2.3s，`hits=1923`，`data[]` 含 `title` / `stockName` / `orgCode` | 少 `beginTime`/`endTime`/`code=*` 任一 → **400** |
| Google News RSS | 聚合检索 | `https://news.google.com/rss/search?q=A股&hl=zh-CN&gl=CN&ceid=CN:zh-Hans` | RSS | 否 | 无 | **200**，63 `<item>`，1.0s | 链接是聚合跳转页，解析不回原文（既有结论） |
| 新浪 RSS 老口 | — | `http://rss.sina.com.cn/news/marquee/ddt.xml` | RSS | 否 | 无 | **200** 但只有 **1 个 item** | 废弃口，不能当源 |

## 2. 两个 POST 口的请求体（可直接复用）

36 氪快讯：

```json
{"partner_id":"web","param":{"siteId":1,"platformId":2,"pageSize":20,"pageEvent":0,"pageCallback":"","type":1}}
```

巨潮公告（`form-urlencoded`）：

```text
pageNum=1&pageSize=30&column=szse&tabName=fulltext&seDate=2026-11-06~2026-11-08&isHLtitle=true
```

## 3. 复算方式

每条都是单发 HTTP，用 `curl` 或 `python -c` 即可复核；**必须带桌面浏览器 UA**（`urllib` 默认 UA 会被部分站点区别对待，本表全部用 Chrome 124 UA 测得）：

```bash
curl -s -o NUL -w "%{http_code} %{size_download} %{time_total}\n" -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36" "https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=20"
```

## 4. 对第三段的意义（先说结论，不写「预期」）

1. **可进样本的源（已验证）**：巨潮（公告，B 类）；东财快讯、新浪滚动、华尔街见闻、36 氪 gateway（快讯，A 类）；东财研报（可替代 C 类深度稿的「研报体」）；Google News（D 类聚合）。
2. **不可用、且原因各不相同**：财联社（签名）、澎湃（403）、证券时报（TLS 超时）、财新（无 RSS）、第一财经（无可用列表口）。**不能合并成一句「这几个站挂了」**——五种卡点对应五种不同的代价与翻案条件。
3. **对既有判断的两处更正**：
   - 「华尔街见闻超时」是**瞬时故障**，接口现在稳定可用，应把它列入可用源，但要带重试（1 次超时不算该源失效）。
   - 「36 氪格式不对」不准确：`/feed` 返回的是**单页应用外壳**（两次请求字节数完全相同，25,361B），不是「格式不对的 RSS」。正确路径是 POST `gateway.36kr.com`。
4. **深度稿（C 类）仍缺稳定源**：财新、一财、澎湃三家都取不到结构化列表；只剩「解析首页 HTML」这条路，代价是随改版失效、时间字段无保证。第三段若坚持要有 C 类，只能在「界面/每经 HTML 解析」与「用 36 氪文章流替代」之间选，且要写明该路径的失效风险。
5. **登录与密钥**：上表所有成功的 JSON 口**都不需要登录、不需要密钥**；巨潮只要三个请求头。唯一需要签名的是财联社——**按 §0.5 边界，官方不实现财联社签名，也不为它留后门**。
6. **边界对实现的约束**：只接「公开能直接打开」的路径（巨潮、东财、新浪、华尔街见闻、36 氪 gateway、Google News）。财新 / 一财 / 澎湃只能做公开 HTML 解析，**付费墙与登录墙一律不碰**；公众号不接。插件扩展点保留给用户自行接入，官方不做、不审、不背书。

## 5. 不能断言的部分

- **未做压力测试**：没有验证频控、封 IP、单日额度；上表只证明「单发可取」。
- **财新正文付费墙未验证**：只测了首页 HTML，未点进任何文章；按 §0.5 边界，官方实现不碰这部分。
- **未验证 36 氪 gateway 的稳定性**：这是站点内部接口，无文档、可能随前端改版消失；当次成功不代表下月可用。
- **未测移动端/海外镜像**：只测了桌面端公开入口。
- **未验证界面与每经的条目结构**：首页 HTML 拿到了，但没解析出「标题 + 时间 + 链接」三元组，因此不能写「HTML 可解析」之外的话。
