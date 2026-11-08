import { useState } from 'react'
import { GlassCard, ResultBanner, SectionLabel } from '../components/ds'
import { strings } from '../i18n'
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
  claim: strings.judgments.form.exampleClaim,
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
        title: strings.judgments.notice.criterionParseFailed,
        tags: [err instanceof Error ? err.message : String(err)],
      })
      return
    }

    const missing = [
      !formId.trim() ? strings.judgments.notice.missingFields.id : null,
      !formClaim.trim() ? strings.judgments.notice.missingFields.claim : null,
      !formExpires.trim() ? strings.judgments.notice.missingFields.expires : null,
      !formAt.trim() ? strings.judgments.notice.missingFields.at : null,
    ].filter(Boolean) as string[]

    if (missing.length > 0) {
      setRegisterNotice({
        tone: 'neg',
        title: strings.judgments.notice.missing(missing.join(strings.common.listSeparator)),
        tags: [],
      })
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
      setRegisterNotice({
        tone: 'neg',
        title: result.message ?? strings.common.bridgeNoResult,
        tags: [result.code ?? ''],
      })
      return
    }

    if (result.exitCode !== 0) {
      setRegisterNotice({
        tone: 'neg',
        title: strings.judgments.notice.rejected(result.exitCode),
        tags: [result.stderr.trim() || strings.common.stderrEmpty],
      })
      return
    }

    setRegisterNotice({ tone: 'info', title: strings.judgments.notice.registered(formId.trim()), tags: [] })
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
      <SectionLabel index="01" title={strings.judgments.sectionTitle} />

      <div className="mnx-page-head">
        <h1 className="mnx-page-title">{strings.judgments.title}</h1>
        <p className="mnx-page-lede">{strings.judgments.lede}</p>
      </div>

      <GlassCard>
        <div className="mnx-result-head" style={{ marginBottom: 0 }}>
          <div>
            <div className="mnx-result-title">
              {loading
                ? strings.judgments.loading
                : total === 0
                  ? strings.judgments.noRecords
                  : strings.judgments.recordCount(total)}
            </div>
            <div className="mnx-result-meta">
              {strings.judgments.summary({
                hit: grouped.hit.length,
                miss: grouped.miss.length,
                undetermined: grouped.undetermined.length,
                due: grouped.due.length,
                notDue: grouped.notDue.length,
              })}
            </div>
          </div>
          <div className="mnx-ask-row" style={{ marginTop: 0 }}>
            <button
              type="button"
              className="mnx-btn is-primary"
              onClick={() => void verifyDueRecords()}
              disabled={verifying || grouped.due.length === 0}
            >
              {verifying
                ? strings.judgments.verifyRunning
                : grouped.due.length > 0
                  ? strings.judgments.verifyDue(grouped.due.length)
                  : strings.judgments.verifyNothingDue}
            </button>
            <button type="button" className="mnx-btn" onClick={() => setFormOpen((v) => !v)}>
              {formOpen ? strings.judgments.formClose : strings.judgments.formOpen}
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
            <ResultBanner tone="neg" title={strings.judgments.readFailed} tags={[error]} />
          </div>
        )}

        {formOpen && (
          <div className="mnx-disclosure-body" style={{ marginTop: 20 }}>
            <div className="mnx-grid">
              <div className="mnx-field is-wide">
                <label htmlFor="mnx-claim">{strings.judgments.form.claimLabel}</label>
                <input
                  id="mnx-claim"
                  value={formClaim}
                  onChange={(e) => setFormClaim(e.target.value)}
                  placeholder={strings.judgments.form.claimPlaceholder}
                />
              </div>
              <div className="mnx-field">
                <label htmlFor="mnx-expires">{strings.judgments.form.expiresLabel}</label>
                <input
                  id="mnx-expires"
                  value={formExpires}
                  onChange={(e) => setFormExpires(e.target.value)}
                  placeholder="YYYY-MM-DD"
                />
              </div>
              <div className="mnx-field">
                <label htmlFor="mnx-reg-id">{strings.judgments.form.idLabel}</label>
                <input id="mnx-reg-id" value={formId} onChange={(e) => setFormId(e.target.value)} placeholder="REG-2026-001" />
              </div>
              <div className="mnx-field is-wide">
                <label htmlFor="mnx-reg-at">{strings.judgments.form.atLabel}</label>
                <input id="mnx-reg-at" value={formAt} onChange={(e) => setFormAt(e.target.value)} placeholder="2026-11-08T09:00:00Z" />
              </div>
              <div className="mnx-field is-full">
                <label htmlFor="mnx-criterion">{strings.judgments.form.criterionLabel}</label>
                <textarea
                  id="mnx-criterion"
                  value={formCriterion}
                  onChange={(e) => setFormCriterion(e.target.value)}
                  spellCheck={false}
                  placeholder='{"syntax_version":"criterion/v1", ...}'
                />
                <div className="mnx-field-help">
                  {strings.judgments.form.criterionHelp}{' '}
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
                    {strings.judgments.form.loadExample}
                  </button>
                </div>
              </div>
            </div>
            <div className="mnx-ask-row">
              <button type="button" className="mnx-btn is-primary" onClick={() => void submitJudgment()} disabled={registering}>
                {registering ? strings.judgments.form.submitRunning : strings.judgments.form.submit}
              </button>
              <span className="mnx-ask-hint">{strings.judgments.form.submitHint}</span>
            </div>
          </div>
        )}
      </GlassCard>

      {!loading && total === 0 && !error && (
        <div className="mnx-empty" style={{ marginTop: 24 }}>
          <strong>{strings.judgments.empty.title}</strong>
          {strings.judgments.empty.before}
          <span style={{ fontFamily: 'var(--font-mono)' }}> {ledger}</span>
          {strings.judgments.empty.after}
        </div>
      )}

      {grouped.due.length > 0 && (
        <section className="mnx-section-gap">
          <GroupHeading title={strings.judgments.groups.due} count={grouped.due.length} />
          <div className="mnx-list">
            {grouped.due.sort(byExpiryAsc).map((row) => (
              <RecordItem key={row.id} row={row} state="due" />
            ))}
          </div>
        </section>
      )}

      {grouped.undetermined.length > 0 && (
        <section className="mnx-section-gap">
          <GroupHeading title={strings.judgments.groups.undetermined} count={grouped.undetermined.length} />
          <div className="mnx-list">
            {grouped.undetermined.map((row) => (
              <RecordItem key={row.id} row={row} state="undetermined" />
            ))}
          </div>
        </section>
      )}

      {grouped.miss.length > 0 && (
        <section className="mnx-section-gap">
          <GroupHeading title={strings.judgments.groups.miss} count={grouped.miss.length} />
          <div className="mnx-list">
            {grouped.miss.map((row) => (
              <RecordItem key={row.id} row={row} state="miss" />
            ))}
          </div>
        </section>
      )}

      {grouped.hit.length > 0 && (
        <section className="mnx-section-gap">
          <GroupHeading title={strings.judgments.groups.hit} count={grouped.hit.length} />
          <div className="mnx-list">
            {grouped.hit.map((row) => (
              <RecordItem key={row.id} row={row} state="hit" />
            ))}
          </div>
        </section>
      )}

      {grouped.notDue.length > 0 && (
        <section className="mnx-section-gap">
          <GroupHeading title={strings.judgments.groups.notDue} count={grouped.notDue.length} />
          <div className="mnx-list">
            {grouped.notDue.sort(byExpiryAsc).map((row) => (
              <RecordItem key={row.id} row={row} state="not_due" />
            ))}
          </div>
        </section>
      )}

      {grouped.pending.length > 0 && (
        <section className="mnx-section-gap">
          <GroupHeading title={strings.judgments.groups.pending} count={grouped.pending.length} />
          <div className="mnx-list">
            {grouped.pending.map((row) => (
              <RecordItem key={row.id} row={row} state="pending" />
            ))}
          </div>
        </section>
      )}

      <div className="mnx-section-gap">
        <details className="mnx-disclosure">
          <summary>{strings.judgments.detailSummary}</summary>
          <div className="mnx-disclosure-body">
            <div className="mnx-field is-full">
              <label htmlFor="mnx-ledger">{strings.judgments.ledgerLabel}</label>
              <input id="mnx-ledger" value={ledger} onChange={(e) => onLedgerChange(e.target.value)} spellCheck={false} />
              <div className="mnx-field-help">{strings.judgments.ledgerHelp(DEFAULTS.ledger)}</div>
            </div>
            {verifyResult && (
              <dl className="mnx-details-grid" style={{ marginTop: 16 }}>
                <dt>{strings.common.dt.command}</dt>
                <dd>{verifyResult.command}</dd>
                <dt>{strings.common.dt.exitCode}</dt>
                <dd>{verifyResult.exitCode === null ? strings.common.none : verifyResult.exitCode}</dd>
                {verifyResult.code && (
                  <>
                    <dt>{strings.common.dt.bridgeCode}</dt>
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
      <span>{strings.common.itemCount(count)}</span>
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
      ? strings.judgments.record.dueFlag
      : state === 'undetermined'
        ? strings.judgments.record.undeterminedFlag(reason.bucketMeta.label)
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
          {strings.judgments.record.expiryLine(
            row.expires_on || strings.common.notFilled,
            row.registered_at ? row.registered_at.slice(0, 10) : strings.common.notFilled,
          )}
          {state === 'due' ? strings.judgments.record.dueTail : ''}
        </div>
      </summary>
      <div className="mnx-judgment-body">
        <dl className="mnx-details-grid">
          <dt>verdict</dt>
          <dd>{row.verdict ?? strings.common.emptyValue}</dd>
          <dt>reason_code</dt>
          <dd>{row.reason_code ?? strings.common.none}</dd>
          <dt>{strings.common.dt.reason}</dt>
          <dd>
            {reason.label} · {reason.explain}
          </dd>
          <dt>id</dt>
          <dd>{row.id}</dd>
          <dt>registered_at</dt>
          <dd>{row.registered_at || strings.common.notFilled}</dd>
          <dt>expires_on</dt>
          <dd>{row.expires_on || strings.common.notFilled}</dd>
          <dt>provenance</dt>
          <dd>{row.provenance || strings.common.notRecorded}</dd>
        </dl>
      </div>
    </details>
  )
}

function buildVerifyNotice(result: BridgeResult<VerifyPayload> | null): Notice | null {
  if (!result) return null
  if (!result.ok) {
    return { tone: 'neg', title: result.message ?? strings.judgments.notice.verifyFailed, tags: [result.code ?? ''] }
  }
  if (result.exitCode !== 0) {
    return {
      tone: 'neg',
      title: strings.judgments.notice.verifyExit(result.exitCode ?? strings.common.unknown),
      tags: [result.stderr.trim() || strings.common.stderrEmpty],
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
        title: strings.judgments.notice.verifyAllNotDue(notDue),
        tags: notDueDetails,
      }
    }
    return { tone: 'info', title: strings.judgments.notice.verifyNothingDue, tags: [] }
  }

  const tail = notDue > 0 ? strings.judgments.notice.notDueTail(notDue) : ''

  if (undetermined > 0) {
    return {
      tone: 'warn',
      title: strings.judgments.notice.settledWithUndetermined({ settled, hit, miss, undetermined, tail }),
      tags: [strings.judgments.notice.undeterminedTag, ...(notDue > 0 ? notDueDetails : [])],
    }
  }

  return {
    tone: 'info',
    title: strings.judgments.notice.settled({ settled, hit, miss, tail }),
    tags: notDue > 0 ? notDueDetails : [],
  }
}
