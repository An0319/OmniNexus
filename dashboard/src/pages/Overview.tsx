/** 总览页（清单 §2.1）：一眼看全局——T1 计时条 / 链状态卡 / 预算条。 */

import { useMemo } from 'react'
import { VerdictBadge } from '../components/SignalBadge'
import { budget, buildChainViews, streak } from '../data'
import { fmtCorr, fmtDate, fmtFixed3, fmtLag, fmtUtc } from '../format'
import { useI18n } from '../i18n/I18nProvider'
import type { MessageKey } from '../i18n/messages.zh'
import { isRunUnfinished, useRunState } from '../useRunState'
import type { ChainView } from '../types'

const QUALITY_LABEL_KEY: Record<ChainView['quality'], MessageKey> = {
  green: 'overview.quality.green',
  yellow: 'overview.quality.yellow',
  red: 'overview.quality.red',
  gray: 'overview.quality.gray',
}

function T1Timer() {
  const { t } = useI18n()
  const {
    current_streak,
    target_days,
    started_utc_date,
    last_success_utc_date,
    last_run_utc,
    days,
    breaks,
    resets,
    rule,
  } = streak

  const complete = current_streak >= target_days
  const phase = complete ? 'is-complete' : current_streak === 0 ? 'is-reset' : ''
  const latest = days[days.length - 1]

  return (
    <section aria-labelledby="t1-title">
      <h2 className="section-title" id="t1-title">
        {t('overview.t1.title')}
      </h2>
      <div className="t1-card">
        <div className="t1-head">
          <span className="t1-count">
            {current_streak}/{target_days}
          </span>
          <span className={complete || current_streak === 0 ? 'badge-notpassed' : 'badge-running'}>
            <span className="badge-state-icon" aria-hidden="true">
              {complete ? '✓' : '●'}
            </span>
            {complete
              ? t('overview.t1.complete')
              : current_streak === 0
                ? t('overview.t1.reset')
                : t('overview.t1.running')}
          </span>
        </div>

        <div className={`t1-progress ${phase}`} role="presentation">
          <span style={{ width: `${Math.min(100, (current_streak / target_days) * 100)}%` }} />
        </div>

        <p className="t1-rule">{rule}</p>

        <dl className="t1-grid">
          <div className="field">
            <dt>{t('overview.t1.startDate')}</dt>
            <dd>{fmtDate(started_utc_date)}</dd>
          </div>
          <div className="field">
            <dt>{t('overview.t1.lastSuccess')}</dt>
            <dd>{fmtDate(last_success_utc_date)}</dd>
          </div>
          <div className="field">
            <dt>{t('overview.t1.lastRun')}</dt>
            <dd>{fmtUtc(last_run_utc)}</dd>
          </div>
          <div className="field">
            <dt>{t('overview.t1.recentDay')}</dt>
            <dd>
              {latest
                ? t('overview.t1.latest', {
                    date: latest.utc_date,
                    runs: latest.runs,
                    status: latest.status,
                  })
                : '—'}
            </dd>
          </div>
          <div className="field">
            <dt>{t('overview.t1.breaks')}</dt>
            <dd className={breaks.length ? '' : 'is-missing'}>
              {breaks.length ? breaks.map((b) => b.utc_date).join('、') : t('overview.t1.none')}
            </dd>
          </div>
          <div className="field">
            <dt>{t('overview.t1.resets')}</dt>
            <dd>{t('overview.t1.resetCount', { count: resets.length })}</dd>
          </div>
        </dl>

        {resets.length > 0 && (
          <ul className="t1-history">
            {resets.map((reset) => (
              <li key={`${reset.utc_date}-${reset.archive}`}>
                <span className="t1-history-date">{reset.utc_date}</span>
                <span className="t1-history-tag">{t('overview.t1.opsTag')}</span>
                {reset.reason}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}

function ChainStatusCard({
  view,
  runUnfinished,
  runStartedUtc,
  onOpen,
}: {
  view: ChainView
  runUnfinished: boolean
  runStartedUtc: string | null
  onOpen: (chainId: string) => void
}) {
  const { t } = useI18n()
  return (
    <article
      className="chain-card hover-glow-card"
      tabIndex={0}
      role="link"
      aria-label={t('overview.chain.openAria', { title: view.title })}
      onClick={() => onOpen(view.chainId)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onOpen(view.chainId)
        }
      }}
    >
      <div className="chain-card-top">
        <VerdictBadge verdict={view.verdict} />
        {view.forwardLook && (
          <span className="badge-forward">
            <span className="badge-state-icon" aria-hidden="true">
              k{view.forwardLook.k}
            </span>
            {t('overview.chain.forward')}
          </span>
        )}
      </div>

      <div className="chain-title">{view.title}</div>

      <div className="chain-facts">
        <div className="field">
          <dt>{t('overview.chain.samples')}</dt>
          <dd>
            {view.samples.total_weeks} / {view.samples.effective_weeks}
          </dd>
        </div>
        <div className="field">
          <dt>{t('overview.chain.attemptsUsed')}</dt>
          <dd>
            {view.attemptsUsed}/{view.budgetMax}
          </dd>
        </div>
      </div>

      {view.metrics.map((metric) => (
        <div className="chain-metric" key={metric.name}>
          <span>
            {t('overview.chain.metric', {
              name: metric.name,
              best: fmtLag(metric.best_in_window?.k),
              peak: metric.peak_outside_window
                ? t('overview.chain.metricPeak', { k: fmtLag(metric.peak.k) })
                : '',
            })}
          </span>
          <span
            className="num-cell"
            title={t('overview.chain.corrTitle')}
            aria-label={t('overview.chain.corrAria', {
              name: metric.name,
              corr: fmtCorr(metric.best_in_window?.corr),
            })}
          >
            <span aria-hidden="true">ρ </span>
            {fmtCorr(metric.best_in_window?.corr)}
          </span>
        </div>
      ))}

      <div className="quality-row">
        <span className={`quality-light is-${view.quality}`} aria-hidden="true" />
        <span className="quality-label">{t(QUALITY_LABEL_KEY[view.quality])}</span>
        {view.path && <span className="quality-label">· {view.path}</span>}
        {runUnfinished && (
          <span
            className="badge-running"
            title={t('overview.chain.runningTitle', { started: runStartedUtc ?? '—' })}
          >
            <span className="badge-state-icon" aria-hidden="true">●</span>
            {t('overview.chain.runningLabel')}
          </span>
        )}
      </div>

      <div className="field">
        <dt>{t('overview.chain.lastRun')}</dt>
        <dd className={view.runUtc ? '' : 'is-missing'}>{fmtUtc(view.runUtc)}</dd>
      </div>

      {view.failureReasons.length > 0 && (
        <p className="chain-note">
          {t('overview.chain.failure', { reasons: view.failureReasons.join('；') })}
        </p>
      )}
      <p className="chain-note">{view.note}</p>
    </article>
  )
}

function BudgetBar() {
  const { t } = useI18n()
  const { max_attempts, attempts } = budget
  const used = attempts.length
  const exhausted = used >= max_attempts

  return (
    <section aria-labelledby="budget-title">
      <h2 className="section-title" id="budget-title">
        {t('overview.budget.title')}
      </h2>
      <div
        className="budget-card hover-glow-card"
        role="status"
        tabIndex={0}
        aria-label={t('overview.budget.aria', { used, max: max_attempts })}
      >
        <span className="budget-count">
          {used}/{max_attempts}
        </span>
        <span className="budget-segments" aria-hidden="true">
          {Array.from({ length: max_attempts }, (_, i) => (
            <i key={i} className={i < used ? '' : 'is-free'} />
          ))}
        </span>
        <p className="budget-copy">
          {exhausted
            ? t('overview.budget.exhausted')
            : t('overview.budget.remaining', {
                left: max_attempts - used,
                max: max_attempts,
              })}
        </p>
      </div>
    </section>
  )
}

export function Overview({ onOpenChain }: { onOpenChain: (chainId: string) => void }) {
  const { t } = useI18n()
  const chains = useMemo(() => buildChainViews(), [])
  // E9 运行态（架构审计 D13）：运行时 fetch 单文件，失败回落三态（C3 第 4 态数据源）
  const runState = useRunState()
  const runUnfinished = isRunUnfinished(runState)

  return (
    <>
      <section className="lede">
        <h1>{t('overview.lede.title')}</h1>
        <p>
          {t('overview.lede.lock', { pass: fmtFixed3(0.3), band: fmtFixed3(0.19) })}{' '}
          {t('overview.lede.settled', { count: chains.length })}
          <strong>{t('overview.lede.strong')}</strong>
          {t('overview.lede.tail')}
        </p>
      </section>

      <T1Timer />

      <section aria-labelledby="chains-title">
        <h2 className="section-title" id="chains-title">
          {t('overview.chains.title', { count: chains.length })}
        </h2>
        <div className="chain-grid">
          {chains.map((view) => (
            <ChainStatusCard
              key={view.chainId}
              view={view}
              runUnfinished={runUnfinished}
              runStartedUtc={runState?.started_utc ?? null}
              onOpen={onOpenChain}
            />
          ))}
        </div>
      </section>

      <BudgetBar />
    </>
  )
}
