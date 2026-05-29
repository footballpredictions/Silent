import { ReactNode } from 'react'

/** Centered title with optional right actions (narrow 265px window). */
export default function TitleBar({
  title,
  right,
  dark = false,
}: {
  title: string
  right?: ReactNode
  dark?: boolean
}) {
  return (
    <div
      className="h-8 flex-shrink-0 grid grid-cols-[1fr_auto_1fr] items-center px-2"
      style={{
        background: dark ? '#000000' : undefined,
        WebkitAppRegion: 'drag',
      } as React.CSSProperties}
    >
      <div />
      <span
        className="text-[11px] tracking-widest text-center col-start-2"
        style={{ color: dark ? '#9CA3AF' : '#6B7280' }}
      >
        {title}
      </span>
      <div
        className="col-start-3 flex items-center justify-end gap-1"
        style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
      >
        {right}
      </div>
    </div>
  )
}
