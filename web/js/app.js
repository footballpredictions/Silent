import { api, openPaymentUrl } from "./api.js";
import { displayVpnServers, normalizeSlot, selectedTitle } from "./servers.js";
import { applyPalette, palette } from "./theme.js";
import { dockKind, formatExpireDate, hasVpnAccess, isUnlimitedLike, planLabel } from "./subscription.js";
import { mountToggleSnake, SNAKE_MIN_VISIBLE_MS, toggleMarkup } from "./toggle.js";

let stopSnake = () => {};

const state = {
  theme: null,
  mode: localStorage.getItem("sv-mode") || "light",
  view: "boot",
  tab: "login",
  step: "auth",
  email: "",
  password: "",
  referral: "",
  showPass: false,
  remember: true,
  forgotEmail: "",
  forgotSent: false,
  regDone: false,
  error: "",
  loading: false,
  session: null,
  profile: null,
  connected: false,
  connecting: false,
  disconnecting: false,
  menu: false,
  page: null,
  servers: null,
  referralInfo: null,
  promoCode: "",
  promoMsg: "",
  copyMsg: "",
  lanUrl: "http://192.168.1.1.silent.vpn",
  lanIp: "192.168.1.1",
  routerName: "OpenWrt",
  preview: false,
  dnsPreset: "server",
  dnsCustom: "",
  ruDirect: false,
  dnsMsg: "",
  live: false,
  pressed: false,
};

const $app = document.getElementById("app");
const $chrome = document.getElementById("chrome");
const $studioUrl = document.getElementById("studioUrl");

function ui() {
  return palette(state.theme, state.mode);
}

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function icon(name) {
  const icons = {
    menu: '<svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
    sun: '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="12" r="5"/><g fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round"><path d="M12 2.2v2.4M12 19.4v2.4M2.2 12h2.4M19.4 12h2.4M4.85 4.85l1.7 1.7M17.45 17.45l1.7 1.7M4.85 19.15l1.7-1.7M17.45 6.55l1.7-1.7"/></g></svg>',
    moon: '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="5" fill="currentColor"/><circle cx="16.2" cy="9.2" r="4.4" fill="var(--sv-bg)"/></svg>',
    x: '<svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
    chev: '<svg width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="m9 6 6 6-6 6"/></svg>',
    eye: '<svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
    eyeOff: '<svg width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M3 3l18 18M10.6 10.6A3 3 0 0 0 12 15a3 3 0 0 0 2.4-4.4M9.9 5.1A10.7 10.7 0 0 1 12 5c6.5 0 10 7 10 7a18 18 0 0 1-4.1 4.8M6.1 6.1A18 18 0 0 0 2 12s3.5 7 10 7c1.6 0 3-.3 4.3-.8"/></svg>',
    telegram: '<svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.74-.55 2.92-1.27 4.86-2.11 5.83-2.51 2.78-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .38z"/></svg>',
  };
  return icons[name] || "";
}

function logoHtml(p, size) {
  if (p.logoUrl) {
    return `<img class="logo" src="${esc(p.logoUrl)}" alt="" width="${size}" height="${size}" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'logo',textContent:'S'}))">`;
  }
  return `<div class="logo" aria-hidden="true">S</div>`;
}


function dnsMenuLabel() {
  if (state.dnsPreset !== "custom") return "Как на сервере";
  return (state.dnsCustom || "").trim() || "не задан";
}

function sessionKind(d) {
  if (d.self || d.platform === "openwrt" || /^openwrt/i.test(d.device_name || "")) return "OpenWrt";
  const t = String(d.device_type || "").toLowerCase();
  if (t === "android") return "Android";
  if (t === "ios") return "iOS";
  if (t === "pc" || t === "windows") return "ПК";
  return d.device_type || "—";
}

function sessionRouterName(d) {
  if (d.router_name) return d.router_name;
  const raw = String(d.device_name || "").trim();
  if (/^openwrt\s+/i.test(raw)) return raw.replace(/^openwrt\s+/i, "");
  if (d.self) return state.routerName;
  if (raw && !["Android", "ПК", "PC", "iOS", "Windows", "OpenWrt"].includes(raw)) return raw;
  return "";
}

