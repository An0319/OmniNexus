import { Fragment, useState } from 'react'
import { GlassCard, ResultBanner, SectionLabel } from '../components/ds'
import {
  DEFAULTS,
  SOURCE_LABELS,
  onTimelineProgress,
  openExternal,
  runTimeline,
  shiftDays,
  utcToday,
  type BridgeResult,
  type TimelineData,
  type TimelineEvent,
} from '../lib/bridge'
import { classifyTimeline, type TimelineClass } from '../lib/status-map'
import { detectMode, modeLabel, type QueryMode } from '../lib/mode'

interface RunState {
  mode: QueryMode
  query: string
  result: BridgeResult<TimelineData>
}

interface BannerSpec {
  tone: 'warn' | 'neg' | 'info'
  title: string
  tags: string[]
}

export default function Home({
  introSeen,
  onDismissIntro,
}: {
  introSeen: boolean
  onDismissIntro: () => void
}) {
  const [query, setQuery] = useState('')
  const [askMode, setAskMode] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [end, setEnd] = useState(utcToday())
  const [start, setStart] = useState(() => shiftDays(utcToday(), -30))
  const [sources, setSources] = useState<string[]>(DEFAULTS.sources)
  const [maxPerSource, setMaxPerSource] = useState(DEFAULTS.maxPerSource)
  const [running, setRunning] = useState(false)
  const [log, setLog] = useState<{ seq?: number; line: string }[]>([])
  const [run, setRun] = useState<RunState | null>(null)
  const [showDetail, setShowDetail] = useState(false)

  const detected = detectMode(query)
  const cls: TimelineClass | null = run && run.result.ok ? classifyTimeline(run.result.data?.eventsDoc) : null
  const exitCode = run?.result.exitCode ?? null

  function toggleSource(name: string) {
    setSources((prev) => (prev.includes(name) ? prev.filter((s) => s !== name) : [...prev, name]))
  }

  async function startRun(mode: QueryMode) {
    const text = query.trim()
    if (!text || running) return
    setAskMode(false)
    setRunning(true)
    setLog([])
    setRun(null)
    setShowDetail(false)

    const unsubscribe = onTimelineProgress((payload) => {
      if (payload.kind === 'line' && typeof payload.line === 'string') {
        const line = payload.line
        setLog((prev) => [...prev.slice(-80), { seq: payload.seq, line }])
      }
    })

    try {
      const result = await runTimeline({
        mode,
        topic: mode === 'topic' ? text : null,
        entity: mode === 'entity' ? text : null,
        start,
        end,
        sources,
        maxPerSource,
      })
      setRun({ mode, query: text, result })
    } finally {
      unsubscribe()
      setRunning(false)
    }
  }

  function submit() {
    if (!query.trim() || running) return
    const mode = detectMode(query)
    if (!mode) {
      setAskMode(true)
      return
    }
    void startRun(mode)
  }

  const banner = run && run.result.ok ? buildBanner(cls, exitCode) : null

  const resultMeta = cls
    ? [
        run ? modeLabel(run.mode) : null,
        cls.windowStart && cls.windowEnd ? `${cls.windowStart} → ${cls.windowEnd}` : null,
        cls.requested.length ? `${cls.requested.length} 个消息源` : null,
      ]
        .filter(Boolean)
        .join(' · ')
    : ''

  return (
    <>
      <SectionLabel index="01" title="看什么" />

      <div className="mnx-page-head">
        <h1 className="mnx-page-title">你想看什么？</h1>
        <p className="mnx-page-lede">
          输入一个话题，或一家公司 / 一只代号。系统会去公开消息源里抓事件，抽成按时间排好的线索；抓不到、抓不全、判不了，都会明说。
        </p>
      </div>

      {!introSeen && (
        <GlassCard accent style={{ marginBottom: 32 }}>
          <div className="mnx-intro-copy">
            <p>
              <strong>先说清楚它能干什么：</strong>把公开消息源里的事件抓下来，抽成可核对的线索，按时间排给你看。
            </p>
            <p>
              <strong>关机期间不会核验，开机补算。</strong>到期项会在你打开它的时候补核一次，没有后台常驻进程。
            </p>
            <p>
              <strong>只筛线索，不替你下结论。</strong>判不了时会明说判不了，并说清是缺数据、源不可达，还是到期没对上。
            </p>
          </div>
          <div className="mnx-intro-foot">
            <span>这两句也常驻页脚，随时能看到。</span>
            <button type="button" className="mnx-btn" onClick={onDismissIntro}>
              知道了
            </button>
          </div>
        </GlassCard>
      )}

      <GlassCard accent>
        <label className="mnx-ask-label" htmlFor="mnx-ask">
          看什么
        </label>
        <input
          id="mnx-ask"
          className="mnx-ask-input"
          value={query}
          placeholder="一个话题，或一家公司 / 一只代号"
          autoComplete="off"
          spellCheck={false}
          onChange={(e) => {
            setQuery(e.target.value)
            setAskMode(false)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              submit()
            }
          }}
        />

        <div className="mnx-examples">
          <span>试试</span>
          {[
            { text: '固态电池', hint: '话题' },
            { text: '宁德时代', hint: '公司' },
            { text: 'XBI', hint: '代号' },
          ].map((item) => (
            <button
              key={item.text}
              type="button"
              className="mnx-example"
              title={`示例：${item.hint}`}
              onClick={() => {
                setQuery(item.text)
                setAskMode(false)
              }}
            >
              {item.text}
            </button>
          ))}
        </div>

        <div className="mnx-ask-row">
          <button type="button" className="mnx-btn is-primary" onClick={submit} disabled={running || !query.trim()}>
            {running ? '正在找…' : '开始找'}
          </button>
          <span className="mnx-ask-hint">
            {askMode
              ? '需要确认一下：这是话题，还是某家公司？'
              : detected
                ? `会按「${modeLabel(detected)}」去查 · 按回车也可以`
                : '填好之后按回车'}
          </span>
        </div>

        {askMode && (
          <div className="mnx-ask-row" role="group" aria-label="确认查询类型">
            <span className="mnx-ask-hint">「{query.trim()}」两种都说得通：</span>
            <button type="button" className="mnx-btn" onClick={() => void startRun('topic')}>
              是一个话题
            </button>
            <button type="button" className="mnx-btn" onClick={() => void startRun('entity')}>
              是一家公司 / 一只代号
            </button>
          </div>
        )}

        {running && (
          <div className="mnx-ask-row">
            <div className="mnx-progress-line">
              <i />
              <span>{log.length ? log[log.length - 1].line : '正在启动抓取进程…'}</span>
            </div>
          </div>
        )}

        <details
          className="mnx-disclosure"
          open={settingsOpen}
          onToggle={(e) => setSettingsOpen((e.currentTarget as HTMLDetailsElement).open)}
        >
          <summary>更多设置（时间范围、消息源、每源上限）</summary>
          <div className="mnx-disclosure-body">
            <div className="mnx-grid">
              <div className="mnx-field">
                <label htmlFor="mnx-start">开始日期</label>
                <input id="mnx-start" value={start} onChange={(e) => setStart(e.target.value)} placeholder="YYYY-MM-DD" />
              </div>
              <div className="mnx-field">
                <label htmlFor="mnx-end">结束日期</label>
                <input id="mnx-end" value={end} onChange={(e) => setEnd(e.target.value)} placeholder="YYYY-MM-DD" />
              </div>
              <div className="mnx-field">
                <label htmlFor="mnx-max">每源上限</label>
                <input
                  id="mnx-max"
                  type="number"
                  min={1}
                  max={200}
                  value={maxPerSource}
                  onChange={(e) => setMaxPerSource(Number(e.target.value))}
                />
              </div>
              <div className="mnx-field is-full">
                <label>消息源</label>
                <div className="mnx-examples" style={{ marginTop: 0 }}>
                  {DEFAULTS.sources.map((name) => {
                    const on = sources.includes(name)
                    return (
                      <button
                        key={name}
                        type="button"
                        className="mnx-example"
                        aria-pressed={on}
                        onClick={() => toggleSource(name)}
                        style={
                          on
                            ? {
                                color: 'var(--accent)',
                                borderColor: 'var(--border-accent)',
                                background: 'var(--accent-dim)',
                              }
                            : undefined
                        }
                      >
                        {on ? '✓ ' : '＋ '}
                        {SOURCE_LABELS[name] ?? name}
                      </button>
                    )
                  })}
                </div>
                <div className="mnx-field-help">至少留一个源；参数会显式传给抓取脚本，壳不替它决定默认值。</div>
              </div>
            </div>
          </div>
        </details>
      </GlassCard>

      {run && (
        <div className="mnx-section-gap-lg">
          <SectionLabel index="02" title="结果" />

          {run.result.ok ? (
            <>
              {banner && (
                <div style={{ marginBottom: 16 }}>
                  <ResultBanner
                    tone={banner.tone}
                    title={banner.title}
                    tags={banner.tags}
                    actionLabel={showDetail ? '收起详情' : '看详情'}
                    onAction={() => setShowDetail((v) => !v)}
                  />
                </div>
              )}
              <GlassCard>
                <div className="mnx-result-head">
                  <div>
                    <div className="mnx-result-title">「{run.query}」</div>
                    <div className="mnx-result-meta">{resultMeta}</div>
                  </div>
                  {cls && <div className="mnx-result-meta">{cls.coverageText}</div>}
                </div>

                {cls && <ResultBody cls={cls} exitCode={exitCode} />}

                <details className="mnx-disclosure" open={showDetail}>
                  <summary>详情（技术信息）</summary>
                  <div className="mnx-disclosure-body">
                    <DetailBlock run={run} cls={cls} exitCode={exitCode} log={log} />
                  </div>
                </details>
              </GlassCard>
            </>
          ) : (
            <>
              <ResultBanner
                tone="neg"
                title={run.result.message ?? '桌面壳没有返回结果，这次什么都没拿到。'}
                tags={run.result.code ? [run.result.code] : []}
              />
              <GlassCard style={{ marginTop: 16 }}>
                <DetailBlock run={run} cls={null} exitCode={exitCode} log={log} />
              </GlassCard>
            </>
          )}
        </div>
      )}
    </>
  )
}

