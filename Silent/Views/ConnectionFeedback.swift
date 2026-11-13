import SwiftUI

struct ConnectionProgress: View {
    let stage: ConnectionStage
    let palette: Palette
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        VStack(spacing: 8) {
            ProgressView(value: stage.rawValue)
                .tint(palette.fg)
                .animation(reduceMotion ? nil : .easeOut(duration: 0.24), value: stage)
                .accessibilityHidden(true)
            Text(stage.title)
                .font(.footnote)
                .foregroundColor(palette.fg.opacity(0.7))
        }
        .frame(maxWidth: 250)
        .frame(maxWidth: .infinity)
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
        .sheet(isPresented: $showingLog) {
            NavigationStack {
                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        if vm.connectionLog.isEmpty { Text("Журнал пока пуст.") }
                        ForEach(Array(vm.connectionLog.enumerated()), id: \.offset) { entry in
                            Text(entry.element).font(.footnote.monospacedDigit())
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(20)
                }
                .navigationTitle("Журнал подключения")
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Готово") { showingLog = false }
                    }
                }
            }
        }
    }
}
