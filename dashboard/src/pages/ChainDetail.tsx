/**
 * 链详情页（清单 §2.2）：分析结果可视化。
 * C4 交叉相关柱状图（双指标）+ C5 z 曲线 + C6 数据质量块 + C1 判定徽章 + C9 判定水印。
 */

import { LagProfileChart } from '../components/LagProfileChart'
import { SignalBadge, STATE_LABEL_KEY, VERDICT_STATE } from '../components/SignalBadge'
import { VerdictNav } from '../components/VerdictNav'
import { ZSeriesChart } from '../components/ZSeriesChart'
import { fmtCorr, fmtCount, fmtDate, fmtFixed3, fmtLag, fmtUtc } from '../format'
import { useI18n } from '../i18n/I18nProvider'
import type { MessageKey } from '../i18n/messages.zh'
import { revisions, runLedgers } from '../data'
import type { ChainView, MetricStatus } from '../types'

const METRIC_STATE: Record<MetricStatus, 'verified' | 'grayzone' | 'notpassed'> = {
  verified: 'verified',
  greyzone: 'grayzone',
  not_passed: 'notpassed',
}

function QualityBlock({ view }: { view: ChainView }) {
  const { t } = useI18n()
  const { snapshot } = view
  const lead = snapshot?.lead
  const lag = snapshot?.lag
  const rows: { labelKey: MessageKey; value: string }[] = [
    { labelKey: 'chain.quality.leadSource', value: lead?.source ?? '—' },
    { labelKey: 'chain.quality.leadLatest', value: lead?.latest ? fmtDate(lead.latest) : '—' },
    { labelKey: 'chain.quality.leadPoints', value: fmtCount(lead?.points) },
    {
      labelKey: 'chain.quality.leadMissing',
      value: lead?.missing_weeks === undefined ? '—' : fmtCount(lead.missing_weeks),
    },
    { labelKey: 'chain.quality.lagSource', value: lag?.source ?? '—' },
    { labelKey: 'chain.quality.lagLatest', value: lag?.latest ? fmtDate(lag.latest) : '—' },
    { labelKey: 'chain.quality.lagPoints', value: fmtCount(lag?.weekly_points) },
    {
      labelKey: 'chain.quality.amount',
      value: lag
        ? lag.has_amount
          ? t('chain.quality.hasAmount')
          : t('chain.quality.noAmount')
        : '—',
    },
    { labelKey: 'chain.quality.path', value: lag?.path ?? t('chain.quality.defaultPath') },
    { labelKey: 'chain.quality.snapshotTime', value: fmtUtc(snapshot?.run_utc) },
  ]

  return (
    <div className="quality-block">
      <div className="quality-block-head">
        <div>
          <span className="eyebrow">{t('chain.quality.eyebrow')}</span>
          <div className="panel-title">{t('chain.quality.title')}</div>
        </div>
        <span className={`quality-light is-${view.quality}`} aria-hidden="true" />
      </div>
      <dl className="quality-grid">
        {rows.map((row) => (
          <div className="field" key={row.labelKey}>
            <dt>{t(row.labelKey)}</dt>
            <dd>{row.value}</dd>
          </div>
        ))}
      </dl>
      <p className="quality-note">
        {t('chain.quality.note')}
        {view.degraded && t('chain.quality.noteDegraded')}
      </p>
    </div>
  )
}

