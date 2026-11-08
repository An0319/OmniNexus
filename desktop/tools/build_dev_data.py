#!/usr/bin/env python3
"""生成桌面壳的本地回放数据（dev-data.js，不入库）。

只读取真实产物与真实 CLI 输出，不造样例：
  - 时间线：读取 events.json（status 三档 + 两种 ok 子态 + 旧产物缺 status）
  - 账本：读取 demo.ledger.jsonl，并跑只读的 list / chain-check
  - 注册拒绝：对临时账本实跑三条拒绝 payload，采集真实 stderr 与退出码

默认输入（临时产物可先用命令重建，见文件末尾）：
  ok          %TEMP%/mnx_smoke/events.json      （离线复跑，status=ok，有事件）
  empty       %TEMP%/mnx_empty/events.json       （真无数据，status=ok，0 条）
  partial     %TEMP%/mnx_partial/events.json     （部分覆盖，status=partial，退出码 0）
  failed      phase0/api/demo/out_badsrc/events.json
  legacy      phase0/api/demo/out_timeline/events.json（旧产物，缺 status）
  entity_zero phase0/api/demo/out_badsrc_entity/events.json

用法：
  python desktop/tools/build_dev_data.py
  python desktop/tools/build_dev_data.py --ok <events.json> --empty <events.json> --partial <events.json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "phase0" / "api" / "demo"
CLI = ROOT / "phase0" / "registry" / "cli.py"
OUT = ROOT / "desktop" / "ui" / "dev-data.js"


def temp_dir(name: str) -> Path:
    base = Path(os.environ.get("TEMP") or tempfile.gettempdir())
    return base / name / "events.json"


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def label_for(key: str, data: dict | None) -> str:
    if data is None:
        return key + "（产物不存在）"
    status = data.get("status", "缺失")
    summary = (data.get("meta") or {}).get("stats") or {}
    events = summary.get("events", 0)
    if key == "ok":
        return f"有结果（status=ok，{events} 条）"
    if key == "empty":
        return "真无数据（status=ok，0 条）"
    if key == "partial":
        return f"部分覆盖（status=partial，退出码 0，{events} 条）"
    if key == "failed":
        return "全部失败（status=failed，退出码 3）"
    if key == "legacy":
        return f"旧产物·status 缺失（{events} 条原始事件）"
    if key == "entity_zero":
        return "实体零命中（status=ok，0 条）"
    return key + "（status=" + str(status) + "）"


def run_cli(args: list[str], timeout: int = 90) -> dict:
    try:
        proc = subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "timeout": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": None,
            "stdout": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
            "stderr": f"timeout after {timeout}s",
            "timeout": True,
        }


def registry_snapshot(ledger: Path) -> dict:
    listing = run_cli(["--ledger", str(ledger), "list"])
    chain = run_cli(["--ledger", str(ledger), "chain-check"])
    listed = None
    if listing["exit_code"] == 0:
        try:
            listed = json.loads(listing["stdout"])
        except json.JSONDecodeError:
            listed = None
    checked = None
    if chain["exit_code"] == 0:
        try:
            checked = json.loads(chain["stdout"])
        except json.JSONDecodeError:
            checked = None
    return {
        "ledger_path": rel(ledger),
        "ledger_sha256": sha256(ledger),
        "list": listed,
        "list_error": None if listed is not None else listing["stderr"].strip(),
        "chain_check": checked,
        "chain_error": None if checked is not None else chain["stderr"].strip(),
    }


def register_rejections() -> list[dict]:
    payloads = [
        DEMO / "payload_reject_vague.json",
        DEMO / "payload_reject_source.json",
        DEMO / "payload_reject_late.json",
    ]
    out = []
    workdir = Path(tempfile.mkdtemp(prefix="mnx_shell_reject_"))
    ledger = workdir / "registry.ledger.jsonl"
    for payload in payloads:
        if not payload.exists():
            out.append({
                "payload": rel(payload),
                "missing": True,
                "exit_code": None,
                "code": None,
                "message": "payload 文件不存在",
                "ledger_created": ledger.exists(),
            })
            continue
        result = run_cli([
            "--ledger", str(ledger),
            "register",
            "--payload-file", str(payload),
            "--at", "2026-11-08T00:00:00Z",
        ], timeout=90)
        match = re.search(r"rejected\s*\[([^\]]+)\]:\s*(.*)", result["stderr"], re.S)
        out.append({
            "payload": rel(payload),
            "exit_code": result["exit_code"],
            "code": match.group(1).strip() if match else None,
            "message": (match.group(2).strip() if match else result["stderr"].strip()) or None,
            "ledger_created": ledger.exists(),
            "timeout": result["timeout"],
        })
    return out


def payload_snapshots() -> dict:
    items = {}
    for key, name in [
        ("register", "payload_register.json"),
        ("undetermined", "payload_undetermined.json"),
    ]:
        path = DEMO / name
        items[key] = load_json(path)
        items[key + "_source"] = rel(path)
        items[key + "_missing"] = not path.exists()
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="生成桌面壳本地回放数据")
    parser.add_argument("--ok", default=str(temp_dir("mnx_smoke")))
    parser.add_argument("--empty", default=str(temp_dir("mnx_empty")))
    parser.add_argument("--partial", default=str(temp_dir("mnx_partial")))
    parser.add_argument("--failed", default=str(DEMO / "out_badsrc" / "events.json"))
    parser.add_argument("--legacy", default=str(DEMO / "out_timeline" / "events.json"))
    parser.add_argument("--entity-zero", default=str(DEMO / "out_badsrc_entity" / "events.json"))
    parser.add_argument("--ledger", default=str(DEMO / "demo.ledger.jsonl"))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    cases = [
        ("ok", Path(args.ok)),
        ("empty", Path(args.empty)),
        ("partial", Path(args.partial)),
        ("failed", Path(args.failed)),
        ("legacy", Path(args.legacy)),
        ("entity_zero", Path(args.entity_zero)),
    ]

    timeline = []
    for key, path in cases:
        data = load_json(path)
        timeline.append({
            "key": key,
            "label": label_for(key, data),
            "source_path": rel(path),
            "sha256": sha256(path),
            "missing": data is None,
            "data": data,
        })

    ledger = Path(args.ledger)
    registry = registry_snapshot(ledger)
    payloads = payload_snapshots()
    rejections = register_rejections()

    bundle = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "本地真实产物回放；仅供桌面壳演示，不入库，不作为对外证据。",
        "timeline": timeline,
        "registry": registry,
        "payloads": payloads,
        "register_rejections": rejections,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "window.__MNX_DEV_DATA__ = " + json.dumps(bundle, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )

    print(f"已写入 {rel(out_path)}")
    for item in timeline:
        state = "缺失" if item["missing"] else str((item["data"] or {}).get("status", "无 status"))
        print(f"  timeline {item['key']:11s} status={state:8s} {item['source_path']}")
    print(f"  registry list={'ok' if registry['list'] is not None else '失败'} "
          f"chain={'ok' if registry['chain_check'] is not None else '失败'}")
    for row in rejections:
        print(f"  reject {row['payload']}: exit={row['exit_code']} code={row['code']} "
              f"ledger_created={row['ledger_created']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# 重建临时产物的命令（人工执行，不写入仓库）：
#   python phase0/timeline/timeline.py --topic "clinical trial" --start 2026-10-20 \
#       --end 2026-11-08 --replay phase0/api/demo/out_timeline/raw_items.json \
#       --out-dir %TEMP%\mnx_smoke
#   python phase0/timeline/timeline.py --topic "zzqxvbn nonexistent topic 9000" \
#       --start 2026-10-20 --end 2026-11-08 --sources federal_register --out-dir %TEMP%\mnx_empty
#   $env:HTTPS_PROXY="http://127.0.0.1:9"; $env:NO_PROXY="www.federalregister.gov,federalregister.gov"
#   python phase0/timeline/timeline.py --topic "clinical trial" --start 2026-10-20 \
#       --end 2026-11-08 --sources federal_register,google_news --max-per-source 10 \
#       --out-dir %TEMP%\mnx_partial