function render() {
  const p = ui();
  applyPalette(p);
  if (state.preview) {
    $chrome.hidden = false;
    $studioUrl.textContent = state.lanUrl;
    document.body.classList.add("has-chrome");
  } else {
    $chrome.hidden = true;
    document.body.classList.remove("has-chrome");
  }

  if (!state.session) $app.innerHTML = loginView(p);
  else $app.innerHTML = mainView(p);
  bind();
  stopSnake();
  stopSnake = mountToggleSnake($app.querySelector("canvas.thumb-snake"), p.fg) || (() => {});
}

function loginView(p) {
  const t = state.theme || {};
  const remember = t.login_remember_me_label || "Запомнить меня";
  const forgot = t.login_forgot_password_label || "Забыли пароль?";
  const forgotTitle = t.login_forgot_title || "Восстановление пароля";
  const forgotHint = t.login_forgot_instruction || "Введите email — мы отправим ссылку для установки нового пароля.";
  const refLabel = t.register_referral_or_promo_label || "Промокод или реферальный код";
  const refHint = t.register_referral_or_promo_hint || "Необязательно. Введите промокод или код из реферальной ссылки.";

  let body = "";
  if (state.step === "forgot") {
    body = `
      <button class="back" data-act="auth">← Назад к входу</button>
      <h2 style="margin-bottom:8px;font-size:14px">${esc(forgotTitle)}</h2>
      <p class="hint" style="margin-bottom:14px">${esc(forgotHint)}</p>
      ${state.forgotSent
        ? `<p class="hint">Если email зарегистрирован, письмо отправлено.</p>`
        : `<p class="label">Email</p>
           <input class="field" type="email" data-bind="forgotEmail" value="${esc(state.forgotEmail || state.email)}" placeholder="you@example.com">
           ${state.error ? `<p class="err">${esc(state.error)}</p>` : ""}
           <button class="primary" data-act="forgot" ${state.loading ? "disabled" : ""}>${state.loading ? "…" : "Отправить письмо"}</button>`}
    `;
  } else if (state.regDone) {
    body = `
      <div class="center-msg">
        <p style="font-weight:500;font-size:14px">Подтвердите email</p>
        <p class="hint" style="margin-top:6px">Ссылка отправлена на ${esc(state.email)}</p>
        <p class="hint" style="margin-top:4px">Откройте письмо — после подтверждения войдите с того же роутера.</p>
        <button class="linkish" style="margin-top:16px" data-act="to-login">Войти</button>
      </div>`;
  } else {
    const submit = state.tab === "login" ? "login" : "register";
    const label = state.tab === "login" ? "Войти" : "Зарегистрироваться";
    body = `
      <p class="status-line" style="color:${p.green}">${state.preview
        ? "Preview · вход на живой Улей. Почта и пароль как в приложении (админ или обычный)."
        : "Канал готов. Войдите или зарегистрируйтесь."}</p>
      <div class="tabs">
        <button class="tab ${state.tab === "login" ? "on" : ""}" data-act="tab-login">Войти</button>
        <button class="tab ${state.tab === "register" ? "on" : ""}" data-act="tab-reg">Регистрация</button>
      </div>
      <form data-act="${submit}">
        <p class="label">Email</p>
        <input class="field" type="email" data-bind="email" value="${esc(state.email)}" placeholder="you@example.com" required>
        <p class="label">Пароль</p>
        <div class="field-wrap">
          <input class="field" type="${state.showPass ? "text" : "password"}" data-bind="password" value="${esc(state.password)}" placeholder="••••••••" minlength="8" required>
          <button type="button" class="eye" data-act="eye">${state.showPass ? icon("eyeOff") : icon("eye")}</button>
        </div>
        ${state.tab === "register" ? `
          <p class="label">${esc(refLabel)}</p>
          <input class="field" data-bind="referral" value="${esc(state.referral)}" placeholder="${esc(refHint)}">
        ` : ""}
        <div class="row-between">
          <label class="check"><input type="checkbox" data-bind-check="remember" ${state.remember ? "checked" : ""}> ${esc(remember)}</label>
          <button type="button" class="linkish" data-act="forgot-open">${esc(forgot)}</button>
        </div>
        ${state.error ? `<p class="err">${esc(state.error)}</p>` : ""}
        <button class="primary" type="submit" ${state.loading ? "disabled" : ""}>
          ${state.loading ? "…" : label}
        </button>
      </form>`;
  }

  return `
    <div class="login">
      <aside class="login-hero">
        ${p.homeBgUrl ? `<img class="hero-bg" src="${esc(p.homeBgUrl)}" alt="" onerror="this.remove()">` : ""}
        <div class="hero-copy">
          ${logoHtml(p, 56)}
          <div class="brand-name">${esc(p.appTitle)}</div>
          <div class="hero-host">${esc(state.lanUrl.replace("http://", ""))}</div>
        </div>
      </aside>
      <section class="login-pane">
        <div class="login-tools">
          <button class="mode-btn" data-act="mode" title="Тема">${state.mode === "dark" ? icon("sun") : icon("moon")}</button>
        </div>
        <div class="login-form">${body}</div>
      </section>
    </div>`;
}

