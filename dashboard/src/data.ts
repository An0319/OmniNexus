/**
 * 数据装载（只读）。
 *
 * 全部使用相对导入：JSON 走相对路径静态导入（dev 热更新，构建内联），
 * JSONL 运行账本走 `?raw` 后逐行解析。纯静态、无后端、无 fetch。
 *
 * 红线：本模块及整个看板对 data/ 与 chains/ **只读**，绝不写回——
 * T1 计时连续性（runs.jsonl / streak.json 格式）在 30 天验收期内一字不动。
 */

import budgetRaw from '../../chains/project_budget.json'
import revisionsRaw from '../../chains/revisions.json'
import chain01Profile from '../../chains/chain01.profile.json'
import chain10Profile from '../../chains/chain10.profile.json'
import chain20Profile from '../../chains/chain20.profile.json'
import chain01ZSeries from '../../chains/chain01.zseries.json'
import chain10ZSeries from '../../chains/chain10.zseries.json'
import snapshot01 from '../../data/snapshot_chain01.json'
import snapshot10 from '../../data/snapshot_chain10.json'
import snapshot20 from '../../data/snapshot_chain20.json'
import streakRaw from '../../data/streak.json'
import budgetRunsRaw from '../../chains/project_budget.runs.jsonl?raw'
import runs01Raw from '../../chains/chain01.record.runs.jsonl?raw'
import runs10Raw from '../../chains/chain10.record.runs.jsonl?raw'
import runs20Raw from '../../chains/chain20.record.runs.jsonl?raw'
import type {
  Budget,
  ChainView,
  Profile,
  RevisionsFile,
  RunLedgerEvent,
  Snapshot,
  Streak,
  TimelineEvent,
  ZSeries,
} from './types'

export const streak = streakRaw as unknown as Streak
export const budget = budgetRaw as unknown as Budget
export const revisions = revisionsRaw as unknown as RevisionsFile

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

// chain20 无 zseries 产出（隔夜快传导链未做周频归一）→ null，前端走「无数据」灰态。
export const zSeriesById: Record<string, ZSeries | null> = {
  chain01: chain01ZSeries as unknown as ZSeries,
  chain10: chain10ZSeries as unknown as ZSeries,
  chain20: null,
}

/** 逐行解析 append-only 运行账本（JSONL，空行忽略）。 */
function parseJsonl(raw: string): RunLedgerEvent[] {
  return raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== '')
    .map((line) => JSON.parse(line) as RunLedgerEvent)
}

export const runLedgers: Record<string, RunLedgerEvent[]> = {
  chain01: parseJsonl(runs01Raw),
  chain10: parseJsonl(runs10Raw),
  chain20: parseJsonl(runs20Raw),
}

export const budgetRuns = parseJsonl(budgetRunsRaw)

function deriveQuality(snapshot: Snapshot | undefined): ChainView['quality'] {
  if (!snapshot) return 'gray' // 未运行：灰 = 未观测，不是失败
  if (snapshot.status !== 'ok' || snapshot.failure_reasons.length > 0) return 'red'
  if (snapshot.lead?.degraded || snapshot.lag?.degraded) return 'yellow'
  return 'green'
}

/**
 * 合成链视图。
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
      decidedDate: profile.verdict.decided_utc_date,
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
      judgement: profile.judgement,
      pipeline: profile.pipeline,
      sourceFiles: profile.source_files,
      snapshot: snapshot ?? null,
      zSeries: zSeriesById[profile.chain_id] ?? null,
    }
  })
}

/**
 * 构建公开审计时间线（C8）：尝试（项目账本）/ 修订（链 YAML）/ 运维事件（streak resets）。
 * 三类之外不新增类型；运行账本（指纹留痕）单独成块，不混入时间线。
 * 排序：UTC 日期倒序（同日按尝试 → 修订 → 重置）。
 */
export function buildTimeline(): TimelineEvent[] {
  const kindOrder: Record<TimelineEvent['kind'], number> = { attempt: 0, revision: 1, reset: 2 }
  const events: TimelineEvent[] = []

  for (const attempt of budget.attempts) {
    events.push({
      id: `attempt-${attempt.n}`,
      kind: 'attempt',
      date: attempt.date,
      title: `有效尝试 #${attempt.n} · ${attempt.title}`,
      body: attempt.note,
      chainId: attempt.chain_id,
      countsAsAttempt: true,
    })
  }

  for (const [chainId, entries] of Object.entries(revisions.revisions)) {
    entries.forEach((entry, index) => {
      events.push({
        id: `revision-${chainId}-${index}`,
        kind: 'revision',
        date: entry.date,
        title: `${chainId} · 修订登记`,
        body: entry.reason,
        chainId,
        countsAsAttempt: entry.counts_as_attempt,
      })
    })
  }

  for (const reset of streak.resets) {
    events.push({
      id: `reset-${reset.utc_date}`,
      kind: 'reset',
      date: reset.utc_date,
      title: 'T1 计时主动重置 · 运维事件',
      body: reset.reason,
      countsAsAttempt: false,
    })
  }

  return events.sort((a, b) => {
    if (a.date !== b.date) return a.date < b.date ? 1 : -1
    return kindOrder[a.kind] - kindOrder[b.kind]
  })
}
