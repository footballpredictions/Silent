import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react'

type Props = {
  page: number
  pages: number
  onPageChange: (page: number) => void
  disabled?: boolean
  className?: string
}

export default function ListPagination({
  page,
  pages,
  onPageChange,
  disabled = false,
  className = '',
}: Props) {
  const [pageInput, setPageInput] = useState(String(page))

  useEffect(() => {
    setPageInput(String(page))
  }, [page])

  if (pages <= 1) return null

  const goToPage = (raw: number) => {
    if (!Number.isFinite(raw)) return
    const next = Math.min(pages, Math.max(1, Math.trunc(raw)))
    onPageChange(next)
    setPageInput(String(next))
  }

  const commitPageInput = () => {
    const parsed = Number.parseInt(pageInput.replace(/\D/g, ''), 10)
    if (!Number.isFinite(parsed)) {
      setPageInput(String(page))
      return
    }
    goToPage(parsed)
  }

  const btn =
    'inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-[#2a2a2a] text-xs text-[#ccc] disabled:opacity-40 hover:border-[#444] cursor-pointer'
  const iconBtn =
    'inline-flex items-center justify-center px-2 py-1.5 rounded-lg border border-[#2a2a2a] text-xs text-[#ccc] disabled:opacity-40 hover:border-[#444] cursor-pointer'

  return (
    <div className={`flex items-center justify-between gap-3 ${className}`.trim()}>
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          disabled={page <= 1 || disabled}
          onClick={() => goToPage(1)}
          title="В начало"
          aria-label="В начало"
          className={iconBtn}
        >
          <ChevronsLeft className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          disabled={page <= 1 || disabled}
          onClick={() => goToPage(page - 1)}
          className={btn}
        >
          <ChevronLeft className="w-3.5 h-3.5" /> Назад
        </button>
      </div>
      <div className="flex items-center gap-1.5 text-xs text-[#666]">
        <input
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          value={pageInput}
          disabled={disabled}
          onChange={e => setPageInput(e.target.value.replace(/\D/g, '').slice(0, 6))}
          onBlur={commitPageInput}
          onKeyDown={e => {
            if (e.key === 'Enter') {
              e.preventDefault()
              commitPageInput()
              ;(e.target as HTMLInputElement).blur()
            } else if (e.key === 'Escape') {
              setPageInput(String(page))
              ;(e.target as HTMLInputElement).blur()
            }
          }}
          aria-label="Номер страницы"
          title="Введите номер страницы и нажмите Enter"
          className="w-12 px-2 py-1 rounded-lg border border-[#2a2a2a] bg-[#0a0a0a] text-center text-[#ccc] outline-none focus:border-[#3b82f6] disabled:opacity-40"
        />
        <span>/ {pages}</span>
      </div>
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          disabled={page >= pages || disabled}
          onClick={() => goToPage(page + 1)}
          className={btn}
        >
          Вперёд <ChevronRight className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          disabled={page >= pages || disabled}
          onClick={() => goToPage(pages)}
          title="В конец"
          aria-label="В конец"
          className={iconBtn}
        >
          <ChevronsRight className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  )
}