/* ── 结果正文：只在这里决定「什么能读、什么不能读」 ─────────── */
function ResultBody({ cls, exitCode }: { cls: TimelineClass; exitCode: number | null }) {
  if (cls.blocked || (exitCode !== null && exitCode !== 0)) {
    return (
      <div className="mnx-neutral-note">
        <i>×</i>
        <span>
          这次的内容不当结果展示。抓取进程退出码 {exitCode === null ? '未知' : exitCode}
          ；技术原因在下面的详情里，不做推测。
        </span>
      </div>
    )
  }

  if (cls.tier === 'ok') {
    return (
      <>
        <div className="mnx-neutral-note">
          <i>✓</i>
          <span>
            共 {cls.events.length} 条线索 · 原始 {cls.stats.raw} 条 · 合并重复 {cls.stats.merged} 条
            {cls.stats.rejects > 0 ? ` · 未采用 ${cls.stats.rejects} 条` : ''}
          </span>
        </div>
        <div className="mnx-events">
          {cls.events.map((ev) => (
            <EventRow key={ev.event_id} event={ev} />
          ))}
        </div>
      </>
    )
  }

  if (cls.tier === 'empty' || cls.tier === 'entity-zero') {
    return (
      <div className="mnx-neutral-note">
        <i>∅</i>
        <span>
          {cls.tier === 'entity-zero'
            ? '消息源都查过了，但没抓到可判定的条目；这不等于「这家公司没有事件」。'
            : '消息源都查过了，确实没有匹配的线索——不是抓取失败。'}
        </span>
      </div>
    )
  }

  if (cls.tier === 'unjudged') {
    return (
      <div className="mnx-neutral-note">
        <i>≈</i>
        <span>
          抓到了 {cls.stats.raw} 条原始条目，但没有一条能抽成线索（未采用 {cls.stats.rejects} 条）；原因在详情里，不能读成「没发生」。
        </span>
      </div>
    )
  }

  return null
}

