import { ArrowUpDown, ChevronDown } from 'lucide-react'

export type SortOption = { value: string; label: string }

type Props = {
  value: string
  onChange: (value: string) => void
  options: SortOption[]
  className?: string
  label?: string
}

/** Компактный селект сортировки — тот же визуальный ряд, что SearchInput. */
export default function SortSelect({
  value,
  onChange,
  options,
  className = '',
  label = 'Сортировка',
}: Props) {
  return (
    <div className={`relative ${className}`}>
      <ArrowUpDown className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#555] pointer-events-none" />
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        aria-label={label}
        className="w-full appearance-none pl-8 pr-7 py-1.5 text-xs bg-[#0a0a0a] border border-[#2a2a2a] rounded-lg text-white focus:outline-none focus:border-[#444] cursor-pointer"
      >
        {options.map(o => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#555] pointer-events-none" />
    </div>
  )
}
