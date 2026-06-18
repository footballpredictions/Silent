const VK_ANDROID_CLIENT_ID = 6287487
const VK_REDIRECT = 'https://oauth.vk.com/blank.html'

export function buildVkAndroidOAuthUrl(state: string): string {
  const params = new URLSearchParams({
    client_id: String(VK_ANDROID_CLIENT_ID),
    redirect_uri: VK_REDIRECT,
    response_type: 'token',
    scope: 'offline',
    state,
    display: 'page',
    revoke: '1',
  })
  return `https://oauth.vk.com/authorize?${params.toString()}`
}
