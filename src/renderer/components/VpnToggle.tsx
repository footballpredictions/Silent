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

function buildSnakeStops(snakeColor: string): { offset: number; color: string }[] {
  const stops: { offset: number; color: string }[] = []
  const span = SNAKE_HEAD_POS - SNAKE_TAIL_START
  const steps = 96
  const transparent = 'rgba(0,0,0,0)'

  stops.push({ offset: 0, color: transparent })
  stops.push({ offset: SNAKE_TAIL_START - 0.002, color: transparent })

  for (let i = 0; i <= steps; i++) {
    const t = i / steps
    const pos = SNAKE_TAIL_START + span * t
    const alpha = Math.pow(t, 4.4) * 0.98
    stops.push({ offset: pos, color: rgba(snakeColor, alpha) })
  }

  let gap = SNAKE_HEAD_POS + 0.003
  while (gap <= 1) {
    stops.push({ offset: gap, color: transparent })
    gap += 0.02
  }
  stops.push({ offset: 1, color: transparent })
  return stops
}

/** Один stroke + conic gradient (аналог Android SweepGradient), без сегментов. */
function drawSnakeRing(
  ctx: CanvasRenderingContext2D,
  size: number,
  snakeColor: string,
  rotationDeg: number,
) {
  const cx = size / 2
  const cy = size / 2
  const strokePx = SNAKE_STROKE
  const radius = (size - strokePx) / 2
  const startAngle = ((rotationDeg - 90) * Math.PI) / 180

  const grad = ctx.createConicGradient(startAngle, cx, cy)
  for (const { offset, color } of buildSnakeStops(snakeColor)) {
    const pos = Math.min(1, Math.max(0, offset))
    grad.addColorStop(pos, color)
  }

  ctx.beginPath()
  ctx.arc(cx, cy, radius, 0, Math.PI * 2)
  ctx.strokeStyle = grad
  ctx.lineWidth = strokePx
  ctx.lineCap = 'round'
  ctx.stroke()

  const headAngle = startAngle + SNAKE_HEAD_POS * Math.PI * 2
  const hx = cx + radius * Math.cos(headAngle)
  const hy = cy + radius * Math.sin(headAngle)
  ctx.beginPath()
  ctx.arc(hx, hy, strokePx / 2, 0, Math.PI * 2)
  ctx.fillStyle = snakeColor
  ctx.fill()
}

function SnakeRing({ color, size }: { color: string; size: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef(0)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.round(size * dpr)
    canvas.height = Math.round(size * dpr)
    canvas.style.width = `${size}px`
    canvas.style.height = `${size}px`

    const t0 = performance.now()
    const tick = (now: number) => {
      const rot = (((now - t0) % SNAKE_ROTATION_MS) / SNAKE_ROTATION_MS) * 360
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, size, size)
      drawSnakeRing(ctx, size, color, rot)
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [color, size])

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 pointer-events-none"
      aria-hidden
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
  const showBorder = !showSnake
  const thumbPulse = showSnake
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
