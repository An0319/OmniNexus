/*
 * 进程桥 · 前端契约 mnx-shell-bridge/v1
 *
 * Rust 侧只搬运：spawn Python、回传 exitCode/stdout/stderr/data。
 * 前端在这里做参数校验，失败一律返回结构化的 ok:false，不伪造任何结果。
 * 时间纪律：--at 必须由调用方显式传入 ISO-8601 UTC（带 Z），不交给 Python 取系统时间。
 */

export interface BridgeResult<T = unknown> {
  ok: boolean
  available: boolean
  code: string | null
  message: string | null
  command: string
  exitCode: number | null
  stdout: string
  stderr: string
  data: T | null
}

export interface TimelineRequest {
  mode: 'topic' | 'entity'
  topic?: string | null
  entity?: string | null
  start: string
  end: string
  sources?: string[] | null
  maxPerSource?: number
  outDir?: string
  pythonPath?: string
}

export interface TimelineEvent {
  event_id: string
  time: string
  time_precision?: string
  subject: string
  action: string
  action_text?: string
  object?: string | null
  value?: { kind: string; raw?: string | null; number?: number | null; unit?: string | null }
  source_url: string
  source_name: string
  fetched_at_utc?: string
  excerpt?: string
  sources?: { source_name?: string; source_url?: string }[]
}

export interface TimelineData {
  outDir: string
  eventsJson: string
  eventsMd: string
  rawItemsJson: string
  eventsJsonExists: boolean
  rawItemsJsonExists: boolean
  eventsDoc?: TimelineDoc
}

export interface TimelineDoc {
  status?: string
  meta?: {
    mode?: string
    query?: string
    window_start?: string
    window_end?: string
    generated_at_utc?: string
    sources?: string[]
    sources_stats?: Record<string, { fetched?: number; error?: string | null }>
    stats?: {
      raw_items?: number
      events?: number
      rejects?: number
      merged_duplicates?: number
      reject_reasons?: Record<string, number>
    }
  }
  events?: TimelineEvent[]
  rejects?: { reason?: string; title?: string; source_name?: string; url?: string }[]
}

export interface RegistryRow {
  id: string
  expires_on: string
  registered_at: string
  provenance: string
  claim_canonical: string
  verdict: 'hit' | 'miss' | 'undetermined' | null
  reason_code: string | null
}

export interface VerifyRow {
  id: string
  status: string
  reason_code?: string | null
  detail?: string | null
  observed?: unknown
}

export interface VerifyPayload {
  at: string
  counts: Record<string, number>
  results: VerifyRow[]
}

/* ── 环境常量（与 CLI 默认值保持一致，界面上可改并显式传给 Python） ── */
export const CONTRACT_VERSION = 'mnx-shell-bridge/v1'

export const PYTHON_PATH = 'C:\\Users\\24063\\AppData\\Local\\Programs\\Python\\Python312\\python.exe'

export const DEFAULTS = {
  outDir: 'phase0/timeline/out',
  ledger: 'phase0/registry/registry.ledger.jsonl',
  maxPerSource: 60,
  sources: ['google_news', 'bing_news', 'clinicaltrials', 'federal_register'],
}

export const SOURCE_LABELS: Record<string, string> = {
  google_news: 'Google 新闻',
  bing_news: 'Bing 新闻',
  clinicaltrials: '临床试验登记',
  federal_register: '美国联邦公报',
}

const ISO_AT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

type TauriCore = { invoke: (cmd: string, args?: unknown) => Promise<unknown> }
type TauriEvent = {
  listen: (name: string, cb: (event: { payload?: unknown }) => void) => Promise<() => void>
}

function tauriCore(): TauriCore | null {
  const g = globalThis as unknown as { __TAURI__?: { core?: TauriCore } }
  return g.__TAURI__?.core ?? null
}

function tauriEvent(): TauriEvent | null {
  const g = globalThis as unknown as { __TAURI__?: { event?: TauriEvent } }
  return g.__TAURI__?.event ?? null
}

export function available(): boolean {
  return !!tauriCore()
}

function fail(command: string, code: string, message: string, isAvailable: boolean): BridgeResult<never> {
  return {
    ok: false,
    available: isAvailable,
    code,
    message,
    command,
    exitCode: null,
    stdout: '',
    stderr: '',
    data: null,
  }
}

function invoke<T>(command: string, request: unknown): Promise<BridgeResult<T>> {
  const core = tauriCore()
  if (!core) {
    return Promise.resolve(
      fail(
        command,
        'BRIDGE_NOT_AVAILABLE',
        '进程桥未接入：界面拿不到桌面壳的命令通道（可能是在浏览器里直接打开）。',
        false,
      ),
    )
  }
  return core
    .invoke(command, { request })
    .then((raw) => {
      const payload = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
      return {
        ok: true,
        available: true,
        code: null,
        message: null,
        command,
        exitCode: typeof payload.exitCode === 'number' ? payload.exitCode : null,
        stdout: typeof payload.stdout === 'string' ? payload.stdout : '',
        stderr: typeof payload.stderr === 'string' ? payload.stderr : '',
        data: (payload.data === undefined ? null : payload.data) as T | null,
      }
    })
    .catch((err: unknown) => {
      const message = err instanceof Error ? err.message : String(err)
      return fail(command, 'BRIDGE_ERROR', message, true)
    })
}

/* 外部链接只走这一条：交给系统默认浏览器，不在应用内开新窗口。
   返回 null = 已交出去；返回字符串 = 失败原因，界面必须如实显示，不能假装打开成功。 */
