/*
 * 状态映射（唯一判定落点）
 *
 * 输入是 CLI 产物原文，输出是界面档位。规矩不变：
 *   failed / unknown 一律 blocked，不许当结果渲染；
 *   partial 必须显眼提示；undetermined 必须露出原因，不能只给一个词；
 *   三档失败态不许合并成「暂无数据」。
 * 本文件只做判定与措辞，不合成退出码——退出码一律用桥回传的真值。
 */

import type { TimelineDoc, RegistryRow } from './bridge'
import { strings } from '../i18n'

export type Tone = 'neu' | 'info' | 'warn' | 'neg'

export interface TierMeta {
  key: string
  /** 技术标签：只出现在「详情」里 */
  label: string
  /** 给人看的一句话 */
  plain: string
  tone: Tone
  icon: string
  blocked: boolean
}

export const TIMELINE_TIERS: Record<string, TierMeta> = {
  ok: {
    key: 'ok',
    label: strings.status.tiers.ok.label,
    plain: strings.status.tiers.ok.plain,
    tone: 'neu',
    icon: '✓',
    blocked: false,
  },
  empty: {
    key: 'empty',
    label: strings.status.tiers.empty.label,
    plain: strings.status.tiers.empty.plain,
    tone: 'neu',
    icon: '∅',
    blocked: false,
  },
  'entity-zero': {
    key: 'entity-zero',
    label: strings.status.tiers.entityZero.label,
    plain: strings.status.tiers.entityZero.plain,
    tone: 'neu',
    icon: '∅',
    blocked: false,
  },
  unjudged: {
    key: 'unjudged',
    label: strings.status.tiers.unjudged.label,
    plain: strings.status.tiers.unjudged.plain,
    tone: 'info',
    icon: '≈',
    blocked: false,
  },
  partial: {
    key: 'partial',
    label: strings.status.tiers.partial.label,
    plain: strings.status.tiers.partial.plain,
    tone: 'warn',
    icon: '!',
    blocked: false,
  },
  failed: {
    key: 'failed',
    label: strings.status.tiers.failed.label,
    plain: strings.status.tiers.failed.plain,
    tone: 'neg',
    icon: '×',
    blocked: true,
  },
  unknown: {
    key: 'unknown',
    label: strings.status.tiers.unknown.label,
    plain: strings.status.tiers.unknown.plain,
    tone: 'neg',
    icon: '?',
    blocked: true,
  },
}

export interface TimelineClass {
  tier: string
  tierMeta: TierMeta
  blocked: boolean
  statusRaw: string | null
  hasStatus: boolean
  invalid: boolean
  mode: string | null
  query: string | null
  windowStart: string | null
  windowEnd: string | null
  generatedAtUtc: string | null
  requested: string[]
  failedSources: string[]
  coveredCount: number
  fetchedCount: number
  allFetchedZero: boolean
  /** 逐源原文统计：详情里原样展示，不做解释 */
  sourcesStats: Record<string, { fetched?: number; accepted?: number; rejected?: number; error?: string | null }>
  stats: { raw: number; events: number; rejects: number; merged: number }
  events: NonNullable<TimelineDoc['events']>
  rejects: NonNullable<TimelineDoc['rejects']>
  rejectReasons: Record<string, number>
  coverageText: string
  notes: string[]
}

