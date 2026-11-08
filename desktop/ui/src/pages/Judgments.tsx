import { useState } from 'react'
import { GlassCard, ResultBanner, SectionLabel } from '../components/ds'
import {
  DEFAULTS,
  registryRegister,
  registryVerify,
  utcNowIso,
  utcToday,
  type BridgeResult,
  type RegistryRow,
  type VerifyPayload,
} from '../lib/bridge'
import { byExpiryAsc, groupRecords, type JudgmentState } from '../lib/records'
import { mapVerdict, reasonInfo } from '../lib/status-map'

const EXAMPLE_PAYLOAD = {
  id: 'REG-UI-001',
  claim: '10 年期美债收益率在 2026 年 10 月整月内出现过不低于 4.0% 的读数',
  registered_at: '2026-11-07T23:00:00Z',
  expires_on: '2026-11-30',
  criterion: {
    syntax_version: 'criterion/v1',
    source: { provider: 'fred', id: 'DGS10', field: 'value' },
    window: { start: '2026-10-01', end: '2026-10-31' },
    aggregate: 'max',
    comparator: 'gte',
    threshold: 4.0,
    unit: 'percent',
    min_observations: 15,
    coverage_slack_days: 5,
    settlement_lag_days: 3,
  },
}

interface Notice {
  tone: 'warn' | 'neg' | 'info'
  title: string
  tags: string[]
}

