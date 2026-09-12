/** Dock + subscription copy — same rules as PC MainScreen / Android MainScreen. */

export function isUnlimitedLike(profile) {
  const plan = profile?.subscription?.plan_type;
  return !!(profile?.is_admin || plan === "unlimited" || plan === "test");
}

export function hasVpnAccess(profile) {
  return !!(profile && (profile.is_admin || profile.subscription?.is_active));
}

export function formatExpireDate(iso) {
  const raw = String(iso || "").trim();
  if (!raw) return "";
  const day = raw.split("T")[0];
  const parts = day.split("-");
  if (parts.length !== 3) return "";
  return parts.reverse().join(".");
}

export function planLabel(type) {
  return {
    monthly: "Месяц",
    two_months: "2 месяца",
    quarterly: "3 месяца",
    trial: "Пробный период",
    yearly: "Год",
    unlimited: "Бессрочно",
    test: "Тестовый режим",
    half_year: "Полгода",
    three_days: "3 дня",
  }[type] || type || "—";
}

/** @returns {'test'|'unlimited'|'trial'|'paid'|'pay'|null} */
export function dockKind(profile) {
  if (!profile) return null;
  const sub = profile.subscription || {};
  const plan = sub.plan_type;
  if (plan === "test") return "test";
  if (profile.is_admin || plan === "unlimited") return "unlimited";
  if (sub.is_active && plan === "trial") return "trial";
  if (sub.is_active) return "paid";
  return "pay";
}
