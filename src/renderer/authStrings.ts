/** Login flow copy — keep in sync with Android LoginScreen / MainViewModel. */
export const authStrings = {
  authTitle: 'Вход или регистрация',
  connecting: 'Подключение…',
  connectingWait: 'Подключение… подождите',
  channelReady: 'Канал готов. Войдите или зарегистрируйтесь (2 мин).',
  bootstrapFail:
    'Интернет через VPN не поднялся. Закройте приложение и запустите снова.',
  bootstrapExpired:
    'Время временного интернета истекло (2 мин). Закройте приложение и запустите снова.',
  needBootstrap: 'Временный канал не поднялся. Закройте приложение и запустите снова.',
  internetOff: 'Интернет отключён. VPN включайте на главном экране.',
  confirmEmail: 'Подтвердите email',
  emailSent: (email: string) => `Ссылка отправлена на ${email}`,
  login: 'Войти',
  register: 'Регистрация',
  registerSubmit: 'Зарегистрироваться',
  email: 'Email',
  password: 'Пароль',
} as const
