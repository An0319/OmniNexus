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
import { useI18n } from '../i18n/I18nProvider'
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
  const { t } = useI18n()
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

  // ρ 标签统一在顶层绘制（所有组之后），不被相邻组柱子/前视高亮列遮挡；
  // 组内锚点统一取「组顶」（与柱子朝向解耦），层距恒定 16px；
  // 同层水平间距 < 46px 自动抬升一层——任何链（含 27 滞后位）都不会叠字。
  // 可读性由几何保证；禁用描边/晕圈/底色块补丁（需求清单 §6.6 图表标注红线）。
  const labelPoints = !empty
    ? visibleKs.flatMap((k, index) => {
        const groupX = PLOT.left + index * step + (step - groupWidth) / 2
        const isForward = forwardK !== null && k === forwardK
        if (!(active === k || isForward || bestKs.has(k))) return []
        const entries = metrics.flatMap((metric, metricIndex) => {
          const point = metric.lags.find((lag) => lag.k === k)
          if (!point) return []
          const x = groupX + metricIndex * barWidth
          return [{ key: `${metric.name}-${k}`, cx: x + Math.max(barWidth - 1, 1) / 2, corr: point.corr, level: metricIndex }]
        })
        if (entries.length === 0) return []
        const groupTop = Math.min(
          ...metrics.flatMap((metric) => {
            const point = metric.lags.find((lag) => lag.k === k)
            if (!point) return []
            return [point.corr >= 0 ? y(point.corr) : zeroY]
          }),
        )
        return entries.map((entry) => ({ ...entry, groupTop }))
      })
    : []
  // 同层防撞：层内按 x 排序，与同层前一枚中心距 < 46px 则抬升一层
  if (!empty) {
    labelPoints.sort((a, b) => a.level - b.level || a.cx - b.cx)
    const layerRight: number[] = []
    for (const p of labelPoints) {
      let level = p.level
      while (layerRight[level] !== undefined && p.cx - layerRight[level] < 46) level += 1
      layerRight[level] = p.cx
      p.level = level
    }
  }

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
            ? t('chart.lag.ariaEmpty')
            : t('chart.lag.aria', {
                start: visibleKs[0] ?? 0,
                end: visibleKs[visibleKs.length - 1] ?? 0,
              })
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
                aria-label={`${t('chart.lag.barAria', {
                  k,
                  metrics: metrics
                    .map((metric) => {
                      const point = metric.lags.find((lag) => lag.k === k)
                      return t('chart.lag.barMetric', {
                        name: metric.name,
                        corr: fmtCorr(point?.corr ?? null),
                      })
                    })
                    .join('，'),
                })}${isForward ? t('chart.lag.barForward') : ''}`}
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

        {/* ρ 值标签顶层：最后绘制 + 组顶统一锚点 + 同层防撞 */}
        {!empty &&
          labelPoints.map((p) => (
            <text
              key={p.key}
              x={p.cx}
              y={Math.max(p.groupTop - 10 - p.level * 16, 13)}
              textAnchor="middle"
              className="lag-value-label"
            >
              {`ρ${fmtCorr(p.corr)}`}
            </text>
          ))}

        {empty && (
          <g>
            <text x={WIDTH / 2} y={132} textAnchor="middle" className="chart-empty-symbol">
              ∅
            </text>
            <text x={WIDTH / 2} y={158} textAnchor="middle" className="chart-empty-copy">
              {t('chart.lag.empty')}
            </text>
          </g>
        )}

        <text x={(PLOT.left + PLOT.right) / 2} y={292} textAnchor="middle" className="lag-axis-title">
          {t('chart.lag.axis')}
        </text>
      </svg>

      <p className="chart-scroll-hint">{t('chart.lag.scrollHint')}</p>

      <div className="reference-legend" aria-label={t('chart.lag.legendAria')}>
        <span>
          <i className="legend-threshold" />
          {t('chart.lag.legendThreshold', { value: fmtFixed3(passCorr) })}
        </span>
        {band !== null && (
          <span>
            <i className="legend-band" />
            {t('chart.lag.legendBand', { value: fmtFixed3(band) })}
          </span>
        )}
        {median !== null && (
          <span>
            <i className="legend-noise" />
            {t('chart.lag.legendNoise', { value: fmtFixed3(median) })}
          </span>
        )}
        {forwardK !== null && (
          <span>
            <i className="legend-forward" />
            {t('chart.lag.legendForward', { k: forwardK })}
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

      {median === null && <p className="chart-caption">{t('chart.lag.caption')}</p>}
    </div>
  )
}