function mainView(p) {
  const t = state.theme || {};
  const status = state.disconnecting
    ? "Отключение..."
    : state.connecting
      ? "Подключение..."
      : state.connected
        ? "Подключено"
        : "Отключено";
  const statusColor = state.connecting || state.disconnecting ? p.hint : state.connected ? p.green : p.hint;
  const busy = state.connecting || state.disconnecting;
  const visualOn = state.connected && !state.connecting && !state.disconnecting;
  const showSnake = state.connecting && !state.disconnecting;
  const email = state.profile?.email || state.session?.email || "—";
  const id = state.profile?.display_id || "—";
  const items = [
    [null, "Главная"],
    ["subscription", "Подписка"],
    ["exceptions", "Исключения"],
    ["dns", `DNS · ${dnsMenuLabel()}`],
    ["router", "Роутер"],
    ["servers", "Выбор сервера"],
    ["bonuses", t.menu_bonuses_label || "Бонусы"],
    ["devices", "Сессии"],
    ["support", "Поддержка"],
    ["about", "О сервисе"],
  ];

  const home = `
    <div class="home">
      ${p.homeBgUrl ? `<img class="home-bg" src="${esc(p.homeBgUrl)}" alt="" onerror="this.remove()">` : ""}
      <div class="home-status" style="color:${statusColor}">${esc(status)}</div>
      ${toggleMarkup({ visualOn, showSnake, pressed: state.pressed })}
    </div>
    <div class="dock">${dockHtml(p)}</div>`;

  return `
    <div class="shell">
      <aside class="side ${state.menu ? "open" : ""}">
        <div class="side-head">
          <div class="mail">${esc(email)}</div>
          <div class="meta">Аккаунт: ${esc(id)}</div>
          <div class="meta">Роутер · OpenWrt</div>
        </div>
        <nav class="nav">
          ${items.map(([key, label]) => `
            <button class="nav-item ${(state.page || null) === key ? "on" : ""}" data-act="page" data-page="${key || ""}">
              <span>${esc(label)}</span><span class="chev">${icon("chev")}</span>
            </button>`).join("")}
          <button class="nav-item danger" data-act="logout">${state.loading ? "Выход…" : "Выйти"}</button>
        </nav>
      </aside>
      <main class="stage">
        <div class="topbar">
          <button class="mode-btn menu-toggle" data-act="menu" title="Меню">${icon("menu")}</button>
          <div class="topbar-title">${esc(p.appTitle)}</div>
          <div class="topbar-end">
            <button class="mode-btn" data-act="mode" title="Тема">${state.mode === "dark" ? icon("sun") : icon("moon")}</button>
          </div>
        </div>
        ${state.page ? `<div class="page"><div class="page-inner">${pageInner(p, t)}</div></div>` : home}
      </main>
    </div>`;
}

