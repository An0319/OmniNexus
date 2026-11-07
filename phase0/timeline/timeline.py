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
EXTRACT_METHOD = "rules_v2"

ACTIONS = {
    "trial_start",
    "trial_result",
    "approval",
    "rejection",
    "halt",
    "designation",
    "deal",
    "partnership",
    "funding",
    "policy",
    "registration",
    "publication",
    "personnel",
    "other",
}

# (action, [正则])：命中位置取最早，平手按此表顺序
ACTION_PATTERNS: list[tuple[str, list[str]]] = [
    ("halt", [r"\bhalt(s|ed|ing)?\b", r"\bsuspend(s|ed|ing)?\b", r"\bpause[sd]?\b", r"\bterminat(e|es|ed)\b",
              r"\bstop(s|ped)?\b", r"\bdiscontinu(e|ed|ation)\b", r"\bshut(s|ting)? down\b",
              r"\bwind(s|ing)? down\b", r"\bceas(e|es|ed)\b"]),
    ("rejection", [r"\breject(s|ed|ion)?\b", r"\bdeclin(e|es|ed)\b", r"\bden(y|ies|ied)\b",
                   r"\bcomplete response letter\b", r"\bCRL\b"]),
    ("approval", [r"\bapprov(e|es|ed|al)\b", r"\bauthoriz(e|es|ed|ation)\b", r"\bclear(s|ed)?\b",
                  r"\bclearance\b", r"\bgreen[- ]light(s|ed)?\b"]),
    ("designation", [r"\borphan\b", r"\bbreakthrough therapy\b", r"\bfast[- ]track\b", r"\bpriority review\b",
                     r"\bdesignat(e|es|ed|ion)\b"]),
    ("trial_result", [r"\bresults?\b", r"\btopline\b", r"\bread[- ]?out\b", r"\bmet (its|the) primary endpoint\b",
                      r"\bmiss(es|ed)? (its|the) primary endpoint\b", r"\bfail(s|ed|ure)?\b",
                      r"\bdemonstrat(e|es|ed)\b", r"\bshow(s|ed|n)? (promising|positive|efficacy|promise)\b",
                      r"\bremission\b", r"\bresponse rate\b", r"\bsurvival\b", r"\bendpoint\b",
                      r"\bclinical progress\b", r"\bweight loss\b", r"\bhelped (people|patients)\b"]),
    ("trial_start", [r"\binitiat(e|es|ed|ion)\b", r"\blaunch(es|ed|ing)?\b", r"\bstart(s|ed|ing)?\b",
                     r"\bbegin(s|ning)?\b", r"\benroll(s|ed|ing|ment)?\b", r"\badvanc(e|es|ed|ing)\b",
                     r"\bfirst patient (dosed|enrolled|treated|receiv)", r"\bopen(s|ed)? (a |the )?(phase|trial|study)\b",
                     r"\bjoin(s|ed)?\b", r"\bparticipat(e|es|ed|ing)\b", r"\bnow in (clinical )?trials?\b",
                     r"\benters? (a |the )?(clinical |phase)?trial\b"]),
    ("deal", [r"\bacquir(e|es|ed|ing|sition)\b", r"\bmerger\b", r"\bmerg(e|es|ed)\b", r"\btakeover\b",
              r"\bbuy(s|ing)?\b", r"\bsell(s|ing)?\b", r"\blicens(e|es|ed|ing)\b"]),
    ("partnership", [r"\bpartner(s|ed|ship)?\b", r"\bcollaborat(e|es|ed|ion)\b", r"\bteam(s|ed)? up\b",
                     r"\bjoint venture\b"]),
    ("funding", [r"\brais(e|es|ed|ing)\b", r"\bfund(s|ed|ing)?\b", r"\binvest(s|ed|ing|ment)?\b",
                 r"\bround\b", r"\bfinanc(e|es|ed|ing)\b"]),
    ("policy", [r"\bfinal rule\b", r"\bproposed rule\b", r"\brulemaking\b", r"\bnotice of\b",
                r"\bguidance\b", r"\brequest for information\b", r"\bcomment period\b"]),
    ("registration", [r"\bregist(er|ered|ration|ry)\b", r"\bposted\b", r"\bnew trial\b"]),
    ("publication", [r"\bpreprint\b", r"\bstudy published\b", r"\bpublished in\b", r"\bresearchers? (find|show|report)\b",
                     r"\bstud(y|ies) (finds?|shows?|suggests?|reports?)\b",
                     r"\bpaper\b", r"\brandomi[sz]ed (controlled |clinical )?trial\b"]),
    ("personnel", [r"\bappoint(s|ed|ment)?\b", r"\bname[sd]?\b", r"\bresign(s|ed|ation)?\b",
                   r"\bsteps? down\b", r"\bhir(e|es|ed)\b", r"\bCEO\b"]),
]
COMPILED = [(a, [re.compile(p, re.I) for p in pats]) for a, pats in ACTION_PATTERNS]

