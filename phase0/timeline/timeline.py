"""一条命令：给定主题或主体 + 时间窗 → 结构化事件时间线。

设计原则（与 phase0/timeline/schema.md 对齐）：
- 输出落字段，不落自由文本；抽不出来返回显式拒绝态，不猜。
- 缺来源 URL / 抓取时刻 / 原文片段任一项的事件不许进表。
- 同一事件多家报道合并为一条，保留最早，保留全部来源。

用法：
    python phase0/timeline/timeline.py --topic "clinical trial" --start 2026-10-01 --end 2026-11-08
    python phase0/timeline/timeline.py --entity XBI --start 2026-10-01 --end 2026-11-08
    python phase0/timeline/timeline.py --topic "clinical trial" --start 2026-10-01 --end 2026-11-08 --replay phase0/timeline/out/raw_items.json

产物写到 --out-dir（默认 phase0/timeline/out）：events.json / events.md / raw_items.json。
第三方原文只留在 out/（已被 out/.gitignore 排除），不入库。
"""

from __future__ import annotations

import argparse
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

UA = "OmniNexus-timeline/0.1 (+https://github.com/an0319/OmniNexus)"
TIMEOUT = 30
RULESET_DIR = Path(__file__).resolve().parent / "rulesets"
DEFAULT_LANG = "zh"


class Ruleset:
    """一份语言规则集：只装数据，不含任何分支逻辑。

    判据与引擎解耦（AGENTS.md R24）：引擎按规则集参数判，语言差异全部落在
    rulesets/<lang>.json 的四样东西——动作动词表、门槛、拒绝码、正反例。
    """

    def __init__(self, data: dict):
        self.lang = data["lang"]
        self.version = data.get("version", "unknown")
        self.extract_method = data.get("extract_method", f"rules_{self.lang}")
        self.source_params = data.get("source_params", {})
        self.default_sources = data.get("default_sources", {"topic": [], "entity": []})
        self.actions = set(data["actions"])
        self.action_patterns = [
            (action, [re.compile(p, re.I) for p in pats]) for action, pats in data["action_patterns"]
        ]
        self.value_patterns = [
            (p["kind"], re.compile(p["pattern"], re.I), p) for p in data["value_patterns"]
        ]
        self.filters = [
            {
                "key": f["key"],
                "stage": f.get("stage", "title"),
                "where": f.get("where", "contains"),
                "pattern": re.compile(f["pattern"], re.I),
                "unless": [re.compile(p, re.I) for p in f.get("unless_patterns") or []],
            }
            for f in data.get("filters", [])
        ]
        s = data["subject"]
        self.subject = {
            "anchor_prefix": bool(s.get("anchor_prefix", False)),
            "anchor_skip_res": [re.compile(p) for p in s.get("anchor_skip") or []],
            "strip_chars": s.get("strip_chars", " .\"'()"),
            "split_re": re.compile(s["split"]) if s.get("split") else None,
            "cut_re": re.compile(s["cut"], re.I) if s.get("cut") else None,
            "leading_re": re.compile(s["leading_clause"], re.I) if s.get("leading_clause") else None,
            "trailing_re": re.compile(s["trailing_strip"], re.I) if s.get("trailing_strip") else None,
            "article_re": re.compile(s["article_strip"], re.I) if s.get("article_strip") else None,
        }
        self.gates = data["gates"]
        self.tokenize = data["tokenize"]
        self.dedupe = data["dedupe"]
        self.reject_codes = data["reject_codes"]
        self.samples = data.get("samples", {})

    def code(self, key: str) -> str:
        return self.reject_codes[key]

    def params(self, source_id: str) -> dict:
        return self.source_params.get(source_id, {})


def load_ruleset(lang: str) -> Ruleset:
    path = RULESET_DIR / f"{lang}.json"
    return Ruleset(json.loads(path.read_text(encoding="utf-8")))