function pageInner(p, t) {
  const page = state.page;
  if (page === "subscription") return subscriptionPage(t);
  if (page === "exceptions") return exclusionsPage();
  if (page === "dns") return dnsPage();
  if (page === "router") return routerPage();
  if (page === "servers") return serversPage();
  if (page === "bonuses") return bonusesPage(t);
  if (page === "devices") return devicesPage();
  if (page === "support") return supportPage(t);
  if (page === "about") {
    return `<h2>Silent VPN</h2>
      <p class="hint">Версия 1.0.165 · OpenWrt</p>
      <p class="hint" style="margin-top:8px">Туннель как у PC и Android: WireGuard + WDTT. Этот веб — только панель роутера.</p>`;
  }
  return "";
}

function dockHtml(p) {
  const kind = dockKind(state.profile);
  const sub = state.profile?.subscription || {};
  if (kind === "test") {
    return `<div class="dock-title" style="color:#9333EA">Тестовый режим</div><div class="dock-sub">Безлимит</div>`;
  }
  if (kind === "unlimited") {
    return `<div class="dock-title" style="color:${p.green}">Бессрочно</div><div class="dock-sub">Полный доступ</div>`;
  }
  if (kind === "trial") {
    return `<div class="dock-title" style="color:#2563EB">Пробный период</div>
      <div class="dock-sub">осталось ${esc(sub.days_left ?? 0)} дн.</div>`;
  }
  if (kind === "paid") {
    const until = formatExpireDate(sub.expires_at);
    return `<div class="dock-title" style="color:${p.green}">Оплачено</div>
      ${until ? `<div class="dock-sub">до ${esc(until)}</div>` : ""}`;
  }
  if (kind === "pay") {
    return `<button type="button" class="dock-pay" data-act="page" data-page="subscription">Оформить подписку</button>`;
  }
  return "";
}

function subscriptionPage(t) {
  const profile = state.profile || {};
  const sub = profile.subscription || {};
  if (isUnlimitedLike(profile) || sub.is_active) {
    return `<h2>Подписка активна</h2>
      <p class="hint">Тариф: ${esc(planLabel(sub.plan_type))}<br>
      ${isUnlimitedLike(profile) ? "Безлимитный доступ" : `Осталось: ${esc(sub.days_left ?? 0)} дней`}</p>`;
  }
  const plans = [
    ["monthly", "Месяц", "199 ₽"],
    ["two_months", "2 месяца", "359 ₽"],
    ["quarterly", "3 месяца", "478 ₽"],
  ];
  return `<h2>Выберите тариф</h2>
    ${plans.map(([id, label, price]) => `
      <button class="card-btn" data-act="pay" data-plan="${id}"><span>${label}</span><span>${price}</span></button>
    `).join("")}
    <p class="hint" style="margin-top:10px">Оплата откроется в браузере (YuMoney). После оплаты вернитесь сюда.</p>
    ${state.error ? `<p class="err">${esc(state.error)}</p>` : ""}`;
}

function routerPage() {
  return `<h2>Роутер</h2>
    <p class="hint" style="margin-bottom:12px">Веб-панель всегда открывается как адрес LAN + <strong>.silent.vpn</strong>. LuCI на голом IP не трогаем.</p>
    <p class="label">Адрес панели</p>
    <input class="field" readonly value="${esc(state.lanUrl)}">
    <p class="label">LAN IPv4</p>
    <input class="field" readonly value="${esc(state.lanIp)}">
    <p class="hint">Примеры: 192.168.1.1.silent.vpn, 192.168.0.1.silent.vpn, 10.0.0.1.silent.vpn</p>
    <p class="hint" style="margin-top:12px">Весь дом идёт в туннель, кроме самой LAN-подсети. Kill-switch: если туннель упал — WAN для клиентов гасится, панель остаётся.</p>`;
}

