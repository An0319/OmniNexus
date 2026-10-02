/**
 * 集中式格式化（AGENTS.md：格式化必须集中，同一数值在卡片/表格/导出中渲染一致）。
 * 缺失一律渲染为 "—"（零是数据，缺失是缺席）。
 */

const MINUS = '\u2212' // U+2212，不用连字符

/** 相关系数：三位小数 + 显式符号，例如 +0.215 / −0.108。 */
export function fmtCorr(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const sign = value < 0 ? MINUS : '+'
  return `${sign}${Math.abs(value).toFixed(3)}`
}

/** 阈值/参数：三位小数，无符号（判定线 0.300）。 */
export function fmtFixed3(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toFixed(3)
}

/** 运行时间戳：YYYY-MM-DD HH:mm:ss UTC（绝不出现裸时间戳）。 */
export function fmtUtc(iso: string | null | undefined): string {
  if (!iso) return '—'
  const parsed = new Date(iso)
  if (Number.isNaN(parsed.getTime())) return '—'
  return `${parsed.toISOString().slice(0, 19).replace('T', ' ')} UTC`
}

/** 数据日期：YYYY-MM-DD · UTC 日界（数据日期不是时间戳）。 */
export function fmtDate(date: string | null | undefined): string {
  if (!date) return '—'
  return `${date} · UTC 日界`
}

/** 滞后位：k=1。 */
export function fmtLag(k: number | null | undefined): string {
  if (k === null || k === undefined) return '—'
  return `k=${k}`
}
