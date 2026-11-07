"""闭环自检：注册 → 到期 → 核验 → 对账，全链路实跑，并逐条断言。

用法（仓库根目录，``--at`` 必填，脚本不读系统时钟）：

  python phase0/registry/selftest.py --at 2026-11-08T12:00:00Z --reset

产物：
  phase0/registry/backfill.ledger.jsonl   回填测试账本（独立文件，不碰批次一账本）
  phase0/registry/selftest_result.json    本次自检的结构化证据

自检覆盖：
  1. 三态齐活：hit / miss / undetermined 各至少一条。
  2. 第三种状态不被折算：undetermined 独立计数、不进命中率分母。
  3. 判据真机器可判：删掉 claim 文本后重判，结论与数值不变。
  4. 命中即冻结：已判 hit/miss 的事件拒绝重跑。
  5. 判据被改会被发现：改 threshold 后核验报 CRITERION_TAMPERED。
  6. 未到期不落判定。
  7. 注册即拒：含糊句、缺判据、未知字段、取不到数、窗口越界等逐条拒绝且账本不动。
  8. 追加只在前缀后长：核验前后账本前缀逐字节一致。
  9. 无系统时钟调用：静态扫描本目录 *.py。
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pandas as pd  # noqa: E402

import criterion as C  # noqa: E402
import evaluate as E  # noqa: E402
import ledger as L  # noqa: E402
import ops as O  # noqa: E402
import reconcile as R  # noqa: E402
import sources as S  # noqa: E402
import timeutil as T  # noqa: E402

BACKFILL_LEDGER = HERE / "backfill.ledger.jsonl"
EVENTS = HERE / "backfill_events.json"
RESULT = HERE / "selftest_result.json"
CLI = HERE / "cli.py"

# 拼出来的禁词表：避免本文件自身被静态扫描误伤（扫描的是同一批字符串）。
FORBIDDEN_CLOCK = (
    "datetime" + ".now",
    "datetime" + "." + "utc" + "now",
    "utc" + "now",
    "date" + ".today",
    "time" + ".time(",
)


def _ok(name: str, passed: bool, detail: str) -> dict:
    return {"name": name, "ok": bool(passed), "detail": detail}


def _payloads() -> list[dict]:
    return json.loads(EVENTS.read_text(encoding="utf-8"))


def _write_payload(payload: dict, directory: Path, name: str) -> Path:
    path = directory / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _expect_reject(name: str, payload: dict, code: str, ledger_path: Path, at: str) -> dict:
    before = ledger_path.read_bytes() if ledger_path.exists() else b""
    try:
        O.build_registration(payload, at, ledger_path)
        got = None
        detail = "未被拒绝"
    except (O.RegistrationRejected, C.CriterionError) as exc:
        got = getattr(exc, "code", type(exc).__name__)
        detail = getattr(exc, "message", str(exc))
    after = ledger_path.read_bytes() if ledger_path.exists() else b""
    passed = got == code and before == after
    if got != code:
        detail = f"期望 {code}，实际 {got}：{detail}"
    elif before != after:
        detail = "拒绝路径仍写入了账本"
    return _ok(f"reject:{name}", passed, detail)


def _run_cli(args: list[str], env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", **(env_extra or {})}
    return subprocess.run([sys.executable, str(CLI), *args], cwd=str(ROOT),
                          capture_output=True, text=True, encoding="utf-8", env=env)


def main() -> int:
    ap = argparse.ArgumentParser(description="事件注册闭环自检")
    ap.add_argument("--at", required=True, help="本次自检的统一时刻，ISO-8601 UTC；必填")
    ap.add_argument("--reset", action="store_true",
                    help="重建回填账本（会删除既有 backfill.ledger.jsonl）")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    at = args.at
    T.parse_iso_utc(at)
    if BACKFILL_LEDGER.exists():
        if not args.reset:
            print(f"{BACKFILL_LEDGER} 已存在；确认要重建请加 --reset", file=sys.stderr)
            return 2
        BACKFILL_LEDGER.unlink()

    assertions: list[dict] = []
    rejections: list[dict] = []
    payloads = _payloads()
    tmpdir = Path(tempfile.mkdtemp(prefix="omni_registry_selftest_"))

    # ---- 0) 补录声明：时间线矛盾必须明写，不能用一句「回填」抹平
    L.append(BACKFILL_LEDGER, {
        "kind": "backfill_notice",
        "note": "本账本为闭环自检产物，全部记录为事后补录，不构成实时注册证据",
        "covers": [p["id"] for p in payloads],
        "claimed_registration_range": "2025-12-29T09:00:00Z..2026-09-30T09:00:00Z",
        "appended_at": at,
        "original_event_time": "各 registered_at 为构造值，原始实时注册时刻不可考；"
                               "本条与全部注册记录的真实写入时刻均为本条的 appended_at",
    }, at=at)

    # ---- 1) 注册
    registered: list[dict] = []
    for payload in payloads:
        registered.append(O.build_registration(payload, at, BACKFILL_LEDGER))
    assertions.append(_ok(
        "register:all",
        len(registered) == len(payloads),
        f"注册 {len(registered)}/{len(payloads)} 条"))
    assertions.append(_ok(
        "register:probe_complete",
        all(r["source_probe"]["sha256"] and len(r["source_probe"]["sha256"]) == 64
            and r["source_probe"]["rows"] > 0 for r in registered),
        "每条注册都带完整数据源指纹（SHA256 / 行数 / 首末日期）"))

    # ---- 2) 核验前快照（用于证明只在前缀后追加）
    prefix_before = BACKFILL_LEDGER.read_bytes()
    lines_before = len(L.read_entries(BACKFILL_LEDGER))
    S.reset_cache()  # 强制核验阶段重新抓取，证明不依赖注册时的内存副本
    verification = O.verify_all(at, BACKFILL_LEDGER)
    prefix_after = BACKFILL_LEDGER.read_bytes()
    assertions.append(_ok(
        "ledger:append_only",
        prefix_after.startswith(prefix_before) and len(prefix_after) > len(prefix_before),
        f"追加前 {len(prefix_before)} 字节，追加后 {len(prefix_after)} 字节，前缀逐字节一致"))

    entries = L.read_entries(BACKFILL_LEDGER)
    verdicts = R.latest_verdicts(entries)
    statuses = {v["id"]: v for v in verification}
    assertions.append(_ok(
        "verify:one_verdict_per_event",
        len(entries) - lines_before == len(payloads) and len(verdicts) == len(payloads),
        f"新增 {len(entries) - lines_before} 条判定，覆盖 {len(verdicts)} 个事件"))

    # ---- 3) 三态齐活
    kinds = {"hit": [], "miss": [], "undetermined": []}
    for reg_id, verdict in verdicts.items():
        kinds[verdict["verdict"]].append(reg_id)
    for kind in ("hit", "miss", "undetermined"):
        assertions.append(_ok(
            f"verdict:{kind}_present",
            len(kinds[kind]) >= 1,
            f"{kind} {len(kinds[kind])} 条：{', '.join(sorted(kinds[kind]))}"))

    # ---- 4) 对账：undetermined 不进分母
    summary = O.reconcile(BACKFILL_LEDGER)
    assertions.append(_ok(
        "reconcile:undetermined_not_in_denominator",
        summary["hit_rate"]["n"] == summary["hit"] + summary["miss"]
        and summary["decided"] == summary["hit"] + summary["miss"]
        and summary["undetermined"] == len(kinds["undetermined"]),
        f"命中率分母 {summary['hit_rate']['n']} = hit {summary['hit']} + miss {summary['miss']}；"
        f"undetermined {summary['undetermined']} 单列"))
    assertions.append(_ok(
        "reconcile:small_sample_interval_only",
        summary["hit_rate"]["n"] < R.POINT_ESTIMATE_MIN
        and summary["hit_rate"]["point"] is None
        and summary["hit_rate"]["ci95"] is not None,
        f"n={summary['hit_rate']['n']}<{R.POINT_ESTIMATE_MIN}，只报区间 "
        f"{summary['hit_rate']['ci95']}，不给点估计"))

    # ---- 5) 判据真机器可判：删掉 claim 后结论不变
    changed = []
    for reg in registered:
        stored = verdicts[reg["id"]]
        stripped = {k: v for k, v in reg.items() if k not in ("claim", "claim_canonical")}
        redo = E.evaluate(stripped, at)
        same = (redo["verdict"] == stored["verdict"]
                and redo["reason_code"] == stored["reason_code"]
                and (redo["observed"] or {}).get("value")
                == (stored["observed"] or {}).get("value"))
        if not same:
            changed.append(reg["id"])
    assertions.append(_ok(
        "criterion:claim_independent",
        not changed,
        "删除 claim 文本后重判，全部结论与观测值不变" if not changed
        else f"以下事件改判：{changed}"))

    # ---- 6) 取数失败必须落 undetermined，不得折算成 miss
    inject_reg = next(r for r in registered if r["id"] in kinds["hit"])
    original_probe = S.probe

    def _boom(*_args, **_kwargs):
        raise S.SourceUnavailable("SOURCE_UNREACHABLE", "自检注入的取数失败")

    S.probe = _boom
    try:
        injected = E.evaluate(inject_reg, at)
    finally:
        S.probe = original_probe
    assertions.append(_ok(
        "verdict:source_failure_is_undetermined",
        injected["verdict"] == "undetermined" and injected["reason_code"] == "SOURCE_UNREACHABLE",
        f"{injected['verdict']}/{injected['reason_code']}（注入取数失败，不记 miss）"))

    # ---- 6b) 聚合无定义（pct_change 首值为 0）必须落 undetermined，不得崩也不得记 miss
    zero_series = pd.Series(
        [0.0, 1.0, 2.0, 3.0, 4.0],
        index=pd.to_datetime(["2026-09-01", "2026-09-02", "2026-09-03",
                              "2026-09-04", "2026-09-05"]))
    zero_record = {
        "id": "SELFCHECK-ZERO-01",
        "expires_on": "2026-09-05",
        "criterion": {
            "syntax_version": "criterion/v1",
            "source": {"provider": "fred", "id": "DGS10", "field": "value"},
            "window": {"start": "2026-09-01", "end": "2026-09-05"},
            "aggregate": "pct_change",
            "comparator": "gte",
            "threshold": 1.0,
            "unit": "percent",
            "min_observations": 2,
            "coverage_slack_days": 0,
            "settlement_lag_days": 0,
        },
    }
    original_probe_zero = S.probe
    S.probe = lambda *_a, **_k: (zero_series, {"provider": "fred", "id": "DGS10",
                                               "field": "value", "fetched_at_utc": at,
                                               "note": "自检注入的合成序列"})
    try:
        zero_result = E.evaluate(zero_record, at)
    finally:
        S.probe = original_probe_zero
    assertions.append(_ok(
        "verdict:aggregate_undefined",
        zero_result["verdict"] == "undetermined"
        and zero_result["reason_code"] == "AGGREGATE_UNDEFINED",
        f"{zero_result['verdict']}/{zero_result['reason_code']}（首值为 0，不记 miss）"))

    # ---- 7) 命中即冻结
    frozen_ok = True
    frozen_detail = ""
    for reg_id in kinds["hit"] + kinds["miss"]:
        reg = next(r for r in registered if r["id"] == reg_id)
        count_before = len(L.read_entries(BACKFILL_LEDGER))
        try:
            O.verify_one(reg, at, BACKFILL_LEDGER)
            frozen_ok = False
            frozen_detail = f"{reg_id} 被允许重跑"
            break
        except O.FrozenVerdict:
            if len(L.read_entries(BACKFILL_LEDGER)) != count_before:
                frozen_ok = False
                frozen_detail = f"{reg_id} 拒绝重跑时仍写了账本"
                break
    assertions.append(_ok("verify:frozen_after_decided", frozen_ok,
                          frozen_detail or "hit/miss 事件全部拒绝重跑，账本未增长"))

    # ---- 8) 判据被改会被发现
    tampered = copy.deepcopy(next(r for r in registered if r["id"] in kinds["hit"]))
    tampered["criterion"]["threshold"] = float(tampered["criterion"]["threshold"]) + 1
    try:
        O.verify_one(tampered, at, BACKFILL_LEDGER)
        tamper_ok, tamper_detail = False, "判据被改后仍通过核验"
    except L.LedgerError as exc:
        tamper_ok = exc.code == "CRITERION_TAMPERED"
        tamper_detail = f"{exc.code}: {exc.message}"
    assertions.append(_ok("verify:criterion_hash_guard", tamper_ok, tamper_detail))

    # ---- 9) 未到期不落判定
    notdue_ledger = tmpdir / "notdue.ledger.jsonl"
    notdue_payload = {
        "id": "SELFCHECK-NOTDUE-01",
        "claim": "美国常规零售汽油 2026 年 9 月周均价不低于 4.3 美元/加仑",
        "registered_at": "2026-11-01T00:00:00Z",
        "expires_on": "2026-12-31",
        "provenance": {"kind": "live", "note": "自检用：到期在未来的正常注册"},
        "criterion": {
            "syntax_version": "criterion/v1",
            "source": {"provider": "fred", "id": "GASREGW", "field": "value"},
            "window": {"start": "2026-09-01", "end": "2026-09-30"},
            "aggregate": "mean",
            "comparator": "gte",
            "threshold": 4.3,
            "unit": "USD/gallon",
            "min_observations": 4,
            "coverage_slack_days": 10,
            "settlement_lag_days": 3,
        },
    }
    O.build_registration(notdue_payload, at, notdue_ledger)
    notdue_before = notdue_ledger.read_bytes()
    notdue_results = O.verify_all(at, notdue_ledger)
    notdue_after = notdue_ledger.read_bytes()
    assertions.append(_ok(
        "verify:not_due_skipped",
        notdue_results and notdue_results[0]["status"] == "not_due"
        and notdue_before == notdue_after,
        f"状态 {notdue_results[0]['status'] if notdue_results else None}，账本未增长"))

    # ---- 10) 注册即拒（全部要求账本字节不变）
    base = copy.deepcopy(payloads[0])
    vague = copy.deepcopy(base)
    vague["id"] = "REJ-VAGUE"
    vague["claim"] = "该标的后续大概率上涨，走势值得期待"
    missing = copy.deepcopy(base)
    missing["id"] = "REJ-MISSING"
    del missing["criterion"]
    null_crit = copy.deepcopy(base)
    null_crit["id"] = "REJ-NULL"
    null_crit["criterion"] = None
    bad_cmp = copy.deepcopy(base)
    bad_cmp["id"] = "REJ-CMP"
    bad_cmp["criterion"]["comparator"] = "approximately"
    bad_provider = copy.deepcopy(base)
    bad_provider["id"] = "REJ-PROVIDER"
    bad_provider["criterion"]["source"] = {"provider": "bloomberg", "id": "SPY",
                                           "field": "adjclose"}
    bad_series = copy.deepcopy(base)
    bad_series["id"] = "REJ-SERIES"
    bad_series["criterion"]["source"] = {"provider": "fred", "id": "NOT_A_SERIES_XYZ",
                                         "field": "value"}
    nan_thr = copy.deepcopy(base)
    nan_thr["id"] = "REJ-NAN"
    nan_thr["criterion"]["threshold"] = float("nan")
    window_late = copy.deepcopy(base)
    window_late["id"] = "REJ-WINDOW"
    window_late["criterion"]["window"] = {"start": "2026-04-01", "end": "2026-04-30"}
    live_late = copy.deepcopy(base)
    live_late["id"] = "REJ-LIVE-LATE"
    live_late["registered_at"] = "2025-12-29T09:00:00Z"
    live_late["expires_on"] = "2026-01-31"
    live_late["criterion"]["window"] = {"start": "2026-01-01", "end": "2026-01-31"}
    live_late["provenance"] = {"kind": "live", "note": "到期后才写入的 live 注册"}
    unknown_field = copy.deepcopy(base)
    unknown_field["id"] = "REJ-UNKNOWN"
    unknown_field["confidence"] = "high"
    bad_expiry = copy.deepcopy(base)
    bad_expiry["id"] = "REJ-EXPIRY"
    bad_expiry["expires_on"] = "2026-02-30"

    for name, payload, code in (
        ("vague_claim", vague, "VAGUE_CLAIM"),
        ("missing_criterion", missing, "MISSING_FIELD"),
        ("null_criterion", null_crit, "CRITERION_MISSING"),
        ("unknown_comparator", bad_cmp, "COMPARATOR_UNKNOWN"),
        ("unknown_provider", bad_provider, "SOURCE_PROVIDER"),
        ("bogus_series", bad_series, "SOURCE_HTTP"),
        ("nan_threshold", nan_thr, "THRESHOLD_INVALID"),
        ("window_after_expiry", window_late, "WINDOW_AFTER_EXPIRY"),
        ("live_after_expiry", live_late, "REGISTRATION_AFTER_EXPIRY"),
        ("unknown_field", unknown_field, "UNKNOWN_FIELD"),
        ("bad_expiry_date", bad_expiry, "DATE_FORMAT"),
        ("duplicate_id", copy.deepcopy(base), "DUPLICATE_ID"),
    ):
        rejections.append(_expect_reject(name, payload, code, BACKFILL_LEDGER, at))
    assertions.extend(rejections)

    # ---- 11) CLI 层：--at 缺失必须失败；含糊句经 CLI 也被拒
    cli_ledger = tmpdir / "cli.ledger.jsonl"
    payload_file = _write_payload(vague, tmpdir, "vague.json")
    no_at = _run_cli(["--ledger", str(cli_ledger), "register",
                      "--payload-file", str(payload_file)])
    assertions.append(_ok(
        "cli:at_required",
        no_at.returncode == 2 and "--at" in (no_at.stderr + no_at.stdout),
        f"exit={no_at.returncode}"))
    with_at = _run_cli(["--ledger", str(cli_ledger), "register",
                        "--payload-file", str(payload_file), "--at", at])
    assertions.append(_ok(
        "cli:vague_rejected",
        with_at.returncode == 2 and "VAGUE_CLAIM" in with_at.stderr
        and not cli_ledger.exists(),
        f"exit={with_at.returncode}，账本未创建"))
    reconcile_cli = _run_cli(["--ledger", str(BACKFILL_LEDGER), "reconcile"])
    assertions.append(_ok(
        "cli:reconcile_runs",
        reconcile_cli.returncode == 0 and "命中率" in reconcile_cli.stdout,
        f"exit={reconcile_cli.returncode}"))

    # ---- 12) 账本哈希链与无系统时钟
    chain = L.verify_chain(BACKFILL_LEDGER)
    assertions.append(_ok(
        "ledger:hash_chain", chain["ok"] and chain["count"] > 0,
        f"{chain['count']} 条记录，head={chain['head_sha256'][:12] if chain['head_sha256'] else None}，"
        f"问题 {len(chain['problems'])} 个"))
    clock_hits = []
    for py in sorted(HERE.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        hits = [tok for tok in FORBIDDEN_CLOCK if tok in text]
        if hits:
            clock_hits.append({"file": py.name, "tokens": hits})
    assertions.append(_ok(
        "code:no_wall_clock", not clock_hits,
        "本目录脚本没有读取系统时钟" if not clock_hits else json.dumps(clock_hits, ensure_ascii=False)))

    # ---- 13) 落盘证据
    per_event = []
    for reg in registered:
        verdict = verdicts[reg["id"]]
        per_event.append({
            "id": reg["id"],
            "claim_canonical": reg["claim_canonical"],
            "verdict": verdict["verdict"],
            "reason_code": verdict["reason_code"],
            "value": (verdict["observed"] or {}).get("value"),
            "n": (verdict["observed"] or {}).get("n"),
        })
    passed = all(a["ok"] for a in assertions)
    result = {
        "at": at,
        "passed": passed,
        "ledger": str(BACKFILL_LEDGER.relative_to(ROOT)),
        "ledger_bytes": len(prefix_after),
        "ledger_chain": chain,
        "events": per_event,
        "reconcile": {k: summary[k] for k in
                      ("registered", "verified", "no_verdict", "hit", "miss",
                       "undetermined", "decided", "hit_rate", "by_source", "note")},
        "assertions": assertions,
    }
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{'id':<12}{'verdict':<14}{'reason':<28}{'value':>12}{'n':>5}")
    for row in per_event:
        value = "—" if row["value"] is None else f"{row['value']:.4f}"
        print(f"{row['id']:<12}{row['verdict']:<14}{str(row['reason_code'] or '—'):<28}"
              f"{value:>12}{str(row['n']):>5}")
    print()
    print(R.rate_line(summary))
    print(f"hit={summary['hit']} miss={summary['miss']} undetermined={summary['undetermined']} "
          f"no_verdict={summary['no_verdict']}")
    print()
    for item in assertions:
        print(f"[{'PASS' if item['ok'] else 'FAIL'}] {item['name']}: {item['detail']}")
    print()
    print(f"结果写入 {RESULT}")
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