function serversPage() {
  const list = displayVpnServers(state.servers?.servers);
  const selected = normalizeSlot(state.servers?.selected_server || "server1");
  const locked = state.connected || state.connecting;
  return `<h2>Выбор сервера</h2>
    <p class="hint" style="margin-bottom:14px">Слоты 1–4 всегда на месте. Живые IP подтягиваются с Улья сами.</p>
    ${locked ? `<p class="hint" style="margin-bottom:12px">Переключение недоступно: VPN активен.</p>` : ""}
    ${list.map((s) => `
      <button class="opt ${s.key === selected ? "on" : ""}" data-act="server" data-key="${esc(s.key)}" ${locked ? "disabled" : ""}>
        <span class="opt-dot"></span>
        <span>${esc(s.title)}</span>
      </button>`).join("")}`;
}

function bonusesPage(t) {
  const r = state.referralInfo || {};
  return `<h2>${esc(t.bonuses_title || t.menu_bonuses_label || "Бонусы")}</h2>
    <p class="hint" style="white-space:pre-line;margin-bottom:16px">${esc(t.bonuses_intro_text || "")}</p>
    <h2>${esc(t.bonuses_referral_title || "Ваша ссылка")}</h2>
    <p class="hint" style="margin-bottom:8px">${esc(t.bonuses_referral_hint || "Скопируйте и отправьте другу")}</p>
    <input class="field" readonly value="${esc(r.referral_link || "")}" placeholder="Загрузка…">
    <button class="primary" data-act="copy-ref">${esc(t.bonuses_copy_link_label || "Копировать ссылку")}</button>
    ${state.copyMsg ? `<p class="hint" style="margin:8px 0">${esc(state.copyMsg)}</p>` : ""}
    <h2 style="margin-top:20px">${esc(t.bonuses_promo_title || "Промокод")}</h2>
    <p class="hint" style="margin-bottom:8px">${esc(t.bonuses_promo_hint || "")}</p>
    <input class="field" data-bind="promoCode" value="${esc(state.promoCode)}" placeholder="Введите код">
    <button class="primary" data-act="promo">Проверить</button>
    ${state.promoMsg ? `<p class="hint" style="margin-top:8px">${esc(state.promoMsg)}</p>` : ""}`;
}

function devicesPage() {
  const devices = state.profile?.devices || [];
  return `<h2>Сессии</h2>
    <p class="hint" style="margin-bottom:12px">VPN онлайн: ${devices.filter((d) => d.is_connected).length} из ${state.profile?.devices_count || devices.length}</p>
    ${devices.map((d) => {
      const kind = sessionKind(d);
      const extra = sessionRouterName(d);
      return `
      <div class="session">
        <span class="dot ${d.is_connected ? "on" : ""}"></span>
        <div>
          <div style="font-size:14px;font-weight:500">${esc(kind)}${d.self ? ' <span class="hint">· это вы</span>' : ""}</div>
          ${extra ? `<div class="hint">${esc(extra)}</div>` : ""}
          <div class="hint" style="${d.is_connected ? `color:var(--sv-green)` : ""}">${d.is_connected ? "В сети" : "Не в сети"}</div>
        </div>
      </div>`;
    }).join("") || `<p class="hint">Нет зарегистрированных устройств</p>`}`;
}

function supportPage(t) {
  const channel = t.telegram_channel_url || "https://t.me/silentvpn3";
  const support = t.support_url || "https://t.me/silentvpn3?direct";
  return `<h2>Поддержка</h2>
    <p class="hint" style="margin-bottom:16px">По вопросам обратитесь через Telegram.</p>
    <div class="tg-row">
      <a class="tg-tile" href="${esc(channel)}" target="_blank" rel="noreferrer">
        <span class="tg-ico">${icon("telegram")}</span>
        <span>Канал</span>
      </a>
      <a class="tg-tile" href="${esc(support)}" target="_blank" rel="noreferrer">
        <span class="tg-ico">${icon("telegram")}</span>
        <span>Поддержка</span>
      </a>
    </div>`;
}

