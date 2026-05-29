/** Login flow copy — keep in sync with Android HashInputSection / MainViewModel. */
export const authStrings = {
  step1Title: 'Шаг 1 — хеш звонка VK',
  step1Hint:
    'Временный интернет на 2 минуты — только для входа или регистрации. По истечении хеш сбросится.',
  hashPlaceholder: 'Хеш или ссылка на звонок VK',
  connectBtn: 'Подключить для входа',
  connecting: 'Подключение…',
  connectingWait: 'Подключение… подождите',
  channelReady: 'Канал готов. Можно войти или зарегистрироваться.',
  connectedBtn: 'Подключено ✓',
  invalidHash: 'Неверный хеш. Вставьте ссылку vk.com/call/join/… или сам хеш',
  bootstrapFail: 'Не удалось получить bootstrap-конфиг или подключиться',
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
