import { useCallback, useEffect, useId, useRef, useState } from 'react'
import type { AppearanceMode } from '../clientTheme'

const SIZE = 18
const VIEW = 24
const CX = 12
const CY = 12
const DISC_R = 5
const DURATION_MS = 520

function easeOutCubic(t: number) {
  return 1 - (1 - t) ** 3
}

/**
 * Telegram-style sun ↔ moon: rAF morph (CSS mask transitions are janky in Electron).
 * Monochrome via `color` (theme fg).
 */
export default function ThemeModeToggle({
  mode,
  onToggle,
  color,
}: {
  mode: AppearanceMode
  onToggle: () => void
  color: string
  fg?: string
  trackOff?: string
  trackOn?: string
}) {
  const dark = mode === 'dark'
  const target = dark ? 1 : 0
  const [pressed, setPressed] = useState(false)
  const [reduced, setReduced] = useState(false)
  const progressRef = useRef(target)
  const [progress, setProgress] = useState(target)
  const rafRef = useRef(0)
  const startRef = useRef({ t0: 0, from: target, to: target })

  const uid = useId().replace(/:/g, '')
  const maskId = `silent-tm-${uid}`

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    setReduced(mq.matches)
    const onChange = () => setReduced(mq.matches)
    mq.addEventListener?.('change', onChange)
    return () => mq.removeEventListener?.('change', onChange)
  }, [])

  useEffect(() => {
    if (reduced) {
      progressRef.current = target
      setProgress(target)
      return
    }
    cancelAnimationFrame(rafRef.current)
    const from = progressRef.current
    const to = target
    if (Math.abs(from - to) < 0.001) {
      progressRef.current = to
      setProgress(to)
      return
    }
    startRef.current = { t0: performance.now(), from, to }
    const tick = (now: number) => {
      const { t0, from: f, to: dest } = startRef.current
      const u = Math.min(1, (now - t0) / DURATION_MS)
      const p = f + (dest - f) * easeOutCubic(u)
      progressRef.current = p
      setProgress(p)
      if (u < 1) rafRef.current = requestAnimationFrame(tick)
      else {
        progressRef.current = dest
        setProgress(dest)
      }
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [target, reduced])

  const handle = useCallback(() => onToggle(), [onToggle])
  const t = progress
  const rayOpacity = Math.max(0, 1 - t * 1.15)
  const rayScale = 1 - 0.55 * t
  const rayRot = 90 * t
  // Mask circle: off-screen at t=0 → carves crescent at t=1
  const maskCx = 17 + (1 - t) * 10
  const maskCy = 9 - (1 - t) * 8
  const maskR = 5.2 + 2.3 * t
  const discScale = 1 + 0.1 * t
  const discRot = -28 * t

  return (
    <button
      type="button"
      aria-label={dark ? 'Светлая тема' : 'Тёмная тема'}
      aria-pressed={dark}
      title={dark ? 'Светлая тема' : 'Тёмная тема'}
      onClick={handle}
      onPointerDown={() => setPressed(true)}
      onPointerUp={() => setPressed(false)}
      onPointerLeave={() => setPressed(false)}
      className="relative shrink-0 flex items-center justify-center select-none"
      style={{
        width: 22,
        height: 22,
        padding: 0,
        margin: 0,
        border: 'none',
        background: 'transparent',
        cursor: 'pointer',
        transform: `scale(${pressed ? 0.88 : 1})`,
        transition: 'transform 140ms cubic-bezier(0.32, 0.72, 0, 1)',
        WebkitAppRegion: 'no-drag',
        color,
      } as React.CSSProperties}
    >
      <svg width={SIZE} height={SIZE} viewBox={`0 0 ${VIEW} ${VIEW}`} aria-hidden style={{ display: 'block', overflow: 'visible' }}>
        <defs>
          <mask id={maskId}>
            <rect width={VIEW} height={VIEW} fill="white" />
            <circle cx={maskCx} cy={maskCy} r={maskR} fill="black" />
          </mask>
        </defs>

        <g
          stroke="currentColor"
          strokeWidth="1.65"
          strokeLinecap="round"
          fill="none"
          opacity={rayOpacity}
          style={{
            transformOrigin: `${CX}px ${CY}px`,
            transform: `rotate(${rayRot}deg) scale(${rayScale})`,
          }}
        >
          <path d="M12 2.2v2.4M12 19.4v2.4M2.2 12h2.4M19.4 12h2.4" />
          <path d="M4.85 4.85l1.7 1.7M17.45 17.45l1.7 1.7M4.85 19.15l1.7-1.7M17.45 6.55l1.7-1.7" />
        </g>

        <circle
          cx={CX}
          cy={CY}
          r={DISC_R}
          fill="currentColor"
          mask={`url(#${maskId})`}
          style={{
            transformOrigin: `${CX}px ${CY}px`,
            transform: `rotate(${discRot}deg) scale(${discScale})`,
          }}
        />
      </svg>
    </button>
  )
}
