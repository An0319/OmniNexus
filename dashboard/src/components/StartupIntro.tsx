/**
 * 启动动画（§13.1 组件迁移，源：设计稿导出，原件不随本仓库分发）。
 * 三态状态机：loading（默认，完整叙事一遍 → 延长态等 ready）/ loop（?loop=1 调试循环）/
 * reduced-motion（静画 + 最短停留）。样式见同目录 startup-intro.css（作用域化迁移版）。
 */
import './startup-intro.css'
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react"

export type IntroProgress = {
  /** 已完成的加载阶段数 */
  done: number
  /** 总加载阶段数 */
  total: number
  /** 当前阶段描述（可选，展示于进度行） */
  label?: string
}

type StartupIntroProps = {
  onComplete: () => void
  /**
   * "loading"（默认）：完整播放一遍后进入延长态（Σ 静息 + 真实加载进度），
   * 等待 ready 信号后退出。
   * "loop"：调试模式，场景无限循环，仅「跳过」可退出。URL 加 ?loop=1 启用。
   */
  mode?: "loop" | "loading"
  /** 延长态展示的真实加载进度，由 App 层传入 */
  progress?: IntroProgress
  /** App 主界面就绪信号；loading 模式下 ready 为 true 时退出 */
  ready?: boolean
}

const domains = [
  { code: "ACA", label: "ACADEMIC", x: 180, y: 188, side: "left" },
  { code: "PUB", label: "PUBLIC", x: 118, y: 458, side: "left" },
  { code: "NWS", label: "NEWS", x: 254, y: 714, side: "left" },
  { code: "FIN", label: "MARKET", x: 1260, y: 188, side: "right" },
  { code: "IND", label: "INDUSTRY", x: 1322, y: 458, side: "right" },
  { code: "ALT", label: "ALTERNATIVE", x: 1186, y: 714, side: "right" },
]

const paths = [
  {
    id: "academic-path",
    d: "M180 188 C330 188 402 336 540 450",
    primary: false,
    start: "1.7s",
    speed: "3.4s",
  },
  {
    id: "public-path",
    d: "M118 458 C280 458 382 454 540 450",
    primary: true,
    start: "2.05s",
    speed: "3.1s",
  },
  {
    id: "news-path",
    d: "M254 714 C380 680 430 540 620 450",
    primary: false,
    start: "2.35s",
    speed: "3.6s",
  },
  {
    id: "market-path",
    d: "M1260 188 C1110 188 1032 336 900 450",
    primary: true,
    start: "1.9s",
    speed: "3.05s",
  },
  {
    id: "industry-path",
    d: "M1322 458 C1160 458 1058 454 900 450",
    primary: false,
    start: "2.25s",
    speed: "3.65s",
  },
  {
    id: "alternative-path",
    d: "M1186 714 C1060 680 1010 540 820 450",
    primary: false,
    start: "2.55s",
    speed: "3.85s",
  },
]

/** 第一遍叙事总时长（Σ 双环结束 + 停留），与原循环周期一致 */
const FIRST_PASS_MS = 12200
/** 减少动态下的最短静画停留 */
const REDUCED_MIN_HOLD_MS = 900

function SkipControl({ onSkip }: { onSkip: () => void }) {
  return (
    <button className="intro-skip" type="button" onClick={onSkip}>
      <span>跳过</span>
      <span className="intro-skip-divider" aria-hidden="true" />
      <span>SKIP</span>
    </button>
  )
}

/**
 * 延长态的真实加载进度：把加载阶段映射为 Σ 下方 T−LAG→T0 的采样点轨道
 * （y=580，避开 Σ 字形占位；延长态 Z-Score 面板已淡出，该区域净空）。
 * 每完成一个阶段点亮一格（复用 tick-align 的"对齐脉冲"语义），
 * 全部完成后时间轴中心做一次短促脉冲。视觉词汇全部复用既有系统，
 * 不引入新图形语言。
 */
function ProgressTrack({ progress }: { progress: IntroProgress }) {
  const total = Math.max(1, Math.floor(progress.total))
  const done = Math.min(Math.max(0, Math.floor(progress.done)), total)
  const xs = Array.from({ length: total }, (_, i) =>
    total > 1 ? 540 + (360 * i) / (total - 1) : 720,
  )
  return (
    <g className="progress-track" aria-hidden="true">
      {xs.map((x, i) => (
        <circle
          key={i}
          cx={x}
          cy={580}
          r={i < done ? 3.5 : 2.5}
          className={`progress-dot${i < done ? " progress-dot--done" : ""}`}
        />
      ))}
      <text x={720} y={622} textAnchor="middle" className="progress-meta">
        {(progress.label ?? "ALIGNING SOURCES").toUpperCase()} ·{" "}
        {String(done).padStart(2, "0")}/{String(total).padStart(2, "0")}
      </text>
      {done >= total ? (
        <circle
          key={`pulse-${done}`}
          cx={720}
          cy={580}
          r={8}
          className="progress-pulse"
        />
      ) : null}
    </g>
  )
}