function num(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function unique(list: string[]): string[] {
  return Array.from(new Set(list.map(String)))
}

export function classifyTimeline(doc: TimelineDoc | null | undefined): TimelineClass {
  if (doc === null || typeof doc !== 'object') {
    return {
      tier: 'unknown',
      tierMeta: TIMELINE_TIERS.unknown,
      blocked: true,
      statusRaw: null,
      hasStatus: false,
      invalid: true,
      mode: null,
      query: null,
      windowStart: null,
      windowEnd: null,
      generatedAtUtc: null,
      requested: [],
      failedSources: [],
      coveredCount: 0,
      fetchedCount: 0,
      allFetchedZero: false,
      sourcesStats: {},
      stats: { raw: 0, events: 0, rejects: 0, merged: 0 },
      events: [],
      rejects: [],
      rejectReasons: {},
      coverageText: strings.status.noDocCoverage,
      notes: [strings.status.notes.noDoc],
    }
  }

  const meta = doc.meta
  if (!meta || typeof meta !== 'object') {
    return {
      tier: 'unknown',
      tierMeta: TIMELINE_TIERS.unknown,
      blocked: true,
      statusRaw: typeof doc.status === 'string' ? doc.status : null,
      hasStatus: !!doc.status,
      invalid: true,
      mode: null,
      query: null,
      windowStart: null,
      windowEnd: null,
      generatedAtUtc: null,
      requested: [],
      failedSources: [],
      coveredCount: 0,
      fetchedCount: 0,
      allFetchedZero: false,
      sourcesStats: {},
      stats: { raw: 0, events: 0, rejects: 0, merged: 0 },
      events: [],
      rejects: [],
      rejectReasons: {},
      coverageText: strings.status.noMetaCoverage,
      notes: [strings.status.notes.noMeta],
    }
  }

  const stats = meta.sources_stats && typeof meta.sources_stats === 'object' ? meta.sources_stats : {}
  const requested = Array.isArray(meta.sources) ? unique(meta.sources) : Object.keys(stats)
  const events = Array.isArray(doc.events) ? doc.events : []
  const rejects = Array.isArray(doc.rejects) ? doc.rejects : []
  const summary = meta.stats && typeof meta.stats === 'object' ? meta.stats : {}
  const rejectReasons = summary.reject_reasons && typeof summary.reject_reasons === 'object' ? summary.reject_reasons : {}

  const failedSources = requested.filter((source) => !!(stats[source] && stats[source].error))
  const fetchedCount = requested.filter((source) => num(stats[source]?.fetched) > 0).length
  const coveredCount = requested.filter((source) => !(stats[source] && stats[source].error)).length
  const allFetchedZero =
    requested.length > 0 &&
    requested.every((source) => num(stats[source]?.fetched) === 0) &&
    failedSources.length === 0

  const statusRaw = typeof doc.status === 'string' ? doc.status : null
  const hasStatus = !!statusRaw
  const notes: string[] = []

  // 防御：status 与逐源统计不一致时，以更保守的一档展示。
  let effectiveStatus = statusRaw
  if (statusRaw === 'ok' && failedSources.length > 0) {
    effectiveStatus = 'partial'
    notes.push(strings.status.notes.statusOkButFailed)
  }
  if (statusRaw === 'partial' && failedSources.length === 0) {
    notes.push(strings.status.notes.statusPartialNoFailed)
  }

  let tier = 'unknown'
  let emptyKind: string | null = null

  if (!hasStatus) {
    tier = 'unknown'
    notes.push(strings.status.notes.noStatus)
  } else if (effectiveStatus === 'failed') {
    tier = 'failed'
  } else if (effectiveStatus === 'partial') {
    tier = 'partial'
  } else if (effectiveStatus === 'ok') {
    if (events.length > 0) {
      tier = 'ok'
    } else if (allFetchedZero) {
      tier = 'empty'
      emptyKind = meta.mode === 'entity' ? 'entity-zero' : 'topic-empty'
      if (emptyKind === 'entity-zero') {
        notes.push(strings.status.notes.entityZero)
      }
    } else {
      tier = 'unjudged'
      notes.push(strings.status.notes.noEvents)
    }
  } else {
    tier = 'unknown'
    notes.push(strings.status.notes.unknownStatus(String(statusRaw)))
  }

  if (requested.length === 0) {
    tier = 'unknown'
    notes.push(strings.status.notes.noRequested)
  }

  const tierMeta = TIMELINE_TIERS[emptyKind === 'entity-zero' ? 'entity-zero' : tier] ?? TIMELINE_TIERS.unknown

  let coverageText: string
  if (tier === 'failed') {
    coverageText = strings.status.coverage.failed(
      requested.length,
      failedSources.join(strings.common.listSeparator) || strings.status.coverageNames.none,
    )
  } else if (tier === 'unknown' && !hasStatus) {
    coverageText = strings.status.coverage.legacy(requested.length, failedSources.length)
  } else if (tier === 'partial') {
    coverageText = strings.status.coverage.partial(
      coveredCount,
      requested.length,
      failedSources.join(strings.common.listSeparator) || strings.status.coverageNames.inconsistent,
    )
  } else {
    coverageText = strings.status.coverage.complete(coveredCount, requested.length)
  }

  return {
    tier,
    tierMeta,
    blocked: tierMeta.blocked,
    statusRaw,
    hasStatus,
    invalid: false,
    mode: meta.mode ?? null,
    query: meta.query ?? null,
    windowStart: meta.window_start ?? null,
    windowEnd: meta.window_end ?? null,
    generatedAtUtc: meta.generated_at_utc ?? null,
    requested,
    failedSources,
    coveredCount,
    fetchedCount,
    allFetchedZero,
    sourcesStats: stats,
    stats: {
      raw: num(summary.raw_items),
      events: num(summary.events),
      rejects: num(summary.rejects),
      merged: num(summary.merged_duplicates),
    },
    events,
    rejects,
    rejectReasons,
    coverageText,
    notes,
  }
}

/* ── 记录：reason_code → 给人看的解释 ───────────────────────── */
export interface ReasonBucket {
  label: string
  tone: Tone
  meaning: string
}

export const REASON_BUCKETS: Record<string, ReasonBucket> = {
  no_data: {
    label: strings.status.reasonBuckets.noData.label,
    tone: 'warn',
    meaning: strings.status.reasonBuckets.noData.meaning,
  },
  unreachable: {
    label: strings.status.reasonBuckets.unreachable.label,
    tone: 'neg',
    meaning: strings.status.reasonBuckets.unreachable.meaning,
  },
  undefined: {
    label: strings.status.reasonBuckets.undefined.label,
    tone: 'info',
    meaning: strings.status.reasonBuckets.undefined.meaning,
  },
  unknown: {
    label: strings.status.reasonBuckets.unknown.label,
    tone: 'warn',
    meaning: strings.status.reasonBuckets.unknown.meaning,
  },
  missing: {
    label: strings.status.reasonBuckets.missing.label,
    tone: 'neg',
    meaning: strings.status.reasonBuckets.missing.meaning,
  },
}

export const REASON_CODES: Record<string, { bucket: string; label: string; explain: string }> = {
  NO_OBSERVATIONS_IN_WINDOW: {
    bucket: 'no_data',
    label: strings.status.reasonCodes.noObservationsInWindow.label,
    explain: strings.status.reasonCodes.noObservationsInWindow.explain,
  },
  SOURCE_EMPTY: {
    bucket: 'no_data',
    label: strings.status.reasonCodes.sourceEmpty.label,
    explain: strings.status.reasonCodes.sourceEmpty.explain,
  },
  INSUFFICIENT_OBSERVATIONS: {
    bucket: 'no_data',
    label: strings.status.reasonCodes.insufficientObservations.label,
    explain: strings.status.reasonCodes.insufficientObservations.explain,
  },
  WINDOW_NOT_COVERED: {
    bucket: 'no_data',
    label: strings.status.reasonCodes.windowNotCovered.label,
    explain: strings.status.reasonCodes.windowNotCovered.explain,
  },
  SOURCE_UNREACHABLE: {
    bucket: 'unreachable',
    label: strings.status.reasonCodes.sourceUnreachable.label,
    explain: strings.status.reasonCodes.sourceUnreachable.explain,
  },
  SOURCE_HTTP: {
    bucket: 'unreachable',
    label: strings.status.reasonCodes.sourceHttp.label,
    explain: strings.status.reasonCodes.sourceHttp.explain,
  },
  SOURCE_PARSE: {
    bucket: 'unreachable',
    label: strings.status.reasonCodes.sourceParse.label,
    explain: strings.status.reasonCodes.sourceParse.explain,
  },
  SOURCE_FIELD_MISSING: {
    bucket: 'unreachable',
    label: strings.status.reasonCodes.sourceFieldMissing.label,
    explain: strings.status.reasonCodes.sourceFieldMissing.explain,
  },
  AGGREGATE_UNDEFINED: {
    bucket: 'undefined',
    label: strings.status.reasonCodes.aggregateUndefined.label,
    explain: strings.status.reasonCodes.aggregateUndefined.explain,
  },
}

export function reasonInfo(code: string | null | undefined): {
  code: string | null
  known: boolean
  bucket: string
  bucketMeta: ReasonBucket
  label: string
  explain: string
} {
  if (!code) {
    const b = REASON_BUCKETS.missing
    return { code: null, known: false, bucket: 'missing', bucketMeta: b, label: b.label, explain: b.meaning }
  }
  const raw = String(code)
  const entry = REASON_CODES[raw]
  if (!entry) {
    const b = REASON_BUCKETS.unknown
    return {
      code: raw,
      known: false,
      bucket: 'unknown',
      bucketMeta: b,
      label: b.label,
      explain: strings.status.unknownReason,
    }
  }
  const bucketMeta = REASON_BUCKETS[entry.bucket]
  return { code: raw, known: true, bucket: entry.bucket, bucketMeta, label: entry.label, explain: entry.explain }
}

/* ── 记录：判定状态 → 人话 ─────────────────────────────────── */
export interface VerdictMeta {
  key: string
  /** 给人看的标签 */
  label: string
  tone: Tone
  icon: string
  /** 详细信息（含技术词） */
  note: string
}

export const VERDICTS: Record<string, VerdictMeta> = {
  hit: { key: 'hit', label: strings.status.verdicts.hit.label, tone: 'neu', icon: '✓', note: strings.status.verdicts.hit.note },
  miss: { key: 'miss', label: strings.status.verdicts.miss.label, tone: 'neg', icon: '×', note: strings.status.verdicts.miss.note },
  undetermined: {
    key: 'undetermined',
    label: strings.status.verdicts.undetermined.label,
    tone: 'warn',
    icon: '≈',
    note: strings.status.verdicts.undetermined.note,
  },
  not_due: {
    key: 'not_due',
    label: strings.status.verdicts.notDue.label,
    tone: 'neu',
    icon: '∅',
    note: strings.status.verdicts.notDue.note,
  },
  frozen: {
    key: 'frozen',
    label: strings.status.verdicts.frozen.label,
    tone: 'neu',
    icon: '●',
    note: strings.status.verdicts.frozen.note,
  },
}

export function mapVerdict(verdict: string | null | undefined): VerdictMeta {
  if (verdict === null || verdict === undefined || verdict === '') {
    return {
      key: 'pending',
      label: strings.status.pendingVerdict.label,
      tone: 'neu',
      icon: '∅',
      note: strings.status.pendingVerdict.note,
    }
  }
  return (
    VERDICTS[String(verdict)] ?? {
      key: 'unknown',
      label: strings.status.unknownVerdict.label,
      tone: 'warn',
      icon: '?',
      note: strings.status.unknownVerdict.note,
    }
  )
}

export interface RegistrySummary {
  total: number
  hit: number
  miss: number
  undetermined: number
  pending: number
  frozen: number
  other: number
}

export function summarizeRegistry(rows: RegistryRow[]): RegistrySummary {
  const summary: RegistrySummary = { total: 0, hit: 0, miss: 0, undetermined: 0, pending: 0, frozen: 0, other: 0 }
  ;(Array.isArray(rows) ? rows : []).forEach((row) => {
    summary.total += 1
    const mapped = mapVerdict(row?.verdict)
    if (mapped.key === 'hit') summary.hit += 1
    else if (mapped.key === 'miss') summary.miss += 1
    else if (mapped.key === 'undetermined') summary.undetermined += 1
    else if (mapped.key === 'pending') summary.pending += 1
    else if (mapped.key === 'frozen') summary.frozen += 1
    else summary.other += 1
  })
  return summary
}
