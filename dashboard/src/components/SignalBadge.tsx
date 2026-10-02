/**
 * C1 判定徽章 · 七态（design-system/AGENTS.md「Signal status badges」）。
 *
 * 三通道冗余：颜色 + 图标/形状/图案 + 文字。图标取 AGENTS.md 的严格口径，
 * 不沿用样品页旧 fixture 的图标（AGENTS.md：旧样品属已知 fixture 局限）。
 * 尤其：证伪用「完成勾 + 印章边框」，绝不与运行失败共享视觉；未通过用空心圆。
 */

import type { VerdictStatus } from '../types'

export type SignalState =
  | 'verified'
  | 'falsified'
  | 'grayzone'
  | 'nodata'
  | 'notpassed'
  | 'forward'
  | 'running'

const STATE_LABEL: Record<SignalState, string> = {
  verified: 'VERIFIED · 通过',
  falsified: 'FALSIFIED · 证伪',
  grayzone: 'GRAY ZONE · 灰区',
  nodata: 'NO DATA · 无数据',
  notpassed: 'NOT PASSED · 未通过',
  forward: 'FORWARD-LOOK · 前视不计入',
  running: 'RUNNING · 运行中',
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
  return (
    <span className={`badge-${state}`}>
      <span className="badge-state-icon" aria-hidden="true">
        {STATE_ICON[state]}
      </span>
      {STATE_LABEL[state]}
    </span>
  )
}

export function VerdictBadge({ verdict }: { verdict: VerdictStatus }) {
  return <SignalBadge state={VERDICT_STATE[verdict]} />
}
