# -*- coding: utf-8 -*-
"""P0-2 数据源连通性探针：我们的三级降级链，在 GitHub Actions 的云 IP 上还能活吗？

为什么必须单独测
----------------
本地跑链10 时，滞后面被反爬一路降级到**第三级（新浪个股代理）**才拿到数据。
GitHub Actions 跑在云机房 IP 上——比家庭宽带更容易被风控。而 M3 的验收标准是
"30 天无人值守"。如果云上第 1/2 级全灭、第 3 级也偶发失败，30 天必然中断，
M3 就是空头承诺。

本探针只回答一个问题：**从云 IP 出发，三级降级各自走到哪一步、花多久、为什么失败。**

做法：直接调用生产代码（omninexus.sources），不做任何模仿实现——
测的必须是真货，否则结论无意义。

产出：probe_result.json（结论）+ 标准输出（人类可读日志）
"""
import datetime as dt
import json
import sys
import time
import traceback
from pathlib import Path

# 本脚本在 tools/ 下，Python 只会把 tools/ 放进 sys.path；
# 显式补上仓库根目录，保证 `from omninexus.sources import ...` 在本地与 CI 都能跑。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RESULT = {"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
          "probes": {}}


def timed(fn, *a, **kw):
    t0 = time.time()
    try:
        out = fn(*a, **kw)
        return {"ok": out is not None, "seconds": round(time.time() - t0, 2),
                "rows": (len(out) if out is not None else 0)}
    except Exception as e:
        return {"ok": False, "seconds": round(time.time() - t0, 2),
                "error": f"{type(e).__name__}: {str(e)[:200]}",
                "trace": traceback.format_exc()[-500:]}


def raw_http_probe(url, params=None, headers=None, name=""):
    """裸 HTTP 诊断：状态码/内容类型/响应开头——分辨"被封"还是"接口改了"。"""
    import requests
    t0 = time.time()
    try:
        r = requests.get(url, params=params, headers=headers or {}, timeout=20)
        head = r.text[:200].replace("\n", " ")
        return {"ok": r.status_code == 200, "status": r.status_code,
                "ctype": r.headers.get("Content-Type", ""),
                "seconds": round(time.time() - t0, 2), "head": head}
    except Exception as e:
        return {"ok": False, "seconds": round(time.time() - t0, 2),
                "error": f"{type(e).__name__}: {str(e)[:200]}"}


