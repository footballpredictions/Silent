/** Brand mark: black rounded square + white S (Android: 56dp / 16dp radius / 22sp). */
export default function SilentLogo({ size = 56, className = '' }: { size?: number; className?: string }) {
  const radius = Math.round(size * (16 / 56))
  const fontSize = Math.round(size * (22 / 56))
  return (
    <div
      className={`inline-flex items-center justify-center bg-black text-white font-bold leading-none select-none ${className}`}
      style={{ width: size, height: size, borderRadius: radius, fontSize }}
      aria-hidden
    >
      S
    </div>
  )
}
