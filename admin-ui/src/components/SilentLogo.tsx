/** Brand mark for admin UI — same proportions as mobile login (56 / 16 / 22). */
export default function SilentLogo({ size = 56, className = '' }: { size?: number; className?: string }) {
  const radius = Math.round(size * (16 / 56))
  const src = size <= 40 ? '/logo-32.png' : '/logo.png'
  return (
    <img
      src={src}
      alt="Silent"
      width={size}
      height={size}
      className={className}
      style={{ width: size, height: size, borderRadius: radius }}
    />
  )
}
