/**
 * 数据装载（只读）。
 *
 * 全部使用相对导入：JSON 走相对路径静态导入（dev 热更新，构建内联），
 * JSONL 运行账本走 `?raw` 后逐行解析。纯静态、无后端、无 fetch——
 * 唯一例外：E9 运行态 run_state.json 由 useRunState.ts 运行时 fetch
 * （架构审计 D13 已拍板豁免，本模块不参与）。
 *
 * 红线：本模块及整个看板对 data/ 与 chains/ **只读**，绝不写回——
 * T1 计时连续性（runs.jsonl / streak.json 格式）在 30 天验收期内一字不动。
 */

import budgetRaw from '../../chains/project_budget.json'
import revisionsRaw from '../../chains/revisions.json'
import streakRaw from '../../data/streak.json'
import budgetRunsRaw from '../../chains/project_budget.runs.jsonl?raw'
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

type JsonModule<T> = { default: T }

/**
 * 链清单按目录实际文件驱动，不在代码里写死数量与顺序：
 * - chains/<id>.profile.json       链配置（必需，决定链是否存在）
 * - data/snapshot_<id>.json        日更快照（可选，缺失 → 未运行灰态）
 * - chains/<id>.zseries.json       周频归一序列（可选，缺失 → 无数据空态）
 * - chains/<id>.record.runs.jsonl  运行账本（可选，缺失 → 空账本）
 * 新增链只需放入以上文件，本模块与任何组件均无需改动。
 */
const profileModules = import.meta.glob<JsonModule<Profile>>('../../chains/*.profile.json', {
  eager: true,
})
const snapshotModules = import.meta.glob<JsonModule<Snapshot>>('../../data/snapshot_*.json', {
  eager: true,
})
const zSeriesModules = import.meta.glob<JsonModule<ZSeries>>('../../chains/*.zseries.json', {
  eager: true,
})
const runLedgerModules = import.meta.glob<string>('../../chains/*.record.runs.jsonl', {
  eager: true,
  query: '?raw',
  import: 'default',
})

function byChainId<T extends { chain_id: string }>(
  modules: Record<string, JsonModule<T>>,
): Record<string, T> {
  return Object.fromEntries(
    Object.values(modules).map((module) => [module.default.chain_id, module.default]),
  )
}

/** 链清单：按 profile 自带的 chain_id 排序，与文件名无关；新增文件自动登记。 */
export const profiles: Profile[] = Object.values(profileModules)
  .map((module) => module.default)
  .sort((a, b) => a.chain_id.localeCompare(b.chain_id))

const snapshots = byChainId(snapshotModules)
// 无 zseries 产出的链不登记（如 chain20），前端走「无数据」灰态，不伪造曲线。
const zSeriesById = byChainId(zSeriesModules)

/** 逐行解析 append-only 运行账本（JSONL，空行忽略）。 */
function parseJsonl(raw: string): RunLedgerEvent[] {
  return raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== '')
    .map((line) => JSON.parse(line) as RunLedgerEvent)
}

const ledgerRawById: Record<string, string> = Object.fromEntries(
  Object.entries(runLedgerModules).map(([path, raw]) => [
    path.match(/([^/]+)\.record\.runs\.jsonl$/)?.[1] ?? path,
    raw,
  ]),
)

/** 运行账本按链清单对齐：无账本文件的链给空数组，表格据此显示「—」。 */
export const runLedgers: Record<string, RunLedgerEvent[]> = Object.fromEntries(
  profiles.map((profile) => [profile.chain_id, parseJsonl(ledgerRawById[profile.chain_id] ?? '')]),
)

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
      title: attempt.title,
      body: attempt.note,
      chainId: attempt.chain_id,
      countsAsAttempt: true,
      attemptNo: attempt.n,
    })
  }

  for (const [chainId, entries] of Object.entries(revisions.revisions)) {
    entries.forEach((entry, index) => {
      events.push({
        id: `revision-${chainId}-${index}`,
        kind: 'revision',
        date: entry.date,
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
      body: reset.reason,
      countsAsAttempt: false,
    })
  }

  return events.sort((a, b) => {
    if (a.date !== b.date) return a.date < b.date ? 1 : -1
    return kindOrder[a.kind] - kindOrder[b.kind]
  })
}