DEFAULT_RULESET = load_ruleset(DEFAULT_LANG)

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(value: str) -> dt.datetime | None:
    if not value:
        return None
    v = str(value).strip()
    parsed = None
    if v.isdigit() and len(v) in (10, 13):
        # 中文源多回 epoch：快讯 sort/showtime 可能是秒，巨潮 announcementTime、36 氪 publishTime 是毫秒
        try:
            ts = int(v) / (1000 if len(v) == 13 else 1)
            return dt.datetime.fromtimestamp(ts, dt.timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
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


def clean(text: str) -> str:
    """去标签、解 HTML 实体、压空白。首版漏了解实体，摘要里残留 &nbsp;，此处修正。"""
    import html

    return SPACE_RE.sub(" ", TAG_RE.sub(" ", html.unescape(text or ""))).strip()


def rss_items(text: str) -> list[dict]:
    root = ET.fromstring(text)
    items: list[dict] = []
    for node in root.iter():
        if node.tag.split("}")[-1].lower() not in ("item", "entry"):
            continue
        row = {"title": "", "link": "", "date": "", "excerpt": "", "source_name": "", "source_url": ""}
        for child in list(node):
            ctag = child.tag.split("}")[-1].lower()
            if ctag == "title":
                row["title"] = clean(child.text or "")
            elif ctag == "link":
                row["link"] = (child.text or "").strip() or child.get("href", "")
            elif ctag in ("pubdate", "published", "updated", "date"):
                if not row["date"]:
                    row["date"] = (child.text or "").strip()
            elif ctag in ("description", "summary", "content", "abstract"):
                if not row["excerpt"]:
                    row["excerpt"] = clean(child.text or "")[:400]
            elif ctag == "source":
                row["source_name"] = clean(child.text or "")
                row["source_url"] = child.get("url", "")
        items.append(row)
    return items


# ---------------------------------------------------------------- 源适配器


class RulesetConfigError(Exception):
    """规则集缺必要参数：宁可明确失败，也不静默兜底。"""


def _need(cfg: dict, key: str, source: str) -> str:
    value = (cfg or {}).get(key)
    if not value:
        raise RulesetConfigError(
            f"规则集 source_params.{source} 缺 {key}；语言/地区参数必须由规则集提供，引擎不设默认值"
        )
    return value


def fetch_google_news(
    query: str, start: dt.date, end: dt.date, limit: int, cfg: dict | None = None
) -> list[dict]:
    """近期窗口用 when:Nd；历史窗口用 after:/before: 运算符（已实测可用，2026-11-08）。

    语言区参数全部来自规则集；引擎不留任何语言默认值，缺参数直接报错。
    """
    hl = _need(cfg, "hl", "google_news")
    gl = _need(cfg, "gl", "google_news")
    ceid = _need(cfg, "ceid", "google_news")
    source_id = _need(cfg, "source_id", "google_news")
    today = dt.datetime.now(dt.timezone.utc).date()
    if (today - end).days <= 7:
        days = max(1, (end - start).days + 1)
        q = f"{quote_plus(query)}+when:{days}d"
    else:
        q = f"{quote_plus(query)}+after:{start.isoformat()}+before:{(end + dt.timedelta(days=1)).isoformat()}"
    url = f"https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    resp.raise_for_status()
    out = []
    for it in rss_items(resp.text)[:limit]:
        title = it["title"]
        name = it["source_name"]
        excerpt = it["excerpt"]
        if name:
            if title.endswith(f" - {name}"):
                title = title[: -(len(name) + 3)].strip()
            if excerpt.endswith(name):
                excerpt = excerpt[: -len(name)].strip()
        out.append(
            {
                "source_id": source_id,
                "title": title,
                "link": it["link"],
                "url_kind": "aggregator",
                "date": it["date"],
                "excerpt": excerpt or title,
                "excerpt_kind": None,
                "source_name": name or "Google News",
                "fetched_at_utc": now_utc(),
                "subject_hint": None,
                "action_hint": None,
                "object": None,
            }
        )
    return out


def fetch_bing_news(query: str, start: dt.date, end: dt.date, limit: int, **_cfg) -> list[dict]:
    url = f"https://www.bing.com/news/search?q={quote_plus(query)}&format=RSS"
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    resp.raise_for_status()
    out = []
    for it in rss_items(resp.text)[:limit]:
        out.append(
            {
                "source_id": "bing_news",
                "title": it["title"],
                "link": it["link"],
                "url_kind": "publisher",
                "date": it["date"],
                "excerpt": it["excerpt"] or it["title"],
                "excerpt_kind": None,
                "source_name": it["source_name"] or "Bing News",
                "fetched_at_utc": now_utc(),
                "subject_hint": None,
                "action_hint": None,
                "object": None,
            }
        )
    return out


def fetch_federal_register(query: str, start: dt.date, end: dt.date, limit: int, **_cfg) -> list[dict]:
    params = {
        "conditions[term]": query,
        "conditions[publication_date][gte]": start.isoformat(),
        "conditions[publication_date][lte]": end.isoformat(),
        "per_page": str(min(limit, 100)),
        "order": "newest",
    }
    resp = requests.get(
        "https://www.federalregister.gov/api/v1/documents.json", params=params, headers={"User-Agent": UA}, timeout=TIMEOUT
    )
    resp.raise_for_status()
    out = []
    for r in resp.json().get("results", [])[:limit]:
        agencies = r.get("agencies") or []
        agency = agencies[0].get("name") if agencies and isinstance(agencies[0], dict) else None
        out.append(
            {
                "source_id": "federal_register",
                "title": r.get("title", ""),
                "link": r.get("html_url", ""),
                "url_kind": "official",
                "date": r.get("publication_date", ""),
                "excerpt": (r.get("abstract") or r.get("title") or "")[:400],
                "excerpt_kind": "abstract" if r.get("abstract") else "headline",
                "source_name": agency or "Federal Register",
                "fetched_at_utc": now_utc(),
                "subject_hint": agency,
                "action_hint": "policy",
                "object": r.get("title"),
            }
        )
    return out


def fetch_clinicaltrials(query: str, start: dt.date, end: dt.date, limit: int, **_cfg) -> list[dict]:
    params = {
        "query.term": query,
        "pageSize": str(min(limit, 100)),
        "sort": "LastUpdatePostDate:desc",
    }
    resp = requests.get(
        "https://clinicaltrials.gov/api/v2/studies", params=params, headers={"User-Agent": UA}, timeout=TIMEOUT
    )
    resp.raise_for_status()
    out = []
    for s in resp.json().get("studies", [])[:limit]:
        p = s.get("protocolSection", {})
        ident = p.get("identificationModule", {}) or {}
        status = p.get("statusModule", {}) or {}
        sponsor = (p.get("sponsorCollaboratorsModule", {}) or {}).get("leadSponsor", {}) or {}
        phases = (p.get("designModule", {}) or {}).get("phases", []) or []
        first_post = status.get("studyFirstPostDateStruct")
        date = first_post.get("date", "") if isinstance(first_post, dict) else str(first_post or "")
        out.append(
            {
                "source_id": "clinicaltrials",
                "title": ident.get("briefTitle", ""),
                "link": f"https://clinicaltrials.gov/study/{ident.get('nctId', '')}",
                "url_kind": "official",
                "date": date,
                "excerpt": (p.get("descriptionModule", {}) or {}).get("briefSummary", "")[:400],
                "excerpt_kind": "abstract",
                "source_name": sponsor.get("name") or "ClinicalTrials.gov",
                "fetched_at_utc": now_utc(),
                "subject_hint": sponsor.get("name"),
                "action_hint": "registration",
                "object": ident.get("briefTitle"),
                "phase_hint": phases[0] if phases else None,
            }
        )
    return out


def fetch_arxiv(query: str, start: dt.date, end: dt.date, limit: int, **_cfg) -> list[dict]:
    url = (
        "http://export.arxiv.org/api/query?search_query=all:%22"
        f"{quote_plus(query)}%22&start=0&max_results={min(limit, 100)}"
        "&sortBy=submittedDate&sortOrder=descending"
    )
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    resp.raise_for_status()
    out = []
    for it in rss_items(resp.text)[:limit]:
        out.append(
            {
                "source_id": "arxiv",
                "title": it["title"],
                "link": it["link"],
                "url_kind": "official",
                "date": it["date"],
                "excerpt": it["excerpt"],
                "excerpt_kind": "abstract",
                "source_name": "arXiv",
                "fetched_at_utc": now_utc(),
                "subject_hint": None,
                "action_hint": "publication",
                "object": it["title"],
            }
        )
    return out


def fetch_yahoo(symbol: str, start: dt.date, end: dt.date, limit: int, cfg: dict | None = None) -> list[dict]:
    """region/lang 由规则集提供；引擎不留英文兜底。"""
    region = _need(cfg, "region", "yahoo_finance")
    lang = _need(cfg, "lang", "yahoo_finance")
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={quote_plus(symbol)}&region={region}&lang={lang}"
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    resp.raise_for_status()
    out = []
    for it in rss_items(resp.text)[:limit]:
        out.append(
            {
                "source_id": "yahoo_finance",
                "title": it["title"],
                "link": it["link"],
                "url_kind": "publisher",
                "date": it["date"],
                "excerpt": it["excerpt"] or it["title"],
                "excerpt_kind": None,
                "source_name": it["source_name"] or "Yahoo Finance",
                "fetched_at_utc": now_utc(),
                "subject_hint": symbol,
                "action_hint": None,
                "object": None,
            }
        )
    return out


def fetch_cnbc(query: str, start: dt.date, end: dt.date, limit: int, **_cfg) -> list[dict]:
    resp = requests.get(
        "https://www.cnbc.com/id/100003114/device/rss/rss.html", headers={"User-Agent": UA}, timeout=TIMEOUT
    )
    resp.raise_for_status()
    out = []
    for it in rss_items(resp.text)[:limit]:
        out.append(
            {
                "source_id": "cnbc",
                "title": it["title"],
                "link": it["link"],
                "url_kind": "publisher",
                "date": it["date"],
                "excerpt": it["excerpt"] or it["title"],
                "excerpt_kind": None,
                "source_name": "CNBC",
                "fetched_at_utc": now_utc(),
                "subject_hint": None,
                "action_hint": None,
                "object": None,
            }
        )
    return out


def _epoch(ts, unit: str = "s") -> str:
    try:
        val = float(ts)
    except (TypeError, ValueError):
        return ""
    if unit == "ms":
        val = val / 1000.0
    return dt.datetime.fromtimestamp(val, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _match_query(query: str, text: str) -> bool:
    """取数层的粗筛（不是判据）：主题词或其 ≥2 字片段命中即保留。"""
    if not query:
        return True
    if query in text:
        return True
    return any(t and len(t) >= 2 and t in text for t in re.split(r"[\s,，、]+", query))


def fetch_eastmoney_news(query: str, start: dt.date, end: dt.date, limit: int, **_cfg) -> list[dict]:
    """东方财富快讯：JSONP，需剥 `var ajaxResult=` 前缀（2026-11-08 实测）。"""
    resp = requests.get(
        "https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_50_1_.html",
        headers={"User-Agent": UA},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    payload = json.loads(resp.text.split("=", 1)[1])
    out = []
    for r in (payload.get("LivesList") or [])[:limit]:
        title = clean(r.get("title") or "")
        excerpt = clean(r.get("digest") or "")[:400]
        if not _match_query(query, f"{title}{excerpt}"):
            continue
        out.append(
            {
                "source_id": "eastmoney_news",
                "title": title,
                "link": r.get("url_unique") or "",
                "url_kind": "publisher",
                "date": r.get("showtime") or "",
                "excerpt": excerpt or title,
                "excerpt_kind": None,
                "source_name": "东方财富",
                "fetched_at_utc": now_utc(),
                "subject_hint": None,
                "action_hint": None,
                "object": None,
            }
        )
    return out


def fetch_sina_roll(query: str, start: dt.date, end: dt.date, limit: int, **_cfg) -> list[dict]:
    """新浪财经滚动列表：JSON（2026-11-08 实测；当天 `pdps` 可能为空，属源侧波动）。"""
    url = f"https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&num={min(limit, 30)}"
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    resp.raise_for_status()
    out = []
    for r in (resp.json().get("result", {}).get("pdps") or [])[:limit]:
        title = clean(r.get("title") or "")
        excerpt = clean(r.get("intro") or "")[:400]
        if not _match_query(query, f"{title}{excerpt}"):
            continue
        out.append(
            {
                "source_id": "sina_roll",
                "title": title,
                "link": r.get("url") or "",
                "url_kind": "publisher",
                "date": _epoch(r.get("ctime")),
                "excerpt": excerpt or title,
                "excerpt_kind": None,
                "source_name": "新浪财经",
                "fetched_at_utc": now_utc(),
                "subject_hint": None,
                "action_hint": None,
                "object": None,
            }
        )
    return out


def fetch_wallstreetcn(query: str, start: dt.date, end: dt.date, limit: int, **_cfg) -> list[dict]:
    """华尔街见闻快讯：JSON，`display_time` 为 epoch 秒（2026-11-08 实测）。"""
    url = f"https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit={min(limit, 50)}"
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    resp.raise_for_status()
    out = []
    for r in (resp.json().get("data", {}).get("items") or [])[:limit]:
        title = clean(r.get("title") or (r.get("content_text") or "")[:60])
        excerpt = clean(r.get("content_text") or "")[:400]
        if not _match_query(query, f"{title}{excerpt}"):
            continue
        out.append(
            {
                "source_id": "wallstreetcn",
                "title": title,
                "link": r.get("uri") or "https://wallstreetcn.com/livenews",
                "url_kind": "publisher",
                "date": _epoch(r.get("display_time")),
                "excerpt": excerpt or title,
                "excerpt_kind": None,
                "source_name": "华尔街见闻",
                "fetched_at_utc": now_utc(),
                "subject_hint": None,
                "action_hint": None,
                "object": None,
            }
        )
    return out


def fetch_kr36(query: str, start: dt.date, end: dt.date, limit: int, **_cfg) -> list[dict]:
    """36 氪快讯：gateway JSON POST，无需登录（2026-11-08 实测）。

    边界（zh_source_access.md §0.5）：这是公开网页自己调的接口，不是绕过技术措施；
    随前端改版可能失效，失效时按取源失败处理，不做逆向修补。
    """
    body = {
        "partner_id": "web",
        "param": {
            "siteId": 1,
            "platformId": 2,
            "pageSize": min(limit, 30),
            "pageEvent": 0,
            "pageCallback": "",
            "type": 1,
        },
    }
    resp = requests.post(
        "https://gateway.36kr.com/api/mis/nav/newsflash/flow",
        json=body,
        headers={"User-Agent": UA},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    out = []
    for r in (resp.json().get("data", {}).get("itemList") or [])[:limit]:
        mat = r.get("templateMaterial") or {}
        title = clean(mat.get("widgetTitle") or "")
        excerpt = clean(mat.get("widgetContent") or "")[:400]
        if not _match_query(query, f"{title}{excerpt}"):
            continue
        out.append(
            {
                "source_id": "kr36",
                "title": title,
                "link": f"https://36kr.com/newsflashes/{r.get('itemId')}" if r.get("itemId") else "",
                "url_kind": "publisher",
                "date": _epoch(mat.get("publishTime"), "ms"),
                "excerpt": excerpt or title,
                "excerpt_kind": None,
                "source_name": "36氪",
                "fetched_at_utc": now_utc(),
                "subject_hint": None,
                "action_hint": None,
                "object": None,
            }
        )
    return out


def fetch_cninfo(query: str, start: dt.date, end: dt.date, limit: int, **_cfg) -> list[dict]:
    """巨潮资讯公告查询：JSON POST，需 Referer/Origin/X-Requested-With（2026-11-08 实测）。"""
    headers = {
        "User-Agent": UA,
        "Referer": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
        "Origin": "http://www.cninfo.com.cn",
        "X-Requested-With": "XMLHttpRequest",
    }
    data = {
        "pageNum": 1,
        "pageSize": min(limit, 30),
        "column": "szse",
        "tabName": "fulltext",
        "searchkey": query or "",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
        "seDate": f"{start.isoformat()}~{end.isoformat()}",
    }
    resp = requests.post(
        "http://www.cninfo.com.cn/new/hisAnnouncement/query", data=data, headers=headers, timeout=TIMEOUT
    )
    resp.raise_for_status()
    out = []
    for a in (resp.json().get("announcements") or [])[:limit]:
        sec = clean(a.get("secName") or "")
        ann = clean(a.get("announcementTitle") or "")
        out.append(
            {
                "source_id": "cninfo",
                "title": f"{sec}：{ann}" if sec else ann,
                "link": f"http://static.cninfo.com.cn/{a.get('adjunctUrl')}" if a.get("adjunctUrl") else "",
                "url_kind": "official",
                "date": _epoch(a.get("announcementTime"), "ms"),
                "excerpt": ann,
                "excerpt_kind": None,
                "source_name": "巨潮资讯",
                "fetched_at_utc": now_utc(),
                "subject_hint": sec or None,
                "action_hint": None,
                "object": ann or None,
            }
        )
    return out


FETCHERS = {
    "google_news": fetch_google_news,
    "bing_news": fetch_bing_news,
    "federal_register": fetch_federal_register,
    "clinicaltrials": fetch_clinicaltrials,
    "arxiv": fetch_arxiv,
    "yahoo_finance": fetch_yahoo,
    "cnbc": fetch_cnbc,
    "eastmoney_news": fetch_eastmoney_news,
    "sina_roll": fetch_sina_roll,
    "wallstreetcn": fetch_wallstreetcn,
    "kr36": fetch_kr36,
    "cninfo": fetch_cninfo,
}


# ---------------------------------------------------------------- 抽取


def filter_hit(flt: dict, text: str) -> bool:
    where = flt["where"]
    m = flt["pattern"].match(text) if where == "title_prefix" else flt["pattern"].search(text)
    if not m:
        return False
    return not any(u.search(text) for u in flt["unless"])


def apply_filters(stage: str, text: str, rs: Ruleset) -> str | None:
    """按规则集的过滤表判；命中返回拒绝码键，否则 None。"""
    for flt in rs.filters:
        if flt["stage"] == stage and filter_hit(flt, text):
            return flt["key"]
    return None


def detect_action(text: str, rs: Ruleset) -> tuple[str | None, str | None, int | None]:
    """返回 (action, 原文锚点, 锚点起始位)。位置最早者胜；同位置按规则集表序。"""
    best: tuple[int, int, str, str] | None = None
    for order, (action, pats) in enumerate(rs.action_patterns):
        for pat in pats:
            m = pat.search(text)
            if not m:
                continue
            key = (m.start(), order, action, m.group(0))
            if best is None or key[:2] < best[:2]:
                best = key
    if best is None:
        return None, None, None
    return best[2], best[3][:60], best[0]


def detect_value(text: str, rs: Ruleset) -> dict:
    best: tuple[int, int, str, str] | None = None
    for order, (kind, pat, _cfg) in enumerate(rs.value_patterns):
        m = pat.search(text)
        if not m:
            continue
        key = (m.start(), order, kind, m.group(0))
        if best is None or key[:2] < best[:2]:
            best = key
    if best is None:
        return {"kind": "none", "raw": None, "number": None, "unit": None}
    kind, raw = best[2], best[3]
    number = None
    unit = None
    for k, pat, cfg in rs.value_patterns:
        if k != kind:
            continue
        m = pat.search(text)
        if not m:
            break
        try:
            number = float(m.group(cfg.get("number_group", 1)).replace(",", ""))
        except (ValueError, IndexError):
            number = None
        if cfg.get("unit") == "lower":
            unit = m.group(cfg["unit_group"]).lower()
        else:
            unit = cfg.get("unit")
        break
    return {"kind": kind, "raw": raw.strip(), "number": number, "unit": unit}


def extract_subject(prefix: str, rs: Ruleset, action_start: int | None = None) -> str | None:
    s = rs.subject
    strip = s["strip_chars"]
    raw = prefix.replace("\n", " ").strip()
    if s["anchor_prefix"] and action_start:
        # 中文：以动作锚点为右边界取前缀，主体名天然逐字落在原文里
        head = raw[:action_start]
        parts = [p.strip(strip) for p in (s["split_re"].split(head) if s["split_re"] else [head])]
        parts = [p for p in parts if p]
        # 「关于…的公告」这类定语小句落在锚点左侧时会被当成主体，按规则集给的式样回退一段
        while parts and any(r.match(parts[-1]) for r in s["anchor_skip_res"]):
            parts.pop()
        cand = parts[-1] if parts else ""
    else:
        chunks = [c.strip(strip) for c in s["split_re"].split(raw) if c.strip(strip)]
        if not chunks:
            return None
        # 以时间/原因状语开头的标题（"After two deaths..., Artiva is shutting down"），主体在最后一段
        cand = chunks[-1] if s["leading_re"] and s["leading_re"].match(chunks[0]) else chunks[0]
        if s["cut_re"]:
            cand = s["cut_re"].split(cand, maxsplit=1)[0].strip(strip)
        if s["trailing_re"]:
            cand = s["trailing_re"].sub("", cand)
        if s["article_re"]:
            cand = s["article_re"].sub("", cand).strip(strip)
    g = rs.gates
    if len(cand) < g["subject_min_len"] or len(cand) > g["subject_max_len"]:
        return None
    # 股票代码开头的标题（"301189 再签…"）主体就是那个代码：规则集给了式样才启用
    lead = g.get("subject_lead_code")
    code_m = re.match(lead, cand) if lead else None
    if code_m:
        cand = code_m.group(0)
    else:
        # 首版把 "83% problem" 当主体，这里要求主体以字母/汉字开头且达到最少字符数
        if not re.match(g["subject_first_char"], cand):
            return None
        if len(re.findall(g["subject_first_char"], cand)) < g["subject_min_class_chars"]:
            return None
    return cand


def build_event(
    item: dict,
    start: dt.date,
    end: dt.date,
    entity: str | None = None,
    ruleset: Ruleset | None = None,
) -> tuple[dict | None, str | None]:
    rs = ruleset or DEFAULT_RULESET
    when = parse_date(item.get("date", ""))
    if when is None:
        return None, rs.code("missing_time")
    day = when.date()
    if not (start <= day <= end):
        return None, rs.code("out_of_window")

    url = (item.get("link") or "").strip()
    if not url.startswith(("http://", "https://")):
        return None, rs.code("missing_url")

    excerpt = SPACE_RE.sub(" ", (item.get("excerpt") or "")).strip()
    if len(excerpt) < rs.gates["excerpt_min"]:
        return None, rs.code("missing_excerpt")

    title = item.get("title", "") or ""
    text = f"{title}. {excerpt}"
    if entity and entity.lower() not in text.lower():
        return None, rs.code("subject_not_in_text")
    key = apply_filters("title", title.strip(), rs)
    if key:
        return None, rs.code(key)
    key = apply_filters("text", text, rs)
    if key:
        return None, rs.code(key)

    action = item.get("action_hint")
    anchor = None
    action_start = None
    if action is None:
        action, anchor, action_start = detect_action(text, rs)
        if action is None:
            return None, rs.code("unparsed_action")
    else:
        anchor = title[:60] or action

    subject = item.get("subject_hint")
    if not subject:
        subject = extract_subject(title, rs, action_start)
        if not subject:
            return None, rs.code("unparsed_subject")
    key = apply_filters("subject", str(subject), rs)
    if key:
        return None, rs.code(key)

    value = detect_value(text, rs)
    if item.get("phase_hint") and value["kind"] == "none":
        value = {"kind": "phase", "raw": item["phase_hint"], "number": None, "unit": "phase"}

    event = {
        "event_id": hashlib.sha256(
            f"{subject}|{action}|{day.isoformat()}|{url}".encode()
        ).hexdigest()[:16],
        "time": day.isoformat(),
        "time_precision": "day" if not re.search(r"\d{2}:\d{2}", item.get("date", "")) else "minute",
        "subject": subject,
        "action": action,
        "action_text": anchor,
        "object": item.get("object"),
        "value": value,
        "source_url": url,
        "url_kind": item.get("url_kind", "publisher"),
        "source_name": item.get("source_name") or "unknown",
        "fetched_at_utc": item.get("fetched_at_utc"),
        "excerpt": excerpt[:400],
        "excerpt_kind": item.get("excerpt_kind")
        or ("summary" if len(excerpt) >= rs.gates["excerpt_kind_min"] else "headline"),
        "extract_method": rs.extract_method,
        "sources": [
            {
                "source_url": url,
                "source_name": item.get("source_name") or "unknown",
                "url_kind": item.get("url_kind", "publisher"),
                "fetched_at_utc": item.get("fetched_at_utc"),
                "excerpt": excerpt[:200],
            }
        ],
    }
    reason = validate_event(event, rs)
    return (None, reason) if reason else (event, None)


def validate_event(ev: dict, ruleset: Ruleset | None = None) -> str | None:
    rs = ruleset or DEFAULT_RULESET
    g = rs.gates
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ev.get("time", "")):
        return rs.code("missing_time")
    if not ev.get("subject") or len(ev["subject"]) > g["subject_max_len"]:
        return rs.code("unparsed_subject")
    if ev.get("action") not in rs.actions:
        return rs.code("unparsed_action")
    if not str(ev.get("source_url", "")).startswith(("http://", "https://")):
        return rs.code("missing_url")
    if parse_date(ev.get("fetched_at_utc", "")) is None:
        return rs.code("missing_time")
    if len(SPACE_RE.sub(" ", ev.get("excerpt", "")).strip()) < g["excerpt_min"]:
        return rs.code("missing_excerpt")
    for src in ev.get("sources") or []:
        if not str(src.get("source_url", "")).startswith(("http://", "https://")):
            return rs.code("missing_url")
        if parse_date(src.get("fetched_at_utc", "")) is None:
            return rs.code("missing_time")
        if len(SPACE_RE.sub(" ", src.get("excerpt", "")).strip()) < g["excerpt_min"]:
            return rs.code("missing_excerpt")
    if not ev.get("sources"):
        return rs.code("missing_excerpt")
    return None


# ---------------------------------------------------------------- 去重


def norm_tokens(title: str, rs: Ruleset) -> set[str]:
    words = re.findall(rs.tokenize["pattern"], title.lower())
    stop = set(rs.tokenize.get("stopwords") or [])
    return {w for w in words if w not in stop and len(w) >= rs.tokenize.get("min_len", 1)}


def same_event(a: dict, b: dict, rs: Ruleset | None = None) -> bool:
    rs = rs or DEFAULT_RULESET
    cfg = rs.dedupe
    # 官方记录（Federal Register / ClinicalTrials / arXiv / 巨潮公告）每条是独立文书，
    # 标题相近不代表同一事件，所以只在新闻源之间做合并。
    if a.get("_source_id") not in cfg["merge_sources"] or b.get("_source_id") not in cfg["merge_sources"]:
        return False
    if a["action"] != b["action"]:
        return False
    d1 = dt.date.fromisoformat(a["time"])
    d2 = dt.date.fromisoformat(b["time"])
    if abs((d1 - d2).days) > cfg["day_tolerance"]:
        return False
    ta, tb = norm_tokens(a["_title"], rs), norm_tokens(b["_title"], rs)
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    union = len(ta | tb)
    return union > 0 and inter / union >= cfg["jaccard_min"]


def merge_events(events: list[dict], ruleset: Ruleset | None = None) -> tuple[list[dict], int]:
    merged: list[dict] = []
    dup_count = 0
    for ev in sorted(events, key=lambda e: (e["time"], e["sources"][0]["fetched_at_utc"])):
        for cur in merged:
            if same_event(cur, ev, ruleset):
                if len(cur["sources"]) < 8:
                    cur["sources"].append(ev["sources"][0])
                dup_count += 1
                break
        else:
            merged.append(ev)
    return merged, dup_count


# ---------------------------------------------------------------- 输出


def write_outputs(out_dir: Path, status: str, meta: dict, events: list[dict], rejects: list[dict], raw: list[dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "events.json").write_text(
        json.dumps({"status": status, "meta": meta, "events": events, "rejects": rejects}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "raw_items.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 事件时间线：{meta['query']}",
        "",
        f"- 时间窗：{meta['window_start']} → {meta['window_end']}",
        f"- 生成时刻（UTC）：{meta['generated_at_utc']}",
        f"- 抽取器：{meta['extract_method']}",
        f"- **本次状态：{status}**（ok=全部源抓取成功；partial=部分源失败；failed=全部源失败，此表不代表「今天没有事件」）",
        f"- 入表 {len(events)} 条，拒绝 {len(rejects)} 条，合并重复 {meta['stats']['merged_duplicates']} 条",
        f"- 源统计：{json.dumps(meta['sources_stats'], ensure_ascii=False)}",
        "",
    ]
    if status == "failed":
        lines.append("_全部源抓取失败：本表为空是因为没抓到数据，不表示这段时间没有事件。_")
    elif status == "partial":
        lines.append("_部分源抓取失败：本表只覆盖成功的源，不表示全量。拒绝原因见 events.json 的 rejects 字段。_")
    elif not events:
        lines.append("_本次没有事件通过硬校验。拒绝原因见 events.json 的 rejects 字段。_")
    current_day = None
    for ev in events:
        if ev["time"] != current_day:
            current_day = ev["time"]
            lines += ["", f"## {current_day}", ""]
        val = ev["value"]
        val_txt = f"{val['raw']}" if val["kind"] != "none" else "—"
        lines.append(f"- **{ev['subject']}** · `{ev['action']}` · 数值 {val_txt}")
        lines.append(f"  > {ev['excerpt'][:200]}")
        for src in ev["sources"]:
            lines.append(
                f"  - [{src['source_name']}]({src['source_url']}) · {src['url_kind']} · 抓取 {src['fetched_at_utc']}"
            )
    (out_dir / "events.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    if start > end:
        print("时间窗起止反了：--start 必须 <= --end", file=sys.stderr)
        return 2

    rs = load_ruleset(args.lang)
    out_dir = Path(args.out_dir)
    raw: list[dict] = []
    sources_stats: dict[str, dict] = {}

    if args.replay:
        raw = json.loads(Path(args.replay).read_text(encoding="utf-8"))
        for it in raw:
            stats = sources_stats.setdefault(it["source_id"], {"fetched": 0, "accepted": 0, "rejected": 0})
            stats["fetched"] += 1
        print(f"[replay] 读取 {len(raw)} 条：{args.replay}")
    else:
        names = [s.strip() for s in args.sources.split(",") if s.strip()]
        query = args.topic if args.topic else (args.entity or "")
        if not query:
            print("必须给 --topic 或 --entity", file=sys.stderr)
            return 2
        for i, name in enumerate(names):
            if name not in FETCHERS:
                print(f"未知源：{name}；可选 {sorted(FETCHERS)}", file=sys.stderr)
                return 2
            if i:
                time.sleep(1.2)
            try:
                items = FETCHERS[name](query, start, end, args.max_per_source, cfg=rs.params(name))
                raw.extend(items)
                sources_stats.setdefault(name, {"fetched": 0, "accepted": 0, "rejected": 0})
                sources_stats[name]["fetched"] += len(items)
                print(f"[fetch] {name}: {len(items)} 条")
            except Exception as exc:  # noqa: BLE001 - 单源失败不影响其它源
                sources_stats.setdefault(name, {"fetched": 0, "accepted": 0, "rejected": 0, "error": ""})
                sources_stats[name]["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
                print(f"[fetch] {name}: FAIL {type(exc).__name__}: {str(exc)[:120]}")

    # 抓取状态：与「有没有事件」分开记。全部源失败 ≠ 今天没有事件。
    if args.replay:
        status = "ok"
    else:
        requested = [s.strip() for s in args.sources.split(",") if s.strip()]
        failed = [n for n in requested if sources_stats.get(n, {}).get("error")]
        if len(failed) == len(requested):
            status = "failed"
        elif failed:
            status = "partial"
        else:
            status = "ok"

    rejects: list[dict] = []
    events: list[dict] = []
    for item in raw:
        ev, reason = build_event(item, start, end, entity=args.entity, ruleset=rs)
        if ev is None:
            rejects.append(
                {
                    "source_id": item.get("source_id"),
                    "title": (item.get("title") or "")[:120],
                    "url": item.get("link"),
                    "date": item.get("date"),
                    "reason": reason,
                }
            )
            stats = sources_stats.setdefault(item.get("source_id", "?"), {"fetched": 0, "accepted": 0, "rejected": 0})
            stats["rejected"] = stats.get("rejected", 0) + 1
            continue
        ev["_title"] = item.get("title", "")
        ev["_source_id"] = item.get("source_id")
        events.append(ev)

    merged, dup_count = merge_events(events, rs)
    for ev in merged:
        ev.pop("_title", None)
        source_id = ev.pop("_source_id", None)
        stats = sources_stats.setdefault(source_id or "?", {"fetched": 0, "accepted": 0, "rejected": 0})
        stats["accepted"] = stats.get("accepted", 0) + 1

    reason_counts: dict[str, int] = {}
    for r in rejects:
        reason_counts[r["reason"]] = reason_counts.get(r["reason"], 0) + 1

    meta = {
        "query": args.topic or args.entity,
        "mode": "topic" if args.topic else "entity",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "generated_at_utc": now_utc(),
        "extract_method": rs.extract_method,
        "ruleset": f"{rs.lang}/{rs.version}",
        "sources": [s.strip() for s in args.sources.split(",") if s.strip()],
        "sources_stats": sources_stats,
        "stats": {
            "raw_items": len(raw),
            "events": len(merged),
            "rejects": len(rejects),
            "merged_duplicates": dup_count,
            "reject_reasons": reason_counts,
        },
    }

    write_outputs(out_dir, status, meta, merged, rejects, raw)

    print(
        f"\n[result] raw={len(raw)} events={len(merged)} rejects={len(rejects)} "
        f"merged={dup_count} reasons={reason_counts}"
    )
    print(f"[status] {status}  sources={json.dumps(sources_stats, ensure_ascii=False)}")
    print(f"[write] {out_dir / 'events.json'}")
    print(f"[write] {out_dir / 'events.md'}")
    print(f"[write] {out_dir / 'raw_items.json'}")
    if status == "failed":
        print("[status] FAILED: 全部源抓取失败，本次结果无证据力（退出码 3）", file=sys.stderr)
        return 3
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="主题/主体 + 时间窗 → 事件时间线")
    ap.add_argument("--topic", help="主题词，如 clinical trial")
    ap.add_argument("--entity", help="主体词，如 XBI 或公司名")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--sources", default=None, help="逗号分隔的源名；默认按规则集的 default_sources 给")
    ap.add_argument("--lang", default=DEFAULT_LANG, help=f"规则集语言；默认 {DEFAULT_LANG}（可用：zh / en）")
    ap.add_argument("--max-per-source", type=int, default=60)
    ap.add_argument("--out-dir", default=str(Path(__file__).resolve().parent / "out"))
    ap.add_argument("--replay", default=None, help="离线复跑：读取 raw_items.json")
    args = ap.parse_args()
    if args.sources is None:
        rs = load_ruleset(args.lang)
        args.sources = ",".join(rs.default_sources["topic" if args.topic else "entity"])
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