function dnsPage() {
  const locked = state.connected || state.connecting;
  return `<h2>DNS</h2>
    <p class="hint" style="margin-bottom:14px">Используйте рекомендуемый DNS или укажите свой. Применяется при следующем подключении VPN.</p>
    ${locked ? `<p class="hint" style="margin-bottom:12px">Смена недоступна, пока VPN включён.</p>` : ""}
    <button class="opt ${state.dnsPreset === "server" ? "on" : ""}" data-act="dns-preset" data-preset="server" ${locked ? "disabled" : ""}>
      <span class="opt-dot"></span>
      <span><strong>Как на сервере</strong><br><span class="hint">Рекомендуется</span></span>
    </button>
    <button class="opt ${state.dnsPreset === "custom" ? "on" : ""}" data-act="dns-preset" data-preset="custom" ${locked ? "disabled" : ""}>
      <span class="opt-dot"></span>
      <span><strong>Свой DNS</strong><br><span class="hint">до 3 адресов через запятую</span></span>
    </button>
    ${state.dnsPreset === "custom" ? `
      <input class="field" data-bind="dnsCustom" value="${esc(state.dnsCustom)}" placeholder="77.88.8.8, 1.1.1.1" ${locked ? "disabled" : ""}>
      <button class="primary" data-act="dns-save" ${locked ? "disabled" : ""}>Сохранить</button>
    ` : ""}
    ${state.dnsMsg ? `<p class="hint" style="margin-top:10px">${esc(state.dnsMsg)}</p>` : ""}`;
}

function exclusionsPage() {
  return `<h2>Исключения</h2>
    <p class="hint" style="margin-bottom:16px">На роутере нет списка приложений, как на телефоне. Вместо этого весь дом ходит через DNS роутера: можно вывести российские сервисы в обход туннеля.</p>
    <div class="switch-row">
      <div>
        <div style="font-size:14px;font-weight:500">Российские сервисы мимо VPN</div>
        <p class="hint" style="margin-top:4px">Яндекс, VK, Госуслуги, банки, Почта, маркетплейсы — напрямую в WAN. YouTube, Google и остальное остаются в туннеле.</p>
      </div>
      <button class="mini-toggle ${state.ruDirect ? "on" : ""}" data-act="ru-direct" aria-pressed="${state.ruDirect}">
        <span class="mini-thumb"></span>
      </button>
    </div>
    <p class="hint" style="margin-top:16px">Как это видят программы в доме: браузер и приложения берут DNS с роутера — RU-домены получают «домашние» IP и уходят мимо WG. Если программа сама ходит в DoH (Chrome «безопасный DNS») или зашила IP, она может остаться в VPN. Телефоны с своим VPN-клиентом Silent этот обход не дублируют: у них свои исключения.</p>`;
}


function bind() {
  $app.querySelectorAll("[data-bind]").forEach((el) => {
    el.addEventListener("input", () => {
      state[el.dataset.bind] = el.value;
    });
  });
  $app.querySelectorAll("[data-bind-check]").forEach((el) => {
    el.addEventListener("change", () => {
      state[el.dataset.bindCheck] = el.checked;
    });
  });
  $app.querySelectorAll("[data-act]").forEach((el) => {
    const act = el.dataset.act;
    if (el.tagName === "FORM") {
      el.addEventListener("submit", (e) => {
        e.preventDefault();
        void handle(act);
      });
    } else {
      el.addEventListener("click", (e) => {
        e.preventDefault();
        void handle(act, el);
      });
    }
  });
  const knob = $app.querySelector(".toggle");
  if (knob) {
    const setPressed = (on) => {
      if (state.connecting || state.disconnecting) return;
      if (state.pressed === on) return;
      state.pressed = on;
      knob.classList.toggle("pressed", on);
    };
    knob.addEventListener("pointerdown", () => setPressed(true));
    knob.addEventListener("pointerup", () => setPressed(false));
    knob.addEventListener("pointerleave", () => setPressed(false));
    knob.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        void handle("toggle");
      }
    });
  }
}