export async function openExternal(url: string): Promise<string | null> {
  const text = (url || '').trim()
  if (!/^(https?):\/\/\S+$/i.test(text)) {
    return '只允许 http / https 链接'
  }
  const core = tauriCore()
  if (!core) {
    return '进程桥未接入，唤不起系统浏览器'
  }
  try {
    await core.invoke('plugin:opener|open_url', { url: text })
    return null
  } catch (err) {
    return err instanceof Error ? err.message : String(err)
  }
}

export function validateAt(value: string): string | null {
  const text = (value || '').trim()
  if (!ISO_AT.test(text)) {
    return '时刻必须是 ISO-8601 UTC，例如 2026-11-08T09:00:00Z（必须带 Z）'
  }
  return null
}

export function validateDate(value: string, label: string): string | null {
  if (!ISO_DATE.test((value || '').trim())) return `${label} 必须是 YYYY-MM-DD`
  return null
}

export function runTimeline(request: TimelineRequest): Promise<BridgeResult<TimelineData>> {
  const command = 'run_timeline'
  const mode = request.mode === 'entity' ? 'entity' : 'topic'
  const query = mode === 'entity' ? request.entity : request.topic
  if (!query || !String(query).trim()) {
    return Promise.resolve(
      fail(command, 'INVALID_REQUEST', mode === 'entity' ? '请先填写公司名或代号' : '请先填写想看的话题', true),
    )
  }
  const startErr = validateDate(request.start, '开始日期')
  if (startErr) return Promise.resolve(fail(command, 'INVALID_REQUEST', startErr, true))
  const endErr = validateDate(request.end, '结束日期')
  if (endErr) return Promise.resolve(fail(command, 'INVALID_REQUEST', endErr, true))
  if (request.start > request.end) {
    return Promise.resolve(fail(command, 'INVALID_REQUEST', '开始日期不能晚于结束日期', true))
  }
  const max = request.maxPerSource === undefined ? DEFAULTS.maxPerSource : Number(request.maxPerSource)
  if (!Number.isFinite(max) || max < 1 || max > 200) {
    return Promise.resolve(fail(command, 'INVALID_REQUEST', '每个源的上限必须是 1–200 的整数', true))
  }
  return invoke<TimelineData>(command, {
    mode,
    topic: mode === 'topic' ? String(request.topic).trim() : null,
    entity: mode === 'entity' ? String(request.entity).trim() : null,
    start: request.start.trim(),
    end: request.end.trim(),
    sources: Array.isArray(request.sources) && request.sources.length ? request.sources : null,
    maxPerSource: Math.floor(max),
    outDir: request.outDir || DEFAULTS.outDir,
    pythonPath: request.pythonPath || PYTHON_PATH,
  })
}

export function registryRegister(request: {
  payload: Record<string, unknown>
  at: string
  ledger?: string
  pythonPath?: string
}): Promise<BridgeResult<{ status: string; record: unknown; ledger: string }>> {
  const command = 'registry_register'
  const atErr = validateAt(request.at)
  if (atErr) return Promise.resolve(fail(command, 'INVALID_REQUEST', atErr, true))
  return invoke(command, {
    payload: request.payload,
    at: request.at.trim(),
    ledger: request.ledger || DEFAULTS.ledger,
    pythonPath: request.pythonPath || PYTHON_PATH,
  })
}

export function registryVerify(request: {
  at: string
  id?: string
  ledger?: string
  pythonPath?: string
}): Promise<BridgeResult<VerifyPayload>> {
  const command = 'registry_verify'
  const atErr = validateAt(request.at)
  if (atErr) return Promise.resolve(fail(command, 'INVALID_REQUEST', atErr, true))
  return invoke(command, {
    at: request.at.trim(),
    id: request.id ? request.id.trim() : null,
    ledger: request.ledger || DEFAULTS.ledger,
    pythonPath: request.pythonPath || PYTHON_PATH,
  })
}

export function registryList(request: {
  ledger?: string
  pythonPath?: string
}): Promise<BridgeResult<RegistryRow[]>> {
  return invoke('registry_list', {
    ledger: request.ledger || DEFAULTS.ledger,
    pythonPath: request.pythonPath || PYTHON_PATH,
  })
}

export function registryChainCheck(request: {
  ledger?: string
  pythonPath?: string
}): Promise<BridgeResult<{ ok?: boolean; broken_at?: number | null; total?: number; note?: string }>> {
  return invoke('registry_chain_check', {
    ledger: request.ledger || DEFAULTS.ledger,
    pythonPath: request.pythonPath || PYTHON_PATH,
  })
}

export function registryReconcile(request: {
  ledger?: string
  pythonPath?: string
}): Promise<BridgeResult<Record<string, unknown>>> {
  return invoke('registry_reconcile', {
    ledger: request.ledger || DEFAULTS.ledger,
    pythonPath: request.pythonPath || PYTHON_PATH,
  })
}

export interface ProgressPayload {
  kind: 'line' | 'exit'
  seq?: number
  line?: string
  exitCode?: number
}

export function onTimelineProgress(callback: (payload: ProgressPayload) => void): () => void {
  const evt = tauriEvent()
  if (!evt) return () => {}
  let unlisten: (() => void) | null = null
  let disposed = false
  evt
    .listen('timeline-progress', (event) => {
      const payload = (event?.payload ?? event) as ProgressPayload
      callback(payload)
    })
    .then((fn) => {
      if (disposed) fn()
      else unlisten = fn
    })
    .catch(() => {
      unlisten = null
    })
  return () => {
    disposed = true
    if (unlisten) unlisten()
  }
}

/* ── 时间工具：界面只在显示层换算，任务参数一律显式传 UTC ── */
export function utcNowIso(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')
}

export function utcToday(): string {
  return new Date().toISOString().slice(0, 10)
}

export function shiftDays(dateIso: string, days: number): string {
  const d = new Date(`${dateIso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}
