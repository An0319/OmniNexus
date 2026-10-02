/**
 * C5 z 曲线：领先面 vs 滞后面，同轴归一显示（共享 x 轴、各自 z 归一）。
 *
 * 缺失周保留显式断口，绝不跨缺段连线、绝不把缺失补成零。
 * 无 zseries 产出的链（如 chain20）走「无数据」灰态，不伪造曲线。
 */

import { fmtShortDate } from '../format'
import type { ZSeries } from '../types'

const WIDTH = 720
const HEIGHT = 220
const PLOT = { left: 44, right: 700, top: 16, bottom: 168 }

export function ZSeriesChart({ series }: { series: ZSeries | null }) {
  const points = series?.points ?? []
  if (!series || points.length === 0) {
    return (
      <div className="z-chart-card z-chart-card--empty">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="z-chart" role="img" aria-label="无周频归一数据">
          <text x={WIDTH / 2} y={94} textAnchor="middle" className="chart-empty-symbol">
            ∅
          </text>
          <text x={WIDTH / 2} y={120} textAnchor="middle" className="chart-empty-copy">
            本链无周频归一产出 · 暂不提供 z 曲线
          </text>
        </svg>
      </div>
    )
  }

  const magnitude = Math.max(
    1,
    ...points.map((point) => Math.abs(point.lead ?? 0)),
    ...points.map((point) => Math.abs(point.lag_ret ?? 0)),
  )
  const yScale = magnitude
  const y = (value: number) => (PLOT.top + PLOT.bottom) / 2 - (value * ((PLOT.bottom - PLOT.top) / 2)) / yScale
  const x = (index: number) => PLOT.left + (index * (PLOT.right - PLOT.left)) / Math.max(points.length - 1, 1)

  const buildPaths = (pick: (point: ZSeries['points'][number]) => number | null) => {
    const paths: string[] = []
    let current = ''
    points.forEach((point, index) => {
      const value = pick(point)
      if (value === null) {
        if (current) paths.push(current)
        current = ''
        return
      }
      current += `${current ? ' L' : 'M'} ${x(index)} ${y(value)}`
    })
    if (current) paths.push(current)
    return paths
  }

  const leadPaths = buildPaths((point) => point.lead)
  const lagPaths = buildPaths((point) => point.lag_ret)
  const lastIndex = points.length - 1
  const tickIndexes = [0, Math.round(lastIndex / 3), Math.round((lastIndex * 2) / 3), lastIndex]

  return (
    <div className="z-chart-card">
      <div className="z-chart-legend">
        <span className="z-legend-item">
          <i className="z-legend-a" />
          领先面 z（学术/指数热度）
        </span>
        <span className="z-legend-item">
          <i className="z-legend-b" />
          滞后面 z（板块周收益率）
        </span>
      </div>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="z-chart"
        role="img"
        aria-label={`双序列 z-score 曲线，共 ${points.length} 周，${fmtShortDate(points[0].date)} 至 ${fmtShortDate(points[lastIndex].date)}`}
      >
        {[1, 0, -1].map((value) => (
          <line
            key={value}
            x1={PLOT.left}
            x2={PLOT.right}
            y1={y(value)}
            y2={y(value)}
            className={value === 0 ? 'lag-grid-line' : 'chart-grid-line'}
          />
        ))}
        {leadPaths.map((d, index) => (
          <path key={`lead-${index}`} d={d} className="z-line z-line-a" />
        ))}
        {lagPaths.map((d, index) => (
          <path key={`lag-${index}`} d={d} className="z-line z-line-b" />
        ))}
      </svg>
      <div className="z-chart-axis">
        {tickIndexes.map((index) => (
          <span key={index}>{fmtShortDate(points[index]?.date)}</span>
        ))}
      </div>
      <p className="chart-caption">
        共享周一对齐 x 轴，各序列独立 z 归一（无量纲，可比的是形状）。缺失周保留显式断口，不跨段连线。
      </p>
    </div>
  )
}
