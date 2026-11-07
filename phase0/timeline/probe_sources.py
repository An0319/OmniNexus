"""数据可得性探针：真实抓取一次候选新闻/事件源，只记录可核验指纹。

输出到 phase0/timeline/probe_sources.json：来源 id、请求 URL、抓取时刻（UTC）、
HTTP 状态、响应字节数、SHA256、条目数、首末条目时间、样例标题、失败原因。
第三方原文一律不入库，本文件只存指纹与短引用。

用法：python phase0/timeline/probe_sources.py
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote_plus

import requests

OUT = Path(__file__).resolve().parent / "probe_sources.json"

UA = "OmniNexus-timeline-probe/0.1 (+https://github.com/an0319/OmniNexus)"
TIMEOUT = 30

# 查询主题：与项目首批举证域相关的公开词，不涉及任何私有数据。
TOPIC = "clinical trial"


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(value: str) -> dt.datetime | None:
    """把 RFC822 / ISO / YYYY-MM-DD 统一解析成带时区 datetime。

    首版探针直接用字符串比大小，RFC822 的星期前缀使 min/max 算错
    （"Fri, 06 Nov 2026" 字典序小于 "Wed, 30 Jan 2019"）。此函数修正该缺陷。
    """
    if not value:
        return None
    v = str(value).strip()
    parsed = None
    try:
        parsed = dt.datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime

            parsed = parsedate_to_datetime(v)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    return TAG_RE.sub(" ", text or "").replace("&nbsp;", " ").strip()


def rss_items(text: str) -> list[dict]:
    """极简 RSS2.0/Atom 解析：title/link/date/excerpt。不引入额外依赖。"""
    root = ET.fromstring(text)
    items: list[dict] = []
    for node in root.iter():
        tag = node.tag.split("}")[-1].lower()
        if tag not in ("item", "entry"):
            continue
        row = {"title": "", "link": "", "date": "", "excerpt": ""}
        for child in list(node):
            ctag = child.tag.split("}")[-1].lower()
            if ctag == "title":
                row["title"] = strip_html(child.text or "")
            elif ctag == "link":
                row["link"] = (child.text or "").strip() or child.get("href", "")
            elif ctag in ("pubdate", "published", "updated", "date"):
                row_date = (child.text or "").strip()
                if row_date and not row["date"]:
                    row["date"] = row_date
            elif ctag in ("description", "summary", "content", "abstract"):
                if not row["excerpt"]:
                    row["excerpt"] = strip_html(child.text or "")[:400]
        items.append(row)
    return items


def parse_items(parser: str, resp: requests.Response) -> list[dict]:
    if parser == "rss":
        return rss_items(resp.text)
    if parser == "arxiv_xml":
        return rss_items(resp.text)
    if parser == "gdelt_json":
        data = resp.json()
        return [
            {"title": a.get("title", ""), "link": a.get("url", ""), "date": a.get("seendate", ""), "excerpt": ""}
            for a in data.get("articles", [])
        ]
    if parser == "ctgov_json":
        data = resp.json()
        items = []
        for s in data.get("studies", []):
            p = s.get("protocolSection", {})
            ident = p.get("identificationModule", {}) or {}
            status = p.get("statusModule", {}) or {}
            first_post = status.get("studyFirstPostDateStruct")
            date = first_post.get("date", "") if isinstance(first_post, dict) else str(first_post or "")
            items.append(
                {
                    "title": ident.get("briefTitle", ""),
                    "link": f"https://clinicaltrials.gov/study/{ident.get('nctId', '')}",
                    "date": date,
                    "excerpt": (p.get("descriptionModule", {}) or {}).get("briefSummary", "")[:400],
                }
            )
        return items
    if parser == "fedreg_json":
        data = resp.json()
        return [
            {
                "title": r.get("title", ""),
                "link": r.get("html_url", ""),
                "date": r.get("publication_date", ""),
                "excerpt": (r.get("abstract") or "")[:400],
            }
            for r in data.get("results", [])
        ]
    raise ValueError(f"unknown parser {parser}")


def fetch(name: str, url: str, parser: str, note: str, retries: int = 1) -> dict:
    rec: dict = {
        "source_id": name,
        "request_url": url,
        "parser": parser,
        "note": note,
        "attempts": [],
    }
    items: list[dict] = []
    for attempt in range(retries + 1):
        rec["fetched_at_utc"] = now_utc()
        t0 = time.time()
        try:
            resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
            rec["attempts"].append(
                {"at_utc": rec["fetched_at_utc"], "http_status": resp.status_code, "bytes": len(resp.content)}
            )
            rec["http_status"] = resp.status_code
            rec["bytes"] = len(resp.content)
            rec["sha256"] = hashlib.sha256(resp.content).hexdigest()
            rec["elapsed_ms"] = int((time.time() - t0) * 1000)
            if resp.status_code >= 400:
                rec["failure_reason"] = (
                    f"HTTP {resp.status_code}: {resp.content[:200].decode('utf-8', 'replace')}"
                )
                if attempt < retries:
                    time.sleep(7)
                    continue
                rec["ok"] = False
                return rec
            items = parse_items(parser, resp)
            rec.pop("failure_reason", None)
            rec["ok"] = True
            break
        except Exception as exc:  # noqa: BLE001 - 探针必须把任何失败都记录下来
            rec["attempts"].append(
                {"at_utc": rec["fetched_at_utc"], "error": f"{type(exc).__name__}: {str(exc)[:180]}"}
            )
            rec["failure_reason"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            rec["elapsed_ms"] = int((time.time() - t0) * 1000)
            if attempt < retries:
                time.sleep(7)
                continue
            rec["ok"] = False
            return rec

    rec["item_count"] = len(items)
    rec["items_with_link"] = sum(1 for i in items if i["link"])
    rec["items_with_excerpt"] = sum(1 for i in items if len(i["excerpt"]) >= 20)
    dated = [(parse_date(i["date"]), i["date"]) for i in items]
    dated = [(d, raw) for d, raw in dated if d is not None]
    rec["items_with_date"] = len(dated)
    rec["first_item_date"] = min(dated)[0].strftime("%Y-%m-%dT%H:%M:%SZ") if dated else None
    rec["last_item_date"] = max(dated)[0].strftime("%Y-%m-%dT%H:%M:%SZ") if dated else None
    rec["sample_items"] = [
        {"title": i["title"][:160], "link": i["link"][:300], "date": i["date"], "excerpt": i["excerpt"][:120]}
        for i in items[:2]
    ]
    return rec


def main() -> int:
    q = quote_plus(TOPIC)
    q_zh = quote_plus("临床试验")
    targets = [
        (
            "google_news_rss_en",
            f"https://news.google.com/rss/search?q={q}+when:30d&hl=en-US&gl=US&ceid=US:en",
            "rss",
            "通用新闻检索 RSS；支持 when:30d 时间限定词；link 为 news.google.com 聚合页而非出版商原文",
            1,
        ),
        (
            "google_news_rss_zh",
            f"https://news.google.com/rss/search?q={q_zh}+when:30d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            "rss",
            "中文新闻检索 RSS；同一接口另一语言区",
            1,
        ),
        (
            "bing_news_rss",
            f"https://www.bing.com/news/search?q={q}&format=RSS",
            "rss",
            "必应新闻 RSS；link 经 bing 跳转可落到出版商原文；description 为真实摘要",
            1,
        ),
        (
            "gdelt_doc_api",
            f"https://api.gdeltproject.org/api/v2/doc/doc?query={q}&mode=artlist&format=json&maxrecords=40&sort=datedesc",
            "gdelt_json",
            "GDELT 2.0 DOC API；无密钥；限速 1 次/5 秒，共享 IP 易 429",
            1,
        ),
        (
            "clinicaltrials_gov_api_v2",
            "https://clinicaltrials.gov/api/v2/studies?query.term=lung%20cancer&pageSize=30&sort=LastUpdatePostDate:desc",
            "ctgov_json",
            "临床试验登记结构化事件源；无密钥；含 briefSummary 原文摘要",
            2,
        ),
        (
            "federal_register_api",
            f"https://www.federalregister.gov/api/v1/documents.json?conditions%5Bterm%5D={q}&per_page=30&order=newest",
            "fedreg_json",
            "美国联邦公报；政策类事件；含 abstract 原文摘要；无密钥",
            1,
        ),
        (
            "arxiv_api",
            "http://export.arxiv.org/api/query?search_query=all:%22clinical%20trial%22&start=0&max_results=30&sortBy=submittedDate&sortOrder=descending",
            "arxiv_xml",
            "论文预印本事件源；Atom 含 summary 原文摘要",
            1,
        ),
        (
            "yahoo_finance_rss",
            "https://feeds.finance.yahoo.com/rss/2.0/headline?s=XBI&region=US&lang=en-US",
            "rss",
            "按标的代码的新闻 RSS；用于主体=标的场景；无主题检索",
            1,
        ),
        (
            "cnbc_rss",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
            "rss",
            "通用财经新闻 RSS；无主题检索能力",
            1,
        ),
        ("sina_finance_rss", "https://rss.sina.com.cn/finance/stock1.xml", "rss", "中文财经 RSS；境外可达性待验", 0),
    ]

    results = []
    for name, url, parser, note, retries in targets:
        print(f"[probe] {name} ...", flush=True)
        results.append(fetch(name, url, parser, note, retries=retries))

    payload = {
        "probe_version": 2,
        "topic": TOPIC,
        "probed_at_utc": now_utc(),
        "note": "只存指纹与短引用，不存第三方原文；原文可由 request_url + fetched_at 重抓",
        "results": results,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = [r for r in results if r.get("ok")]
    print(f"\n成功 {len(ok)}/{len(results)}")
    for r in results:
        if r.get("ok"):
            print(
                f"  OK   {r['source_id']:<26} items={r['item_count']:>3} "
                f"date={r.get('items_with_date', 0):>3} excerpt={r.get('items_with_excerpt', 0):>3} "
                f"{r.get('first_item_date')} .. {r.get('last_item_date')}"
            )
        else:
            print(f"  FAIL {r['source_id']:<26} attempts={len(r.get('attempts', []))} {r.get('failure_reason', '')[:100]}")
    print(f"\n写入 {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
