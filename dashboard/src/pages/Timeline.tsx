/**
 * 判定与修订时间线页（清单 §2.3）：公开审计页。
 * C8 时间线条目三类：尝试 / 修订 / 运维事件。
 * 运行账本（append-only 指纹留痕）单独成块，不混入时间线三类。
 */

import { budgetRuns, buildTimeline, runLedgers } from '../data'
import { fmtUtc } from '../format'
import { useI18n } from '../i18n/I18nProvider'
import type { MessageKey } from '../i18n/messages.zh'
import type { TimelineEvent, TimelineKind } from '../types'

const KIND_META: Record<TimelineKind, { labelKey: MessageKey; dot: string }> = {
  attempt: { labelKey: 'timeline.kind.attempt', dot: 'is-attempt' },
  revision: { labelKey: 'timeline.kind.revision', dot: 'is-revision' },
  reset: { labelKey: 'timeline.kind.reset', dot: 'is-reset' },
}

function TimelineRow({ event }: { event: TimelineEvent }) {
  const { t } = useI18n()
  const meta = KIND_META[event.kind]
  const title =
    event.kind === 'attempt'
      ? `${t('timeline.attemptTitle', { n: event.attemptNo ?? '' })} · ${event.title ?? ''}`
      : event.kind === 'revision'
        ? t('timeline.revisionTitle', { chainId: event.chainId ?? '' })
        : t('timeline.resetTitle')
  return (
    <div className="revision-entry">
      <div className="revision-connector-col">
        <div className={`revision-dot ${meta.dot}`} />
        <div className="revision-line" />
      </div>
      <div className="revision-body">
        <div className="revision-meta">
          <span className="revision-ts">{event.date}</span>
          <span className={`tl-tag tl-tag--${event.kind}`}>{t(meta.labelKey)}</span>
          {event.chainId && <span className="revision-author">{event.chainId}</span>}
          {event.countsAsAttempt && (
            <span className="tl-tag tl-tag--budget">{t('timeline.countsBudget')}</span>
          )}
        </div>
        <div className="revision-change">
          <span className="revision-change-key">{title}</span>
        </div>
        <div className="revision-reason">{event.body}</div>
      </div>
    </div>
  )
}

function RunLedger() {
  const { t } = useI18n()
  const chains = Object.keys(runLedgers)
  return (
    <div className="ledger-block">
      <table className="ledger-table">
        <thead>
          <tr>
            <th scope="col">{t('timeline.ledger.chain')}</th>
            <th scope="col">{t('timeline.ledger.lastRegistered')}</th>
            <th scope="col">{t('timeline.ledger.fingerprint')}</th>
            <th scope="col">{t('timeline.ledger.substantive')}</th>
            <th scope="col">{t('timeline.ledger.budgetUsed')}</th>
            <th scope="col">{t('timeline.ledger.revisionsSeen')}</th>
          </tr>
        </thead>
        <tbody>
          {chains.map((chainId) => {
            const events = runLedgers[chainId]
            const last = events[events.length - 1]
            return (
              <tr key={chainId}>
                <td className="mono-cell">{chainId}</td>
                <td className="mono-cell">{fmtUtc(last?.last_run ?? last?.at)}</td>
                <td className="mono-cell">{last?.fingerprint ? last.fingerprint.slice(0, 12) : '—'}</td>
                <td className="mono-cell">
                  {last?.substantive_fingerprint ? last.substantive_fingerprint.slice(0, 12) : '—'}
                </td>
                <td className="mono-cell">{last?.budget_used ?? '—'}</td>
                <td className="mono-cell">{last?.revisions_seen ?? '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <ul className="ledger-events">
        {budgetRuns.map((event, index) => (
          <li key={index}>
            <span className="ledger-ts">{event.at}</span>
            <span className="ledger-kind">{event.event}</span>
            <span className="ledger-note">
              {event.entry
                ? `#${event.entry.n} · ${event.entry.chain_id} · ${event.entry.date}`
                : (event.note ?? '')}
            </span>
          </li>
        ))}
      </ul>
      <p className="chart-caption">{t('timeline.ledger.caption')}</p>
    </div>
  )
}

export function Timeline() {
  const { t } = useI18n()
  const events = buildTimeline()

  return (
    <>
      <section className="lede">
        <h1>{t('timeline.lede.title')}</h1>
        <p>
          {t('timeline.lede.prefix')}
          <strong>{t('timeline.lede.strong')}</strong>
          {t('timeline.lede.tail')}
        </p>
      </section>

      <section aria-labelledby="c8-title">
        <h2 className="section-title" id="c8-title">
          {t('timeline.title', { count: events.length })}
        </h2>
        <div className="detail-card">
          <div className="revision-timeline">
            {events.map((event) => (
              <TimelineRow key={event.id} event={event} />
            ))}
          </div>
        </div>
      </section>

      <section aria-labelledby="ledger-title">
        <h2 className="section-title" id="ledger-title">
          {t('timeline.ledger.title')}
        </h2>
        <div className="detail-card">
          <RunLedger />
        </div>
      </section>
    </>
  )
}
