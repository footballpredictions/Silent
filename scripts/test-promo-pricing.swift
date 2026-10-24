import Foundation

@main
struct PromoPricingTest {
    static func main() throws {
        let plan = ShopPlan(id: "monthly", name: "Месяц", price: 199, days: 30, devices: 3)
        let now = Date(timeIntervalSince1970: 1792843200)
        let decoder = JSONDecoder()
        let raw = #"{"amount":139.3,"expires_at":"2026-11-24T12:00:00Z","message":"","calculated_at":"2026-10-24T12:00:00Z","promo_code":"ЧЕЧИЛ"}"#
        let quote = try decoder.decode(PaymentPreview.self, from: Data(raw.utf8))
        precondition(plan.priceLabel(preview: quote, now: now) == "139,30 ₽")
        precondition(plan.priceLabel(preview: nil, now: now) == "199 ₽")
        precondition(plan.priceLabel(preview: quote, now: now.addingTimeInterval(301)) == "199 ₽")
        precondition(plan.priceLabel(preview: quote, now: now.addingTimeInterval(-1)) == "199 ₽")
        var legacyObject = try JSONSerialization.jsonObject(with: Data(raw.utf8)) as! [String: Any]
        legacyObject.removeValue(forKey: "promo_code")
        let legacy = try decoder.decode(PaymentPreview.self, from: JSONSerialization.data(withJSONObject: legacyObject))
        precondition(plan.priceLabel(preview: legacy, now: now) == "199 ₽")
        for (amount, expected) in [(139.3,"139,30 ₽"),(251.3,"251,30 ₽"),(334.6,"334,60 ₽"),
                                   (1049.3,"1049,30 ₽"),(231.0,"231 ₽"),(415.8,"415,80 ₽"),(554.4,"554,40 ₽"),(0.0,"0 ₽")] {
            precondition(ShopPlan.currencyLabel(amount) == expected)
        }
        let invalid = try decoder.decode(PaymentPreview.self, from: Data(raw.replacingOccurrences(of: "139.3", with: "-1").utf8))
        precondition(plan.priceLabel(preview: invalid, now: now) == "199 ₽")
        print("Promo card pricing: PASS")
    }
}
