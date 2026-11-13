import SwiftUI
import UIKit

struct SilentBrandHeader: View {
    let title: String
    let color: Color

    var body: some View {
        VStack(spacing: 12) {
            Text("S")
                .font(.system(size: 22, weight: .bold))
                .foregroundStyle(.white)
                .frame(width: 56, height: 56)
                .background(.black, in: RoundedRectangle(cornerRadius: 16))
                .accessibilityHidden(true)
            Text(title)
                .font(.headline.weight(.bold))
                .tracking(3)
                .foregroundColor(color)
        }
        .frame(maxWidth: .infinity)
    }
}

struct LaunchSplash: View {
    let stage: ConnectionStage
    let palette: Palette
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var progress = 0.03

    var body: some View {
        VStack(spacing: 28) {
            SilentBrandHeader(title: "SILENT VPN", color: palette.fg)
            ZStack(alignment: .leading) {
                Capsule().fill(palette.fg.opacity(0.15))
                Capsule().fill(palette.fg)
                    .scaleEffect(x: progress, y: 1, anchor: .leading)
            }
            .frame(width: 208, height: 3)
            .accessibilityLabel(stage.title)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(palette.bg.ignoresSafeArea())
        .onAppear { updateProgress(stage) }
        .onChange(of: stage) { updateProgress($0) }
    }

    private func updateProgress(_ stage: ConnectionStage) {
        withAnimation(reduceMotion ? nil : .easeOut(duration: 0.24)) {
            progress = max(progress, stage.rawValue)
        }
    }
}

struct ConnectionLogButton: View {
    @EnvironmentObject private var vm: MainViewModel
    @State private var showingLog = false
    let palette: Palette

    var body: some View {
        Button { showingLog = true } label: {
            Text("Лог")
                .font(.footnote.weight(.medium))
                .foregroundColor(palette.fg.opacity(0.68))
                .frame(minWidth: 44, minHeight: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityHint("Открывает журнал подключения")
        .sheet(isPresented: $showingLog) { VPNLogPanel() }
    }
}

private struct VPNLogPanel: View {
    @EnvironmentObject private var vm: MainViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var tunnelEntries: [VPNLogEntry] = []
    @State private var copied = false

    private var entries: [VPNLogEntry] { (vm.connectionLog + tunnelEntries).sorted { $0.date < $1.date } }
    private let background = Color(red: 0.067, green: 0.094, blue: 0.153)

    var body: some View {
        VStack(spacing: 0) {
            ViewThatFits(in: .horizontal) {
                HStack { title; Spacer(); actions }
                VStack(alignment: .leading, spacing: 4) { title; actions }
            }
            .padding(.horizontal, 16)
            .padding(.top, 12)
            Divider().overlay(.white.opacity(0.15))
            ScrollViewReader { scroll in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 8) {
                        if entries.isEmpty {
                            Text("Лог пуст. Подключите VPN.").foregroundStyle(.white.opacity(0.65))
                        }
                        ForEach(entries) { entry in
                            Text(entry.line)
                                .foregroundStyle(color(for: entry.level))
                                .textSelection(.enabled)
                                .id(entry.id)
                        }
                    }
                    .font(.footnote.monospaced())
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(16)
                }
                .onChange(of: entries.last?.id) { id in
                    if let id { scroll.scrollTo(id, anchor: .bottom) }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(background.ignoresSafeArea())
        .preferredColorScheme(.dark)
        .task {
            while !Task.isCancelled {
                tunnelEntries = VPNLog.read()
                do { try await Task.sleep(nanoseconds: 1_000_000_000) } catch { return }
            }
        }
    }

    private var title: some View { Text("Лог VPN").font(.headline).foregroundStyle(.white) }

    private var actions: some View {
        HStack(spacing: 12) {
            Button(copied ? "Скопировано" : "Копировать") {
                UIPasteboard.general.string = entries.map(\.line).joined(separator: "\n")
                copied = true
            }
            .foregroundStyle(Color(red: 0.38, green: 0.65, blue: 0.98))
            .disabled(entries.isEmpty)
            Button("Очистить") {
                vm.clearVPNLog()
                tunnelEntries = []
                copied = false
            }
            Button("Закрыть") { dismiss() }
        }
        .font(.footnote.weight(.medium))
        .foregroundStyle(.white.opacity(0.72))
        .buttonStyle(.plain)
        .frame(minHeight: 44)
    }

    private func color(for level: VPNLogLevel) -> Color {
        switch level {
        case .info: return Color(white: 0.90)
        case .success: return Color(red: 0.20, green: 0.83, blue: 0.60)
        case .error: return Color(red: 1, green: 0.48, blue: 0.48)
        }
    }
}
