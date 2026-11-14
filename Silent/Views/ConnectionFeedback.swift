import SwiftUI
import UIKit

struct SilentBrandHeader: View {
    let title: String
    let color: Color
    var progress: Double? = nil
    var stageLabel = ""

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
                .padding(.bottom, progress == nil ? 0 : 31)
                .overlay(alignment: .bottom) {
                    if let progress {
                        Capsule().fill(color.opacity(0.15))
                            .overlay {
                                Capsule().fill(color)
                                    .scaleEffect(x: progress, y: 1, anchor: .leading)
                            }
                            .frame(height: 3)
                            .accessibilityLabel(stageLabel)
                    }
                }
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
        SilentBrandHeader(title: "SILENT VPN", color: palette.fg, progress: progress, stageLabel: stage.title)
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

    private var entries: [VPNLogRow] { VPNLogRow.grouped(vm.connectionLog + tunnelEntries) }
    private let background = Color(red: 0.067, green: 0.094, blue: 0.153)

    var body: some View {
        let rows = entries
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
                        if rows.isEmpty {
                            Text("Лог пуст. Подключите VPN.").foregroundStyle(.white.opacity(0.65))
                        }
                        ForEach(rows) { row in
                            HStack(alignment: .top, spacing: 10) {
                                Text(row.count.formatted())
                                    .font(.caption2.weight(.bold).monospacedDigit())
                                    .foregroundStyle(Color(red: 0.48, green: 0.72, blue: 1))
                                    .padding(.horizontal, 6)
                                    .frame(minWidth: 24, minHeight: 22)
                                    .background(Color(red: 0.12, green: 0.24, blue: 0.39), in: Capsule())
                                    .accessibilityLabel("Повторов: \(row.count)")
                                Text(row.entry.line)
                                    .foregroundStyle(color(for: row.entry.level))
                                    .shadow(color: row.entry.level == .success ? ThemePalette.successGlow(dark: true) : .clear, radius: 4)
                                    .textSelection(.enabled)
                            }
                        }
                        Color.clear.frame(height: 1).id("log-end").accessibilityHidden(true)
                    }
                    .font(.footnote.monospaced())
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(16)
                }
                .onChange(of: vm.connectionLog.last?.id) { _ in
                    scroll.scrollTo("log-end", anchor: .bottom)
                }
                .onChange(of: rows.last?.id) { _ in
                    scroll.scrollTo("log-end", anchor: .bottom)
                }
                .onAppear { scroll.scrollTo("log-end", anchor: .bottom) }
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
        case .success: return ThemePalette.success(dark: true)
        case .error: return Color(red: 1, green: 0.48, blue: 0.48)
        }
    }
}
