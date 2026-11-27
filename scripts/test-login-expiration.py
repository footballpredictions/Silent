"""Replay the app's temporary-tunnel disconnect handling at expiry."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
vm = (root / "Silent/ViewModels/MainViewModel.swift").read_text(encoding="utf-8")
view = (root / "Silent/Views/LoginView.swift").read_text(encoding="utf-8")
observer = vm.split("private func onVPNStateChanged(", 1)[1]
bootstrap = observer[observer.index("        if bootstrapActive {"):
                     observer.index("        guard (loggedIn || api.isLoggedIn)")]
timer = vm[vm.index("    func expireBootstrap(at"):vm.index("    func prepareToCloseExpiredLogin")]

fixture = r'''
import Foundation

enum State { case disconnected, reconnecting }
enum RegistrationTunnelRoute { static let expiredMessage = "Время временного VPN истекло" }
struct API { var isLoggedIn = false }
struct VPN {
    var error: String?
    func readError() -> String? { error }
}

final class LoginFixture {
    var api = API()
    var vpn = VPN()
    var loggedIn = false
    var bootstrapActive = true, bootstrapStarting = false, bootstrapReconnecting = false
    var bootstrapExpired = false, bootstrapFailed = false, bootstrapMailReady = true
    var bootstrapDeadline: Date? = .now.addingTimeInterval(120)
    func disconnect() {
        let state = State.disconnected
        BOOTSTRAP
    }
    TIMER
    func logConnection(_ text: String) {}
}

@main struct LoginExpirationTest {
    static func main() {
        let timer = LoginFixture()
        timer.vpn.error = RegistrationTunnelRoute.expiredMessage
        timer.disconnect()
        guard timer.bootstrapExpired && !timer.bootstrapFailed && timer.bootstrapDeadline == nil else {
            print("FAIL: provider timeout is shown as a connection failure instead of expired login")
            exit(1)
        }
        let early = LoginFixture()
        early.vpn.error = "Network unavailable"
        early.disconnect()
        precondition(!early.bootstrapExpired && early.bootstrapFailed)

        let late = LoginFixture()
        late.bootstrapDeadline = .distantPast
        late.disconnect()
        precondition(late.bootstrapExpired && !late.bootstrapFailed)

        let mail = LoginFixture()
        mail.bootstrapStarting = true
        mail.vpn.error = RegistrationTunnelRoute.expiredMessage
        mail.disconnect()
        precondition(mail.bootstrapExpired && !mail.bootstrapActive)

        let signedIn = LoginFixture()
        signedIn.api.isLoggedIn = true
        signedIn.bootstrapStarting = true
        signedIn.vpn.error = RegistrationTunnelRoute.expiredMessage
        signedIn.disconnect()
        precondition(!signedIn.bootstrapExpired)
        let foreground = LoginFixture()
        let oldDeadline = Date().addingTimeInterval(-30)
        foreground.expireBootstrap(at: oldDeadline)
        precondition(!foreground.bootstrapExpired)
        foreground.bootstrapDeadline = oldDeadline
        foreground.expireBootstrap(at: oldDeadline)
        precondition(foreground.bootstrapExpired)
        foreground.disconnect()
        precondition(foreground.bootstrapExpired && !foreground.bootstrapFailed)
        print("PASS: temporary VPN expiry, old timer rejection, early failure, and mail-route transition")
    }
}
'''

with tempfile.TemporaryDirectory(prefix="silent-login-expiry-") as directory:
    path = Path(directory)
    swift = path / "Expiry.swift"
    swift.write_text(fixture.replace("        BOOTSTRAP", bootstrap).replace("    TIMER", timer), encoding="utf-8")
    binary = path / "expiry-test"
    subprocess.run(["swiftc", "-parse-as-library", str(swift), "-o", str(binary)], check=True, timeout=60)
    subprocess.run([str(binary)], check=True, timeout=10)

assert "if vm.bootstrapExpired {" in view and "vm.expireBootstrap(at: deadline)" in view
assert 'Text("Закрыть приложение")' in view and "requestSceneSessionDestruction" in view
