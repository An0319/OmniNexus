/**
 * C1 判定徽章：契约六态（需求清单 §3 C1；K7 拍板去掉「运行中」）。
 * `running` 仅作组件库预留（E9 行权后接线），当前无数据生产者。
 *
 * 三通道冗余：颜色 + 图标/形状/图案 + 文字。图标取 AGENTS.md 的严格口径，
 * 不沿用样品页旧 fixture 的图标（AGENTS.md：旧样品属已知 fixture 局限）。
 * 尤其：证伪用「完成勾 + 印章边框」，绝不与运行失败共享视觉；未通过用空心圆。
 */

import { useI18n } from '../i18n/I18nProvider'
import type { MessageKey } from '../i18n/messages.zh'
import type { VerdictStatus } from '../types'

export type SignalState =
  | 'verified'
  | 'falsified'
  | 'grayzone'
  | 'nodata'
  | 'notpassed'
  | 'forward'
  | 'running'

export const STATE_LABEL_KEY: Record<SignalState, MessageKey> = {
  verified: 'badge.verified',
  falsified: 'badge.falsified',
  grayzone: 'badge.grayzone',
  nodata: 'badge.nodata',
  notpassed: 'badge.notpassed',
  forward: 'badge.forward',
  running: 'badge.running',
}

const STATE_ICON: Record<SignalState, string> = {
  verified: '✓',
  falsified: '✓',
  grayzone: '≈',
  nodata: '∅',
  notpassed: '○',
  forward: 'k0',
  running: '●',
}

/** 链级判定 → 徽章态。 */
export const VERDICT_STATE: Record<VerdictStatus, SignalState> = {
  verified: 'verified',
  falsified: 'falsified',
  greyzone: 'grayzone',
  not_passed: 'notpassed',
}

export function SignalBadge({ state }: { state: SignalState }) {
  const { t } = useI18n()
  return (
    <span className={`badge-${state}`}>
      <span className="badge-state-icon" aria-hidden="true">
        {STATE_ICON[state]}
      </span>
      {t(STATE_LABEL_KEY[state])}
    </span>
  )
}

export function VerdictBadge({ verdict }: { verdict: VerdictStatus }) {
  return <SignalBadge state={VERDICT_STATE[verdict]} />
}
