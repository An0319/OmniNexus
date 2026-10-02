/**
 * 看板外壳：顶栏导航 + 四页切换（无路由库，轻量 state）+ 固定免责条。
 *
 * 红线：只读 data/ 与 chains/；不触发回测、不写账本；私有阶段只本地跑。
 */

import { useEffect, useMemo, useState } from 'react'
import { buildChainViews, streak } from './data'
import { fmtUtc } from './format'
import { About } from './pages/About'
import { ChainDetail } from './pages/ChainDetail'
import { Overview } from './pages/Overview'
import { Timeline } from './pages/Timeline'

type View = 'overview' | 'chain' | 'timeline' | 'about'

const NAV: { id: View; label: string }[] = [
  { id: 'overview', label: '总览' },
  { id: 'chain', label: '链详情' },
  { id: 'timeline', label: '时间线' },
  { id: 'about', label: '说明' },
]

function DisclaimerBar() {
  return (
    <div className="disclaimer-bar" role="contentinfo">
      <span>
        <strong>免责声明</strong> 本页仅为方法论演示与公开留痕，不构成任何投资建议；证伪是正常产出，不是事故。
      </span>
      <span>数据截至 {fmtUtc(streak.last_run_utc)}</span>
    </div>
  )
}

export default function App() {
  const [light, setLight] = useState(false)
  const [view, setView] = useState<View>('overview')
  const [selectedChain, setSelectedChain] = useState('chain01')
  const chains = useMemo(() => buildChainViews(), [])

  useEffect(() => {
    document.documentElement.classList.toggle('light', light)
  }, [light])

  const openChain = (chainId: string) => {
    setSelectedChain(chainId)
    setView('chain')
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            Σ
          </span>
          <span className="brand-name">脉络</span>
          <span className="brand-sub">预注册验证流水线 · M2</span>
        </div>

        <nav className="app-nav" aria-label="主导航">
          {NAV.map((item) => (
            <button
              type="button"
              key={item.id}
              className={`nav-item${view === item.id ? ' is-active' : ''}`}
              aria-current={view === item.id ? 'page' : undefined}
              onClick={() => setView(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <button
          type="button"
          className="theme-toggle"
          onClick={() => setLight((value) => !value)}
          aria-label={light ? '切换到暗色主题' : '切换到亮色主题'}
        >
          {light ? 'DARK' : 'LIGHT'}
        </button>
      </header>

      <main className="app-main">
        {view === 'overview' && <Overview onOpenChain={openChain} />}
        {view === 'chain' && (
          <ChainDetail
            chains={chains}
            selectedId={selectedChain}
            onSelect={setSelectedChain}
            onOpenTimeline={() => setView('timeline')}
          />
        )}
        {view === 'timeline' && <Timeline />}
        {view === 'about' && <About />}
      </main>

      <DisclaimerBar />
    </div>
  )
}
