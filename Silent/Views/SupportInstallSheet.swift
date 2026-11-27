import CoreImage
import SwiftUI
import UIKit

enum SupportMobileInstaller: String, Identifiable {
    case android = "Android"
    case ios = "iOS"

    var id: String { rawValue }
}

struct SupportInstallSheet: View {
    let platform: SupportMobileInstaller
    let palette: Palette
    @Environment(\.dismiss) private var dismiss
    @State private var apk: URL?
    @State private var loading = true
    @State private var attempt = 0

    private static let testFlight = URL(string: "https://apps.apple.com/app/testflight/id899247664")!
    private static let invitation = URL(string: "https://testflight.apple.com/join/FVCNuq38")!
    private static let qrContext = CIContext()

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    if platform == .ios {
                        qrLink("TestFlight", to: Self.testFlight)
                        qrLink("Silent VPN", to: Self.invitation)
                    } else if loading {
                        ProgressView().tint(palette.fg)
                    } else if let apk {
                        qrLink("Silent VPN для Android", to: apk)
                    } else {
                        Text("Не удалось получить ссылку на актуальную версию.")
                            .font(.subheadline)
                            .foregroundStyle(palette.fg)
                        Button("Повторить") {
                            loading = true
                            attempt += 1
                        }
                        .tint(palette.link)
                    }
                }
                .multilineTextAlignment(.center)
                .frame(maxWidth: 420)
                .padding(20)
                .frame(maxWidth: .infinity)
            }
            .background(palette.bg.ignoresSafeArea())
            .navigationTitle(platform.rawValue)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Закрыть") { dismiss() }.tint(palette.link)
                }
            }
        }
        .presentationDetents([.large])
        .task(id: attempt) {
            guard platform == .android else { return }
            apk = try? await Self.latestAndroidApk()
            if !Task.isCancelled { loading = false }
        }
    }

    private func qrLink(_ title: String, to url: URL) -> some View {
        Link(destination: url) {
            VStack(spacing: 8) {
                Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(palette.fg)
                if let image = Self.qrImage(url) {
                    Image(uiImage: image)
                        .resizable()
                        .interpolation(.none)
                        .scaledToFit()
                        .frame(maxWidth: 204)
                        .padding(28)
                        .background(.white, in: RoundedRectangle(cornerRadius: 8))
                        .accessibilityHidden(true)
                }
            }
        }
    }

    private static func qrImage(_ url: URL) -> UIImage? {
        guard let filter = CIFilter(name: "CIQRCodeGenerator") else { return nil }
        filter.setValue(Data(url.absoluteString.utf8), forKey: "inputMessage")
        filter.setValue("M", forKey: "inputCorrectionLevel")
        guard let output = filter.outputImage else { return nil }
        let image = output.transformed(by: CGAffineTransform(scaleX: 12, y: 12))
        return qrContext.createCGImage(image, from: image.extent).map { UIImage(cgImage: $0) }
    }

    private static func latestAndroidApk() async throws -> URL? {
        struct ReleaseIndex: Decodable {
            struct Android: Decodable { let download_url: URL }
            let android: Android
        }
        let manifest = URL(string: "https://silentvpn3.github.io/releases.json?_=\(Date().timeIntervalSince1970)")!
        let request = URLRequest(url: manifest, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 8)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        let url = try JSONDecoder().decode(ReleaseIndex.self, from: data).android.download_url
        return url.scheme == "https" && url.host == "github.com" &&
            url.path.hasPrefix("/silentvpn3/silentvpn3.github.io/releases/download/") &&
            url.pathExtension == "apk" && url.query == nil && url.fragment == nil ? url : nil
    }
}
