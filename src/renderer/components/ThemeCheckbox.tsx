/** Чекбокс как Android CheckboxDefaults — checkedColor = fg, не системный синий. */
export default function ThemeCheckbox({
  checked,
  onChange,
  disabled,
  fg,
  bg,
  border,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
  fg: string
  bg: string
  border: string
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="shrink-0 flex items-center justify-center rounded transition-colors disabled:opacity-40"
      style={{
        width: 18,
        height: 18,
        border: `2px solid ${checked ? fg : border}`,
        background: checked ? fg : 'transparent',
        cursor: disabled ? 'default' : 'pointer',
      }}
    >
      {checked && (
        <svg width="10" height="8" viewBox="0 0 10 8" fill="none" aria-hidden>
          <path
            d="M1 4L3.5 6.5L9 1"
            stroke={bg}
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </button>
  )
}