export default function Judgments({
  rows,
  loading,
  error,
  ledger,
  onLedgerChange,
  reload,
  bootVerify,
}: {
  rows: RegistryRow[] | null
  loading: boolean
  error: string | null
  ledger: string
  onLedgerChange: (path: string) => void
  reload: () => Promise<void>
  bootVerify: BridgeResult<VerifyPayload> | null
}) {
  const today = utcToday()
  const grouped = groupRecords(rows ?? [], today)
  const total = rows?.length ?? 0

  const [verifying, setVerifying] = useState(false)
  const [verifyResult, setVerifyResult] = useState<BridgeResult<VerifyPayload> | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [registerNotice, setRegisterNotice] = useState<Notice | null>(null)
  const [registering, setRegistering] = useState(false)

  const [formId, setFormId] = useState('')
  const [formClaim, setFormClaim] = useState('')
  const [formExpires, setFormExpires] = useState('')
  const [formAt, setFormAt] = useState(utcNowIso())
  const [formCriterion, setFormCriterion] = useState('')

  async function verifyDueRecords() {
    if (verifying) return
    setVerifying(true)
    setVerifyResult(null)
    const result = await registryVerify({ at: utcNowIso(), ledger })
    setVerifyResult(result)
    setVerifying(false)
    await reload()
  }

  async function submitJudgment() {
    if (registering) return
    setRegisterNotice(null)

    let criterion: unknown
    try {
      criterion = JSON.parse(formCriterion)
    } catch (err) {
      setRegisterNotice({
        tone: 'neg',
        title: '判据 JSON 解析失败，还没提交。',
        tags: [err instanceof Error ? err.message : String(err)],
      })
      return
    }

    const missing = [
      !formId.trim() ? '编号' : null,
      !formClaim.trim() ? '一句话判断' : null,
      !formExpires.trim() ? '到期日' : null,
      !formAt.trim() ? '登记时刻' : null,
    ].filter(Boolean) as string[]

    if (missing.length > 0) {
      setRegisterNotice({ tone: 'neg', title: `还缺：${missing.join('、')}`, tags: [] })
      return
    }

    setRegistering(true)
    const result = await registryRegister({
      payload: {
        id: formId.trim(),
        claim: formClaim.trim(),
        registered_at: formAt.trim(),
        expires_on: formExpires.trim(),
        criterion,
      },
      at: formAt.trim(),
      ledger,
    })
    setRegistering(false)

    if (!result.ok) {
      setRegisterNotice({ tone: 'neg', title: result.message ?? '桌面壳没有返回结果。', tags: [result.code ?? ''] })
      return
    }

    if (result.exitCode !== 0) {
      setRegisterNotice({
        tone: 'neg',
        title: `这条判断被拒了（退出码 ${result.exitCode}）；我的记录零新增。`,
        tags: [result.stderr.trim() || '（stderr 为空）'],
      })
      return
    }

    setRegisterNotice({ tone: 'info', title: `已记入我的记录：${formId.trim()}`, tags: [] })
    setFormId('')
    setFormClaim('')
    setFormExpires('')
    setFormCriterion('')
    setFormAt(utcNowIso())
    await reload()
  }

  const verifyNotice = buildVerifyNotice(verifyResult ?? bootVerify)

  return (
    <>
      <SectionLabel index="01" title="我的判断" />

      <div className="mnx-page-head">
        <h1 className="mnx-page-title">我的判断</h1>
        <p className="mnx-page-lede">
          你记下过的判断、到期日与核对结果。到期项排在最上面；判不了的会单列，并说清是缺数据、源不可达，还是算不出。
        </p>
      </div>

      <GlassCard>
        <div className="mnx-result-head" style={{ marginBottom: 0 }}>
          <div>
            <div className="mnx-result-title">
              {loading ? '正在读我的记录…' : total === 0 ? '还没有任何记录' : `共 ${total} 条判断`}
            </div>
            <div className="mnx-result-meta">
              兑现 {grouped.hit.length} · 没兑现 {grouped.miss.length} · 判不了 {grouped.undetermined.length} · 到期未核{' '}
              {grouped.due.length} · 未到期 {grouped.notDue.length}
            </div>
          </div>
          <div className="mnx-ask-row" style={{ marginTop: 0 }}>
            <button
              type="button"
              className="mnx-btn is-primary"
              onClick={() => void verifyDueRecords()}
              disabled={verifying || grouped.due.length === 0}
            >
              {verifying ? '正在核对…' : grouped.due.length > 0 ? `核对到期的 ${grouped.due.length} 条` : '没有到期的'}
            </button>
            <button type="button" className="mnx-btn" onClick={() => setFormOpen((v) => !v)}>
              {formOpen ? '收起' : '记一条新判断'}
            </button>
          </div>
        </div>

        {verifyNotice && (
          <div style={{ marginTop: 16 }}>
            <ResultBanner tone={verifyNotice.tone} title={verifyNotice.title} tags={verifyNotice.tags} />
          </div>
        )}

        {registerNotice && (
          <div style={{ marginTop: 16 }}>
            <ResultBanner tone={registerNotice.tone} title={registerNotice.title} tags={registerNotice.tags} />
          </div>
        )}

        {error && (
          <div style={{ marginTop: 16 }}>
            <ResultBanner tone="neg" title="读记录失败，界面不替你补一个空列表。" tags={[error]} />
          </div>
        )}

        {formOpen && (
          <div className="mnx-disclosure-body" style={{ marginTop: 20 }}>
            <div className="mnx-grid">
              <div className="mnx-field is-wide">
                <label htmlFor="mnx-claim">一句话判断</label>
                <input
                  id="mnx-claim"
                  value={formClaim}
                  onChange={(e) => setFormClaim(e.target.value)}
                  placeholder="如：10 年期美债收益率在窗口内最高读数不低于 4.0%"
                />
              </div>
              <div className="mnx-field">
                <label htmlFor="mnx-expires">到期日</label>
                <input
                  id="mnx-expires"
                  value={formExpires}
                  onChange={(e) => setFormExpires(e.target.value)}
                  placeholder="YYYY-MM-DD"
                />
              </div>
              <div className="mnx-field">
                <label htmlFor="mnx-reg-id">编号</label>
                <input id="mnx-reg-id" value={formId} onChange={(e) => setFormId(e.target.value)} placeholder="REG-2026-001" />
              </div>
              <div className="mnx-field is-wide">
                <label htmlFor="mnx-reg-at">登记时刻（UTC）</label>
                <input id="mnx-reg-at" value={formAt} onChange={(e) => setFormAt(e.target.value)} placeholder="2026-11-08T09:00:00Z" />
              </div>
              <div className="mnx-field is-full">
                <label htmlFor="mnx-criterion">判据（JSON，注册时冻结，不合规会被拒）</label>
                <textarea
                  id="mnx-criterion"
                  value={formCriterion}
                  onChange={(e) => setFormCriterion(e.target.value)}
                  spellCheck={false}
                  placeholder='{"syntax_version":"criterion/v1", ...}'
                />
                <div className="mnx-field-help">
                  判据必须一次写对：注册后不许改，否则整条记录作废。{' '}
                  <button
                    type="button"
                    className="mnx-btn is-quiet"
                    onClick={() => {
                      setFormId(EXAMPLE_PAYLOAD.id)
                      setFormClaim(EXAMPLE_PAYLOAD.claim)
                      setFormExpires(EXAMPLE_PAYLOAD.expires_on)
                      setFormAt(utcNowIso())
                      setFormCriterion(JSON.stringify(EXAMPLE_PAYLOAD.criterion, null, 2))
                    }}
                  >
                    载入仓库里的真实示例
                  </button>
                </div>
              </div>
            </div>
            <div className="mnx-ask-row">
              <button type="button" className="mnx-btn is-primary" onClick={() => void submitJudgment()} disabled={registering}>
                {registering ? '正在写入…' : '记下这条判断'}
              </button>
              <span className="mnx-ask-hint">写入我的记录时，参数与判据一并冻结；被拒不会留下半条。</span>
            </div>
          </div>
        )}
      </GlassCard>

      {!loading && total === 0 && !error && (
        <div className="mnx-empty" style={{ marginTop: 24 }}>
          <strong>这份记录文件里还没有判断。</strong>
          先在「看什么」找到线索，再回来把它记成一条可核对的判断；到期后这里会提醒你去核。当前记录文件是
          <span style={{ fontFamily: 'var(--font-mono)' }}> {ledger}</span>。
        </div>
      )}

      {grouped.due.length > 0 && (
        <section className="mnx-section-gap">
          <GroupHeading title="这个可以去核对了" count={grouped.due.length} />
          <div className="mnx-list">
            {grouped.due.sort(byExpiryAsc).map((row) => (
              <RecordItem key={row.id} row={row} state="due" />
            ))}
          </div>
        </section>
      )}

      {grouped.undetermined.length > 0 && (
        <section className="mnx-section-gap">
          <GroupHeading title="判不了" count={grouped.undetermined.length} />
          <div className="mnx-list">
            {grouped.undetermined.map((row) => (
              <RecordItem key={row.id} row={row} state="undetermined" />
            ))}
          </div>
        </section>
      )}

      {grouped.miss.length > 0 && (
        <section className="mnx-section-gap">
          <GroupHeading title="没兑现" count={grouped.miss.length} />
          <div className="mnx-list">
            {grouped.miss.map((row) => (
              <RecordItem key={row.id} row={row} state="miss" />
            ))}
          </div>
        </section>
      )}

      {grouped.hit.length > 0 && (
        <section className="mnx-section-gap">
          <GroupHeading title="兑现了" count={grouped.hit.length} />
          <div className="mnx-list">
            {grouped.hit.map((row) => (
              <RecordItem key={row.id} row={row} state="hit" />
            ))}
          </div>
        </section>
      )}

      {grouped.notDue.length > 0 && (
        <section className="mnx-section-gap">
          <GroupHeading title="还没到期" count={grouped.notDue.length} />
          <div className="mnx-list">
            {grouped.notDue.sort(byExpiryAsc).map((row) => (
              <RecordItem key={row.id} row={row} state="not_due" />
            ))}
          </div>
        </section>
      )}

      {grouped.pending.length > 0 && (
        <section className="mnx-section-gap">
          <GroupHeading title="还没核对" count={grouped.pending.length} />
          <div className="mnx-list">
            {grouped.pending.map((row) => (
              <RecordItem key={row.id} row={row} state="pending" />
            ))}
          </div>
        </section>
      )}

      <div className="mnx-section-gap">
        <details className="mnx-disclosure">
          <summary>详情（记录文件、技术信息）</summary>
          <div className="mnx-disclosure-body">
            <div className="mnx-field is-full">
              <label htmlFor="mnx-ledger">我的记录文件</label>
              <input id="mnx-ledger" value={ledger} onChange={(e) => onLedgerChange(e.target.value)} spellCheck={false} />
              <div className="mnx-field-help">默认与 CLI 一致：{DEFAULTS.ledger}。改成别的文件只影响界面读取与写入目标。</div>
            </div>
            {verifyResult && (
              <dl className="mnx-details-grid" style={{ marginTop: 16 }}>
                <dt>命令</dt>
                <dd>{verifyResult.command}</dd>
                <dt>退出码</dt>
                <dd>{verifyResult.exitCode === null ? '（无）' : verifyResult.exitCode}</dd>
                {verifyResult.code && (
                  <>
                    <dt>桥错误码</dt>
                    <dd>{verifyResult.code}</dd>
                  </>
                )}
              </dl>
            )}
            {verifyResult?.stderr.trim() && <div className="mnx-log">{verifyResult.stderr.trim()}</div>}
          </div>
        </details>
      </div>
    </>
  )
}

