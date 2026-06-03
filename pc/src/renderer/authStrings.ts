/** Login flow copy — keep in sync with Android HashInputSection / MainViewModel. */
export const authStrings = {
  step1Title: 'Шаг 1 — хеш звонка VK',
  step1Hint:
    'Временный интернет на 2 минуты — только для входа или регистрации. По истечении хеш сбросится.',
  hashPlaceholder: 'Хеш или ссылка на звонок VK',
  connectBtn: 'Подключить для входа',
  connecting: 'Подключение…',
  connectingWait: 'Подключение… подождите',
  channelReadyAlready: 'Канал готов. Можно войти или зарегистрироваться.',
  channelReady: 'Канал готов. Войдите или зарегистрируйтесь (2 мин).',
  connectedBtn: 'Подключено ✓',
  invalidHash: 'Неверный хеш. Вставьте ссылку vk.com/call/join/… или сам хеш',
  bootstrapFail:
    'Интернет через VPN не поднялся. Проверьте хеш и попробуйте снова.',
  needBootstrap: 'Сначала нажмите «Подключить для входа»',
  internetOff: 'Интернет отключён. VPN включайте на главном экране.',
  confirmEmail: 'Подтвердите email',
  emailSent: (email: string) => `Ссылка отправлена на ${email}`,
  login: 'Войти',
  register: 'Регистрация',
  registerSubmit: 'Зарегистрироваться',
  email: 'Email',
  password: 'Пароль',
} as const
