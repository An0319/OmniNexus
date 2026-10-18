/**
 * 看板外壳：启动动画前置层（§13.1 组件迁移方案 A）+ 顶栏导航 + 四页切换
 * （无路由库，轻量 state）+ 固定免责条。
 *
 * 红线：只读 data/ 与 chains/；不触发回测、不写账本；私有阶段只本地跑。
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import StartupIntro, { type IntroProgress } from './components/StartupIntro'
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

// ── 启动动画接入（§13.1）──────────────────────────────────────────
// 真实加载进度：每格对应一个真实事件（字体解码 / 数据模块加载 / 首帧合成）。
// 数据模块在构建期已随主包内联、resolve 极快，故加节奏阀：每格点亮最短间隔
// 400ms，真实进度与节奏进度取较慢者——真实快则保仪式完整，真实慢则跟真实（诚实）。
const INTRO_STAGES: { label: string; task: () => Promise<unknown> }[] = [
  { label: 'CALIBRATING TYPE', task: () => document.fonts.ready },
  { label: 'SOURCING CHAIN01', task: () => import('../../chains/chain01.profile.json') },
  { label: 'SOURCING CHAIN10', task: () => import('../../chains/chain10.profile.json') },
  { label: 'SOURCING CHAIN20', task: () => import('../../chains/chain20.profile.json') },
  { label: 'ALIGNING LEDGER', task: () => import('../../data/streak.json') },
  {
    label: 'COMPOSING VIEWS',
    // 视图构建完成 = 主体首帧合成（App 数据为构建期静态导入，挂载即就绪）
    task: () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  },
]
const INTRO_RHYTHM_MS = 400

// TEMP-WEB(sessionStorage)：web 临时脚手架——会话内首次进看板播完整叙事，
// 会话内后续刷新直接进看板。Tauri 壳阶段整段移除（§13.2 零残留验收红线，
// 已列入建壳拆除清单），届时"开机"语义由壳的启动事件接管。
const INTRO_SEEN_KEY = 'mnx.intro.seen.v1'

function readIntroSeen(): boolean {
  try {
    return window.sessionStorage.getItem(INTRO_SEEN_KEY) === '1'
  } catch {
    return false
  }
}

function markIntroSeen(): void {
  try {
    window.sessionStorage.setItem(INTRO_SEEN_KEY, '1')
  } catch {
    // 隐私模式等写入失败场景：退化为每次刷新重播，不影响功能
  }
}

function useIntroBoot(active: boolean) {
  const [done, setDone] = useState(0)

  useEffect(() => {
    if (!active) return
    let cancelled = false
    const timers: number[] = []
    const pace = () =>
      new Promise<void>((resolve) => {
        timers.push(window.setTimeout(resolve, INTRO_RHYTHM_MS))
      })

    void (async () => {
      for (const { task } of INTRO_STAGES) {
        await Promise.all([task(), pace()])
        if (cancelled) return
        setDone((current) => Math.min(INTRO_STAGES.length, current + 1))
      }
    })()

    return () => {
      cancelled = true
      timers.forEach((timer) => window.clearTimeout(timer))
    }
  }, [active])

  return { done, ready: done >= INTRO_STAGES.length }
}

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
  // ?loop=1 调试模式：绕过会话记忆，每次都播循环
  const [loopMode] = useState(() =>
    new URLSearchParams(window.location.search).has('loop'),
  )
  const [introActive, setIntroActive] = useState(
    () => loopMode || !readIntroSeen(),
  )
  const chains = useMemo(() => buildChainViews(), [])

  const { done, ready } = useIntroBoot(introActive && !loopMode)
  const progress: IntroProgress = {
    done,
    total: INTRO_STAGES.length,
    label: INTRO_STAGES[Math.min(done, INTRO_STAGES.length - 1)].label,
  }
  const handleIntroComplete = useCallback(() => {
    if (!loopMode) markIntroSeen()
    setIntroActive(false)
  }, [loopMode])

  useEffect(() => {
    document.documentElement.classList.toggle('light', light)
  }, [light])

  const openChain = (chainId: string) => {
    setSelectedChain(chainId)
    setView('chain')
  }

  return (
    <>
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

      {introActive ? (
        <StartupIntro
          mode={loopMode ? 'loop' : 'loading'}
          progress={progress}
          ready={ready}
          onComplete={handleIntroComplete}
        />
      ) : null}
    </>
  )
}