async function handle(act, el) {
  try {
    if (act === "mode") {
      state.mode = state.mode === "dark" ? "light" : "dark";
      localStorage.setItem("sv-mode", state.mode);
      render();
      return;
    }
    if (act === "tab-login") { state.tab = "login"; state.error = ""; state.regDone = false; render(); return; }
    if (act === "tab-reg") { state.tab = "register"; state.error = ""; render(); return; }
    if (act === "eye") { state.showPass = !state.showPass; render(); return; }
    if (act === "forgot-open") { state.step = "forgot"; state.error = ""; render(); return; }
    if (act === "auth" || act === "to-login") { state.step = "auth"; state.tab = "login"; state.regDone = false; render(); return; }
    if (act === "menu") { state.menu = !state.menu; render(); return; }
    if (act === "menu-close") { state.menu = false; render(); return; }
    if (act === "page") {
      state.page = el.dataset.page || null;
      state.menu = false;
      if (state.page === "bonuses") void loadReferral();
      if (state.page === "servers") void loadServers();
      render();
      return;
    }
    if (act === "page-back") { state.page = null; render(); return; }
    if (act === "login") return login();
    if (act === "register") return register();
    if (act === "forgot") return forgot();
    if (act === "logout") return logout();
    if (act === "toggle") return toggleVpn();
    if (act === "copy-ref") return copyRef();
    if (act === "promo") return checkPromo();
    if (act === "pay") return pay(el.dataset.plan);
    if (act === "server") return pickServer(el.dataset.key);
    if (act === "dns-preset") return setDnsPreset(el.dataset.preset);
    if (act === "dns-save") return saveDns();
    if (act === "ru-direct") return toggleRuDirect();
  } catch (e) {
    state.error = e.message || String(e);
    state.loading = false;
    render();
  }
}

async function login() {
  if (!state.email.includes("@") || state.password.length < 8) {
    state.error = "Укажите email и пароль от 8 символов";
    render();
    return;
  }
  state.loading = true;
  state.error = "";
  render();
  try {
    const res = await api.login(state.email, state.password);
    state.session = res;
    state.profile = res.profile || await api.profile();
    applyExtras(res);
    state.connected = !!res.connected;
    if (res.theme) state.theme = res.theme;
    if (res.live != null) state.live = !!res.live;
    await hydrateAfterAuth();
  } finally {
    state.loading = false;
    render();
  }
}

async function register() {
  state.loading = true;
  state.error = "";
  render();
  try {
    await api.register(state.email, state.password, state.referral);
    state.regDone = true;
  } finally {
    state.loading = false;
    render();
  }
}

async function forgot() {
  state.loading = true;
  state.error = "";
  render();
  try {
    await api.forgot(state.forgotEmail || state.email);
    state.forgotSent = true;
  } finally {
    state.loading = false;
    render();
  }
}

async function logout() {
  state.loading = true;
  render();
  try { await api.logout(); } catch { /* keep going */ }
  state.session = null;
  state.profile = null;
  state.connected = false;
  state.menu = false;
  state.page = null;
  state.live = false;
  state.loading = false;
  render();
}

async function toggleVpn() {
  if (state.connecting || state.disconnecting) return;
  if (!state.connected && !hasVpnAccess(state.profile)) {
    state.page = "subscription";
    render();
    return;
  }
  if (state.connected) {
    state.disconnecting = true;
    render();
    try {
      await api.disconnect();
      state.connected = false;
    } finally {
      state.disconnecting = false;
      render();
    }
    return;
  }
  state.connecting = true;
  render();
  const started = Date.now();
  try {
    await api.connect();
    const wait = Math.max(0, SNAKE_MIN_VISIBLE_MS - (Date.now() - started));
    await new Promise((r) => setTimeout(r, wait));
    state.connected = true;
  } catch (e) {
    state.error = e.message;
  } finally {
    state.connecting = false;
    render();
  }
}

async function loadReferral() {
  try { state.referralInfo = await api.referral(); render(); } catch { /* ignore */ }
}

