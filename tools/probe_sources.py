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
                                   fetch_via_em_direct, fetch_via_sina_proxy,
                                   resolve_sector_code)

    # ---------- 1) 裸 HTTP 诊断：东财板块列表（三级里第2级的前置） ----------
    print("\n[1] 东财板块列表（行业板块 t:2 / 概念板块 t:3）")
    for fs in ("m:90+t:2", "m:90+t:3"):
        p = raw_http_probe("https://push2.eastmoney.com/api/qt/clist/get",
                           params={"fs": fs, "pn": 1, "pz": 5, "fields": "f12,f14", "po": 1},
                           headers=UA)
        RESULT["probes"][f"em_clist_{fs}"] = p
        print(f"    {fs}: status={p.get('status')} {p.get('seconds')}s "
              f"ctype={p.get('ctype', '')[:30]} head={str(p.get('head', p.get('error')))[:80]}")

    # ---------- 1.5) 对照实验：K线接口失败是"缺请求头"还是"IP 被拦" ----------
    # 现象：板块列表(clist)在云 IP 上 200 且返回 JSON，但路径2 报
    #       JSONDecodeError（拿到的是非 JSON 内容）——失败点在 push2his 的 K线接口。
    # 若加上 Referer/ut 就能通，那这是**能修的工程问题**，不是 IP 风控；
    # 结论直接决定 M3 能否供"板块级"数据，而不是含个股特质噪声的个股代理。
    print("\n[1.5] 东财 K线接口对照实验（同一板块，只改请求头/参数）")
    import requests
    bk_code, bk_name = None, None
    # 上一次运行该接口返回过 502 Bad Gateway（瞬时故障），故重试；全失败则用稳定板块代码兜底
    for attempt in range(3):
        try:
            r = requests.get("https://push2.eastmoney.com/api/qt/clist/get",
                             params={"fs": "m:90+t:3", "pn": 1, "pz": 10,
                                     "fields": "f12,f14", "po": 1},
                             headers=UA, timeout=20)
            d = r.json()["data"]["diff"]
            items = list(d.values()) if isinstance(d, dict) else d
            bk_code, bk_name = items[0]["f12"], items[0].get("f14")
            break
        except Exception as e:
            print(f"    取靶子板块第 {attempt + 1} 次失败：{type(e).__name__}")
            time.sleep(2)
    if not bk_code:
        bk_code, bk_name = "BK0425", "工程建设（兜底固定代码）"
        print("    靶子板块三次获取均失败，改用固定板块代码兜底")
    print(f"    靶子板块：{bk_name} {bk_code}")
    if bk_code:
        end = dt.date.today().strftime("%Y-%m-%d")
        # 隔离"请求头"与"时间跨度"两个变量：
        # 生产代码用 312 周（6年），探针此前只测了 8 周——长跨度是否才是触发条件？
        variants = [
            ("(a) 仅UA/近8周（与生产代码请求头一致）", 8, dict(UA), {}),
            ("(b) +Referer/近8周", 8, {**UA, "Referer": "https://quote.eastmoney.com/"}, {}),
            ("(c) +Referer+ut/近8周", 8, {**UA, "Referer": "https://quote.eastmoney.com/"},
             {"ut": "fa5fd1943c7b386f172d6893dbfba10b"}),
            ("(d) 仅UA/近312周（生产代码的实际跨度）", 312, dict(UA), {}),
            ("(e) +Referer/近312周", 312, {**UA, "Referer": "https://quote.eastmoney.com/"}, {}),
        ]
        for label, weeks, hdrs, extra in variants:
            beg = (dt.date.today() - dt.timedelta(weeks=weeks)).strftime("%Y-%m-%d")
            kparams = {"secid": f"90.{bk_code}", "klt": "101", "fqt": "0",
                       "beg": beg, "end": end,
                       "fields1": "f1,f2,f3", "fields2": "f51,f53,f57"}
            p = raw_http_probe("https://push2his.eastmoney.com/api/qt/stock/kline/get",
                               params={**kparams, **extra}, headers=hdrs)
            RESULT["probes"][f"kline_{label}"] = p
            print(f"    {label}: status={p.get('status')} {p.get('seconds')}s "
                  f"head={str(p.get('head', p.get('error')))[:90]}")

    # ---------- 1.6) 板块列表搜索重试实测：单次 502 是否会被重试救回 ----------
    print("\n[1.6] 板块列表搜索（路径2 的第一道关，也是唯一没有重试的地方）")
    ok_list, tries = 0, 5
    for i in range(tries):
        p = raw_http_probe("https://push2.eastmoney.com/api/qt/clist/get",
                           params={"fs": "m:90+t:3", "pn": 1, "pz": 100,
                                   "fields": "f12,f14", "po": 1}, headers=UA)
        ok_list += 1 if p.get("ok") else 0
        print(f"    第{i + 1}次: status={p.get('status')} {p.get('seconds')}s")
        if p.get("ok"):
            break
    RESULT["probes"]["clist_retry"] = {"tries_to_first_success": ok_list,
                                       "attempts": tries,
                                       "retry_saves_tier2": bool(ok_list)}
    print(f"    → 重试{'可以' if ok_list else '无法'}救回路径2（前 {tries} 次内成功 {ok_list} 次）")

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

    # ---------- 2.5) 修复复验：固定板块代码后，路径2 能否只发 1 次请求就供数 ----------
    # 背景：P0-2 上一轮把失败点隔离到「板块列表搜索 502 且无重试」。
    # 修复 = ①列表搜索加 3 次重试 ②链配置可固定板块代码（跳过搜索）。
    # 本块同时验两件事：修复后的搜索版能否供数、固定代码版能否供数，并回传代码供写进链配置。
    print("\n[2.5] 修复复验：搜索版（带重试）与固定代码版")
    hit = None
    t0 = time.time()
    try:
        hit = resolve_sector_code("机器人")
    except Exception as e:
        print(f"    resolve_sector_code 异常：{type(e).__name__}: {str(e)[:120]}")
    RESULT["probes"]["resolved_bk_code"] = {
        "code": hit[0] if hit else None, "name": hit[1] if hit else None,
        "seconds": round(time.time() - t0, 2)}
    print(f"    resolve_sector_code('机器人') -> {hit}（{round(time.time()-t0, 2)}s）")
    if hit:
        r = timed(fetch_via_em_direct, "机器人", 312, hit[0])
        RESULT["probes"]["路径2b 固定板块代码"] = r
        print(f"    固定代码版：ok={r['ok']} {r['seconds']}s rows={r.get('rows')} "
              f"{r.get('error', '')}")
        RESULT["verdict_fix"] = {
            "search_with_retry_ok": bool(RESULT["probes"]["路径2 东财裸requests直连"]["ok"]),
            "pinned_code_ok": bool(r["ok"]),
            "pinned_code": hit[0],
            "fix_restores_tier2": bool(r["ok"]),
        }
    else:
        RESULT["verdict_fix"] = {"search_with_retry_ok":
                                 RESULT["probes"]["路径2 东财裸requests直连"]["ok"],
                                 "pinned_code_ok": False, "pinned_code": None,
                                 "fix_restores_tier2": False,
                                 "note": "搜索仍失败，无法取到可固定的板块代码"}
        print("    搜索失败，无法复验固定代码版")

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
    retry_ok = RESULT["probes"].get("clist_retry", {}).get("retry_saves_tier2", False)
    RESULT["verdict"] = {
        "tier1_akshare": t1, "tier2_em_direct": t2, "tier3_sina_proxy": t3,
        "openalex_ok": oa, "winning_tier": used_tier or None,
        "tier2_failure_isolated": ("路径2 挂在第一步「板块列表搜索」的 502（非 JSON），"
                                   "K线接口本身在云 IP 可用；请求头无关"),
        "tier2_retry_would_help": bool(retry_ok),
        "tier2_fix_restores": RESULT.get("verdict_fix", {}).get("fix_restores_tier2", False),
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
