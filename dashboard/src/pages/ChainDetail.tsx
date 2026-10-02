/**
 * 链详情页（清单 §2.2）：分析结果可视化。
 * C4 交叉相关柱状图（双指标）+ C5 z 曲线 + C6 数据质量块 + C1 判定徽章 + C9 判定水印。
 */

import { LagProfileChart } from '../components/LagProfileChart'
import { SignalBadge, VERDICT_STATE } from '../components/SignalBadge'
import { ZSeriesChart } from '../components/ZSeriesChart'
import { fmtCorr, fmtCount, fmtDate, fmtFixed3, fmtLag, fmtUtc } from '../format'
import { revisions, runLedgers } from '../data'
import type { ChainView, MetricStatus } from '../types'

const METRIC_STATE: Record<MetricStatus, 'verified' | 'grayzone' | 'notpassed'> = {
  verified: 'verified',
  greyzone: 'grayzone',
  not_passed: 'notpassed',
}

const VERDICT_TEXT: Record<ChainView['verdict'], string> = {
  verified: 'VERIFIED · 通过',
  falsified: 'FALSIFIED · 证伪',
  greyzone: 'GRAY ZONE · 灰区',
  not_passed: 'NOT PASSED · 未通过',
}

function QualityBlock({ view }: { view: ChainView }) {
  const { snapshot } = view
  const lead = snapshot?.lead
  const lag = snapshot?.lag
  const rows: { key: string; value: string }[] = [
    { key: '领先面来源', value: lead?.source ?? '—' },
    { key: '领先面最新', value: lead?.latest ? fmtDate(lead.latest) : '—' },
    { key: '领先面点数', value: fmtCount(lead?.points) },
    { key: '领先面缺失周', value: lead?.missing_weeks === undefined ? '—' : fmtCount(lead.missing_weeks) },
    { key: '滞后面来源', value: lag?.source ?? '—' },
    { key: '滞后面最新', value: lag?.latest ? fmtDate(lag.latest) : '—' },
    { key: '滞后面点数', value: fmtCount(lag?.weekly_points) },
    { key: '成交额口径', value: lag ? (lag.has_amount ? '含成交额' : '无成交额') : '—' },
    { key: '降级路径', value: lag?.path ?? '路径1 · 主数据 · 原始口径' },
    { key: '快照时间', value: fmtUtc(snapshot?.run_utc) },
  ]

  return (
    <div className="quality-block">
      <div className="quality-block-head">
        <div>
          <span className="eyebrow">DATA QUALITY · 降级与缺失披露</span>
          <div className="panel-title">数据质量报告块</div>
        </div>
        <span className={`quality-light is-${view.quality}`} aria-hidden="true" />
      </div>
      <dl className="quality-grid">
        {rows.map((row) => (
          <div className="field" key={row.key}>
            <dt>{row.key}</dt>
            <dd>{row.value}</dd>
          </div>
        ))}
      </dl>
      <p className="quality-note">
        降级是运行时源等级，不是故障遮掩：主数据不可用时按既有降级链兜底并在此披露具体路径。
        {view.degraded && ' 本链当前处于降级路径，数值含代理标的特质噪声。'}
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
  const view = chains.find((chain) => chain.chainId === selectedId) ?? chains[0]
  const chainRevisions = revisions.revisions[view.chainId] ?? []
  const ledger = runLedgers[view.chainId] ?? []
  const lastLedger = ledger[ledger.length - 1]
  const hasZSeries = view.zSeries !== null && view.zSeries.points.length > 0

  return (
    <>
      <section className="chain-switch" aria-label="选择链">
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
            <span className="eyebrow">CHAIN DETAIL · {view.chainId.toUpperCase()}</span>
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
            <dt>样本规模（总周 / 有效周）</dt>
            <dd>
              {fmtCount(view.samples.total_weeks)} / {fmtCount(view.samples.effective_weeks)}
            </dd>
          </div>
          <div className="field">
            <dt>判定窗口</dt>
            <dd>
              k∈[{view.judgement.pass_window[0]}, {view.judgement.pass_window[1]}]
            </dd>
          </div>
          <div className="field">
            <dt>判定线 / 弱信号带</dt>
            <dd>
              {fmtFixed3(view.judgement.pass_corr)} / ±
              {view.judgement.noise_band === null ? '—' : fmtFixed3(view.judgement.noise_band)}
            </dd>
          </div>
          <div className="field">
            <dt>已用尝试</dt>
            <dd>
              {view.attemptsUsed}/{view.budgetMax}
            </dd>
          </div>
        </dl>

        {view.forwardLook && (
          <p className="detail-note">
            前视诊断：{fmtLag(view.forwardLook.k)} 为同周共动，{view.forwardLook.rationale}；计入图表作诊断，
            不计入可交易结论。
          </p>
        )}

        {/* C9 判定水印：与状态同体，截图不可只截一半 */}
        <div className="verdict-stamp" role="note" aria-label="判定水印">
          <span className="verdict-stamp-mark" aria-hidden="true">
            ✓
          </span>
          <div className="verdict-stamp-body">
            <strong>{VERDICT_TEXT[view.verdict]}</strong>
            <span>
              判定线锁定于注册日，早于任何数据写入 · 判定日 {view.decidedDate} · 数据截至{' '}
              {fmtUtc(view.runUtc)}
            </span>
          </div>
        </div>
      </section>

      <section className="detail-card" aria-labelledby="c4-title">
        <div className="pattern-intro">
          <div>
            <span className="eyebrow">C4 · CROSS-CORRELATION</span>
            <div className="panel-title" id="c4-title">
              交叉相关滞后剖面
            </div>
          </div>
          <p>
            双指标柱：{view.metrics.map((metric) => metric.name).join(' / ')}。参考线为判定线与弱信号带，
            前视位单独以斜纹列标出。
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
                <em>窗口内最优</em>
                {fmtLag(metric.best_in_window?.k)} · ρ{fmtCorr(metric.best_in_window?.corr)}
              </span>
              <span className="metric-cell">
                <em>峰值</em>
                {fmtLag(metric.peak.k)} · ρ{fmtCorr(metric.peak.corr)}
                {metric.peak_outside_window && <span className="metric-flag">窗口外</span>}
              </span>
              <SignalBadge state={METRIC_STATE[metric.status]} />
            </div>
          ))}
        </div>

        <div className="lag-conclusion">
          <SignalBadge state={VERDICT_STATE[view.verdict]} />
          <span>
            链级结论由作者裁定（不机械取阈值）；上方指标徽章只表示该指标在判定窗口内是否触达判定线。
            候选 ≠ 结论。
          </span>
        </div>
      </section>

      <section className="detail-card" aria-labelledby="c5-title">
        <div className="pattern-intro">
          <div>
            <span className="eyebrow">C5 · WEEKLY Z-SCORE</span>
            <div className="panel-title" id="c5-title">
              领先面 vs 滞后面 · z 曲线
            </div>
          </div>
          <p>
            {hasZSeries
              ? `${fmtCount(view.zSeries?.points.length)} 个周频点，共享周一 x 轴、各自 z 归一。`
              : '本链无周频归一产出，按「无数据」披露，不伪造曲线。'}
          </p>
        </div>

        {hasZSeries && view.zSeries ? (
          <ZSeriesChart series={view.zSeries} />
        ) : (
          <div className="nodata-band">
            <SignalBadge state="nodata" />
            <span>
              来源文件缺失：{view.chainId} 未产出 zseries 快照（隔夜快传导链不适用周频归一）。此处保持空态，
              不以零或近似值填充。
            </span>
          </div>
        )}
      </section>

      <section className="detail-card" aria-labelledby="c6-title">
        <div className="pattern-intro">
          <div>
            <span className="eyebrow">C6 · DATA QUALITY</span>
            <div className="panel-title" id="c6-title">
              数据质量与出处
            </div>
          </div>
        </div>
        <QualityBlock view={view} />
      </section>

      <section className="detail-card detail-foot" aria-labelledby="c8-link-title">
        <div className="pattern-intro">
          <div>
            <span className="eyebrow">ATTEMPTS &amp; REVISIONS</span>
            <div className="panel-title" id="c8-link-title">
              本链尝试 / 修订摘要
            </div>
          </div>
          <button type="button" className="text-link" onClick={onOpenTimeline}>
            查看完整时间线 →
          </button>
        </div>
        <dl className="detail-facts">
          <div className="field">
            <dt>已用尝试</dt>
            <dd>
              {view.attemptsUsed}/{view.budgetMax}
            </dd>
          </div>
          <div className="field">
            <dt>修订登记</dt>
            <dd>{chainRevisions.length} 条</dd>
          </div>
          <div className="field">
            <dt>消耗预算的修订</dt>
            <dd>{chainRevisions.filter((entry) => entry.counts_as_attempt).length} 条</dd>
          </div>
          <div className="field">
            <dt>运行账本指纹</dt>
            <dd className="mono-ellipsis" title={lastLedger?.fingerprint ?? ''}>
              {lastLedger?.fingerprint ? lastLedger.fingerprint.slice(0, 12) : '—'}
            </dd>
          </div>
        </dl>
        <p className="detail-note">
          管线 {view.pipeline.lead} → {view.pipeline.lag}（{view.pipeline.steps.join(' → ')}）· 出处{' '}
          {view.sourceFiles.join(' · ')}
        </p>
      </section>
    </>
  )
}
