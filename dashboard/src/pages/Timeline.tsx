/**
 * 判定与修订时间线页（清单 §2.3）：公开审计页。
 * C8 时间线条目三类：尝试 / 修订 / 运维事件。
 * 运行账本（append-only 指纹留痕）单独成块，不混入时间线三类。
 */

import { budgetRuns, buildTimeline, runLedgers } from '../data'
import { fmtUtc } from '../format'
import type { TimelineEvent, TimelineKind } from '../types'

const KIND_META: Record<TimelineKind, { label: string; dot: string }> = {
  attempt: { label: '尝试 ATTEMPT', dot: 'is-attempt' },
  revision: { label: '修订 REVISION', dot: 'is-revision' },
  reset: { label: '运维事件 RESET', dot: 'is-reset' },
}

function TimelineRow({ event }: { event: TimelineEvent }) {
  const meta = KIND_META[event.kind]
  return (
    <div className="revision-entry">
      <div className="revision-connector-col">
        <div className={`revision-dot ${meta.dot}`} />
        <div className="revision-line" />
      </div>
      <div className="revision-body">
        <div className="revision-meta">
          <span className="revision-ts">{event.date}</span>
          <span className={`tl-tag tl-tag--${event.kind}`}>{meta.label}</span>
          {event.chainId && <span className="revision-author">{event.chainId}</span>}
          {event.countsAsAttempt && <span className="tl-tag tl-tag--budget">计入预算</span>}
        </div>
        <div className="revision-change">
          <span className="revision-change-key">{event.title}</span>
        </div>
        <div className="revision-reason">{event.body}</div>
      </div>
    </div>
  )
}

function RunLedger() {
  const chains = Object.keys(runLedgers)
  return (
    <div className="ledger-block">
      <table className="ledger-table">
        <thead>
          <tr>
            <th scope="col">链</th>
            <th scope="col">最近登记（UTC）</th>
            <th scope="col">指纹（前 12）</th>
            <th scope="col">实质指纹（前 12）</th>
            <th scope="col">预算已用</th>
            <th scope="col">修订已见</th>
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
      <p className="chart-caption">
        运行账本是 append-only 事件流：预算账本每次写入都留一条（含时间与序号），账户外操作在物理上不存在。
      </p>
    </div>
  )
}

export function Timeline() {
  const events = buildTimeline()

  return (
    <>
      <section className="lede">
        <h1>公开审计：尝试、修订与运维事件</h1>
        <p>
          预注册的全部动作按 UTC 日期倒序留痕。三类事件各有独立形制——<strong>修订会标注是否消耗尝试预算</strong>
          ，运维事件（如主动重置）与故障分开陈述：重置是运维事件，不是事故。
        </p>
      </section>

      <section aria-labelledby="c8-title">
        <h2 className="section-title" id="c8-title">
          C8 · 时间线 · 共 {events.length} 条
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
          运行账本 · 指纹留痕
        </h2>
        <div className="detail-card">
          <RunLedger />
        </div>
      </section>
    </>
  )
}
