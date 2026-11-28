"""中文源探活：只探、不改。

对 zh_source_access.md 里列为「已验证可用」的源逐个打一次，输出三列状态：
通 / 空 / 不通，外加耗时与报错原文（不明写「不明」）。

用法：
    python phase0/timeline/probe_zh_sources.py

边界（zh_source_access.md §0.5）：只打公开入口；不登录、不签名、不绕过付费墙。
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
TIMEOUT = 25
HERE = Path(__file__).resolve().parent


def _google_params() -> dict:
    data = json.loads((HERE / "rulesets" / "zh.json").read_text(encoding="utf-8"))
    return data["source_params"]["google_news"]


def _count_items(xml_text: str) -> int:
    return xml_text.lower().count("<item")


def probe_google_news() -> int:
    p = _google_params()
    url = (
        "https://news.google.com/rss/search?q="
        f"{quote_plus('A股')}&hl={p['hl']}&gl={p['gl']}&ceid={p['ceid']}"
    )
    r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    return _count_items(r.text)


def probe_cninfo() -> int:
    headers = {
        "User-Agent": UA,
        "Referer": "http://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice",
        "Origin": "http://www.cninfo.com.cn",
        "X-Requested-With": "XMLHttpRequest",
    }
    today = dt.date.today()
    data = {
        "pageNum": 1,
        "pageSize": 30,
        "column": "szse",
        "tabName": "fulltext",
        "searchkey": "",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
        "seDate": f"{(today - dt.timedelta(days=2)).isoformat()}~{today.isoformat()}",
    }
    r = requests.post(
        "http://www.cninfo.com.cn/new/hisAnnouncement/query", data=data, headers=headers, timeout=TIMEOUT
    )
    r.raise_for_status()
    return len(r.json().get("announcements") or [])


def probe_eastmoney() -> int:
    r = requests.get(
        "https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_50_1_.html",
        headers={"User-Agent": UA},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return len(json.loads(r.text.split("=", 1)[1]).get("LivesList") or [])


def probe_sina() -> int:
    r = requests.get(
        "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&num=20",
        headers={"User-Agent": UA},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return len(((r.json().get("result") or {}).get("pdps")) or [])


def probe_wallstreetcn() -> int:
    r = requests.get(
        "https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=20",
        headers={"User-Agent": UA},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return len(((r.json().get("data") or {}).get("items")) or [])


def probe_kr36() -> int:
    body = {
        "partner_id": "web",
        "param": {"siteId": 1, "platformId": 2, "pageSize": 20, "pageEvent": 0, "pageCallback": "", "type": 1},
    }
    r = requests.post(
        "https://gateway.36kr.com/api/mis/nav/newsflash/flow", json=body, headers={"User-Agent": UA}, timeout=TIMEOUT
    )
    r.raise_for_status()
    return len(((r.json().get("data") or {}).get("itemList")) or [])


def probe_eastmoney_report() -> int:
    today = dt.date.today()
    r = requests.get(
        "https://reportapi.eastmoney.com/report/list",
        params={
            "cb": "datatable",
            "pageSize": 20,
            "pageNo": 1,
            "beginTime": (today - dt.timedelta(days=7)).isoformat(),
            "endTime": today.isoformat(),
            "qType": 0,
            "code": "*",
        },
        headers={"User-Agent": UA},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    body = r.text
    payload = json.loads(body[body.index("(") + 1 : body.rindex(")")])
    return len(payload.get("data") or [])


PROBES = [
    ("巨潮资讯（公告）", "POST hisAnnouncement/query", probe_cninfo),
    ("东方财富快讯", "JSONP getlist_102", probe_eastmoney),
    ("新浪财经滚动", "JSON feed.mix.sina.com.cn", probe_sina),
    ("华尔街见闻·快讯", "JSON api-one.wallstcn.com", probe_wallstreetcn),
    ("36氪·快讯", "POST gateway.36kr.com", probe_kr36),
    ("东方财富研报", "JSONP reportapi", probe_eastmoney_report),
    ("Google News RSS", "RSS search q=A股", probe_google_news),
]


def main() -> int:
    print(f"复验日期：{dt.date.today().isoformat()}（本机日期；与 UTC 日期可能差一天）")
    ok = empty = fail = 0
    for name, how, fn in PROBES:
        t0 = time.perf_counter()
        try:
            n = fn()
            elapsed = round(time.perf_counter() - t0, 2)
            if n == 0:
                empty += 1
                print(f"[空]   {name}｜0 条｜{elapsed}s｜{how}")
            else:
                ok += 1
                print(f"[通]   {name}｜{n} 条｜{elapsed}s｜{how}")
        except Exception as exc:  # noqa: BLE001 - 探活脚本，单源失败继续
            elapsed = round(time.perf_counter() - t0, 2)
            fail += 1
            msg = str(exc).strip() or "不明"
            print(f"[不通] {name}｜—｜{elapsed}s｜{type(exc).__name__}: {msg[:300]}")
    print(f"\n汇总：通 {ok} ／ 空 {empty} ／ 不通 {fail}（共 {len(PROBES)} 个）")
    print("注意：本脚本只探公开入口，不覆盖频控、封 IP、单日额度。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
