import { Search } from 'lucide-react'

type Props = {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  className?: string
}

/** Единый стиль поиска в админке (дашборд, пользователи, подписки). */
export default function SearchInput({
  value,
  onChange,
  placeholder = 'Поиск…',
  className = '',
}: Props) {
  return (
    <div className={`relative min-w-0 max-w-full ${className}`}>
      <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#555] pointer-events-none" />
      <input
        type="search"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full max-w-full min-w-0 pl-8 pr-3 py-1.5 text-xs bg-[#0a0a0a] border border-[#2a2a2a] rounded-lg text-white placeholder:text-[#555] focus:outline-none focus:border-[#444]"
      />
    </div>
  )
}
