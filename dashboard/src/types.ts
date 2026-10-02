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

export interface Snapshot {
  chain_id: string
  status: string
  failure_reasons: string[]
  lead?: { source?: string; symbol?: string; latest?: string; points?: number; degraded?: boolean }
  lag?: {
    source?: string
    sector?: string
    latest?: string
    weekly_points?: number
    has_amount?: boolean
    path?: string
    degraded?: boolean
  }
  run_utc: string
}

/** 总览页的链视图：profile + snapshot + 项目预算账本合成。 */
export interface ChainView {
  chainId: string
  title: string
  verdict: VerdictStatus
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
}
