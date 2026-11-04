/**
 * E9 运行态装载（架构审计 D13）：运行时 fetch data/run_state.json——
 * 全站唯一运行时 fetch 例外（M2「构建期内联、无 fetch」的已拍板豁免）。
 *
 * 语义按实情命名：Pages 有缓存延迟，所见不是实时"正在跑"，
 * 而是「已开工未收尾」（有 started_utc 无 finished_utc），
 * 用于暴露卡死/中断的运行，与 E5 外部心跳互补。
 *
 * fetch 失败或文件缺失（本地 dev / 部署早期）→ 返回 null，看板回落 C3 三态。
 */

import { useEffect, useState } from 'react'
import type { RunState } from './types'

export function useRunState(): RunState | null {
  const [state, setState] = useState<RunState | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch(`${import.meta.env.BASE_URL}run_state.json`)
      .then((res) =>
        res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`)),
      )
      .then((data: RunState) => {
        if (!cancelled) setState(data)
      })
      .catch(() => {
        // 文件缺失 / fetch 失败：运行态不可得，回落三态，不响（诚实降级）
      })
    return () => {
      cancelled = true
    }
  }, [])

  return state
}

/** 「已开工未收尾」判据：有 started_utc 且无 finished_utc。 */
export function isRunUnfinished(runState: RunState | null): boolean {
  return runState !== null && runState.finished_utc === null
}
