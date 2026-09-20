import SwiftUI

struct SubscriptionSheet: View {
    @ObservedObject var vm: MainViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var tier = 3
    @State private var busyPlan: String?
    @State private var errorText: String?

    private struct Plan: Identifiable {
        let id: String
        let name: String
        let price: String
        let devices: Int
    }

    private let plans: [Plan] = [
        .init(id: "monthly", name: "Месяц", price: "199 ₽", devices: 3),
        .init(id: "two_months", name: "2 месяца", price: "359 ₽", devices: 3),
        .init(id: "quarterly", name: "3 месяца", price: "478 ₽", devices: 3),
        .init(id: "monthly_5", name: "Месяц", price: "330 ₽", devices: 5),
        .init(id: "two_months_5", name: "2 месяца", price: "594 ₽", devices: 5),
        .init(id: "quarterly_5", name: "3 месяца", price: "792 ₽", devices: 5),
    ]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    if vm.profile?.subscription.is_active == true {
                        Text("Подписка активна")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundColor(vm.fg)
                        Text("Осталось: \(vm.profile?.subscription.days_left ?? 0) дней")
                            .font(.system(size: 13))
                            .foregroundColor(vm.fg.opacity(0.55))
                    } else {
                        Text(vm.theme?.subscription_choose_tier_title?.nilIfEmpty ?? "Сколько устройств")
                            .font(.system(size: 15, weight: .semibold))
                            .foregroundColor(vm.fg)

                        HStack(spacing: 8) {
                            tierChip(3, vm.theme?.subscription_tier_3_label?.nilIfEmpty ?? "3 устройства")
                            tierChip(5, vm.theme?.subscription_tier_5_label?.nilIfEmpty ?? "5 устройств")
                        }

                        Text(vm.theme?.subscription_choose_plan_title?.nilIfEmpty ?? "Выберите тариф")
                            .font(.system(size: 15, weight: .semibold))
                            .foregroundColor(vm.fg)
                            .padding(.top, 4)

                        ForEach(plans.filter { $0.devices == tier }) { plan in
                            Button {
                                Task { await buy(plan.id) }
                            } label: {
                                HStack {
                                    Text(plan.name)
                                        .font(.system(size: 14, weight: .semibold))
                                    Spacer()
                                    if busyPlan == plan.id {
                                        ProgressView()
                                    } else {
                                        Text(plan.price)
                                            .font(.system(size: 14, weight: .medium))
                                    }
                                }
                                .foregroundColor(vm.bg)
                                .padding(.horizontal, 16)
                                .padding(.vertical, 14)
                                .background(vm.fg)
                                .cornerRadius(12)
                            }
                            .disabled(busyPlan != nil)
                        }

                        Text("Оплата откроется в браузере (YuMoney). После оплаты вернитесь в приложение.")
                            .font(.system(size: 11))
                            .foregroundColor(vm.fg.opacity(0.45))

                        if let errorText {
                            Text(errorText)
                                .font(.system(size: 12))
                                .foregroundColor(.red)
                        }
                    }
                }
                .padding(20)
            }
            .background(vm.bg.ignoresSafeArea())
            .navigationTitle("Подписка")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Закрыть") { dismiss() }
                }
            }
        }
    }

    private func tierChip(_ count: Int, _ label: String) -> some View {
        let on = tier == count
        return Button {
            tier = count
        } label: {
            Text(label)
                .font(.system(size: 13, weight: .semibold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
                .foregroundColor(on ? vm.bg : vm.fg)
                .background(on ? vm.fg : vm.fg.opacity(0.08))
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(vm.fg.opacity(on ? 0.2 : 0.12), lineWidth: 1)
                )
                .cornerRadius(12)
        }
    }

    private func buy(_ planId: String) async {
        busyPlan = planId
        errorText = nil
        defer { busyPlan = nil }
        do {
            let res = try await APIService.shared.initPayment(plan: planId)
            guard let url = URL(string: res.url) else {
                errorText = "Нет ссылки на оплату"
                return
            }
            await UIApplication.shared.open(url)
            await vm.loadProfile()
        } catch {
            errorText = error.localizedDescription
        }
    }
}

private extension String {
    var nilIfEmpty: String? {
        let t = trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty ? nil : t
    }
}
