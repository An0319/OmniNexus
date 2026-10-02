import { useEffect, useMemo, useState } from 'react'
import { budget, buildChainViews, streak } from './data'
import { fmtCorr, fmtDate, fmtFixed3, fmtLag, fmtUtc } from './format'
import type { ChainView, VerdictStatus } from './types'

const VERDICT_LABEL: Record<VerdictStatus, string> = {
  verified: 'VERIFIED · 通过',
  falsified: 'FALSIFIED · 证伪',
  greyzone: 'GRAY ZONE · 灰区',
  not_passed: 'NOT PASSED · 未通过',
}

const VERDICT_CLASS: Record<VerdictStatus, string> = {
  verified: 'badge-verified',
  falsified: 'badge-falsified',
  greyzone: 'badge-grayzone',
  not_passed: 'badge-notpassed',
}

// 色彩 + 形状/图案 + 文字三通道冗余（AGENTS.md）；证伪用"完成勾"，绝不用错误红叉。
const VERDICT_ICON: Record<VerdictStatus, string> = {
  verified: '✓',
  falsified: '✓',
  greyzone: '≈',
  not_passed: '○',
}

const QUALITY_LABEL: Record<ChainView['quality'], string> = {
  green: 'READY · 正常',
  yellow: 'DEGRADED · 降级',
  red: 'FAILED · 失败',
  gray: 'NOT RUN · 未运行',
}

function VerdictBadge({ verdict }: { verdict: VerdictStatus }) {
  return (
    <span className={VERDICT_CLASS[verdict]}>
      <span className="badge-state-icon" aria-hidden="true">
        {VERDICT_ICON[verdict]}
      </span>
      {VERDICT_LABEL[verdict]}
    </span>
  )
}

