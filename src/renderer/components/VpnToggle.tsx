import { useCallback, useEffect, useRef, useState } from 'react'

/** Синхронно с Android MainScreen.kt */
const THUMB_SIZE = 48
const TRACK_W = 120
const TRACK_H = 60
const THUMB_TRAVEL = 64
const SNAKE_STROKE = 4
const SNAKE_ROTATION_MS = 2200
/** Минимум ~1.5 круга змейки при мгновенном ON (как на Android видно эффект). */
const SNAKE_MIN_VISIBLE_MS = Math.round(SNAKE_ROTATION_MS * 1.5)
const SNAKE_TAIL_START = 0.02
const SNAKE_HEAD_POS = 0.875
const THUMB_PULSE_MS = 520
const TRACK_PULSE_MS = 1500

function parseColor(hex: string): { r: number; g: number; b: number } {
  const h = hex.replace('#', '').trim()
  if (h.length === 6) {
    const n = parseInt(h, 16)
    return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 }
  }
  return { r: 0, g: 0, b: 0 }
}

function rgba(hex: string, alpha: number): string {
  const { r, g, b } = parseColor(hex)
  return `rgba(${r},${g},${b},${alpha})`
}

/**
 * Змейка: сегменты дуги на canvas (без createConicGradient и без CSS mask —
 * на Linux Electron оба варианта часто дают сплошной круг или пустоту).
 */
function SnakeRing({ color, size }: { color: string; size: number }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = Math.round(size * dpr)
    canvas.height = Math.round(size * dpr)
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

    const cx = size / 2
    const cy = size / 2
    const r = (size - SNAKE_STROKE) / 2
    const span = SNAKE_HEAD_POS - SNAKE_TAIL_START
    const steps = 56

    ctx.clearRect(0, 0, size, size)
    for (let i = 0; i < steps; i++) {
      const t0 = i / steps
      const t1 = (i + 1) / steps
      if (t1 < SNAKE_TAIL_START || t0 > SNAKE_HEAD_POS) continue
      const mid = (t0 + t1) / 2
      const alpha = Math.pow(Math.max(0, (mid - SNAKE_TAIL_START) / span), 4.4) * 0.98
      if (alpha < 0.03) continue
      const a0 = -Math.PI / 2 + t0 * Math.PI * 2
      const a1 = -Math.PI / 2 + t1 * Math.PI * 2
      ctx.beginPath()
      ctx.arc(cx, cy, r, a0, a1)
      ctx.strokeStyle = rgba(color, alpha)
      ctx.lineWidth = SNAKE_STROKE
      ctx.lineCap = 'round'
      ctx.stroke()
    }
  }, [color, size])

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 pointer-events-none vpn-toggle-snake"
      width={size}
      height={size}
      aria-hidden
      style={{ width: size, height: size }}
    />
  )
}

function VpnToggleThumb({
  showSnake,
  isConnected,
  travelX,
  bg,
  toggleOn,
  toggleOff,
  snakeColor,
}: {
  showSnake: boolean
  isConnected: boolean
  travelX: number
  bg: string
  toggleOn: string
  toggleOff: string
  snakeColor: string
}) {
  const thumbPulse = showSnake
  // При змейке обводку не рисуем — иначе толстое кольцо вокруг canvas.
  const showBorder = !showSnake
  const borderColor = isConnected ? toggleOn : toggleOff

  return (
    <div
      className="absolute top-1 left-1 z-[1]"
      style={{
        width: THUMB_SIZE,
        height: THUMB_SIZE,
        transform: `translateX(${travelX}px)`,
        transition: 'transform 0.38s cubic-bezier(0.34, 1.15, 0.64, 1)',
      }}
    >
      <div
        className={thumbPulse ? 'vpn-toggle-thumb-pulse' : undefined}
        style={{ width: THUMB_SIZE, height: THUMB_SIZE, position: 'relative' }}
      >
        <div
          className="absolute inset-0 rounded-full"
          style={{
            background: bg,
            border: showBorder ? `2px solid ${borderColor}` : '2px solid transparent',
            boxSizing: 'border-box',
          }}
        />
        {showSnake && <SnakeRing color={snakeColor} size={THUMB_SIZE} />}
      </div>
    </div>
  )
}

