/** 数据契约类型：对齐 chains/<id>.profile.json（schema 1.0）与仓库既有文件。 */

export type MetricStatus = 'verified' | 'greyzone' | 'not_passed'
export type VerdictStatus = 'verified' | 'greyzone' | 'not_passed' | 'falsified'

export interface LagPoint {
  k: number
  corr: number
}

export interface Metric {
  name: string
  status: MetricStatus
  best_in_window: LagPoint | null
  peak: LagPoint
  peak_outside_window: boolean
  lags: LagPoint[]
}

export interface Judgement {
  lag_range: [number, number]
  pass_window: [number, number]
  pass_corr: number
  noise_band: number | null
  null_median: number | null
}

export interface Profile {
  schema_version: string
  chain_id: string
  title: string
  generated_at: string
  source_files: string[]
  judgement: Judgement
  verdict: { status: VerdictStatus; decided_utc_date: string; note: string }
  forward_look: { k: number; tradable: boolean; rationale: string } | null
  samples: { total_weeks: number; effective_weeks: number; basis: string }
  pipeline: { lead: string; lag: string; steps: string[] }
  metrics: Metric[]
}

export interface StreakDay {
  utc_date: string
  status: string
  runs: number
  chains: Record<string, string>
  failure_reasons: string[]
  closed?: boolean
}

export interface Streak {
  project: string
  target_days: number
  rule: string
  current_streak: number
  started_utc_date: string
  last_success_utc_date: string
  last_run_utc: string
  days: StreakDay[]
  breaks: { utc_date: string; reason?: string }[]
  resets: { utc_date: string; reason: string; archive: string }[]
}

export interface BudgetAttempt {
  n: number
  chain_id: string
  date: string
  title: string
  note: string
}

export interface Budget {
  max_attempts: number
  attempts: BudgetAttempt[]
  note: string
  backfilled: string
  updated: string
}

export interface SnapshotLead {
  source?: string
  symbol?: string
  keywords?: string[]
  latest?: string
  points?: number
  missing_weeks?: number
  degraded?: boolean
}

export interface SnapshotLag {
  source?: string
  sector?: string
  latest?: string
  weekly_points?: number
  has_amount?: boolean
  path?: string
  degraded?: boolean
}

export interface Snapshot {
  chain_id: string
  status: string
  failure_reasons: string[]
  lead?: SnapshotLead
  lag?: SnapshotLag
  run_utc: string
}

/** chains/<id>.zseries.json：链详情页 z 曲线（C5）的周频归一序列。 */
export interface ZPoint {
  date: string
  lead: number | null
  lag_ret: number | null
  lag_amount: number | null
}

export interface ZSeries {
  chain_id: string
  generated_at: string
  source_file: string
  points: ZPoint[]
}

/** chains/revisions.json：各链 YAML revisions 块的结构化。 */
export interface RevisionEntry {
  date: string
  reason: string
  counts_as_attempt: boolean
}

export interface RevisionsFile {
  generated_at: string
  source_files: string[]
  revisions: Record<string, RevisionEntry[]>
}

/** chains/<id>.record.runs.jsonl / project_budget.runs.jsonl：append-only 运行账本。 */
export interface RunLedgerEvent {
  event?: string
  at?: string
  note?: string
  reason?: string
  last_run?: string
  chain_id?: string
  fingerprint?: string
  substantive_fingerprint?: string
  budget_used?: number
  revisions_seen?: number
  attempts_len?: number
  entry?: { n: number; chain_id: string; date: string; title?: string; note?: string }
  last_verdicts?: { metric: string; status: string; k_best: number; corr: number }[]
}

/** 时间线页（C8）：尝试 / 修订 / 运维事件三类之一。 */
export type TimelineKind = 'attempt' | 'revision' | 'reset'

export interface TimelineEvent {
  id: string
  kind: TimelineKind
  /** UTC 日期，YYYY-MM-DD。 */
  date: string
  /** 可选精确时间戳。 */
  at?: string
  /** 链标题 / 事件标题。 */
  title: string
  /** 一句话原因/结论。 */
  body: string
  chainId?: string
  countsAsAttempt?: boolean
}

/** 链视图：profile + snapshot + z 曲线 + 项目预算账本合成。总览卡片与链详情页共用。 */
export interface ChainView {
  chainId: string
  title: string
  verdict: VerdictStatus
  decidedDate: string
  note: string
  runUtc: string | null
  runStatus: string | null
  failureReasons: string[]
  degraded: boolean
  path: string | null
  quality: 'green' | 'yellow' | 'red' | 'gray'
  attemptsUsed: number
  budgetMax: number
  samples: Profile['samples']
  metrics: Metric[]
  forwardLook: Profile['forward_look']
  judgement: Judgement
  pipeline: Profile['pipeline']
  sourceFiles: Profile['source_files']
  snapshot: Snapshot | null
  zSeries: ZSeries | null
}
