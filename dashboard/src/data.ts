/**
 * 数据装载（只读）。
 *
 * 全部使用相对 JSON 导入：dev 模式随仓库文件热更新，构建时内联为静态资源。
 * 红线：本模块及整个看板对 data/ 与 chains/ **只读**，绝不写回——
 * T1 计时连续性（runs.jsonl / streak.json 格式）在 30 天验收期内一字不动。
 */

import budgetRaw from '../../chains/project_budget.json'
import chain01Profile from '../../chains/chain01.profile.json'
import chain10Profile from '../../chains/chain10.profile.json'
import chain20Profile from '../../chains/chain20.profile.json'
import snapshot01 from '../../data/snapshot_chain01.json'
import snapshot10 from '../../data/snapshot_chain10.json'
import snapshot20 from '../../data/snapshot_chain20.json'
import streakRaw from '../../data/streak.json'
import type { Budget, ChainView, Profile, Snapshot, Streak } from './types'

export const streak = streakRaw as unknown as Streak
export const budget = budgetRaw as unknown as Budget

export const profiles = [
  chain01Profile,
  chain10Profile,
  chain20Profile,
] as unknown as Profile[]

const snapshots: Record<string, Snapshot> = {
  chain01: snapshot01 as unknown as Snapshot,
  chain10: snapshot10 as unknown as Snapshot,
  chain20: snapshot20 as unknown as Snapshot,
}

function deriveQuality(snapshot: Snapshot | undefined): ChainView['quality'] {
  if (!snapshot) return 'gray' // 未运行：灰 = 未观测，不是失败
  if (snapshot.status !== 'ok' || snapshot.failure_reasons.length > 0) return 'red'
  if (snapshot.lead?.degraded || snapshot.lag?.degraded) return 'yellow'
  return 'green'
}

/**
 * 合成总览页视图。
 * 已用尝试数取 chains/project_budget.json（项目账本是唯一真相，
 * 各链 YAML 的 budget.used 只是展示字段）。
 */
export function buildChainViews(): ChainView[] {
  return profiles.map((profile) => {
    const snapshot = snapshots[profile.chain_id]
    const attempts = budget.attempts.filter((a) => a.chain_id === profile.chain_id)
    return {
      chainId: profile.chain_id,
      title: profile.title,
      verdict: profile.verdict.status,
      note: profile.verdict.note,
      runUtc: snapshot?.run_utc ?? null,
      runStatus: snapshot?.status ?? null,
      failureReasons: snapshot?.failure_reasons ?? [],
      degraded: Boolean(snapshot?.lead?.degraded || snapshot?.lag?.degraded),
      path: snapshot?.lag?.path ?? null,
      quality: deriveQuality(snapshot),
      attemptsUsed: attempts.length,
      budgetMax: budget.max_attempts,
      samples: profile.samples,
      metrics: profile.metrics,
      forwardLook: profile.forward_look,
    }
  })
}
