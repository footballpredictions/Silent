import SwiftUI

struct ThemeModeButton: View {
    let dark: Bool
    let ink: Color
    let action: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: action) {
            ThemeGlyph(progress: dark ? 1 : 0, ink: ink)
                .frame(width: 22, height: 22)
                .animation(reduceMotion ? nil : .timingCurve(0.4, 0, 0.2, 1, duration: 0.52), value: dark)
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Сменить тему")
        .accessibilityValue(dark ? "Тёмная" : "Светлая")
    }
}

private struct ThemeGlyph: View, Animatable {
    var progress: Double
    let ink: Color

    var animatableData: Double {
        get { progress }
        set { progress = newValue }
    }

    var body: some View {
        Canvas { context, size in
            let t = min(1, max(0, progress))
            let d = min(size.width, size.height)
            let r = d * 0.22
            let x = size.width / 2
            let y = size.height / 2

            let alpha = max(0, 1 - t * 1.1)
            if alpha > 0.02 {
                let scale = 1 - 0.55 * t
                var rays = Path()
                for i in 0..<8 {
                    let angle = Double(i) * .pi / 4 + .pi / 2 * t
                    let start = (r + d * 0.05) * scale
                    let end = d * 0.44 * scale
                    rays.move(to: CGPoint(x: x + cos(angle) * start, y: y + sin(angle) * start))
                    rays.addLine(to: CGPoint(x: x + cos(angle) * end, y: y + sin(angle) * end))
                }
                context.stroke(rays, with: .color(ink.opacity(alpha)), lineWidth: d * 0.07 * scale)
            }

            var disc = context
            disc.translateBy(x: x, y: y)
            disc.rotate(by: .degrees(-28 * t))
            disc.scaleBy(x: 1 + 0.08 * t, y: 1 + 0.08 * t)
            disc.drawLayer { layer in
                layer.fill(Path(ellipseIn: CGRect(x: -r, y: -r, width: r * 2, height: r * 2)), with: .color(ink))
                if t > 0.01 {
                    let cut = r * (0.82 + 0.08 * t) * t
                    layer.blendMode = .destinationOut
                    layer.fill(Path(ellipseIn: CGRect(x: r * 0.58 - cut, y: -r * 0.32 - cut, width: cut * 2, height: cut * 2)), with: .color(.black))
                }
            }
        }
        .accessibilityHidden(true)
    }
}
