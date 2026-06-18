/** Сравнение профиля без last_connected — не считаем «изменением» heartbeat устройств. */
export function profileSyncFingerprint(profile: unknown): string {
  if (!profile || typeof profile !== 'object') return ''
  const p = profile as Record<string, unknown>
  const sub = (p.subscription as Record<string, unknown> | undefined) || {}
  const devices = Array.isArray(p.devices) ? p.devices : []
  const devFp = devices
    .map(d => {
      const x = d as Record<string, unknown>
      return [
        x.id,
        x.device_name,
        x.device_type,
        x.is_active,
        x.is_connected,
      ].join(':')
    })
    .sort()
    .join('|')
  return [
    p.email,
    p.display_id,
    p.is_admin,
    p.devices_count,
    p.max_devices,
    p.connected_count,
    sub.plan_type,
    sub.is_active,
    sub.expires_at,
    sub.days_left,
    devFp,
  ].join('\n')
}
