import { useEffect, useState } from 'react'
import { Clock } from 'lucide-react'
import { authStrings as s } from '../authStrings'

export default function LoginExpiredPanel({
  fg,
  hint,
  accentColor,
  primaryBtnBg,
  primaryBtnFg,
  onCloseApp,
}: {
  fg: string
  hint: string
  accentColor: string
  primaryBtnBg: string
  primaryBtnFg: string
  onCloseApp: () => void
}) {
  const [revealed, setRevealed] = useState(false)

  useEffect(() => {
    setRevealed(false)
    const t = window.setTimeout(() => setRevealed(true), 40)
    return () => clearTimeout(t)
  }, [])

  return (
    <div
      className="w-full transition-all duration-200"
      style={{
        opacity: revealed ? 1 : 0,
        transform: revealed ? 'scale(1)' : 'scale(0.97)',
      }}
    >
      <div
        className="w-full rounded-2xl px-5 py-5 text-center"
        style={{
          border: `1px solid ${accentColor}2E`,
          background: `${accentColor}0D`,
        }}
      >
        <div
          className="mx-auto mb-3.5 flex h-11 w-11 items-center justify-center rounded-full"
          style={{ background: `${accentColor}1A` }}
        >
          <Clock className="h-5 w-5" style={{ color: accentColor }} />
        </div>
        <p className="text-sm font-semibold" style={{ color: fg }}>
          Время вышло
        </p>
        <p
          className="mt-1.5 text-xs leading-relaxed transition-opacity duration-200"
          style={{
            color: hint,
            opacity: revealed ? 1 : 0,
            transitionDelay: '90ms',
          }}
        >
          {s.bootstrapExpired}
        </p>
        <button
          type="button"
          onClick={onCloseApp}
          className="mt-4 w-full rounded-xl py-3 text-sm font-semibold transition-opacity duration-200"
          style={{
            background: primaryBtnBg,
            color: primaryBtnFg,
            opacity: revealed ? 1 : 0,
            transitionDelay: '160ms',
          }}
        >
          Закрыть приложение
        </button>
      </div>
    </div>
  )
}