VALUE_PATTERNS = [
    ("money", re.compile(r"\$\s?([\d][\d,\.]*)\s?(billion|million|bn|m|b)\b", re.I)),
    ("percent", re.compile(r"([\d][\d\.]*)\s?%", re.I)),
    ("phase", re.compile(r"\bphase\s?(1|2|3|4|i{1,3}|iv)\b", re.I)),
    ("count", re.compile(r"\b([\d][\d,]*)\s+(patients|participants|subjects|sites|countries)\b", re.I)),
]

STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "with", "by", "at", "from", "as",
    "is", "are", "was", "were", "be", "been", "its", "it", "this", "that", "new",
}
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_date(value: str) -> dt.datetime | None:
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


def clean(text: str) -> str:
    """去标签、解 HTML 实体、压空白。首版漏了解实体，摘要里残留 &nbsp;，此处修正。"""
    import html

    return SPACE_RE.sub(" ", TAG_RE.sub(" ", html.unescape(text or ""))).strip()


NOT_EVENT_RE = re.compile(
    r"^(why|how|what|you\b|here'?s what|opinion|analysis|commentary|guest commentary|explainer|podcast|video|newsletter|the case for)\b",
    re.I,
)

LEADING_CLAUSE_RE = re.compile(
    r"^(after|before|following|ahead of|in|as|amid|on|during|with|at|since|once)\b", re.I
)

SUBJECT_CUT_RE = re.compile(
    r"[:\u2014\u2013]|,\s+|\s+(?:to|will|plans?|is|are|was|were|has|have|had|said|says|after|as|amid|"
    r"following|on|in|for|with|by|and|sinks|jumps|surges|slides|rises|falls|plunges|soars|announces|"
    r"reports|launches|starts|begins|wins|loses|teams|files|gets|seeks|faces|bags|achieves|draws?|"
    r"sees?|needs?|aims?|joins?|buys?|sells?|partners?|raises?|sues?|warns?|expects?|targets?|unveils?|"
    r"presents?|publishes?|finds?|shows?|signs?|adds?|names?|calls?|urges?|asks?|makes?|takes?|gives?)\b",
    re.I,
)


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


def fetch_google_news(query: str, start: dt.date, end: dt.date, limit: int) -> list[dict]:
    """近期窗口用 when:Nd；历史窗口用 after:/before: 运算符（已实测可用，2026-11-08）。"""
    today = dt.datetime.now(dt.timezone.utc).date()
    if (today - end).days <= 7:
        days = max(1, (end - start).days + 1)
        q = f"{quote_plus(query)}+when:{days}d"
    else:
        q = f"{quote_plus(query)}+after:{start.isoformat()}+before:{(end + dt.timedelta(days=1)).isoformat()}"
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
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
                "source_id": "google_news",
                "title": title,
                "link": it["link"],
                "url_kind": "aggregator",
                "date": it["date"],
                "excerpt": excerpt or title,
                "excerpt_kind": "summary" if len(excerpt) >= 20 else "headline",
                "source_name": name or "Google News",
                "fetched_at_utc": now_utc(),
                "subject_hint": None,
                "action_hint": None,
                "object": None,
            }
        )
    return out


def fetch_bing_news(query: str, start: dt.date, end: dt.date, limit: int) -> list[dict]:
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
                "excerpt_kind": "summary" if len(it["excerpt"]) >= 20 else "headline",
                "source_name": it["source_name"] or "Bing News",
                "fetched_at_utc": now_utc(),
                "subject_hint": None,
                "action_hint": None,
                "object": None,
            }
        )
    return out


def fetch_federal_register(query: str, start: dt.date, end: dt.date, limit: int) -> list[dict]:
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


def fetch_clinicaltrials(query: str, start: dt.date, end: dt.date, limit: int) -> list[dict]:
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


def fetch_arxiv(query: str, start: dt.date, end: dt.date, limit: int) -> list[dict]:
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


def fetch_yahoo(symbol: str, start: dt.date, end: dt.date, limit: int) -> list[dict]:
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={quote_plus(symbol)}&region=US&lang=en-US"
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
                "excerpt_kind": "summary" if len(it["excerpt"]) >= 20 else "headline",
                "source_name": it["source_name"] or "Yahoo Finance",
                "fetched_at_utc": now_utc(),
                "subject_hint": symbol,
                "action_hint": None,
                "object": None,
            }
        )
    return out


def fetch_cnbc(query: str, start: dt.date, end: dt.date, limit: int) -> list[dict]:
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
                "excerpt_kind": "summary" if len(it["excerpt"]) >= 20 else "headline",
                "source_name": "CNBC",
                "fetched_at_utc": now_utc(),
                "subject_hint": None,
                "action_hint": None,
                "object": None,
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
}