export function ChainDetail({
  chains,
  selectedId,
  onSelect,
  onOpenTimeline,
}: {
  chains: ChainView[]
  selectedId: string
  onSelect: (chainId: string) => void
  onOpenTimeline: () => void
}) {
  const { t } = useI18n()
  const view = chains.find((chain) => chain.chainId === selectedId) ?? chains[0]
  const chainRevisions = revisions.revisions[view.chainId] ?? []
  const ledger = runLedgers[view.chainId] ?? []
  const lastLedger = ledger[ledger.length - 1]
  const hasZSeries = view.zSeries !== null && view.zSeries.points.length > 0

  return (
    <>
      <section className="chain-switch" aria-label={t('chain.switch.aria')}>
        {chains.map((chain) => (
          <button
            type="button"
            key={chain.chainId}
            className={`chain-switch-item${chain.chainId === view.chainId ? ' is-active' : ''}`}
            aria-pressed={chain.chainId === view.chainId}
            onClick={() => onSelect(chain.chainId)}
          >
            <span className="chain-switch-id">{chain.chainId}</span>
            <span className="chain-switch-title">{chain.title}</span>
          </button>
        ))}
      </section>

      <section className="detail-card detail-head" aria-labelledby="detail-title">
        <div className="detail-head-top">
          <div>
            <span className="eyebrow">
              {t('chain.detail.eyebrow', { chainId: view.chainId.toUpperCase() })}
            </span>
            <h1 className="detail-title" id="detail-title">
              {view.title}
            </h1>
          </div>
          <div className="detail-badges">
            <SignalBadge state={VERDICT_STATE[view.verdict]} />
            {view.forwardLook && <SignalBadge state="forward" />}
          </div>
        </div>

        <dl className="detail-facts">
          <div className="field">
            <dt>{t('chain.detail.samples')}</dt>
            <dd>
              {fmtCount(view.samples.total_weeks)} / {fmtCount(view.samples.effective_weeks)}
            </dd>
          </div>
          <div className="field">
            <dt>{t('chain.detail.window')}</dt>
            <dd>
              k∈[{view.judgement.pass_window[0]}, {view.judgement.pass_window[1]}]
            </dd>
          </div>
          <div className="field">
            <dt>{t('chain.detail.line')}</dt>
            <dd>
              {fmtFixed3(view.judgement.pass_corr)} / ±
              {view.judgement.noise_band === null ? '—' : fmtFixed3(view.judgement.noise_band)}
            </dd>
          </div>
          <div className="field">
            <dt>{t('chain.detail.attempts')}</dt>
            <dd>
              {view.attemptsUsed}/{view.budgetMax}
            </dd>
          </div>
        </dl>

        {view.forwardLook && (
          <p className="detail-note">
            {t('chain.detail.forward', {
              k: fmtLag(view.forwardLook.k),
              rationale: view.forwardLook.rationale,
            })}
          </p>
        )}

        {/* C9 判定水印：与状态同体，截图不可只截一半 */}
        <div className="verdict-stamp" role="note" aria-label={t('chain.stamp.aria')}>
          <span className="verdict-stamp-mark" aria-hidden="true">
            ✓
          </span>
          <div className="verdict-stamp-body">
            <strong>{t(STATE_LABEL_KEY[VERDICT_STATE[view.verdict]])}</strong>
            <span>
              {t('chain.stamp.body', {
                decided: view.decidedDate,
                runUtc: fmtUtc(view.runUtc),
              })}
            </span>
          </div>
        </div>

        {/* C14 证伪导航（断点②处置）：判定后不停摆，给出结构化解读与下一步选项 */}
        <VerdictNav view={view} />
      </section>

      <section className="detail-card" aria-labelledby="c4-title">
        <div className="pattern-intro">
          <div>
            <span className="eyebrow">{t('chain.c4.eyebrow')}</span>
            <div className="panel-title" id="c4-title">
              {t('chain.c4.title')}
            </div>
          </div>
          <p>
            {t('chain.c4.intro', {
              names: view.metrics.map((metric) => metric.name).join(' / '),
            })}
          </p>
        </div>

        <LagProfileChart
          metrics={view.metrics}
          judgement={view.judgement}
          forwardLook={view.forwardLook}
          empty={view.samples.effective_weeks === 0}
        />

        <div className="metric-table">
          {view.metrics.map((metric) => (
            <div className="metric-row" key={metric.name}>
              <span className="metric-name">{metric.name}</span>
              <span className="metric-cell">
                <em>{t('chain.c4.windowBest')}</em>
                {fmtLag(metric.best_in_window?.k)} · ρ{fmtCorr(metric.best_in_window?.corr)}
              </span>
              <span className="metric-cell">
                <em>{t('chain.c4.peak')}</em>
                {fmtLag(metric.peak.k)} · ρ{fmtCorr(metric.peak.corr)}
                {metric.peak_outside_window && (
                  <span className="metric-flag">{t('chain.c4.outside')}</span>
                )}
              </span>
              <SignalBadge state={METRIC_STATE[metric.status]} />
            </div>
          ))}
        </div>

        <div className="lag-conclusion">
          <SignalBadge state={VERDICT_STATE[view.verdict]} />
          <span>{t('chain.c4.conclusion')}</span>
        </div>
      </section>

      <section className="detail-card" aria-labelledby="c5-title">
        <div className="pattern-intro">
          <div>
            <span className="eyebrow">{t('chain.c5.eyebrow')}</span>
            <div className="panel-title" id="c5-title">
              {t('chain.c5.title')}
            </div>
          </div>
          <p>
            {hasZSeries
              ? t('chain.c5.points', { count: fmtCount(view.zSeries?.points.length) })
              : t('chain.c5.empty')}
          </p>
        </div>

        {hasZSeries && view.zSeries ? (
          <ZSeriesChart series={view.zSeries} />
        ) : (
          <div className="nodata-band">
            <SignalBadge state="nodata" />
            <span>{t('chain.c5.nodata', { chainId: view.chainId })}</span>
          </div>
        )}
      </section>

      <section className="detail-card" aria-labelledby="c6-title">
        <div className="pattern-intro">
          <div>
            <span className="eyebrow">{t('chain.c6.eyebrow')}</span>
            <div className="panel-title" id="c6-title">
              {t('chain.c6.title')}
            </div>
          </div>
        </div>
        <QualityBlock view={view} />
      </section>

      <section className="detail-card detail-foot" aria-labelledby="c8-link-title">
        <div className="pattern-intro">
          <div>
            <span className="eyebrow">{t('chain.attempts.eyebrow')}</span>
            <div className="panel-title" id="c8-link-title">
              {t('chain.attempts.title')}
            </div>
          </div>
          <button type="button" className="text-link" onClick={onOpenTimeline}>
            {t('chain.attempts.openTimeline')}
          </button>
        </div>
        <dl className="detail-facts">
          <div className="field">
            <dt>{t('chain.attempts.used')}</dt>
            <dd>
              {view.attemptsUsed}/{view.budgetMax}
            </dd>
          </div>
          <div className="field">
            <dt>{t('chain.attempts.revisions')}</dt>
            <dd>{t('chain.attempts.count', { count: chainRevisions.length })}</dd>
          </div>
          <div className="field">
            <dt>{t('chain.attempts.budgetRevisions')}</dt>
            <dd>
              {t('chain.attempts.count', {
                count: chainRevisions.filter((entry) => entry.counts_as_attempt).length,
              })}
            </dd>
          </div>
          <div className="field">
            <dt>{t('chain.attempts.fingerprint')}</dt>
            <dd className="mono-ellipsis" title={lastLedger?.fingerprint ?? ''}>
              {lastLedger?.fingerprint ? lastLedger.fingerprint.slice(0, 12) : '—'}
            </dd>
          </div>
        </dl>
        <p className="detail-note">
          {t('chain.attempts.pipeline', {
            lead: view.pipeline.lead,
            lag: view.pipeline.lag,
            steps: view.pipeline.steps.join(' → '),
            files: view.sourceFiles.join(' · '),
          })}
        </p>
      </section>
    </>
  )
}
