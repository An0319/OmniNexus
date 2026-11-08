import { Fragment, useState } from 'react'
import { GlassCard, ResultBanner, SectionLabel } from '../components/ds'
import { strings } from '../i18n'
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
        cls.requested.length ? strings.result.sourceCount(cls.requested.length) : null,
      ]
        .filter(Boolean)
        .join(' · ')
    : ''

  return (
    <>
      <SectionLabel index="01" title={strings.home.sectionTitle} />

      <div className="mnx-page-head">
        <h1 className="mnx-page-title">{strings.home.title}</h1>
        <p className="mnx-page-lede">{strings.home.lede}</p>
      </div>

      {!introSeen && (
        <GlassCard accent style={{ marginBottom: 32 }}>
          <div className="mnx-intro-copy">
            <p>
              <strong>{strings.home.intro.abilityTitle}</strong>
              {strings.home.intro.abilityBody}
            </p>
            <p>
              <strong>{strings.home.intro.offlineTitle}</strong>
              {strings.home.intro.offlineBody}
            </p>
            <p>
              <strong>{strings.home.intro.scopeTitle}</strong>
              {strings.home.intro.scopeBody}
            </p>
          </div>
          <div className="mnx-intro-foot">
            <span>{strings.home.intro.footerNote}</span>
            <button type="button" className="mnx-btn" onClick={onDismissIntro}>
              {strings.home.intro.dismiss}
            </button>
          </div>
        </GlassCard>
      )}

      <GlassCard accent>
        <label className="mnx-ask-label" htmlFor="mnx-ask">
          {strings.home.askLabel}
        </label>
        <input
          id="mnx-ask"
          className="mnx-ask-input"
          value={query}
          placeholder={strings.home.placeholder}
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
          <span>{strings.home.exampleLabel}</span>
          {strings.home.examples.map((item) => (
            <button
              key={item.text}
              type="button"
              className="mnx-example"
              title={strings.home.exampleTitle(item.hint)}
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
            {running ? strings.home.starting : strings.home.start}
          </button>
          <span className="mnx-ask-hint">
            {askMode
              ? strings.home.confirmAsk
              : detected
                ? strings.home.willQuery(modeLabel(detected))
                : strings.home.enterHint}
          </span>
        </div>

        {askMode && (
          <div className="mnx-ask-row" role="group" aria-label={strings.home.confirmGroupLabel}>
            <span className="mnx-ask-hint">{strings.home.bothWork(query.trim())}</span>
            <button type="button" className="mnx-btn" onClick={() => void startRun('topic')}>
              {strings.home.isTopic}
            </button>
            <button type="button" className="mnx-btn" onClick={() => void startRun('entity')}>
              {strings.home.isEntity}
            </button>
          </div>
        )}

        {running && (
          <div className="mnx-ask-row">
            <div className="mnx-progress-line">
              <i />
              <span>{log.length ? log[log.length - 1].line : strings.home.startingCrawl}</span>
            </div>
          </div>
        )}

        <details
          className="mnx-disclosure"
          open={settingsOpen}
          onToggle={(e) => setSettingsOpen((e.currentTarget as HTMLDetailsElement).open)}
        >
          <summary>{strings.home.settings.summary}</summary>
          <div className="mnx-disclosure-body">
            <div className="mnx-grid">
              <div className="mnx-field">
                <label htmlFor="mnx-start">{strings.common.startDate}</label>
                <input id="mnx-start" value={start} onChange={(e) => setStart(e.target.value)} placeholder="YYYY-MM-DD" />
              </div>
              <div className="mnx-field">
                <label htmlFor="mnx-end">{strings.common.endDate}</label>
                <input id="mnx-end" value={end} onChange={(e) => setEnd(e.target.value)} placeholder="YYYY-MM-DD" />
              </div>
              <div className="mnx-field">
                <label htmlFor="mnx-max">{strings.home.settings.maxPerSource}</label>
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
                <label>{strings.home.settings.sources}</label>
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
                <div className="mnx-field-help">{strings.home.settings.sourceHelp}</div>
              </div>
            </div>
          </div>
        </details>
      </GlassCard>

      {run && (
        <div className="mnx-section-gap-lg">
          <SectionLabel index="02" title={strings.result.sectionTitle} />

          {run.result.ok ? (
            <>
              {banner && (
                <div style={{ marginBottom: 16 }}>
                  <ResultBanner
                    tone={banner.tone}
                    title={banner.title}
                    tags={banner.tags}
                    actionLabel={
                      showDetail ? strings.result.actionHideDetail : strings.common.actionShowDetail
                    }
                    onAction={() => setShowDetail((v) => !v)}
                  />
                </div>
              )}
              <GlassCard>
                <div className="mnx-result-head">
                  <div>
                    <div className="mnx-result-title">{strings.result.quoted(run.query)}</div>
                    <div className="mnx-result-meta">{resultMeta}</div>
                  </div>
                  {cls && <div className="mnx-result-meta">{cls.coverageText}</div>}
                </div>

                {cls && <ResultBody cls={cls} exitCode={exitCode} />}

                <details className="mnx-disclosure" open={showDetail}>
                  <summary>{strings.result.detailSummary}</summary>
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
                title={run.result.message ?? strings.result.failedToRun}
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
        <span>{strings.result.blocked(exitCode === null ? strings.common.unknown : exitCode)}</span>
      </div>
    )
  }

  if (cls.tier === 'ok') {
    return (
      <>
        <div className="mnx-neutral-note">
          <i>✓</i>
          <span>
            {strings.result.counts({
              events: cls.events.length,
              raw: cls.stats.raw,
              merged: cls.stats.merged,
              rejects: cls.stats.rejects,
            })}
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
        <span>{cls.tier === 'entity-zero' ? strings.result.emptyEntity : strings.result.emptyTopic}</span>
      </div>
    )
  }

  if (cls.tier === 'unjudged') {
    return (
      <div className="mnx-neutral-note">
        <i>≈</i>
        <span>{strings.result.unjudged(cls.stats.raw, cls.stats.rejects)}</span>
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
              title={strings.result.openSourceTitle}
            >
              {event.subject}
            </a>
          ) : (
            event.subject
          )}
        </div>
        <div className="mnx-event-line">
          {event.excerpt || event.action_text || event.object || strings.common.noExcerpt}
        </div>
        <div className="mnx-event-tags">
          {event.action_text && <span className="mnx-tag">{event.action_text}</span>}
          {valueText && <span className="mnx-tag is-value">{valueText}</span>}
          {event.source_name && <span className="mnx-tag">{event.source_name}</span>}
        </div>
        {openError && <div className="mnx-link-error">{strings.result.openFailed(openError)}</div>}
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
        <dt>{strings.common.dt.command}</dt>
        <dd>{run.result.command}</dd>
        <dt>{strings.common.dt.exitCode}</dt>
        <dd>{exitCode === null ? strings.common.none : exitCode}</dd>
        <dt>status</dt>
        <dd>{cls?.statusRaw ?? strings.detail.noStatusField}</dd>
        <dt>{strings.detail.tier}</dt>
        <dd>{cls ? `${cls.tier} · ${cls.tierMeta.label}` : strings.detail.notJudged}</dd>
        <dt>{strings.detail.coverage}</dt>
        <dd>{cls?.coverageText ?? '—'}</dd>
        <dt>{strings.detail.artifact}</dt>
        <dd>{run.result.ok ? run.result.data?.eventsJson ?? strings.detail.noPath : strings.detail.noArtifact}</dd>
        {run.result.code && (
          <>
            <dt>{strings.common.dt.bridgeCode}</dt>
            <dd>{run.result.code}</dd>
          </>
        )}
        {run.result.message && (
          <>
            <dt>{strings.detail.bridgeMessage}</dt>
            <dd>{run.result.message}</dd>
          </>
        )}
      </dl>

      {cls && cls.requested.length > 0 && (
        <>
          <div className="mnx-details-note">{strings.detail.sourcesNote}</div>
          <dl className="mnx-details-grid">
            {cls.requested.map((name) => {
              const s = cls.sourcesStats[name]
              const text = s
                ? `fetched ${s.fetched ?? 0} · accepted ${s.accepted ?? 0} · rejected ${s.rejected ?? 0}` +
                  (s.error ? ` · error: ${s.error}` : '')
                : strings.detail.sourceMissing
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
          <div className="mnx-details-note">{strings.detail.notesTitle}</div>
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
          <div className="mnx-details-note">{strings.detail.rejectTitle}</div>
          <dl className="mnx-details-grid">
            {Object.entries(cls.rejectReasons).map(([code, count]) => (
              <Fragment key={code}>
                <dt>{code}</dt>
                <dd>{strings.common.itemCount(count)}</dd>
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
          <div className="mnx-details-note">{strings.detail.progressTitle(shownLog.length)}</div>
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
      title: strings.result.banner.exit(exitCode),
      tags: cls ? [cls.coverageText] : [],
    }
  }

  if (!cls) return null

  if (cls.tier === 'partial') {
    return {
      tone: 'warn',
      title: strings.result.banner.partial(cls.coveredCount, cls.requested.length),
      tags: cls.failedSources.map((name) => strings.result.banner.failedTag(SOURCE_LABELS[name] ?? name)),
    }
  }

  if (cls.tier === 'failed') {
    return {
      tone: 'neg',
      title: strings.result.banner.failed(cls.requested.length),
      tags: cls.failedSources.map((name) => strings.result.banner.failedTag(SOURCE_LABELS[name] ?? name)),
    }
  }

  if (cls.tier === 'unknown') {
    return { tone: 'neg', title: strings.result.banner.missingStatus, tags: cls.notes.slice(0, 2) }
  }

  if (cls.tier === 'unjudged') {
    return {
      tone: 'info',
      title: strings.result.banner.unjudged,
      tags: [strings.result.banner.rejectsTag(cls.stats.rejects)],
    }
  }

  return null
}
