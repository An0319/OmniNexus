/**
 * 看板外壳：启动动画前置层（§13.1 组件迁移方案 A）+ 顶栏导航 + 四页切换
 * （无路由库，轻量 state）+ 固定免责条。
 *
 * 红线：只读 data/ 与 chains/；不触发回测、不写账本；私有阶段只本地跑。
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import StartupIntro, { type IntroProgress } from './components/StartupIntro'
import { buildChainViews, profiles, streak } from './data'
import { fmtUtc } from './format'
import { useI18n } from './i18n/I18nProvider'
import type { MessageKey } from './i18n/messages.zh'
import { About } from './pages/About'
import { ChainDetail } from './pages/ChainDetail'
import { Overview } from './pages/Overview'
import { Timeline } from './pages/Timeline'

type View = 'overview' | 'chain' | 'timeline' | 'about'

const NAV: { id: View; labelKey: MessageKey }[] = [
  { id: 'overview', labelKey: 'app.nav.overview' },
  { id: 'chain', labelKey: 'app.nav.chain' },
  { id: 'timeline', labelKey: 'app.nav.timeline' },
  { id: 'about', labelKey: 'app.nav.about' },
]

// ── 启动动画接入（§13.1）──────────────────────────────────────────
// 真实加载进度：每格对应一个真实事件（字体解码 / 各链配置加载 / 首帧合成）。
// 链阶段由实际链清单生成，新增链自动多一格，不在代码里写死数量。
// 数据模块在构建期已随主包内联、resolve 极快，故加节奏阀：每格点亮最短间隔
// 400ms，真实进度与节奏进度取较慢者——真实快则保仪式完整，真实慢则跟真实（诚实）。
type IntroStage = {
  labelKey: MessageKey
  labelParams?: Record<string, string>
  task: () => Promise<unknown>
}

const profileLoaders = import.meta.glob('../../chains/*.profile.json')

function buildIntroStages(): IntroStage[] {
  return [
    { labelKey: 'intro.stage.calibrating', task: () => document.fonts.ready },
    ...profiles.map((profile) => ({
      labelKey: 'intro.stage.chain' as MessageKey,
      labelParams: { chainId: profile.chain_id.toUpperCase() },
      task: () => {
        const load = profileLoaders[`../../chains/${profile.chain_id}.profile.json`]
        return load ? load() : Promise.resolve()
      },
    })),
    { labelKey: 'intro.stage.ledger', task: () => import('../../data/streak.json') },
    {
      labelKey: 'intro.stage.views',
      // 视图构建完成 = 主体首帧合成（App 数据为构建期静态导入，挂载即就绪）
      task: () =>
        new Promise<void>((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
        ),
    },
  ]
}
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

function useIntroBoot(active: boolean, stages: IntroStage[]) {
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
      for (const { task } of stages) {
        await Promise.all([task(), pace()])
        if (cancelled) return
        setDone((current) => Math.min(stages.length, current + 1))
      }
    })()

    return () => {
      cancelled = true
      timers.forEach((timer) => window.clearTimeout(timer))
    }
  }, [active, stages])

  return { done, ready: done >= stages.length }
}

function DisclaimerBar() {
  const { t } = useI18n()
  return (
    <div className="disclaimer-bar" role="contentinfo">
      <span>
        <strong>{t('app.disclaimer.title')}</strong> {t('app.disclaimer.text')}
      </span>
      <span>{t('app.disclaimer.dataAsOf', { date: fmtUtc(streak.last_run_utc) })}</span>
    </div>
  )
}

export default function App() {
  const { t } = useI18n()
  const [light, setLight] = useState(false)
  const [view, setView] = useState<View>('overview')
  const chains = useMemo(() => buildChainViews(), [])
  const introStages = useMemo(() => buildIntroStages(), [])
  // 默认选中链取自实际链清单首项，不在代码里写死 chain01。
  const [selectedChain, setSelectedChain] = useState(() => chains[0]?.chainId ?? '')
  // ?loop=1 调试模式：绕过会话记忆，每次都播循环
  const [loopMode] = useState(() =>
    new URLSearchParams(window.location.search).has('loop'),
  )
  const [introActive, setIntroActive] = useState(
    () => loopMode || !readIntroSeen(),
  )

  const { done, ready } = useIntroBoot(introActive && !loopMode, introStages)
  const currentStage = introStages[Math.min(done, introStages.length - 1)]
  const progress: IntroProgress = {
    done,
    total: introStages.length,
    label: currentStage ? t(currentStage.labelKey, currentStage.labelParams) : undefined,
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
            <span className="brand-name">{t('app.brand.name')}</span>
            <span className="brand-sub">{t('app.brand.sub')}</span>
          </div>

          <nav className="app-nav" aria-label={t('app.nav.aria')}>
            {NAV.map((item) => (
              <button
                type="button"
                key={item.id}
                className={`nav-item${view === item.id ? ' is-active' : ''}`}
                aria-current={view === item.id ? 'page' : undefined}
                onClick={() => setView(item.id)}
              >
                {t(item.labelKey)}
              </button>
            ))}
          </nav>

          <button
            type="button"
            className="theme-toggle"
            onClick={() => setLight((value) => !value)}
            aria-label={light ? t('app.theme.toDark') : t('app.theme.toLight')}
          >
            {light ? t('app.theme.dark') : t('app.theme.light')}
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