export default function StartupIntro({
  onComplete,
  mode = "loading",
  progress,
  ready = false,
}: StartupIntroProps) {
  const [exiting, setExiting] = useState(false)
  const [cycle, setCycle] = useState(0)
  const [sceneVisible, setSceneVisible] = useState(true)
  const [extended, setExtended] = useState(false)
  const [minHoldDone, setMinHoldDone] = useState(false)
  const [motionReduced] = useState(
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  )
  const exitingRef = useRef(false)
  const sceneRef = useRef<SVGSVGElement>(null)
  const restartFrameRef = useRef<number | null>(null)
  const timersRef = useRef<number[]>([])

  const clearTimers = useCallback(() => {
    timersRef.current.forEach((timer) => window.clearTimeout(timer))
    timersRef.current = []
    if (restartFrameRef.current !== null) {
      window.cancelAnimationFrame(restartFrameRef.current)
      restartFrameRef.current = null
    }
  }, [])

  const beginExit = useCallback(() => {
    if (exitingRef.current) return
    exitingRef.current = true
    setExiting(true)
    clearTimers()
    timersRef.current.push(window.setTimeout(onComplete, 380))
  }, [clearTimers, onComplete])

  useEffect(() => {
    if (motionReduced) {
      // 减少动态：静画最短停留后允许退出（仍需 ready，避免退到未就绪的空屏）
      timersRef.current.push(
        window.setTimeout(() => setMinHoldDone(true), REDUCED_MIN_HOLD_MS),
      )
      return clearTimers
    }

    if (mode === "loop") {
      // 调试循环：Σ 停留后重播整段，仅跳过可退出
      timersRef.current.push(
        window.setTimeout(() => {
          setSceneVisible(false)
          restartFrameRef.current = window.requestAnimationFrame(() => {
            setCycle((current) => current + 1)
            setSceneVisible(true)
            restartFrameRef.current = null
          })
        }, FIRST_PASS_MS),
      )
    } else {
      // 第一遍播完进入延长态：Σ 与极光静息，等待真实加载
      timersRef.current.push(
        window.setTimeout(() => setExtended(true), FIRST_PASS_MS),
      )
    }
    return clearTimers
  }, [mode, motionReduced, cycle, clearTimers])

  // 退出条件：loading 模式 + 主界面就绪；
  // 正常模式等延长态（Σ 已在场），减少动态等最短停留
  useEffect(() => {
    if (mode !== "loading" || exitingRef.current || !ready) return
    if (motionReduced ? minHoldDone : extended) beginExit()
  }, [mode, ready, extended, minHoldDone, motionReduced, beginExit])

  useLayoutEffect(() => {
    const scene = sceneRef.current
    if (!scene) return

    scene.setCurrentTime(0)
    scene.getAnimations({ subtree: true }).forEach((animation) => {
      animation.currentTime = 0
      animation.play()
    })
  }, [cycle])

  return (
    <div
      className={`startup-intro${exiting ? " startup-intro--exiting" : ""}`}
      data-cycle={cycle}
      aria-label="跨域数据对齐与推理链启动视觉"
    >
      <div className="intro-aurora" aria-hidden="true" />

      {sceneVisible ? (
        <svg
          key={cycle}
          ref={sceneRef}
          className="constellation"
          viewBox="0 0 1440 900"
          preserveAspectRatio="xMidYMid slice"
          aria-hidden="true"
          focusable="false"
        >
        <defs>
          <filter id="soft-glow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="5" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <linearGradient id="score-gradient" x1="0" x2="1">
            <stop offset="0" stopColor="var(--intro-text-4)" stopOpacity="0" />
            <stop offset=".58" stopColor="var(--intro-accent-mid)" />
            <stop offset="1" stopColor="var(--intro-accent)" stopOpacity="0" />
          </linearGradient>
        </defs>

        <g className="coordinate-field">
          <path d="M510 450 H930" className="time-axis" />
          {[540, 620, 720, 820, 900].map((x, index) => (
            <g className={`axis-tick axis-tick--${index + 1}`} key={x}>
              <path d={`M${x} 438 V462`} />
              <circle cx={x} cy="450" r="3" />
            </g>
          ))}
          <text x="510" y="481" className="axis-meta">
            T−LAG
          </text>
          <text x="899" y="481" className="axis-meta">
            T0
          </text>
        </g>

        <g className="path-field">
          {paths.map((path) => (
            <g key={path.id}>
              <path
                id={path.id}
                d={path.d}
                className={`domain-path${
                  path.primary ? " domain-path--primary" : ""
                }`}
              />
              <circle
                r={path.primary ? "3.5" : "2.5"}
                className={`flow-particle${
                  path.primary ? " flow-particle--primary" : ""
                }`}
              >
                <animateMotion
                  path={path.d}
                  begin={path.start}
                  dur={path.speed}
                  repeatCount="2"
                  fill="freeze"
                />
              </circle>
              {path.primary ? (
                <circle r="2.5" className="flow-particle flow-particle--echo">
                  <animateMotion
                    path={path.d}
                    begin={`${Number.parseFloat(path.start) + 0.75}s`}
                    dur={path.speed}
                    repeatCount="2"
                    fill="freeze"
                  />
                </circle>
              ) : null}
            </g>
          ))}
        </g>

        <g className="domain-field">
          {domains.map((domain, index) => (
            <g
              className={`domain-node domain-node--${index + 1}`}
              transform={`translate(${domain.x} ${domain.y})`}
              key={domain.code}
            >
              <circle className="domain-node-ring" r="27" />
              <circle className="domain-node-core" r="5" />
              <path d="M-38 0 H-29 M29 0 H38 M0 -38 V-29 M0 29 V38" />
              <text
                x={domain.side === "left" ? 46 : -46}
                y="-4"
                textAnchor={domain.side === "left" ? "start" : "end"}
                className="domain-code"
              >
                {domain.code}
              </text>
              <text
                x={domain.side === "left" ? 46 : -46}
                y="13"
                textAnchor={domain.side === "left" ? "start" : "end"}
                className="domain-label"
              >
                {domain.label}
              </text>
            </g>
          ))}
        </g>

        <g className="inference-field">
          <path d="M540 450 C588 400 662 502 720 450 S846 398 900 450" />
          <circle cx="540" cy="450" r="5" />
          <circle cx="620" cy="450" r="5" />
          <circle cx="720" cy="450" r="5" />
          <circle cx="820" cy="450" r="5" />
          <circle cx="900" cy="450" r="5" />
        </g>

        <g className="zscore-field">
          <path d="M490 596 H950" className="score-reference" />
          <path
            d="M490 624 C526 620 548 628 580 619 C612 610 636 632 666 618 C700 602 724 625 754 600 C784 574 805 612 834 555 C858 510 882 578 916 544 C930 530 941 526 950 528"
            className="score-wave"
          />
          <text x="490" y="585" className="score-meta">
            EXPECTATION GAP / Z
          </text>
          <text x="950" y="585" textAnchor="end" className="score-meta">
            THRESHOLD
          </text>
          <circle cx="834" cy="555" r="8" className="score-pulse" />
        </g>

        {mode === "loading" && (extended || motionReduced) ? (
          <ProgressTrack progress={progress ?? { done: 0, total: 1 }} />
        ) : null}

        <g className="formula-lockup">
          <text x="720" y="334" textAnchor="middle">
            ALIGN × LAG × Z
          </text>
          <path d="M640 350 H800" />
        </g>

        <g className="origin-mark">
          <path d="M678 390 H650 V418 M762 390 H790 V418 M678 510 H650 V482 M762 510 H790 V482" />
          <circle cx="720" cy="450" r="78" />
          <circle cx="720" cy="450" r="102" />
        </g>

        <g className="sigma-lockup" filter="url(#soft-glow)">
          <text x="720" y="499" textAnchor="middle">
            Σ
          </text>
          <circle
            cx="720"
            cy="450"
            r="76"
            className="sigma-ring sigma-ring--one"
          />
          <circle
            cx="720"
            cy="450"
            r="76"
            className="sigma-ring sigma-ring--two"
          />
        </g>
        </svg>
      ) : null}

      <div className="intro-system-note" aria-hidden="true">
        <span>INFERENCE CORE</span>
        <span>ALIGN / TRACE / EXPLAIN</span>
      </div>

      <SkipControl onSkip={beginExit} />
    </div>
  )
}
