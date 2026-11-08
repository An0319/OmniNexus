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
    label: '正常完成',
    plain: '消息源都查过了，有可用线索。',
    tone: 'neu',
    icon: '✓',
    blocked: false,
  },
  empty: {
    key: 'empty',
    label: '真无数据',
    plain: '消息源都查过了，确实没有匹配的线索——不是抓取失败。',
    tone: 'neu',
    icon: '∅',
    blocked: false,
  },
  'entity-zero': {
    key: 'entity-zero',
    label: '实体零命中',
    plain: '消息源都查过了，但没抓到可判定的条目；这不能读成「这家公司没有事件」。',
    tone: 'neu',
    icon: '∅',
    blocked: false,
  },
  unjudged: {
    key: 'unjudged',
    label: '判不了',
    plain: '抓到了条目，但没有一条能当线索；原因在详情里。',
    tone: 'info',
    icon: '≈',
    blocked: false,
  },
  partial: {
    key: 'partial',
    label: '部分覆盖',
    plain: '只拿到一半消息源，这份结果不完整。',
    tone: 'warn',
    icon: '!',
    blocked: false,
  },
  failed: {
    key: 'failed',
    label: '失败',
    plain: '这次没拿到结果：所有消息源都失败了。',
    tone: 'neg',
    icon: '×',
    blocked: true,
  },
  unknown: {
    key: 'unknown',
    label: '状态未知',
    plain: '这份产物缺状态字段（旧产物），不能当结果读。',
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
      coverageText: '没有产物文档，无法确认覆盖',
      notes: ['桌面壳没有拿到 events.json，不能当结果读。'],
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
      coverageText: '产物结构不完整（缺 meta），无法确认覆盖',
      notes: ['产物缺 meta：不能当结果读。'],
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
    notes.push('status 写的是 ok，但逐源统计里有失败源；壳按「部分覆盖」保守展示。')
  }
  if (statusRaw === 'partial' && failedSources.length === 0) {
    notes.push('status 写的是 partial，但逐源统计里没有失败源；仍按部分覆盖展示，并请回仓库核对。')
  }

  let tier = 'unknown'
  let emptyKind: string | null = null

  if (!hasStatus) {
    tier = 'unknown'
    notes.push('产物没有 status 字段（旧产物），无法证明是 ok；事件区已拦截，仅供排障计数。')
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
        notes.push('实体模式零命中：源已覆盖但没抓到条目；不能读成「该主体没有事件」。')
      }
    } else {
      tier = 'unjudged'
      notes.push('源有返回，但抽出的事件为 0；拒绝原因必须展开。')
    }
  } else {
    tier = 'unknown'
    notes.push(`无法识别的 status：${String(statusRaw)}`)
  }

  if (requested.length === 0) {
    tier = 'unknown'
    notes.push('产物没有记录请求过哪些源，无法确认覆盖。')
  }

  const tierMeta = TIMELINE_TIERS[emptyKind === 'entity-zero' ? 'entity-zero' : tier] ?? TIMELINE_TIERS.unknown

  let coverageText: string
  if (tier === 'failed') {
    coverageText = `源覆盖 0/${requested.length}；全部失败：${failedSources.join('、') || '（未记录源名）'}`
  } else if (tier === 'unknown' && !hasStatus) {
    coverageText = `旧产物无 status；逐源记录：${requested.length} 源，失败 ${failedSources.length} 源`
  } else if (tier === 'partial') {
    coverageText = `源覆盖 ${coveredCount}/${requested.length}；失败源：${failedSources.join('、') || '（逐源记录不一致）'}`
  } else {
    coverageText = `源覆盖 ${coveredCount}/${requested.length}；失败源 0`
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
    label: '缺数据',
    tone: 'warn',
    meaning: '到期了，但窗口里没有可用观测；不能读成「没发生」。',
  },
  unreachable: {
    label: '取不到',
    tone: 'neg',
    meaning: '消息源不可用，这次没法判定。',
  },
  undefined: {
    label: '算不出',
    tone: 'info',
    meaning: '不是源的问题，是定义本身算不出值。',
  },
  unknown: {
    label: '未登记原因',
    tone: 'warn',
    meaning: '原因码没在壳里登记；原样展示，需回仓库核对。',
  },
  missing: {
    label: '没给原因',
    tone: 'neg',
    meaning: '状态是判不了却没带原因码；按异常处理，不能猜。',
  },
}

export const REASON_CODES: Record<string, { bucket: string; label: string; explain: string }> = {
  NO_OBSERVATIONS_IN_WINDOW: { bucket: 'no_data', label: '窗口内无观测', explain: '窗口内一条观测都没有。' },
  SOURCE_EMPTY: { bucket: 'no_data', label: '清洗后为空', explain: '源有响应，但清洗后没有可用观测。' },
  INSUFFICIENT_OBSERVATIONS: { bucket: 'no_data', label: '观测不足', explain: '观测条数少于判据要求的最小条数。' },
  WINDOW_NOT_COVERED: { bucket: 'no_data', label: '窗口未被覆盖', explain: '窗口末与最后一个观测的间隔超过允许的天数。' },
  SOURCE_UNREACHABLE: { bucket: 'unreachable', label: '源不可达', explain: '连接或代理失败，取不到数据。' },
  SOURCE_HTTP: { bucket: 'unreachable', label: '源返回 HTTP 错误', explain: '源返回的状态码不是成功响应。' },
  SOURCE_PARSE: { bucket: 'unreachable', label: '响应解析失败', explain: '返回内容不是可解析的数据格式。' },
  SOURCE_FIELD_MISSING: { bucket: 'unreachable', label: '响应缺字段', explain: '返回结构里缺判据需要的字段。' },
  AGGREGATE_UNDEFINED: { bucket: 'undefined', label: '聚合无定义', explain: '数据齐全，但聚合在数学上无定义（例如首条观测为 0 时算涨跌幅）。' },
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
      explain: '该原因码未在壳内登记；原样展示，不做解释，需回仓库核对。',
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
  hit: { key: 'hit', label: '兑现了', tone: 'neu', icon: '✓', note: '核验结论为 hit：命题成立。' },
  miss: { key: 'miss', label: '没兑现', tone: 'neg', icon: '×', note: '核验结论为 miss：命题不成立。' },
  undetermined: {
    key: 'undetermined',
    label: '判不了',
    tone: 'warn',
    icon: '≈',
    note: '核验结论为 undetermined：源不可达、数据缺失、聚合无定义三类共用此值，必须看 reason_code 区分。',
  },
  not_due: { key: 'not_due', label: '未到期', tone: 'neu', icon: '∅', note: '还没到结算时点。' },
  frozen: { key: 'frozen', label: '已冻结', tone: 'neu', icon: '●', note: '参数与判据已冻结，不再改。' },
}

export function mapVerdict(verdict: string | null | undefined): VerdictMeta {
  if (verdict === null || verdict === undefined || verdict === '') {
    return {
      key: 'pending',
      label: '还没核对',
      tone: 'neu',
      icon: '∅',
      note: '记录里还没有判定（未到期或尚未核验）。',
    }
  }
  return (
    VERDICTS[String(verdict)] ?? {
      key: 'unknown',
      label: '未登记结论',
      tone: 'warn',
      icon: '?',
      note: '该判定状态未在壳内登记；原样展示。',
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
