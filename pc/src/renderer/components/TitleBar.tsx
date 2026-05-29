import { ReactNode } from 'react'

/** Top bar: title слева (как Android login), actions справа. */
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
      className="h-8 flex-shrink-0 flex items-center justify-between px-2 border-b"
      style={{
        background: headerBg,
        borderColor: 'rgba(0,0,0,0.06)',
        WebkitAppRegion: 'drag',
      } as React.CSSProperties}
    >
      <span className="text-[11px] tracking-widest shrink-0" style={{ color: headerFg }}>
        {title}
      </span>
      <div
        className="flex items-center justify-end gap-1 shrink-0"
        style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
      >
        {right}
      </div>
    </div>
  )
}
