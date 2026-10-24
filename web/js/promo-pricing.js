export function promotionalPriceLabel(fallback, preview, now = Date.now()) {
  if (!preview || typeof preview.promo_code !== "string" || !preview.promo_code.trim()) return fallback;
  const amount = preview.amount;
  const age = now - Date.parse(preview.calculated_at || "");
  if (typeof amount !== "number" || !Number.isFinite(amount) || amount < 0 ||
      !Number.isFinite(age) || age < 0 || age > 300000) return fallback;
  return new Intl.NumberFormat("ru-RU", {
    useGrouping: false, minimumFractionDigits: Number.isInteger(amount) ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(amount) + " ₽";
}
