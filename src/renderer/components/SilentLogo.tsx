import { useEffect, useState } from 'react'

/** Brand mark: black rounded square + white S, or remote image from theme.logo_url. */
export default function SilentLogo({
  size = 56,
  className = '',
  imageUrl,
}: {
  size?: number
  className?: string
  imageUrl?: string | null
}) {
  const radius = Math.round(size * (16 / 56))
  const fontSize = Math.round(size * (22 / 56))
  const src = (imageUrl || '').trim()
  const [imgFailed, setImgFailed] = useState(false)

  useEffect(() => {
    setImgFailed(false)
  }, [src])

  if (src && !imgFailed) {
    return (
      <img
        src={src}
        alt="Silent VPN"
        width={size}
        height={size}
        className={`inline-block object-cover select-none ${className}`}
        style={{ width: size, height: size, borderRadius: radius }}
        onError={() => setImgFailed(true)}
      />
    )
  }

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
