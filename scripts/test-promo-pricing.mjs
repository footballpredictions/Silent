import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../agent/web/js/promo-pricing.js", import.meta.url), "utf8");
const { promotionalPriceLabel } = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
const now = Date.parse("2026-10-24T12:00:00Z");
const quote = { amount: 139.3, promo_code: "ЧЕЧИЛ", calculated_at: "2026-10-24T12:00:00Z" };

test("only the current account's server promo quote changes card price", () => {
  assert.equal(promotionalPriceLabel("199 ₽", quote, now), "139,30 ₽");
  assert.equal(promotionalPriceLabel("199 ₽", undefined, now), "199 ₽");
  assert.equal(promotionalPriceLabel("199 ₽", { ...quote, promo_code: null }, now), "199 ₽");
  assert.equal(promotionalPriceLabel("199 ₽", { ...quote, promo_code: " " }, now), "199 ₽");
  assert.equal(quote.amount, 139.3);
});

test("expired, future and invalid quotes never leave a stale discount", () => {
  for (const preview of [
    { ...quote, calculated_at: "invalid" }, { ...quote, calculated_at: undefined },
    { ...quote, calculated_at: "2026-10-24T12:01:00Z" },
    { ...quote, calculated_at: "2026-10-24T11:54:59Z" },
    { ...quote, amount: -1 }, { ...quote, amount: NaN },
    { ...quote, amount: Infinity }, { ...quote, amount: "139.3" },
  ]) assert.equal(promotionalPriceLabel("199 ₽", preview, now), "199 ₽");
});

test("all plans use exact server amounts, including fractional rubles", () => {
  for (const [amount, expected] of [[139.3,"139,30 ₽"],[251.3,"251,30 ₽"],[334.6,"334,60 ₽"],[1049.3,"1049,30 ₽"],[231,"231 ₽"],[415.8,"415,80 ₽"],[554.4,"554,40 ₽"],[0,"0 ₽"]]) {
    assert.equal(promotionalPriceLabel("base", { ...quote, amount }, now), expected);
  }
  assert.equal(promotionalPriceLabel("199 ₽", quote, now + 300001), "199 ₽");
});

test("promo check sends the tariff required by the backend", async () => {
  const previousLocation = globalThis.location;
  const previousFetch = globalThis.fetch;
  globalThis.location = { hostname: "localhost" };
  let payload;
  globalThis.fetch = async (_url, options) => {
    payload = JSON.parse(options.body);
    return { ok: true, text: async () => JSON.stringify({ discount_percent: 30 }) };
  };
  try {
    const apiSource = await readFile(new URL("../agent/web/js/api.js", import.meta.url), "utf8");
    const { api } = await import("data:text/javascript;base64," + Buffer.from(apiSource).toString("base64"));
    await api.promo("ЧЕЧИЛ");
    assert.deepEqual(payload, { code: "ЧЕЧИЛ", plan_type: "monthly" });
  } finally {
    globalThis.location = previousLocation;
    globalThis.fetch = previousFetch;
  }
});
