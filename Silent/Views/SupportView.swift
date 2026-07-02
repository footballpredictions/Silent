import SwiftUI

struct SupportView: View {
    @ObservedObject var vm: MainViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationView {
            VStack(alignment: .leading, spacing: 16) {
                Text("По вопросам обратитесь через Telegram.")
                    .font(.system(size: 12))
                    .foregroundColor(vm.fg.opacity(0.5))

                HStack(spacing: 24) {
                    telegramLink(
                        label: "Канал",
                        url: vm.theme?.telegram_channel_url.isEmpty == false
                            ? vm.theme!.telegram_channel_url
                            : "https://t.me/silentvpn3"
                    )
                    telegramLink(
                        label: "Поддержка",
                        url: vm.theme?.support_url.isEmpty == false
                            ? vm.theme!.support_url
                            : "https://t.me/silentvpn3?direct"
                    )
                }
                Spacer()
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(vm.bg)
            .navigationTitle("Поддержка")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Закрыть") { dismiss() }
                }
            }
        }
    }

    @ViewBuilder
    private func telegramLink(label: String, url: String) -> some View {
        Button {
            if let u = URL(string: url) { UIApplication.shared.open(u) }
        } label: {
            VStack(spacing: 8) {
                ZStack {
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .fill(Color(red: 0.95, green: 0.96, blue: 0.97))
                        .frame(width: 48, height: 48)
                    TelegramIconView()
                        .frame(width: 28, height: 28)
                }
                Text(label)
                    .font(.system(size: 11))
                    .foregroundColor(vm.fg.opacity(0.5))
            }
        }
        .buttonStyle(.plain)
    }
}

private struct TelegramIconView: View {
    var body: some View {
        Canvas { context, size in
            let rect = CGRect(origin: .zero, size: size)
            context.fill(Path(ellipseIn: rect), with: .color(.clear))
            let path = Path { p in
                p.addEllipse(in: rect)
            }
            context.fill(path, with: .color(.black))
            // Simplified plane mark
            let plane = Path { p in
                p.move(to: CGPoint(x: size.width * 0.28, y: size.height * 0.48))
                p.addLine(to: CGPoint(x: size.width * 0.78, y: size.height * 0.32))
                p.addLine(to: CGPoint(x: size.width * 0.42, y: size.height * 0.56))
                p.addLine(to: CGPoint(x: size.width * 0.48, y: size.height * 0.72))
                p.closeSubpath()
            }
            context.fill(plane, with: .color(.white))
        }
    }
}
