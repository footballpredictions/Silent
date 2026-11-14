import Foundation

@main
struct TunnelRecoveryTests {
    static func main() {
        for (from, to) in [("Wi-Fi", "Cellular"), ("Cellular", "Wi-Fi"),
                           ("Wi-Fi 1", "Wi-Fi 2"), ("Cellular 1", "Cellular 2")] {
            var tunnel = TunnelRecovery(path: from, received: 100, now: 0)
            tunnel.updatePath(to, received: 100, now: 1)
            precondition(tunnel.tick(now: 1, received: 100) == .probe)
            precondition(tunnel.tick(now: 2, received: 192) == .recovered)
            precondition(tunnel.tick(now: 3, received: 192) == nil)
        }

        var tunnel = TunnelRecovery(path: "Wi-Fi", received: 100, now: 0)
        tunnel.updatePath(nil, received: 0, now: 1)
        precondition(tunnel.tick(now: 60, received: 100) == nil)
        tunnel.updatePath("Cellular", received: 100, now: 61)
        precondition(tunnel.tick(now: 61, received: 100) == nil)
        precondition(tunnel.tick(now: 62, received: 100) == .restart)
        precondition(tunnel.tick(now: 63, received: 0) == nil)
        tunnel.updatePath("Wi-Fi", received: 0, now: 64)
        tunnel.updatePath("Cellular", received: 0, now: 64.5)
        precondition(!tunnel.restartFinished(success: true, received: 92, now: 65))
        precondition(tunnel.tick(now: 66, received: 92) == .restart)
        precondition(!tunnel.restartFinished(success: false, received: 0, now: 67))
        precondition(tunnel.tick(now: 68, received: 0) == nil)
        precondition(tunnel.tick(now: 69, received: 0) == .restart)
        precondition(tunnel.restartFinished(success: true, received: 92, now: 70))

        // A call or a carrier outage can leave the same path selected.
        tunnel.verify(now: 71, received: 92)
        precondition(tunnel.tick(now: 71, received: 92) == .probe)
        precondition(tunnel.tick(now: 76, received: 92) == .probe)
        precondition(tunnel.tick(now: 79, received: 92) == .restart)
        precondition(tunnel.restartFinished(success: true, received: 92, now: 80))
        precondition(tunnel.tick(now: 124, received: 92) == nil)
        precondition(tunnel.tick(now: 125, received: 92) == .probe)
        precondition(tunnel.tick(now: 126, received: 184) == .recovered)
        print("Tunnel recovery: PASS")
    }
}