async function loadServers() {
  try {
    const raw = await api.servers();
    applyServerPayload(raw);
    render();
  } catch {
    applyServerPayload(state.servers);
    render();
  }
}

function applyServerPayload(raw) {
  const list = Array.isArray(raw?.servers)
    ? raw.servers
    : Array.isArray(raw)
      ? raw
      : [];
  const servers = displayVpnServers(list);
  const selected = normalizeSlot(raw?.selected_server || "server1");
  state.servers = {
    ...(raw || {}),
    servers,
    selected_server: selected,
    selected_title: selectedTitle(selected, servers),
  };
}

function applyExtras(payload) {
  if (!payload) return;
  if (payload.lan_url) state.lanUrl = payload.lan_url;
  if (payload.lan_ip) state.lanIp = payload.lan_ip;
  if (payload.router_name) state.routerName = payload.router_name;
  if (payload.dns_preset) state.dnsPreset = payload.dns_preset;
  if (payload.dns_custom != null) state.dnsCustom = payload.dns_custom;
  if (payload.ru_direct != null) state.ruDirect = !!payload.ru_direct;
  if (payload.live != null) state.live = !!payload.live;
  if (payload.servers || payload.selected_server) applyServerPayload(payload.servers ? payload : { servers: payload.servers, selected_server: payload.selected_server });
}

async function hydrateAfterAuth() {
  try { applyServerPayload(await api.servers()); } catch { applyServerPayload(null); }
  try {
    const dns = await api.dns();
    state.dnsPreset = dns.preset || "server";
    state.dnsCustom = dns.custom || "";
  } catch { /* keep */ }
  try {
    const ex = await api.exclusions();
    state.ruDirect = !!ex.ru_direct;
  } catch { /* keep */ }
}

async function setDnsPreset(preset) {
  state.dnsPreset = preset;
  state.dnsMsg = "";
  if (preset === "server") {
    await api.setDns("server", state.dnsCustom);
    state.dnsMsg = "Будет как на сервере, со следующего подключения";
  }
  render();
}

async function saveDns() {
  await api.setDns("custom", state.dnsCustom);
  state.dnsPreset = "custom";
  state.dnsMsg = "Сохранено. Применится при следующем подключении";
  render();
}

async function toggleRuDirect() {
  state.ruDirect = !state.ruDirect;
  render();
  try {
    await api.setRuDirect(state.ruDirect);
  } catch {
    state.ruDirect = !state.ruDirect;
    render();
  }
}

async function copyRef() {
  const link = state.referralInfo?.referral_link;
  if (!link) { await loadReferral(); return; }
  try {
    await navigator.clipboard.writeText(link);
    state.copyMsg = "Ссылка скопирована";
  } catch {
    state.copyMsg = "Не удалось скопировать";
  }
  render();
}

async function checkPromo() {
  try {
    const res = await api.promo(state.promoCode);
    state.promoMsg = res.discount_percent != null ? `Скидка ${res.discount_percent}%` : (res.detail || "Ок");
  } catch (e) {
    state.promoMsg = e.message || "Не найден";
  }
  render();
}

async function pay(plan) {
  state.error = "";
  render();
  try {
    const res = await api.pay(plan);
    openPaymentUrl(res.url);
  } catch (e) {
    state.error = e.message || "Не удалось открыть оплату";
    render();
  }
}

async function pickServer(key) {
  const res = await api.pickServer(key);
  applyServerPayload(res);
  render();
}

async function boot() {
  const host = location.hostname;
  state.preview = host === "127.0.0.1" || host === "localhost";
  try {
    const status = await api.status();
    if (status.theme) state.theme = status.theme;
    applyExtras(status);
    if (status.session) {
      state.session = status.session;
      state.profile = status.profile;
      state.connected = !!status.connected;
      await hydrateAfterAuth();
    } else {
      applyServerPayload(null);
    }
  } catch {
    try { state.theme = await api.theme(); } catch { state.theme = {}; }
  }
  if (!state.theme) {
    try { state.theme = await api.theme(); } catch { state.theme = {}; }
  }
  render();
}

boot();
