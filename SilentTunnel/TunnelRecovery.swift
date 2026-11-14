import Foundation

struct TunnelRecovery {
    enum Action: Equatable { case probe, restart, recovered }

    private enum Phase {
        case healthy(received: Int64, checkAt: TimeInterval)
        case verify(at: TimeInterval, received: Int64, deadline: TimeInterval)
        case retry(at: TimeInterval)
        case restarting
    }

    private var phase: Phase
    private var failures = 0
    private var path: String?
    private var pathVersion = 0
    private var restartPathVersion = 0
    var hasNetwork: Bool { path != nil }
    private static let inactivity: TimeInterval = 45

    init(path: String?, received: Int64, now: TimeInterval) {
        self.path = path
        phase = path == nil ? .retry(at: now) : .healthy(received: received, checkAt: now + Self.inactivity)
    }

    mutating func updatePath(_ path: String?, received: Int64, now: TimeInterval) {
        guard self.path != path else { return }
        let previous = self.path
        self.path = path
        pathVersion += 1
        if case .restarting = phase { return }
        if path == nil || previous == nil {
            failures = 0
            phase = .retry(at: now + 1)
        } else {
            phase = .verify(at: now, received: received, deadline: now + 9)
        }
    }

    mutating func verify(now: TimeInterval, received: Int64) {
        guard path != nil, case .healthy = phase else { return }
        phase = .verify(at: now, received: received, deadline: now + 8)
    }

    mutating func tick(now: TimeInterval, received: Int64) -> Action? {
        guard path != nil else { return nil }
        switch phase {
        case let .healthy(previous, checkAt):
            if received > previous {
                phase = .healthy(received: received, checkAt: now + Self.inactivity)
            } else if now >= checkAt {
                phase = .verify(at: now + 5, received: received, deadline: now + 9)
                return .probe
            }
        case let .verify(at, baseline, deadline):
            if received > baseline {
                phase = .healthy(received: received, checkAt: now + Self.inactivity)
                return .recovered
            }
            if now >= deadline { return startRestart() }
            if now >= at {
                phase = .verify(at: now + 5, received: baseline, deadline: deadline)
                return .probe
            }
        case let .retry(at):
            if now >= at { return startRestart() }
        case .restarting:
            break
        }
        return nil
    }

    mutating func restartFinished(success: Bool, received: Int64, now: TimeInterval) -> Bool {
        guard path != nil, pathVersion == restartPathVersion else {
            phase = .retry(at: now + 1)
            return false
        }
        if success {
            failures = 0
            phase = .healthy(received: received, checkAt: now + Self.inactivity)
            return true
        }
        failures = min(failures + 1, 4)
        phase = .retry(at: now + Double(1 << failures))
        return false
    }

    private mutating func startRestart() -> Action {
        restartPathVersion = pathVersion
        phase = .restarting
        return .restart
    }
}
