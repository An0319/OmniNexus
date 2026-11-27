# -*- coding: utf-8 -*-
"""tools/git_push_retry.py —— 推送自救：重试，失败就真失败。

为什么改：原来那行是 `git push || echo "::warning::push 未完成"`。
数据是当天的，今天没推上去明天补不回来（永久丢失），却只留一条 warning。
常见失败原因是 bot 抢先推（非快进）或网络抖动——这两种重试/变基就能好，不该叫人；
但重试全部失败时必须真失败：退出码非零 → job 失败 → 成功心跳（if: success()）不会发。

判定标准：这一步会让「产出变少」（数据没入库），所以不许吞。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time


def _run(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    return r.returncode, out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--delay-scale", type=float, default=1.0,
                    help="本地复现时设 0，跳过等待")
    ap.add_argument("--no-rebase", action="store_true", help="只重试，不尝试变基")
    args = ap.parse_args(argv)

    delays = (5, 15, 45)
    for i in range(1, args.attempts + 1):
        code, out = _run(["git", "push", args.remote, args.branch])
        if code == 0:
            print(f"[push] 第 {i} 次成功", flush=True)
            print(out, flush=True)
            return 0
        print(f"[push] 第 {i} 次失败（exit {code}）：", flush=True)
        print(out, flush=True)
        if i == args.attempts:
            break
        # bot 抢先推是最常见的可恢复原因：先同步远端再重试
        if not args.no_rebase:
            fc, fout = _run(["git", "fetch", args.remote])
            if fc != 0:
                print(f"[push] fetch 失败：{fout}", flush=True)
            else:
                rc, rout = _run(["git", "rebase", f"{args.remote}/{args.branch}"])
                if rc != 0:
                    print(f"[push] 变基失败，已回滚：{rout}", flush=True)
                    _run(["git", "rebase", "--abort"])
        wait = delays[min(i - 1, len(delays) - 1)] * args.delay_scale
        print(f"[push] {wait:.0f}s 后重试", flush=True)
        time.sleep(wait)

    print(f"[push] {args.attempts} 次全部失败——数据没推上去，按失败处理"
          "（本步不吞异常，成功心跳不会发出）", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