function EventRow({ event }: { event: TimelineEvent }) {
  const [openError, setOpenError] = useState<string | null>(null)
  const value = event.value
  const valueText =
    value && value.kind === 'number' && typeof value.number === 'number'
      ? `${value.number}${value.unit ?? ''}`
      : value && value.raw
        ? value.raw
        : null

  /* 人工复核的入口：链接一律交给系统浏览器，失败就把原因写在这一条下面。 */
  async function openSource(e: { preventDefault: () => void }) {
    e.preventDefault()
    if (!event.source_url) return
    setOpenError(null)
    const error = await openExternal(event.source_url)
    if (error) setOpenError(error)
  }

  return (
    <div className="mnx-event">
      <div className="mnx-event-date">{event.time}</div>
      <div>
        <div className="mnx-event-title">
          {event.source_url ? (
            <a
              href={event.source_url}
              onClick={openSource}
              onAuxClick={openSource}
              title="在系统浏览器里打开原文"
            >
              {event.subject}
            </a>
          ) : (
            event.subject
          )}
        </div>
        <div className="mnx-event-line">
          {event.excerpt || event.action_text || event.object || '（源未提供摘要）'}
        </div>
        <div className="mnx-event-tags">
          {event.action_text && <span className="mnx-tag">{event.action_text}</span>}
          {valueText && <span className="mnx-tag is-value">{valueText}</span>}
          {event.source_name && <span className="mnx-tag">{event.source_name}</span>}
        </div>
        {openError && <div className="mnx-link-error">打不开原文：{openError}</div>}
      </div>
    </div>
  )
}

