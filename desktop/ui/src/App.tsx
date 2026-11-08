import { useCallback, useEffect, useRef, useState } from 'react'
import { DisclaimerBar, MeshBg, SystemIcon, type SystemIconName } from './components/ds'
import Home from './pages/Home'
import Judgments from './pages/Judgments'
import {
  DEFAULTS,
  registryList,
  registryVerify,
  utcNowIso,
  utcToday,
  type BridgeResult,
  type RegistryRow,
  type VerifyPayload,
} from './lib/bridge'
import { countDue } from './lib/records'

type Page = 'home' | 'judgments'

const THEME_KEY = 'mnx-theme'
const INTRO_KEY = 'mnx-intro-seen'
const LEDGER_KEY = 'mnx-ledger'

export default function App() {
  const [light, setLight] = useState(() => localStorage.getItem(THEME_KEY) === 'light')
  const [mounted, setMounted] = useState(false)
  const [page, setPage] = useState<Page>('home')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(max-width: 1080px)').matches,
  )
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [introSeen, setIntroSeen] = useState(() => localStorage.getItem(INTRO_KEY) === '1')

  const [ledger, setLedger] = useState(() => localStorage.getItem(LEDGER_KEY) || DEFAULTS.ledger)
  const [rows, setRows] = useState<RegistryRow[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [bootVerify, setBootVerify] = useState<BridgeResult<VerifyPayload> | null>(null)
  const bootRef = useRef(false)

  useEffect(() => {
    setTimeout(() => setMounted(true), 60)
  }, [])

  useEffect(() => {
    document.documentElement.classList.toggle('light', light)
    localStorage.setItem(THEME_KEY, light ? 'light' : 'dark')
  }, [light])

  useEffect(() => {
    const compactViewport = window.matchMedia('(max-width: 1080px)')
    const sync = (event: MediaQueryListEvent) => setSidebarCollapsed(event.matches)
    compactViewport.addEventListener('change', sync)
    return () => compactViewport.removeEventListener('change', sync)
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    const result = await registryList({ ledger })
    if (!result.ok) {
      setRows(null)
      setError(result.message ?? '桌面壳没有返回结果。')
    } else if (result.exitCode !== 0) {
      setRows(null)
      setError(result.stderr.trim() || `读记录退出码 ${result.exitCode}`)
    } else {
      setRows(Array.isArray(result.data) ? result.data : [])
      setError(null)
    }
    setLoading(false)
  }, [ledger])

  useEffect(() => {
    void load()
  }, [load])

  /* 开机补算：打开壳时，把已到期但还没结论的记录核一次。
     这里没有后台常驻进程；核验只发生在这一个时刻。 */
  useEffect(() => {
    if (!rows || bootRef.current) return
    bootRef.current = true
    const due = countDue(rows, utcToday())
    if (due === 0) return
    void (async () => {
      const result = await registryVerify({ at: utcNowIso(), ledger })
      setBootVerify(result)
      await load()
    })()
  }, [rows, ledger, load])

  const due = countDue(rows ?? [], utcToday())

  function dismissIntro() {
    localStorage.setItem(INTRO_KEY, '1')
    setIntroSeen(true)
  }

  function changeLedger(path: string) {
    setLedger(path)
    localStorage.setItem(LEDGER_KEY, path)
    bootRef.current = false
    setBootVerify(null)
  }

  function navigate(next: Page) {
    setPage(next)
    setMobileSidebarOpen(false)
  }

  const navItems: { id: Page; label: string; meta?: string; icon: SystemIconName }[] = [
    { id: 'home', label: '看什么', icon: 'flow' },
    { id: 'judgments', label: '我的判断', icon: 'timer', meta: due > 0 ? `${due}` : undefined },
  ]

  return (
    <div className={light ? 'light' : ''} style={{ minHeight: '100vh' }}>
      <MeshBg light={light} />

      <header
        className="app-header"
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 40,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 52px',
          height: 54,
          background: 'var(--header-bg)',
          borderBottom: '1px solid var(--border)',
          backdropFilter: 'blur(16px)',
          transition: 'background 0.35s ease',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, minWidth: 0 }}>
          <button
            className="mobile-nav-trigger"
            onClick={() => setMobileSidebarOpen(true)}
            aria-label="打开导航"
          >
            ≡
          </button>
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: 6,
              background: 'var(--btn-3d-face)',
              boxShadow: '0 2px 8px var(--btn-3d-glow)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
              fontWeight: 700,
              color: '#fff',
              flexShrink: 0,
            }}
          >
            Σ
          </div>
          <span
            className="header-product-name"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.75rem',
              fontWeight: 600,
              color: 'var(--text-2)',
              letterSpacing: '0.04em',
              whiteSpace: 'nowrap',
            }}
          >
            脉络 · 预注册验证工作台
          </span>
          <span className="header-divider" style={{ color: 'var(--border-strong)', fontSize: 18, lineHeight: 1 }}>
            |
          </span>
          <span
            className="header-version"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.6875rem',
              color: 'var(--text-3)',
              letterSpacing: '0.06em',
              whiteSpace: 'nowrap',
            }}
          >
            MNX · DESKTOP SHELL · v0.1.0
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <span
            className="header-theme-label"
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.6875rem',
              fontWeight: 500,
              color: 'var(--text-3)',
              letterSpacing: '0.06em',
            }}
          >
            {light ? 'LIGHT' : 'DARK'}
          </span>
          <ModeToggle light={light} onToggle={() => setLight((v) => !v)} />
        </div>
      </header>

      <div className={`app-layout${sidebarCollapsed ? ' sidebar-is-collapsed' : ' sidebar-is-expanded'}`}>
        <aside className={`app-sidebar${mobileSidebarOpen ? ' is-mobile-open' : ''}`} aria-label="主导航">
          <nav className="sidebar-nav">
            <div className="sidebar-group">
              <div className="sidebar-group-label">操作面</div>
              {navItems.map((item) => {
                const selected = page === item.id
                return (
                  <button
                    className={`sidebar-item${selected ? ' is-active' : ''}`}
                    key={item.id}
                    onClick={() => navigate(item.id)}
                    title={sidebarCollapsed ? item.label : undefined}
                    aria-current={selected ? 'page' : undefined}
                  >
                    <span className="sidebar-item-icon">
                      <SystemIcon name={item.icon} />
                    </span>
                    <span className="sidebar-item-label">{item.label}</span>
                    {item.meta && <span className="sidebar-item-meta">{item.meta}</span>}
                  </button>
                )
              })}
            </div>
          </nav>

          <div className="sidebar-footer">
            <div className="sidebar-status" title={sidebarCollapsed ? '开机时补算核验' : undefined}>
              <span className="sidebar-status-dot is-idle" />
              <span className="sidebar-copy">
                <span className="sidebar-status-title">开机时补算核验</span>
                <span className="sidebar-status-meta">关机期间不核验 · 非后台服务</span>
              </span>
            </div>
            <button
              className="sidebar-collapse"
              onClick={() => setSidebarCollapsed((v) => !v)}
              aria-label={sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'}
            >
              <span className="sidebar-collapse-icon">{sidebarCollapsed ? '→' : '←'}</span>
              <span className="sidebar-item-label">{sidebarCollapsed ? '展开' : '收起侧边栏'}</span>
            </button>
          </div>
        </aside>

        {mobileSidebarOpen && (
          <button
            className="mobile-sidebar-backdrop"
            onClick={() => setMobileSidebarOpen(false)}
            aria-label="关闭导航"
          />
        )}

        <div className="app-content">
          <main className={`mnx-main${mounted ? ' is-mounted' : ''}`} key={page}>
            {page === 'home' ? (
              <Home introSeen={introSeen} onDismissIntro={dismissIntro} />
            ) : (
              <Judgments
                rows={rows}
                loading={loading}
                error={error}
                ledger={ledger}
                onLedgerChange={changeLedger}
                reload={load}
                bootVerify={bootVerify}
              />
            )}
          </main>
        </div>
      </div>

      <DisclaimerBar collapsed={sidebarCollapsed} />
    </div>
  )
}

