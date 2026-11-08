/*
 * 设计系统组件抽取
 *
 * 来源：design-system/src/App.tsx（React 19 + Vite + Tailwind v4 样板页）。
 * 这里的 useInView / GlassCard / SectionLabel / MeshBg / SystemIcon 是原样搬运，
 * 未改结构、未改视觉参数；只有 DisclaimerBar 与 ResultBanner 的文案换成本产品的话。
 */
import { useEffect, useRef, useState, type CSSProperties, type ReactNode, type RefObject } from 'react'
import { strings } from '../i18n'

export function useInView(threshold = 0.12): [RefObject<HTMLDivElement | null>, boolean] {
  const ref = useRef<HTMLDivElement>(null)
  const [inView, setInView] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const obs = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          setInView(true)
          obs.disconnect()
        }
      },
      { threshold },
    )
    obs.observe(el)
    return () => obs.disconnect()
  }, [threshold])
  return [ref, inView]
}

export function GlassCard({
  children,
  style = {},
  accent = false,
  delay = 0,
}: {
  children: ReactNode
  style?: CSSProperties
  accent?: boolean
  delay?: number
}) {
  const [ref, inView] = useInView(0.08)
  return (
    <div
      ref={ref}
      style={{
        padding: 28,
        background: 'var(--surface-1)',
        border: `1px solid ${accent ? 'var(--border-accent)' : 'var(--border)'}`,
        borderRadius: 'var(--radius-md)',
        boxShadow: accent ? 'var(--shadow-glow), var(--shadow-card)' : 'var(--shadow-card)',
        backdropFilter: 'blur(12px)',
        opacity: inView ? 1 : 0,
        transform: inView ? 'translateY(0)' : 'translateY(18px)',
        transition: `opacity 0.55s ease ${delay}ms, transform 0.55s cubic-bezier(0.4,0,0.2,1) ${delay}ms, border-color 0.22s ease, box-shadow 0.22s ease`,
        ...style,
      }}
      onMouseEnter={(e) => {
        const el = e.currentTarget as HTMLElement
        el.style.borderColor = 'var(--border-accent)'
        el.style.boxShadow = 'var(--shadow-glow), var(--shadow-float)'
        el.style.transform = 'translateY(-2px)'
      }}
      onMouseLeave={(e) => {
        const el = e.currentTarget as HTMLElement
        el.style.borderColor = accent ? 'var(--border-accent)' : 'var(--border)'
        el.style.boxShadow = accent ? 'var(--shadow-glow), var(--shadow-card)' : 'var(--shadow-card)'
        el.style.transform = 'translateY(0)'
      }}
    >
      {children}
    </div>
  )
}

export function SectionLabel({ index, title }: { index: string; title: string }) {
  const [ref, inView] = useInView(0.3)
  return (
    <div ref={ref} style={{ display: 'flex', alignItems: 'center', gap: 18, marginBottom: 40 }}>
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.6875rem',
          fontWeight: 500,
          color: 'var(--accent)',
          letterSpacing: '0.14em',
          background: 'var(--accent-dim)',
          border: '1px solid var(--border-accent)',
          borderRadius: 'var(--radius-xs)',
          padding: '3px 10px',
          opacity: inView ? 1 : 0,
          transform: inView ? 'none' : 'translateX(-8px)',
          transition: 'opacity 0.45s ease, transform 0.45s ease',
        }}
      >
        ( {index} )
      </span>
      <div style={{ flex: 1, height: '1px', overflow: 'hidden', position: 'relative' }}>
        <div
          style={{
            position: 'absolute',
            inset: 0,
            background: 'linear-gradient(90deg, var(--border-accent), var(--border))',
            transformOrigin: 'left center',
            transform: inView ? 'scaleX(1)' : 'scaleX(0)',
            transition: 'transform 0.75s cubic-bezier(0.4, 0, 0.2, 1) 0.15s',
          }}
        />
      </div>
      <span
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.6875rem',
          fontWeight: 600,
          color: 'var(--text-3)',
          letterSpacing: '0.12em',
          opacity: inView ? 1 : 0,
          transition: 'opacity 0.45s ease 0.5s',
        }}
      >
        {title}
      </span>
    </div>
  )
}

export function MeshBg({ light }: { light: boolean }) {
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 0, pointerEvents: 'none', overflow: 'hidden' }}>
      <div
        style={{
          position: 'absolute',
          top: '-25%',
          right: '-8%',
          width: '55vw',
          height: '55vw',
          borderRadius: '50%',
          background: light
            ? 'radial-gradient(circle, rgba(91,33,182,0.065) 0%, transparent 68%)'
            : 'radial-gradient(circle, rgba(168,85,247,0.09) 0%, transparent 68%)',
          animation: 'breathe 8s ease-in-out infinite',
          filter: 'blur(1px)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          bottom: '5%',
          left: '-12%',
          width: '42vw',
          height: '42vw',
          borderRadius: '50%',
          background: light
            ? 'radial-gradient(circle, rgba(91,33,182,0.038) 0%, transparent 68%)'
            : 'radial-gradient(circle, rgba(109,40,217,0.065) 0%, transparent 68%)',
          animation: 'breathe 12s ease-in-out infinite reverse',
          filter: 'blur(1px)',
        }}
      />
      <div
        style={{
          position: 'absolute',
          top: '40%',
          left: '20%',
          width: '28vw',
          height: '28vw',
          borderRadius: '50%',
          background: light
            ? 'radial-gradient(circle, rgba(124,58,237,0.025) 0%, transparent 70%)'
            : 'radial-gradient(circle, rgba(192,132,252,0.04) 0%, transparent 70%)',
          animation: 'breathe 15s ease-in-out infinite',
        }}
      />
      <div
        style={{
          position: 'absolute',
          inset: 0,
          backgroundImage: 'radial-gradient(circle, var(--border-strong) 0.75px, transparent 0.75px)',
          backgroundSize: '28px 28px',
          opacity: 0.45,
        }}
      />
    </div>
  )
}