function GroupHeading({ title, count }: { title: string; count: number }) {
  return (
    <div className="mnx-group-label">
      <strong>{title}</strong>
      <span>{count} 条</span>
    </div>
  )
}

function RecordItem({ row, state }: { row: RegistryRow; state: JudgmentState }) {
  const verdict = mapVerdict(row.verdict)
  const reason = reasonInfo(row.reason_code)
  const cls =
    state === 'due' ? 'is-due' : state === 'undetermined' ? 'is-undetermined' : state === 'miss' ? 'is-miss' : state === 'hit' ? 'is-hit' : 'is-pending'

  const flagClass =
    state === 'due'
      ? 'is-due'
      : state === 'undetermined'
        ? 'is-undetermined'
        : state === 'miss'
          ? 'is-miss'
          : state === 'hit'
            ? 'is-hit'
            : 'is-neutral'
  const flagText =
    state === 'due'
      ? '这个可以去核对了'
      : state === 'undetermined'
        ? `判不了 · ${reason.bucketMeta.label}`
        : verdict.label
  const flagIcon = state === 'due' ? '!' : verdict.icon

  return (
    <details className={`mnx-judgment ${cls}`}>
      <summary>
        <div className="mnx-judgment-head">
          <span className={`mnx-flag ${flagClass}`}>
            <i>{flagIcon}</i>
            {flagText}
          </span>
          <span className="mnx-judgment-meta">{row.id}</span>
        </div>
        <div className="mnx-judgment-claim">{row.claim_canonical}</div>
        <div className="mnx-judgment-meta">
          到期 {row.expires_on || '（未填）'} · 记于 {row.registered_at ? row.registered_at.slice(0, 10) : '（未填）'}
          {state === 'due' ? ' · 到期后还没核对（关机期间不核验）' : ''}
        </div>
      </summary>
      <div className="mnx-judgment-body">
        <dl className="mnx-details-grid">
          <dt>verdict</dt>
          <dd>{row.verdict ?? '（空）'}</dd>
          <dt>reason_code</dt>
          <dd>{row.reason_code ?? '（无）'}</dd>
          <dt>原因</dt>
          <dd>
            {reason.label} · {reason.explain}
          </dd>
          <dt>id</dt>
          <dd>{row.id}</dd>
          <dt>registered_at</dt>
          <dd>{row.registered_at || '（未填）'}</dd>
          <dt>expires_on</dt>
          <dd>{row.expires_on || '（未填）'}</dd>
          <dt>provenance</dt>
          <dd>{row.provenance || '（未记录）'}</dd>
        </dl>
      </div>
    </details>
  )
}