/* ── 亮暗切换：照搬 DS 的 ModeToggle ───────────────────────── */
function ModeToggle({ light, onToggle }: { light: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      aria-label={light ? '切换到暗色' : '切换到亮色'}
      aria-pressed={light}
      style={{
        position: 'relative',
        width: 56,
        height: 28,
        borderRadius: 99,
        background: light ? 'var(--surface-3)' : 'var(--surface-2)',
        border: '1px solid var(--border-strong)',
        cursor: 'pointer',
        transition: 'background 0.3s ease, border-color 0.3s ease',
        padding: 0,
        flexShrink: 0,
      }}
    >
      <span
        style={{
          position: 'absolute',
          left: 7,
          top: '50%',
          transform: 'translateY(-50%)',
          fontSize: 10,
          opacity: light ? 0.3 : 0.7,
          transition: 'opacity 0.3s',
        }}
      >
        ●
      </span>
      <span
        style={{
          position: 'absolute',
          right: 7,
          top: '50%',
          transform: 'translateY(-50%)',
          fontSize: 10,
          opacity: light ? 0.7 : 0.3,
          transition: 'opacity 0.3s',
        }}
      >
        ○
      </span>
      <span
        style={{
          position: 'absolute',
          top: 3,
          left: light ? 31 : 3,
          width: 20,
          height: 20,
          borderRadius: '50%',
          background: 'var(--accent)',
          boxShadow: '0 2px 8px var(--accent-glow)',
          transition: 'left 0.28s cubic-bezier(0.4,0,0.2,1), box-shadow 0.28s ease',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 9,
          color: '#fff',
        }}
      >
        {light ? '☀' : '☾'}
      </span>
    </button>
  )
}
