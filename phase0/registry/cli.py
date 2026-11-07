"""事件注册闭环的命令行入口。

用法（仓库根目录）：

  python phase0/registry/cli.py register --payload-file payload.json --at 2026-11-08T09:00:00Z
  python phase0/registry/cli.py verify   --at 2026-11-08T09:05:00Z
  python phase0/registry/cli.py reconcile
  python phase0/registry/cli.py list
  python phase0/registry/cli.py chain-check

``--at`` 是本次写入时刻，必须显式给出；本脚本不读系统时钟。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import criterion as C  # noqa: E402
import ledger as L  # noqa: E402
import ops as O  # noqa: E402
import reconcile as R  # noqa: E402
import sources as S  # noqa: E402
import timeutil as T  # noqa: E402


def _load_payload(args) -> dict:
    raw = args.payload if args.payload is not None else Path(args.payload_file).read_text(
        encoding="utf-8")
    return json.loads(raw)


def _fail(code: str, message: str) -> int:
    print(f"rejected [{code}]: {message}", file=sys.stderr)
    return 2


def cmd_register(args) -> int:
    try:
        payload = _load_payload(args)
    except (json.JSONDecodeError, OSError) as exc:
        return _fail("PAYLOAD_INVALID", str(exc))
    try:
        record = O.build_registration(payload, args.at, args.ledger)
    except O.RegistrationRejected as exc:
        return _fail(exc.code, exc.message)
    except (C.CriterionError, T.TimeFormatError, L.LedgerError) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        return _fail(code, getattr(exc, "message", str(exc)))
    print(json.dumps({"status": "registered", "record": record,
                      "ledger": str(args.ledger)}, ensure_ascii=False, indent=2))
    return 0


def cmd_verify(args) -> int:
    try:
        results = O.verify_all(args.at, args.ledger, only_id=args.id)
    except (O.RegistrationRejected, T.TimeFormatError, L.LedgerError,
            C.CriterionError, S.SourceUnavailable) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        return _fail(code, getattr(exc, "message", str(exc)))
    counts: dict[str, int] = {}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(json.dumps({"at": args.at, "counts": counts, "results": results},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_reconcile(args) -> int:
    try:
        summary = O.reconcile(args.ledger, point_min=args.point_min)
    except L.LedgerError as exc:
        return _fail(exc.code, exc.message)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(R.to_markdown(summary))
    return 0


def cmd_list(args) -> int:
    entries = L.read_entries(args.ledger)
    verdicts = R.latest_verdicts(entries)
    rows = []
    for entry in entries:
        if entry.get("kind") != "registration":
            continue
        latest = verdicts.get(entry["id"])
        rows.append({
            "id": entry["id"],
            "expires_on": entry["expires_on"],
            "registered_at": entry["registered_at"],
            "provenance": entry["provenance"]["kind"],
            "claim_canonical": entry["claim_canonical"],
            "verdict": latest["verdict"] if latest else None,
            "reason_code": latest["reason_code"] if latest else None,
        })
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


def cmd_chain(args) -> int:
    report = L.verify_chain(args.ledger)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="事件注册闭环：注册 / 到期核验 / 对账")
    ap.add_argument("--ledger", default=str(L.DEFAULT_LEDGER),
                    help="账本路径（默认 phase0/registry/registry.ledger.jsonl）")
    sub = ap.add_subparsers(dest="command", required=True)

    reg = sub.add_parser("register", help="注册一条预测（判据不合规即拒）")
    src = reg.add_mutually_exclusive_group(required=True)
    src.add_argument("--payload", help="注册请求的 JSON 字符串")
    src.add_argument("--payload-file", help="注册请求 JSON 文件")
    reg.add_argument("--at", required=True, help="写入时刻，ISO-8601 UTC；必填")
    reg.set_defaults(func=cmd_register)

    ver = sub.add_parser("verify", help="到期核验（命中 / 未命中 / 无法判定）")
    ver.add_argument("--at", required=True, help="核验时刻，ISO-8601 UTC；必填")
    ver.add_argument("--id", help="只核验指定 id")
    ver.set_defaults(func=cmd_verify)

    rec = sub.add_parser("reconcile", help="对账：累计命中率只报区间")
    rec.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    rec.add_argument("--point-min", type=int, default=R.POINT_ESTIMATE_MIN,
                     help=f"允许报点估计的最小已判定样本数（默认 {R.POINT_ESTIMATE_MIN}）")
    rec.set_defaults(func=cmd_reconcile)

    lst = sub.add_parser("list", help="列出注册事件及最新判定")
    lst.set_defaults(func=cmd_list)

    chk = sub.add_parser("chain-check", help="只读校验账本哈希链")
    chk.set_defaults(func=cmd_chain)
    return ap


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