function buildVerifyNotice(result: BridgeResult<VerifyPayload> | null): Notice | null {
  if (!result) return null
  if (!result.ok) {
    return { tone: 'neg', title: result.message ?? '核对没有跑起来。', tags: [result.code ?? ''] }
  }
  if (result.exitCode !== 0) {
    return {
      tone: 'neg',
      title: `核对退出码 ${result.exitCode ?? '未知'}，结果不可用。`,
      tags: [result.stderr.trim() || '（stderr 为空）'],
    }
  }

  const counts = result.data?.counts ?? {}
  const hit = counts.hit ?? 0
  const miss = counts.miss ?? 0
  const undetermined = counts.undetermined ?? 0
  const notDue = counts.not_due ?? 0
  const notDueDetails = (result.data?.results ?? [])
    .filter((r) => r.status === 'not_due' && r.detail)
    .map((r) => r.detail as string)
    .slice(0, 3)
  const settled = hit + miss + undetermined

  if (settled === 0) {
    if (notDue > 0) {
      return {
        tone: 'info',
        title: `这次核对了 ${notDue} 条，都还没到结算日，所以没出结论。`,
        tags: notDueDetails,
      }
    }
    return { tone: 'info', title: '这次没有可核对的到期项。', tags: [] }
  }

  const tail = notDue > 0 ? ` · 还没到结算日 ${notDue}` : ''

  if (undetermined > 0) {
    return {
      tone: 'warn',
      title: `这次核对了 ${settled} 条：兑现 ${hit} · 没兑现 ${miss} · 判不了 ${undetermined}${tail}`,
      tags: [
        '判不了的条目已单列在下方，原因在各自详情里',
        ...(notDue > 0 ? notDueDetails : []),
      ],
    }
  }

  return {
    tone: 'info',
    title: `这次核对了 ${settled} 条：兑现 ${hit} · 没兑现 ${miss}${tail}`,
    tags: notDue > 0 ? notDueDetails : [],
  }
}
