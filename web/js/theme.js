const DEFAULTS = {
  primary_color: "#000000",
  background_color: "#FFFFFF",
  text_color: "#000000",
  accent_color: "#1A1A1A",
  toggle_on_color: "#000000",
  toggle_off_color: "#CCCCCC",
  font_family: "Inter",
  app_name: "Silent VPN",
  login_link_color: "#4680C2",
};

const ASSET_BASE = "https://132-243-234-162.nip.io";

function hex(value, fallback) {
  const raw = String(value || "").trim();
  if (/^#[0-9a-fA-F]{6}$/.test(raw)) return raw.toUpperCase();
  return fallback;
}

function rgb(h) {
  const n = parseInt(String(h).replace("#", ""), 16);
  if (Number.isNaN(n)) return null;
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

function lum(h) {
  const c = rgb(h);
  if (!c) return 0.5;
  return (0.299 * c.r + 0.587 * c.g + 0.114 * c.b) / 255;
}

function invert(h, fallback) {
  const c = rgb(h);
  if (!c) return fallback;
  const to = (n) => Math.max(0, Math.min(255, 255 - n)).toString(16).padStart(2, "0");
  return `#${to(c.r)}${to(c.g)}${to(c.b)}`.toUpperCase();
}

export function resolveAppName(raw) {
  const name = String(raw || "").trim();
  if (!name || name.toLowerCase() === "silent") return "Silent VPN";
  return name;
}

export function resolveAssetUrl(path) {
  let raw = String(path || "").trim();
  if (!raw) return "";
  if (raw.includes("?")) raw = raw.split("?")[0];
  if (/^https?:\/\//i.test(raw)) {
    return raw.replace("://132.243.234.162", "://132-243-234-162.nip.io");
  }
  const rel = raw.startsWith("/") ? raw : `/${raw}`;
  return `${ASSET_BASE}${rel}`;
}

export function palette(theme, mode) {
  const t = theme || {};
  const wantDark = mode === "dark";
  const lightBg = hex(t.background_color, DEFAULTS.background_color);
  const lightFg = hex(t.text_color, DEFAULTS.text_color);
  const lightPrimary = hex(t.primary_color, lightFg);
  const lightOn = hex(t.toggle_on_color, DEFAULTS.toggle_on_color);
  const lightOff = hex(t.toggle_off_color, DEFAULTS.toggle_off_color);
  const lightLink = hex(t.login_link_color, DEFAULTS.login_link_color);

  const pick = (darkKey, lightVal, inverted) => {
    if (!wantDark) return lightVal;
    const d = hex(t[darkKey], "");
    return d || inverted;
  };

  const bg = pick("dark_background_color", lightBg, "#0B0B0F");
  const fg = pick("dark_text_color", lightFg, "#F5F5F7");
  const dark = lum(bg) < 0.45;
  const font = String(t.font_family || DEFAULTS.font_family).trim() || "Inter";

  return {
    bg,
    fg,
    muted: dark ? `${fg}B3` : `${fg}99`,
    border: dark ? "#2A2A32" : "#E5E7EB",
    surface: dark ? "#14141A" : "#F3F4F6",
    field: dark ? "#16161C" : "#F3F4F6",
    hint: dark ? "#9CA3AF" : "#6B7280",
    link: pick("dark_login_link_color", lightLink, "#7DD3FC"),
    green: dark ? "#4ADE80" : "#16A34A",
    red: "#EF4444",
    btnBg: dark ? "#FFFFFF" : fg,
    btnFg: dark ? "#000000" : bg,
    toggleOn: pick("dark_toggle_on_color", lightOn, "#FFFFFF"),
    toggleOff: pick("dark_toggle_off_color", lightOff, "#3F3F46"),
    primary: pick("dark_primary_color", lightPrimary, invert(lightPrimary, "#FFFFFF")),
    fontFamily: `${font}, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`,
    appTitle: resolveAppName(t.app_name).toUpperCase(),
    logoUrl: resolveAssetUrl(t.logo_url),
    homeBgUrl: resolveAssetUrl(t.home_bg_image_url),
    dark,
  };
}

export function applyPalette(ui) {
  const root = document.documentElement;
  const map = {
    "--sv-bg": ui.bg,
    "--sv-fg": ui.fg,
    "--sv-muted": ui.muted,
    "--sv-border": ui.border,
    "--sv-surface": ui.surface,
    "--sv-field": ui.field,
    "--sv-hint": ui.hint,
    "--sv-link": ui.link,
    "--sv-green": ui.green,
    "--sv-red": ui.red,
    "--sv-btn-bg": ui.btnBg,
    "--sv-btn-fg": ui.btnFg,
    "--sv-toggle-on": ui.toggleOn,
    "--sv-toggle-off": ui.toggleOff,
    "--sv-font": ui.fontFamily,
  };
  Object.entries(map).forEach(([k, v]) => root.style.setProperty(k, v));
  document.body.style.fontFamily = ui.fontFamily;
}