export default function VpnToggle({
  connected,
  connecting,
  disconnecting,
  toggleOn,
  toggleOff,
  fg,
  bg,
  onToggle,
}: {
  connected: boolean
  connecting: boolean
  disconnecting: boolean
  toggleOn: string
  toggleOff: string
  fg: string
  bg: string
  onToggle: () => void
}) {
  const [pendingToggle, setPendingToggle] = useState(false)
  const [pressed, setPressed] = useState(false)
  const pendingTimeoutRef = useRef<number | null>(null)
  // Пока змейка (1.5 оборота): бегунок слева. Потом сдвиг в ON.
  const visualOn = connected && !connecting && !disconnecting && !pendingToggle
  const showSnake = !visualOn && !disconnecting && (pendingToggle || connecting)
  const interactionLocked = connecting || disconnecting || pendingToggle

  useEffect(() => {
    if (disconnecting) {
      if (pendingTimeoutRef.current) {
        window.clearTimeout(pendingTimeoutRef.current)
        pendingTimeoutRef.current = null
      }
      setPendingToggle(false)
    }
  }, [disconnecting])

  useEffect(() => {
    return () => {
      if (pendingTimeoutRef.current) window.clearTimeout(pendingTimeoutRef.current)
    }
  }, [])

  const handleClick = useCallback(() => {
    if (interactionLocked) return
    // Змейка только при включении. При выключении — сразу в исходное положение.
    if (!connected) {
      setPendingToggle(true)
      if (pendingTimeoutRef.current) window.clearTimeout(pendingTimeoutRef.current)
      pendingTimeoutRef.current = window.setTimeout(() => {
        setPendingToggle(false)
        pendingTimeoutRef.current = null
      }, SNAKE_MIN_VISIBLE_MS)
    } else {
      setPendingToggle(false)
      if (pendingTimeoutRef.current) {
        window.clearTimeout(pendingTimeoutRef.current)
        pendingTimeoutRef.current = null
      }
    }
    onToggle()
  }, [connected, interactionLocked, onToggle])

  const pressScale = pressed && !interactionLocked ? 0.95 : 1

  return (
    <div style={{ paddingTop: 14, paddingBottom: 14 }}>
      <div
        role="button"
        tabIndex={0}
        aria-pressed={visualOn}
        aria-busy={interactionLocked}
        onClick={handleClick}
        onKeyDown={e => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            handleClick()
          }
        }}
        onPointerDown={() => { if (!interactionLocked) setPressed(true) }}
        onPointerUp={() => setPressed(false)}
        onPointerLeave={() => setPressed(false)}
        className="relative mx-auto select-none"
        style={{
          width: TRACK_W,
          height: TRACK_H,
          transform: `scale(${pressScale})`,
          transition: 'transform 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
          cursor: interactionLocked ? 'default' : 'pointer',
        }}
      >
        {visualOn && (
          <div
            className="absolute inset-0 rounded-full vpn-toggle-track-pulse pointer-events-none"
            style={{ background: rgba(toggleOn, 0.2) }}
          />
        )}
        <div
          className="absolute inset-0 rounded-full"
          style={{ background: visualOn ? toggleOn : toggleOff }}
        />
        <VpnToggleThumb
          showSnake={showSnake}
          isConnected={visualOn}
          travelX={visualOn ? THUMB_TRAVEL : 0}
          bg={bg}
          toggleOn={toggleOn}
          toggleOff={toggleOff}
          snakeColor={fg}
        />
      </div>
    </div>
  )
}

export { THUMB_PULSE_MS, TRACK_PULSE_MS, SNAKE_MIN_VISIBLE_MS }
