/*
 * 「我的判断」分组
 *
 * 只做一件事：把记录行按人要看的方式归类。
 * 到期项置顶；判不了单独一组（不许并进「没兑现」或「暂无数据」）。
 */
import type { RegistryRow } from './bridge'

export type JudgmentState = 'due' | 'undetermined' | 'miss' | 'hit' | 'not_due' | 'pending'

export interface GroupedRecords {
  due: RegistryRow[]
  undetermined: RegistryRow[]
  miss: RegistryRow[]
  hit: RegistryRow[]
  notDue: RegistryRow[]
  pending: RegistryRow[]
}

export function judgmentState(row: RegistryRow, today: string): JudgmentState {
  const verdict = row?.verdict ?? null
  if (verdict === 'undetermined') return 'undetermined'
  if (verdict === 'miss') return 'miss'
  if (verdict === 'hit') return 'hit'
  const expires = row?.expires_on ?? ''
  if (!expires) return 'pending'
  if (expires <= today) return 'due'
  return 'not_due'
}

export function groupRecords(rows: RegistryRow[], today: string): GroupedRecords {
  const grouped: GroupedRecords = { due: [], undetermined: [], miss: [], hit: [], notDue: [], pending: [] }
  ;(Array.isArray(rows) ? rows : []).forEach((row) => {
    const state = judgmentState(row, today)
    if (state === 'due') grouped.due.push(row)
    else if (state === 'undetermined') grouped.undetermined.push(row)
    else if (state === 'miss') grouped.miss.push(row)
    else if (state === 'hit') grouped.hit.push(row)
    else if (state === 'not_due') grouped.notDue.push(row)
    else grouped.pending.push(row)
  })
  return grouped
}

export function countDue(rows: RegistryRow[], today: string): number {
  return groupRecords(rows, today).due.length
}

/** 到期日排序：越早到期越靠前 */
export function byExpiryAsc(a: RegistryRow, b: RegistryRow): number {
  return (a.expires_on || '9999-99-99').localeCompare(b.expires_on || '9999-99-99')
}
