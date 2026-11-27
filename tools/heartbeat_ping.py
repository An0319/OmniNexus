# -*- coding: utf-8 -*-
"""tools/heartbeat_ping.py —— 发外部心跳，并把结果写进可持久化的状态文件。

为什么单独写一个脚本：原来的写法是 `curl ... || echo "::warning::心跳失败"`，
等于用坏掉的嗓子喊自己哑了——ping 发不出去时，那条 warning 也没人看得见。
现在心跳失败会落进 data/heartbeat_state.json，由下一次运行的哨兵读出来并开 issue。

铁律：本脚本**永远返回 0**。心跳是通知，不是产出；它失败不许让日更失败。
（唯一例外在 workflow 的推送步骤：推不上去本来就该失败。）
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "heartbeat_state.json"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(p: Path, obj: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


def ping(url: str, attempts: int = 3, delays: tuple[float, ...] = (2, 5, 10)) -> tuple[bool, str]:
    last = ""
    for i in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                body = r.read(64).decode("utf-8", "replace").strip()
                print(f"心跳第 {i + 1} 次：HTTP {r.status} {body}", flush=True)
                return True, ""
        except (urllib.error.URLError, OSError, ValueError) as e:
            last = f"{e.__class__.__name__}: {e}"
            print(f"心跳第 {i + 1} 次失败：{last}", flush=True)
            if i < attempts - 1:
                time.sleep(delays[min(i, len(delays) - 1)])
    return False, last


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="")
    ap.add_argument("--kind", default="success", choices=["success", "failure"])
    ap.add_argument("--state", default=str(STATE))
    ap.add_argument("--delay-scale", type=float, default=1.0)
    args = ap.parse_args(argv)

    state_path = Path(args.state)
    if not args.url:
        print(f"::warning::心跳 URL 未配置（{args.kind}），跳过", flush=True)
        _write(state_path, {"kind": args.kind, "url_present": False,
                            "last_attempt_utc": _now(), "last_ok": None,
                            "last_error": "URL 未配置"})
        return 0

    delays = tuple(d * args.delay_scale for d in (2, 5, 10))
    ok, err = ping(args.url, delays=delays)
    _write(state_path, {
        "kind": args.kind,
        "url_present": True,
        "last_attempt_utc": _now(),
        "last_ok": ok,
        "last_error": err or None,
    })
    if not ok:
        # 不抛错：留痕交给下一次运行的哨兵
        print(f"::warning::{args.kind} 心跳发送失败，已记入 {state_path.name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
