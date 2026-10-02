/**
 * C4 交叉相关滞后剖面图（真实数据版）。
 *
 * 参考线语义固定（AGENTS.md）：判定线实线 / 弱信号带着色带 / 噪声中位虚线 /
 * k=0 前视位斜纹列——四者在灰度下仍可区分，且 k=0 无需 hover 即持续可见。
 * 阈值不适用时省略并在图注说明原因，绝不静默改值。
 *
 * 双指标：每条链最多两根柱（周收益率 / 周成交额），各占组内一半。
 */

import { useId, useState } from 'react'
import { fmtCorr, fmtFixed3 } from '../format'
import type { Judgement, Metric, Profile } from '../types'

interface Props {
  metrics: Metric[]
  judgement: Judgement
  forwardLook: Profile['forward_look']
  /** 无有效周数据：只画参考线骨架 + 空态符号。 */
  empty?: boolean
  /** 去掉前视位柱（用于「已排除前视」对照态）。 */
  excludeForward?: boolean
}

const WIDTH = 720
const HEIGHT = 300
const PLOT = { left: 48, right: 704, top: 24, bottom: 240 }

export function LagProfileChart({ metrics, judgement, forwardLook, empty = false, excludeForward = false }: Props) {
  const [active, setActive] = useState<number | null>(null)
  const patternId = useId().replace(/[:]/g, '')

  const forwardK = forwardLook?.k ?? null
  const ks = Array.from(new Set(metrics.flatMap((metric) => metric.lags.map((lag) => lag.k)))).sort(
    (a, b) => a - b,
  )
  const visibleKs = excludeForward && forwardK !== null ? ks.filter((k) => k !== forwardK) : ks

  // y 轴对称定义域：至少覆盖「判定线 + 余量」与实测最大 |ρ|
  const maxAbs =
    Math.max(
      judgement.pass_corr + 0.06,
      judgement.noise_band ? judgement.noise_band + 0.04 : 0,
      ...metrics.flatMap((metric) => metric.lags.map((lag) => Math.abs(lag.corr))),
      0,
    ) + 0.02
  const yMax = Math.min(Math.max(maxAbs, 0.25), 0.6)
  const y = (value: number) => PLOT.bottom - ((value + yMax) / (2 * yMax)) * (PLOT.bottom - PLOT.top)
  const zeroY = y(0)

  const band = judgement.noise_band
  const median = judgement.null_median
  const passCorr = judgement.pass_corr

  const step = (PLOT.right - PLOT.left) / Math.max(visibleKs.length, 1)
  const groupWidth = Math.min(step * 0.72, 34)
  const barWidth = groupWidth / Math.max(metrics.length, 1)

  const labelStride = Math.max(1, Math.ceil(visibleKs.length / 14))
  const bestKs = new Set(metrics.map((metric) => metric.best_in_window?.k).filter((k): k is number => k !== undefined))

  const tickSet = new Set<number>(
    [yMax, -yMax, 0, passCorr, -passCorr].map((value) => Math.round(value * 1000) / 1000),
  )
  if (band !== null && band > 0 && band < passCorr - 0.01) {
    tickSet.add(Math.round(band * 1000) / 1000)
    tickSet.add(-Math.round(band * 1000) / 1000)
  }
  const ticks = [...tickSet].filter((value) => Math.abs(value) <= yMax + 1e-9).sort((a, b) => b - a)

  return (
    <div className="lag-chart-shell">
      <svg
        className="lag-chart"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={
          empty
            ? '交叉相关滞后剖面图，无可用数据'
            : `交叉相关滞后剖面图，滞后 k=${visibleKs[0] ?? 0} 至 k=${visibleKs[visibleKs.length - 1] ?? 0} 的皮尔逊相关系数`
        }
      >
        <defs>
          <pattern id={patternId} width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="3" height="8" className="chart-hatch-fill" />
          </pattern>
        </defs>

        {/* 弱信号带着色带 */}
        {band !== null && band > 0 && (
          <rect
            x={PLOT.left}
            y={y(band)}
            width={PLOT.right - PLOT.left}
            height={y(-band) - y(band)}
            className="weak-band"
          />
        )}

        {/* 网格与刻度 */}
        {ticks.map((value) => (
          <g key={value}>
            <line
              x1={PLOT.left}
              x2={PLOT.right}
              y1={y(value)}
              y2={y(value)}
              className={value === passCorr ? 'decision-line' : 'lag-grid-line'}
            />
            <text x={PLOT.left - 8} y={y(value) + 3} textAnchor="end" className="lag-axis-label">
              {fmtCorr(value)}
            </text>
          </g>
        ))}

        {/* 噪声中位参照（链20 专属零分布；其余链未标定，省略） */}
        {median !== null && (
          <line x1={PLOT.left} x2={PLOT.right} y1={y(median)} y2={y(median)} className="noise-line" />
        )}

        {!empty &&
          visibleKs.map((k, index) => {
            const groupX = PLOT.left + index * step + (step - groupWidth) / 2
            const isForward = forwardK !== null && k === forwardK
            const highlighted = active === k
            return (
              <g
                key={k}
                className={`lag-bar-group${highlighted ? ' is-highlighted' : ''}`}
                tabIndex={0}
                role="button"
                aria-label={`滞后 k=${k}，${metrics
                  .map((metric) => {
                    const point = metric.lags.find((lag) => lag.k === k)
                    return `${metric.name}相关系数 ${fmtCorr(point?.corr ?? null)}`
                  })
                  .join('，')}${isForward ? '，前视位不计入可交易结论' : ''}`}
                onMouseEnter={() => setActive(k)}
                onMouseLeave={() => setActive(null)}
                onFocus={() => setActive(k)}
                onBlur={() => setActive(null)}
              >
                {isForward && (
                  <rect
                    x={groupX - (step - groupWidth) / 2}
                    y={PLOT.top}
                    width={step}
                    height={PLOT.bottom - PLOT.top}
                    className="forward-column"
                  />
                )}
                {metrics.map((metric, metricIndex) => {
                  const point = metric.lags.find((lag) => lag.k === k)
                  if (!point) return null
                  const x = groupX + metricIndex * barWidth
                  const top = point.corr >= 0 ? y(point.corr) : zeroY
                  const height = Math.max(Math.abs(y(point.corr) - zeroY), 1)
                  const showLabel = highlighted || isForward || bestKs.has(k)
                  return (
                    <g key={metric.name}>
                      <rect
                        x={x}
                        y={top}
                        width={Math.max(barWidth - 1, 1)}
                        height={height}
                        className={`lag-bar${metricIndex > 0 ? ' is-metric-b' : ''}${isForward ? ' is-forward' : ''}`}
                      />
                      {isForward && (
                        <rect
                          x={x}
                          y={top}
                          width={Math.max(barWidth - 1, 1)}
                          height={height}
                          fill={`url(#${patternId})`}
                        />
                      )}
                      {showLabel && (
                        <text
                          x={x + Math.max(barWidth - 1, 1) / 2}
                          y={Math.max(top - 8, 13)}
                          textAnchor="middle"
                          className="lag-value-label"
                        >
                          {`ρ${fmtCorr(point.corr)}`}
                        </text>
                      )}
                    </g>
                  )
                })}
                {(labelStride === 1 || index % labelStride === 0 || index === visibleKs.length - 1) && (
                  <text x={groupX + groupWidth / 2} y={PLOT.bottom + 18} textAnchor="middle" className="lag-axis-label">
                    k={k}
                  </text>
                )}
              </g>
            )
          })}

        {empty && (
          <g>
            <text x={WIDTH / 2} y={132} textAnchor="middle" className="chart-empty-symbol">
              ∅
            </text>
            <text x={WIDTH / 2} y={158} textAnchor="middle" className="chart-empty-copy">
              无有效周数据 · NO DATA
            </text>
          </g>
        )}

        <text x={(PLOT.left + PLOT.right) / 2} y={292} textAnchor="middle" className="lag-axis-title">
          滞后 k（周）· 正值表示前序序列领先
        </text>
      </svg>

      <p className="chart-scroll-hint">图表按 720 设计宽度绘制；窄屏可左右滑动查看全部滞后位。</p>

      <div className="reference-legend" aria-label="参考线图例">
        <span>
          <i className="legend-threshold" />
          判定线 {fmtFixed3(passCorr)}
        </span>
        {band !== null && (
          <span>
            <i className="legend-band" />
            弱信号带 ±{fmtFixed3(band)}
          </span>
        )}
        {median !== null && (
          <span>
            <i className="legend-noise" />
            噪声中位 {fmtFixed3(median)}
          </span>
        )}
        {forwardK !== null && (
          <span>
            <i className="legend-forward" />k = {forwardK} 前视位
          </span>
        )}
        {metrics.length > 1 && (
          <span className="legend-metric">
            <i className="legend-metric-a" />
            {metrics[0].name}
            <i className="legend-metric-b" />
            {metrics[1].name}
          </span>
        )}
      </div>

      {median === null && (
        <p className="chart-caption">
          本链未做零分布相位标定，故不绘制「噪声中位」参照线；判定只依判定线与弱信号带。
        </p>
      )}
    </div>
  )
}