/* ── 详情：排障用，默认合上 ──────────────────────────────────── */
function DetailBlock({
  run,
  cls,
  exitCode,
  log,
}: {
  run: RunState
  cls: TimelineClass | null
  exitCode: number | null
  log: { seq?: number; line: string }[]
}) {
  const shownLog = log.filter((item) => item.line.trim()).slice(-40)
  return (
    <>
      <dl className="mnx-details-grid">
        <dt>命令</dt>
        <dd>{run.result.command}</dd>
        <dt>退出码</dt>
        <dd>{exitCode === null ? '（无）' : exitCode}</dd>
        <dt>status</dt>
        <dd>{cls?.statusRaw ?? '（产物没有 status 字段）'}</dd>
        <dt>档位</dt>
        <dd>{cls ? `${cls.tier} · ${cls.tierMeta.label}` : '（未判定）'}</dd>
        <dt>覆盖</dt>
        <dd>{cls?.coverageText ?? '—'}</dd>
        <dt>产物</dt>
        <dd>{run.result.ok ? run.result.data?.eventsJson ?? '（未回传路径）' : '（本次没有产物）'}</dd>
        {run.result.code && (
          <>
            <dt>桥错误码</dt>
            <dd>{run.result.code}</dd>
          </>
        )}
        {run.result.message && (
          <>
            <dt>桥消息</dt>
            <dd>{run.result.message}</dd>
          </>
        )}
      </dl>

      {cls && cls.requested.length > 0 && (
        <>
          <div className="mnx-details-note">逐源 fetched / accepted / rejected / error（原样展示）</div>
          <dl className="mnx-details-grid">
            {cls.requested.map((name) => {
              const s = cls.sourcesStats[name]
              const text = s
                ? `fetched ${s.fetched ?? 0} · accepted ${s.accepted ?? 0} · rejected ${s.rejected ?? 0}` +
                  (s.error ? ` · error: ${s.error}` : '')
                : '（产物里没有这个源的统计）'
              return (
                <Fragment key={name}>
                  <dt>{name}</dt>
                  <dd>{text}</dd>
                </Fragment>
              )
            })}
          </dl>
        </>
      )}

      {cls && cls.notes.length > 0 && (
        <>
          <div className="mnx-details-note">判定备注</div>
          <dl className="mnx-details-grid">
            {cls.notes.map((note, index) => (
              <Fragment key={`${index}-${note.slice(0, 12)}`}>
                <dt>note</dt>
                <dd>{note}</dd>
              </Fragment>
            ))}
          </dl>
        </>
      )}

      {cls && Object.keys(cls.rejectReasons).length > 0 && (
        <>
          <div className="mnx-details-note">未采用原因（reason code 原样）</div>
          <dl className="mnx-details-grid">
            {Object.entries(cls.rejectReasons).map(([code, count]) => (
              <Fragment key={code}>
                <dt>{code}</dt>
                <dd>{count} 条</dd>
              </Fragment>
            ))}
          </dl>
        </>
      )}

      {run.result.stderr.trim() && (
        <>
          <div className="mnx-details-note">stderr</div>
          <div className="mnx-log">{run.result.stderr.trim()}</div>
        </>
      )}

      {shownLog.length > 0 && (
        <>
          <div className="mnx-details-note">进度输出（最后 {shownLog.length} 行）</div>
          <div className="mnx-log">
            {shownLog
              .map((item) => `${item.seq !== undefined ? `#${item.seq} ` : ''}${item.line}`)
              .join('\n')}
          </div>
        </>
      )}
    </>
  )
}

/* ── 横幅：三档失败各自独立，不合并成一句 ───────────────────── */
function buildBanner(cls: TimelineClass | null, exitCode: number | null): BannerSpec | null {
  if (exitCode !== null && exitCode !== 0 && (!cls || !cls.blocked)) {
    return {
      tone: 'neg',
      title: `抓取没有跑完（退出码 ${exitCode}），这份内容不能当结果读`,
      tags: cls ? [cls.coverageText] : [],
    }
  }

  if (!cls) return null

  if (cls.tier === 'partial') {
    return {
      tone: 'warn',
      title: `只拿到 ${cls.coveredCount}/${cls.requested.length} 个消息源，这份结果不完整`,
      tags: cls.failedSources.map((name) => `${SOURCE_LABELS[name] ?? name} · 失败`),
    }
  }

  if (cls.tier === 'failed') {
    return {
      tone: 'neg',
      title: `这次没拿到结果：${cls.requested.length} 个消息源全部失败`,
      tags: cls.failedSources.map((name) => `${SOURCE_LABELS[name] ?? name} · 失败`),
    }
  }

  if (cls.tier === 'unknown') {
    return { tone: 'neg', title: '这份产物缺 status 字段（旧产物），不能当结果读', tags: cls.notes.slice(0, 2) }
  }

  if (cls.tier === 'unjudged') {
    return { tone: 'info', title: '抓到了条目，但没有一条能当线索', tags: [`未采用 ${cls.stats.rejects} 条`] }
  }

  return null
}