export type SystemIconName =
  | 'foundation'
  | 'type'
  | 'tokens'
  | 'components'
  | 'flow'
  | 'spatial'
  | 'engine'
  | 'table'
  | 'chart'
  | 'timer'

export function SystemIcon({ name, size = 18 }: { name: SystemIconName; size?: number }) {
  const paths: Record<SystemIconName, ReactNode> = {
    foundation: (
      <>
        <path d="M4 5.5h16M6.5 9.5h11v10h-11z" />
        <path d="M10 13.5h4" />
      </>
    ),
    type: (
      <>
        <path d="M5 6h14M12 6v13M8.5 19h7" />
      </>
    ),
    tokens: (
      <>
        <circle cx="8" cy="8" r="3" />
        <circle cx="16" cy="8" r="3" />
        <circle cx="12" cy="16" r="3" />
      </>
    ),
    components: (
      <>
        <rect x="4" y="4" width="6" height="6" rx="1" />
        <rect x="14" y="4" width="6" height="6" rx="1" />
        <rect x="4" y="14" width="6" height="6" rx="1" />
        <rect x="14" y="14" width="6" height="6" rx="1" />
      </>
    ),
    flow: (
      <>
        <circle cx="5" cy="12" r="2.5" />
        <circle cx="19" cy="6" r="2.5" />
        <circle cx="19" cy="18" r="2.5" />
        <path d="M7.5 11 16.5 7M7.5 13l9 4" />
      </>
    ),
    spatial: (
      <>
        <path d="M5 5h5v5H5zM14 14h5v5h-5zM14 5h5M5 14v5h5" />
      </>
    ),
    engine: (
      <>
        <circle cx="12" cy="12" r="3.5" />
        <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" />
      </>
    ),
    table: (
      <>
        <rect x="4" y="5" width="16" height="14" rx="1.5" />
        <path d="M4 10h16M10 5v14M15 10v9" />
      </>
    ),
    chart: (
      <>
        <path d="M4 19h16M6 16v-5M10 16V7M14 16v-3M18 16V5" />
        <path d="M4 9h16" strokeDasharray="2 2" />
      </>
    ),
    timer: (
      <>
        <circle cx="12" cy="13" r="7" />
        <path d="M12 13V9M9 3h6M17 6l1.5-1.5" />
      </>
    ),
  }

  return (
    <svg
      aria-hidden
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {paths[name]}
    </svg>
  )
}

export function DisclaimerBar({ collapsed }: { collapsed: boolean }) {
  return (
    <div className={`disclaimer-bar${collapsed ? ' is-sidebar-collapsed' : ''}`} role="contentinfo">
      <span className="disclaimer-text">{strings.disclaimer.text}</span>
      <span className="disclaimer-ts">
        UPDATED · {new Date().toISOString().slice(0, 16).replace('T', ' ')} UTC
      </span>
    </div>
  )
}

/**
 * 结果横幅：颜色、边框、结构沿用 DS 的 degradation-banner；
 * 只把「标本尺度」的标题抬到可读的 14px（见 shell.css 的 .mnx-banner）。
 * 三档各自独立，不许合并成一句「暂无数据」。
 */
export function ResultBanner({
  tone,
  title,
  tags = [],
  actionLabel = strings.common.actionShowDetail,
  onAction,
}: {
  tone: 'warn' | 'neg' | 'info'
  title: string
  tags?: string[]
  actionLabel?: string
  onAction?: () => void
}) {
  const cls =
    'degradation-banner mnx-banner' +
    (tone === 'neg' ? ' is-critical' : '') +
    (tone === 'info' ? ' is-reset' : '')
  return (
    <div className={cls} role={tone === 'info' ? 'status' : 'alert'}>
      <span className="degradation-banner-icon">{tone === 'neg' ? '×' : tone === 'info' ? 'i' : '!'}</span>
      <div className="degradation-banner-body">
        <div className="degradation-banner-title">{title}</div>
        {tags.length > 0 && (
          <div className="degradation-banner-sources">
            {tags.map((tag) => (
              <span key={tag} className="degradation-source-tag">
                {tag}
              </span>
            ))}
          </div>
        )}
      </div>
      <span className="degradation-banner-ts">
        {onAction ? (
          <button type="button" className="mnx-banner-action" onClick={onAction}>
            {actionLabel}
          </button>
        ) : null}
      </span>
    </div>
  )
}
