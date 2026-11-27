type Platform = 'pc' | 'mac' | 'linux'

export default function InstallerIcon({ platform, surface }: { platform: Platform; surface: string }) {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {platform === 'linux' ? <>
      <ellipse fill="currentColor" stroke="none" cx="8.2" cy="21.4" rx="2.4" ry="1.15"/>
      <ellipse fill="currentColor" stroke="none" cx="15.8" cy="21.4" rx="2.4" ry="1.15"/>
      <path fill="currentColor" stroke="none" d="M12 3.2c-2.6 0-4.6 2-4.6 4.5 0 .55.1 1.05.28 1.5C5.4 10.5 3.8 13 3.8 15.8c0 3.7 3.5 6.2 8.2 6.2s8.2-2.5 8.2-6.2c0-2.8-1.6-5.3-3.88-6.6.18-.45.28-.95.28-1.5 0-2.5-2-4.5-4.6-4.5z"/>
      <ellipse fill={surface} stroke="none" cx="12" cy="15.6" rx="3.5" ry="5.1"/>
      <path fill="currentColor" stroke="none" d="M6.2 12.2c-2.4 1.1-3.6 3.4-3 5.6 1.7-1.4 3.1-2.6 3.8-4.8-.3-.25-.55-.55-.8-.8z"/>
      <path fill="currentColor" stroke="none" d="M17.8 12.2c2.4 1.1 3.6 3.4 3 5.6-1.7-1.4-3.1-2.6-3.8-4.8.3-.25.55-.55.8-.8z"/>
      <circle fill="currentColor" stroke="none" cx="12" cy="7.1" r="4.15"/>
      <path fill="currentColor" stroke="none" d="M12.15 8.15 L17.1 9.35 L12.15 10.7 Z"/>
      <circle fill={surface} stroke="none" cx="10.25" cy="6.25" r="1.2"/>
      <circle fill={surface} stroke="none" cx="13.75" cy="6.25" r="1.2"/>
      <circle fill="currentColor" stroke="none" cx="10.55" cy="6.45" r="0.52"/>
      <circle fill="currentColor" stroke="none" cx="14.05" cy="6.45" r="0.52"/>
      </> : platform === 'mac' ? <>
      <rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8M12 17v4"/><path fill="currentColor" stroke="none" transform="translate(6.6 5.1) scale(.45)" d="M17.1 12.3c0-2.1 1.7-3.1 1.8-3.2-1-1.5-2.6-1.7-3.2-1.7-1.4-.2-2.7.8-3.4.8-.7 0-1.8-.8-3-.8-1.5 0-3 .9-3.8 2.2-1.6 2.7-.4 6.8 1.1 9 .7 1.1 1.6 2.2 2.8 2.2 1.1 0 1.6-.7 3-.7s1.8.7 3 .7 2-1.1 2.7-2.1c.8-1.2 1.2-2.4 1.2-2.5-.1 0-2.2-.9-2.2-3.9ZM14.8 6c.6-.8 1.1-1.9 1-3-.9 0-2.1.6-2.8 1.4-.6.7-1.2 1.8-1 2.9 1 .1 2.1-.5 2.8-1.3Z"/>
      </> : <>
      <rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>
      </>}
    </svg>
  )
}
