const host = location.hostname;
const isPreview = host === "127.0.0.1" || host === "localhost";
const API = isPreview ? "/silent/api" : "/cgi-bin/silent-api";

async function send(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await res.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text || res.statusText };
  }
  if (!res.ok) {
    const err = new Error(formatDetail(data.detail) || data.error || `HTTP ${res.status}`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

function formatDetail(detail) {
  if (!detail) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((x) => x.msg || x).filter(Boolean).join("; ");
  return String(detail);
}

export const api = {
  status: () => send("/status"),
  theme: () => send("/theme"),
  login: (email, password) => send("/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  register: (email, password, referral_or_promo) =>
    send("/register", { method: "POST", body: JSON.stringify({ email, password, referral_or_promo }) }),
  forgot: (email) => send("/forgot", { method: "POST", body: JSON.stringify({ email }) }),
  logout: () => send("/logout", { method: "POST", body: "{}" }),
  connect: () => send("/connect", { method: "POST", body: "{}" }),
  disconnect: () => send("/disconnect", { method: "POST", body: "{}" }),
  profile: () => send("/profile"),
  servers: () => send("/servers"),
  pickServer: (key) => send("/server", { method: "POST", body: JSON.stringify({ key }) }),
  referral: () => send("/referral"),
  promo: (code) => send("/promo", { method: "POST", body: JSON.stringify({ code }) }),
  pay: (plan_type) => send("/pay", { method: "POST", body: JSON.stringify({ plan_type }) }),
  dns: () => send("/dns"),
  setDns: (preset, custom) => send("/dns", { method: "POST", body: JSON.stringify({ preset, custom }) }),
  exclusions: () => send("/exclusions"),
  setRuDirect: (enabled) => send("/exclusions", { method: "POST", body: JSON.stringify({ ru_direct: !!enabled }) }),
};

/** Like Android PaymentBrowser: no website Referer (YuMoney binds QuickPay to the site). */
export function openPaymentUrl(url) {
  const href = String(url || "").trim();
  if (!href.startsWith("https://yoomoney.ru/quickpay/")) {
    throw new Error("Сервер не вернул ссылку на оплату");
  }
  const a = document.createElement("a");
  a.href = href;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  a.referrerPolicy = "no-referrer";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