def main():
    print("=" * 72)
    print("P0-2 云 IP 数据源连通性探针")
    print("=" * 72)

    # ---------- 0) 环境识别：确认真的在云上、出口 IP 是什么 ----------
    env = raw_http_probe("https://api.ipify.org", name="egress-ip")
    RESULT["probes"]["egress_ip"] = env
    print(f"\n[0] 出口 IP：{env.get('head', env.get('error'))}")

    from omninexus.sources import (UA, fetch_sector_daily, fetch_via_akshare,
                                   fetch_via_em_direct, fetch_via_sina_proxy)

    # ---------- 1) 裸 HTTP 诊断：东财板块列表（三级里第2级的前置） ----------
    print("\n[1] 东财板块列表（行业板块 t:2 / 概念板块 t:3）")
    for fs in ("m:90+t:2", "m:90+t:3"):
        p = raw_http_probe("https://push2.eastmoney.com/api/qt/clist/get",
                           params={"fs": fs, "pn": 1, "pz": 5, "fields": "f12,f14", "po": 1},
                           headers=UA)
        RESULT["probes"][f"em_clist_{fs}"] = p
        print(f"    {fs}: status={p.get('status')} {p.get('seconds')}s "
              f"ctype={p.get('ctype', '')[:30]} head={str(p.get('head', p.get('error')))[:80]}")

    # ---------- 2) 三级降级逐级实测（调用生产代码） ----------
    print("\n[2] 三级降级逐级实测（生产代码 omninexus.sources）")
    tiers = [
        ("路径1 akshare 板块历史", fetch_via_akshare, ("机器人", 312)),
        ("路径2 东财裸requests直连", fetch_via_em_direct, ("机器人", 312)),
        ("路径3 新浪个股代理(绿的谐波)", fetch_via_sina_proxy, (("sh688017", "绿的谐波"), 312)),
    ]
    for label, fn, args in tiers:
        r = timed(fn, *args)
        RESULT["probes"][label] = r
        print(f"    {label}: ok={r['ok']} {r['seconds']}s rows={r.get('rows')} "
              f"{r.get('error', '')}")

    # ---------- 3) 复合函数：最终哪一级救了场 ----------
    print("\n[3] fetch_sector_daily（复合三级降级）——看最终由哪一级供数")
    r = timed(fetch_sector_daily, "机器人", ("sh688017", "绿的谐波"), 312)
    RESULT["probes"]["fetch_sector_daily"] = r
    print(f"    结果：ok={r['ok']} {r['seconds']}s rows={r.get('rows')} {r.get('error', '')}")

    # ---------- 4) OpenAlex（不带 key，只测 3 周，避免烧额度） ----------
    print("\n[4] OpenAlex 连通性（不带 API key，仅 3 周）")
    import os
    import requests
    has_key = bool(os.environ.get("OPENALEX_API_KEY"))
    RESULT["probes"]["openalex_has_key"] = has_key
    print(f"    环境变量 OPENALEX_API_KEY：{'已配置' if has_key else '未配置（走免费额度）'}")
    ok_cnt, errs = 0, []
    t0 = time.time()
    for w in range(3, 0, -1):
        end = dt.date.today() - dt.timedelta(weeks=w)
        start = end - dt.timedelta(weeks=1)
        params = {"filter": f"title_and_abstract.search:humanoid robot,"
                            f"from_publication_date:{start},to_publication_date:{end}",
                  "mailto": "omninexus.phase0@example.com"}
        if has_key:
            params["api_key"] = os.environ["OPENALEX_API_KEY"]
        try:
            rr = requests.get("https://api.openalex.org/works", params=params, timeout=30)
            if rr.status_code == 200:
                ok_cnt += 1
            else:
                errs.append(f"HTTP {rr.status_code}")
        except Exception as e:
            errs.append(f"{type(e).__name__}")
    RESULT["probes"]["openalex"] = {"ok": ok_cnt > 0, "success": f"{ok_cnt}/3",
                                    "seconds": round(time.time() - t0, 2),
                                    "errors": errs}
    print(f"    成功 {ok_cnt}/3，耗时 {round(time.time()-t0, 2)}s，错误 {errs}")

    # ---------- 判定 ----------
    t1 = RESULT["probes"]["路径1 akshare 板块历史"]["ok"]
    t2 = RESULT["probes"]["路径2 东财裸requests直连"]["ok"]
    t3 = RESULT["probes"]["路径3 新浪个股代理(绿的谐波)"]["ok"]
    oa = RESULT["probes"]["openalex"]["ok"]
    used_tier = 1 if t1 else (2 if t2 else (3 if t3 else 0))
    RESULT["verdict"] = {
        "tier1_akshare": t1, "tier2_em_direct": t2, "tier3_sina_proxy": t3,
        "openalex_ok": oa, "winning_tier": used_tier or None,
        "can_sustain_30d": bool(used_tier and oa),
        "note": ("三级降级可用，但降级到第3级时结论含个股特质噪声"
                 if used_tier == 3 else
                 "板块级数据可用" if used_tier in (1, 2) else
                 "三条路径全部失败：M3 的 30 天无人值守不可承诺"),
    }
    print("\n" + "=" * 72)
    print(f"判定：第1级={t1} 第2级={t2} 第3级={t3}；最终供数级别="
          f"{used_tier or '全灭'}；OpenAlex={oa}")
    print(f"结论：{RESULT['verdict']['note']}")
    print("=" * 72)

    with open("probe_result.json", "w", encoding="utf-8") as f:
        json.dump(RESULT, f, ensure_ascii=False, indent=2)
    print("结果已写入 probe_result.json")


if __name__ == "__main__":
    main()