# ---------------------------------------------------------------- 抽取


def detect_action(text: str) -> tuple[str | None, str | None]:
    """返回 (action, 原文锚点)。位置最早者胜；同位置按表序。"""
    best: tuple[int, int, str, str] | None = None
    for order, (action, pats) in enumerate(COMPILED):
        for pat in pats:
            m = pat.search(text)
            if not m:
                continue
            key = (m.start(), order, action, m.group(0))
            if best is None or key[:2] < best[:2]:
                best = key
    if best is None:
        return None, None
    return best[2], best[3][:60]


def detect_value(text: str) -> dict:
    best: tuple[int, int, str, str] | None = None
    for order, (kind, pat) in enumerate(VALUE_PATTERNS):
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
    m = dict(VALUE_PATTERNS)[kind].search(text)
    if m:
        num = m.group(1).replace(",", "")
        try:
            number = float(num)
        except ValueError:
            number = None
        if kind == "money":
            unit = m.group(2).lower()
        elif kind == "percent":
            unit = "percent"
        elif kind == "phase":
            unit = "phase"
        elif kind == "count":
            unit = m.group(2).lower()
    return {"kind": kind, "raw": raw.strip(), "number": number, "unit": unit}


def extract_subject(prefix: str) -> str | None:
    raw = prefix.replace("\n", " ").strip()
    chunks = [c.strip(" .\"'()") for c in re.split(r",\s+|\s+[-\u2014\u2013]\s+", raw) if c.strip(" .\"'()")]
    if not chunks:
        return None
    # 以时间/原因状语开头的标题（"After two deaths..., Artiva is shutting down"），主体在最后一段
    cand = chunks[-1] if LEADING_CLAUSE_RE.match(chunks[0]) else chunks[0]
    cand = SUBJECT_CUT_RE.split(cand, maxsplit=1)[0].strip(" .\"'()")
    cand = re.sub(r"\s+(?:is|are|was|were|has|have|had|will|would|to|be|been|being)$", "", cand, flags=re.I)
    cand = re.sub(r"^(the|a|an)\s+", "", cand, flags=re.I).strip(" .\"'()")
    if len(cand) < 2 or len(cand) > 80:
        return None
    # 首版把 "83% problem" 当主体，这里要求主体以字母开头且至少含 3 个字母
    if not re.match(r"[A-Za-z\u4e00-\u9fff]", cand):
        return None
    if len(re.findall(r"[A-Za-z\u4e00-\u9fff]", cand)) < 3:
        return None
    return cand


def build_event(item: dict, start: dt.date, end: dt.date, entity: str | None = None) -> tuple[dict | None, str | None]:
    when = parse_date(item.get("date", ""))
    if when is None:
        return None, "missing_time"
    day = when.date()
    if not (start <= day <= end):
        return None, "out_of_window"

    url = (item.get("link") or "").strip()
    if not url.startswith(("http://", "https://")):
        return None, "missing_url"

    excerpt = SPACE_RE.sub(" ", (item.get("excerpt") or "")).strip()
    if len(excerpt) < 20:
        return None, "missing_excerpt"

    title = item.get("title", "") or ""
    text = f"{title}. {excerpt}"
    if entity and entity.lower() not in text.lower():
        return None, "subject_not_in_text"
    if NOT_EVENT_RE.match(title.strip()) or title.strip().endswith("?"):
        return None, "not_an_event"

    action = item.get("action_hint")
    anchor = None
    if action is None:
        action, anchor = detect_action(text)
        if action is None:
            return None, "unparsed_action"
    else:
        anchor = title[:60] or action

    subject = item.get("subject_hint")
    if not subject:
        subject = extract_subject(title)
        if not subject:
            m = re.search(r"[\w ]+", text)
            subject = None
        if not subject:
            return None, "unparsed_subject"

    value = detect_value(text)
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
        "excerpt_kind": item.get("excerpt_kind", "summary"),
        "extract_method": EXTRACT_METHOD,
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
    reason = validate_event(event)
    return (None, reason) if reason else (event, None)


def validate_event(ev: dict) -> str | None:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ev.get("time", "")):
        return "missing_time"
    if not ev.get("subject") or len(ev["subject"]) > 80:
        return "unparsed_subject"
    if ev.get("action") not in ACTIONS:
        return "unparsed_action"
    if not str(ev.get("source_url", "")).startswith(("http://", "https://")):
        return "missing_url"
    if parse_date(ev.get("fetched_at_utc", "")) is None:
        return "missing_time"
    if len(SPACE_RE.sub(" ", ev.get("excerpt", "")).strip()) < 20:
        return "missing_excerpt"
    for src in ev.get("sources") or []:
        if not str(src.get("source_url", "")).startswith(("http://", "https://")):
            return "missing_url"
        if parse_date(src.get("fetched_at_utc", "")) is None:
            return "missing_time"
        if len(SPACE_RE.sub(" ", src.get("excerpt", "")).strip()) < 20:
            return "missing_excerpt"
    if not ev.get("sources"):
        return "missing_excerpt"
    return None


