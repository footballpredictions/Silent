import { ReactNode } from 'react'

/** Centered title with optional right actions (narrow 265px window). */
export default function TitleBar({
  title,
  right,
  headerBg = '#000000',
  headerFg = '#9CA3AF',
}: {
  title: string
  right?: ReactNode
  headerBg?: string
  headerFg?: string
}) {
  return (
    <div
      className="h-8 flex-shrink-0 grid grid-cols-[1fr_auto_1fr] items-center px-2 border-b"
      style={{
        background: headerBg,
        borderColor: 'rgba(0,0,0,0.06)',
        WebkitAppRegion: 'drag',
      } as React.CSSProperties}
    >
      <div />
      <span
        className="text-[11px] tracking-widest text-center col-start-2"
        style={{ color: headerFg }}
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