function T1Timer() {
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
        T1 · 无人值守日更
      </h2>
      <div className="t1-card">
        <div className="t1-head">
          <span className="t1-count">
            {current_streak}/{target_days}
          </span>
          <span className={`${phase ? 'badge-notpassed' : 'badge-running'}`}>
            <span className="badge-state-icon" aria-hidden="true">
              {complete ? '✓' : '◉'}
            </span>
            {complete ? 'COMPLETE · 已达成' : current_streak === 0 ? 'RESET · 已归零' : 'IN PROGRESS · 进行中'}
          </span>
        </div>

        <div className={`t1-progress ${phase}`} role="presentation">
          <span style={{ width: `${Math.min(100, (current_streak / target_days) * 100)}%` }} />
        </div>

        <p className="t1-rule">{rule}</p>

        <dl className="t1-grid">
          <div className="field">
            <dt>起始日</dt>
            <dd>{fmtDate(started_utc_date)}</dd>
          </div>
          <div className="field">
            <dt>最近成功日</dt>
            <dd>{fmtDate(last_success_utc_date)}</dd>
          </div>
          <div className="field">
            <dt>最近运行</dt>
            <dd>{fmtUtc(last_run_utc)}</dd>
          </div>
          <div className="field">
            <dt>最近一日</dt>
            <dd>
              {latest
                ? `${latest.utc_date} · ${latest.runs} 次运行 · ${latest.status}`
                : '—'}
            </dd>
          </div>
          <div className="field">
            <dt>断更</dt>
            <dd className={breaks.length ? '' : 'is-missing'}>
              {breaks.length ? breaks.map((b) => b.utc_date).join('、') : '无'}
            </dd>
          </div>
          <div className="field">
            <dt>重置次数</dt>
            <dd>{resets.length} 次</dd>
          </div>
        </dl>

        {resets.length > 0 && (
          <ul className="t1-history">
            {resets.map((reset) => (
              <li key={`${reset.utc_date}-${reset.archive}`}>
                <span className="t1-history-date">{reset.utc_date}</span>
                <span className="t1-history-tag">运维事件 · 非故障</span>
                {reset.reason}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}

function ChainStatusCard({ view }: { view: ChainView }) {
  return (
    <article
      className="chain-card hover-glow-card"
      tabIndex={0}
      aria-label={`${view.title}，判定 ${VERDICT_LABEL[view.verdict]}`}
    >
      <div className="chain-card-top">
        <VerdictBadge verdict={view.verdict} />
        {view.forwardLook && (
          <span className="badge-forward">
            <span className="badge-state-icon" aria-hidden="true">
              k{view.forwardLook.k}
            </span>
            前视不计入
          </span>
        )}
      </div>

      <div className="chain-title">{view.title}</div>

      <div className="chain-facts">
        <div className="field">
          <dt>样本 / 有效周</dt>
          <dd>
            {view.samples.total_weeks} / {view.samples.effective_weeks}
          </dd>
        </div>
        <div className="field">
          <dt>已用尝试</dt>
          <dd>
            {view.attemptsUsed}/{view.budgetMax}
          </dd>
        </div>
      </div>

      {view.metrics.map((metric) => (
        <div className="chain-metric" key={metric.name}>
          <span>
            {metric.name}（窗口内最优 {fmtLag(metric.best_in_window?.k)}
            {metric.peak_outside_window ? ` · 峰值 ${fmtLag(metric.peak.k)} 在窗口外` : ''}）
          </span>
          <span
            className="num-cell"
            title="皮尔逊相关系数"
            aria-label={`${metric.name}相关系数 ${fmtCorr(metric.best_in_window?.corr)}`}
          >
            <span aria-hidden="true">ρ </span>
            {fmtCorr(metric.best_in_window?.corr)}
          </span>
        </div>
      ))}

      <div className="quality-row">
        <span className={`quality-light is-${view.quality}`} aria-hidden="true" />
        <span className="quality-label">{QUALITY_LABEL[view.quality]}</span>
        {view.path && <span className="quality-label">· {view.path}</span>}
      </div>

      <div className="field">
        <dt>最近运行（UTC）</dt>
        <dd className={view.runUtc ? '' : 'is-missing'}>{fmtUtc(view.runUtc)}</dd>
      </div>

      {view.failureReasons.length > 0 && (
        <p className="chain-note">失败原因：{view.failureReasons.join('；')}</p>
      )}
      <p className="chain-note">{view.note}</p>
    </article>
  )
}

function BudgetBar() {
  const { max_attempts, attempts } = budget
  const used = attempts.length
  const exhausted = used >= max_attempts

  return (
    <section aria-labelledby="budget-title">
      <h2 className="section-title" id="budget-title">
        项目预算 · 全链唯一
      </h2>
      <div
        className="budget-card hover-glow-card"
        role="status"
        tabIndex={0}
        aria-label={`换链尝试预算已用 ${used} / ${max_attempts}`}
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
            ? '换链预算已用尽：不再接受新链，检验已有链不受影响。'
            : `剩余 ${max_attempts - used}/${max_attempts}：可提交新链，提交须经预算守卫登记。`}
        </p>
      </div>
    </section>
  )
}

function DisclaimerBar() {
  return (
    <div className="disclaimer-bar" role="contentinfo">
      <span>
        <strong>免责声明</strong> 本页仅为方法论演示与公开留痕，不构成任何投资建议；证伪是正常产出，不是事故。
      </span>
      <span>数据截至 {fmtUtc(streak.last_run_utc)}</span>
    </div>
  )
}

export default function App() {
  const [light, setLight] = useState(false)
  const chains = useMemo(() => buildChainViews(), [])

  useEffect(() => {
    document.documentElement.classList.toggle('light', light)
  }, [light])

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            Σ
          </span>
          <span className="brand-name">脉络</span>
          <span className="brand-sub">预注册验证流水线 · M2 总览</span>
        </div>
        <button
          type="button"
          className="theme-toggle"
          onClick={() => setLight((value) => !value)}
          aria-label={light ? '切换到暗色主题' : '切换到亮色主题'}
        >
          {light ? 'DARK' : 'LIGHT'}
        </button>
      </header>

      <main className="app-main">
        <section className="lede">
          <h1>先锁定，后结算，公开留痕</h1>
          <p>
            判定线在见数据之前写死：通过门槛 {fmtFixed3(0.3)}、弱信号带 ±
            {fmtFixed3(0.19)} 全部随协议登记。当前三条链均已结算，
            <strong>证伪与未通过是正常产出，不是事故</strong>——这正是预注册要保护的东西。
          </p>
        </section>

        <T1Timer />

        <section aria-labelledby="chains-title">
          <h2 className="section-title" id="chains-title">
            链状态 · 已结算 {chains.length} 条
          </h2>
          <div className="chain-grid">
            {chains.map((view) => (
              <ChainStatusCard key={view.chainId} view={view} />
            ))}
          </div>
        </section>

        <BudgetBar />
      </main>

      <DisclaimerBar />
    </div>
  )
}