# ---------------------------------------------------------------- 去重


def norm_tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 1}


NEWS_SOURCES = {"google_news", "bing_news", "yahoo_finance", "cnbc"}


def same_event(a: dict, b: dict) -> bool:
    # 官方记录（Federal Register / ClinicalTrials / arXiv）每条是独立文书，
    # 标题相近不代表同一事件，所以只在新闻源之间做合并。
    if a.get("_source_id") not in NEWS_SOURCES or b.get("_source_id") not in NEWS_SOURCES:
        return False
    if a["action"] != b["action"]:
        return False
    d1 = dt.date.fromisoformat(a["time"])
    d2 = dt.date.fromisoformat(b["time"])
    if abs((d1 - d2).days) > 3:
        return False
    ta, tb = norm_tokens(a["_title"]), norm_tokens(b["_title"])
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    union = len(ta | tb)
    return union > 0 and inter / union >= 0.55


def merge_events(events: list[dict]) -> tuple[list[dict], int]:
    merged: list[dict] = []
    dup_count = 0
    for ev in sorted(events, key=lambda e: (e["time"], e["sources"][0]["fetched_at_utc"])):
        for cur in merged:
            if same_event(cur, ev):
                if len(cur["sources"]) < 8:
                    cur["sources"].append(ev["sources"][0])
                dup_count += 1
                break
        else:
            merged.append(ev)
    return merged, dup_count


# ---------------------------------------------------------------- 输出


def write_outputs(out_dir: Path, meta: dict, events: list[dict], rejects: list[dict], raw: list[dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "events.json").write_text(
        json.dumps({"meta": meta, "events": events, "rejects": rejects}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "raw_items.json").write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 事件时间线：{meta['query']}",
        "",
        f"- 时间窗：{meta['window_start']} → {meta['window_end']}",
        f"- 生成时刻（UTC）：{meta['generated_at_utc']}",
        f"- 抽取器：{meta['extract_method']}",
        f"- 入表 {len(events)} 条，拒绝 {len(rejects)} 条，合并重复 {meta['stats']['merged_duplicates']} 条",
        f"- 源统计：{json.dumps(meta['sources_stats'], ensure_ascii=False)}",
        "",
    ]
    if not events:
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
                items = FETCHERS[name](query, start, end, args.max_per_source)
                raw.extend(items)
                sources_stats.setdefault(name, {"fetched": 0, "accepted": 0, "rejected": 0})
                sources_stats[name]["fetched"] += len(items)
                print(f"[fetch] {name}: {len(items)} 条")
            except Exception as exc:  # noqa: BLE001 - 单源失败不影响其它源
                sources_stats.setdefault(name, {"fetched": 0, "accepted": 0, "rejected": 0, "error": ""})
                sources_stats[name]["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
                print(f"[fetch] {name}: FAIL {type(exc).__name__}: {str(exc)[:120]}")

    rejects: list[dict] = []
    events: list[dict] = []
    for item in raw:
        ev, reason = build_event(item, start, end, entity=args.entity)
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

    merged, dup_count = merge_events(events)
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
        "extract_method": EXTRACT_METHOD,
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

    write_outputs(out_dir, meta, merged, rejects, raw)

    print(
        f"\n[result] raw={len(raw)} events={len(merged)} rejects={len(rejects)} "
        f"merged={dup_count} reasons={reason_counts}"
    )
    print(f"[write] {out_dir / 'events.json'}")
    print(f"[write] {out_dir / 'events.md'}")
    print(f"[write] {out_dir / 'raw_items.json'}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="主题/主体 + 时间窗 → 事件时间线")
    ap.add_argument("--topic", help="主题词，如 clinical trial")
    ap.add_argument("--entity", help="主体词，如 XBI 或公司名")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD")
    ap.add_argument("--sources", default=None, help="逗号分隔的源名；默认按模式给")
    ap.add_argument("--max-per-source", type=int, default=60)
    ap.add_argument("--out-dir", default=str(Path(__file__).resolve().parent / "out"))
    ap.add_argument("--replay", default=None, help="离线复跑：读取 raw_items.json")
    args = ap.parse_args()
    if args.sources is None:
        args.sources = (
            "google_news,bing_news,clinicaltrials,federal_register"
            if args.topic
            else "yahoo_finance,google_news,cnbc"
        )
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
