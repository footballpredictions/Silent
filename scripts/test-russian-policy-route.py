"""Replay the actual policy fetch when LTE only permits the VPN gateway."""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'Shared/RussianServices.swift').read_text(encoding='utf-8')
model = source[source.index('struct RussianRoutingPolicy'):source.index('enum RussianServices')]
start = source.index('    static func refresh(')
opening = source.index('{', start)
depth, end = 1, opening + 1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1
method = source[start:end].replace('URLSession(configuration:', 'PolicyHTTP(configuration:')
active = 'refresh(tunnelActive: true)' if 'tunnelActive:' in method.split('{', 1)[0] else 'refresh()'
offline = 'refresh(tunnelActive: false)' if 'tunnelActive:' in method.split('{', 1)[0] else 'refresh()'
fixture = '''import Foundation
MODEL
@MainActor final class PolicyHTTP {
    static var requests:[String] = []
    static var gatewayOnly = true
    init(configuration: URLSessionConfiguration) {}
    func invalidateAndCancel() {}
    func data(from url:URL) async throws -> (Data,URLResponse) {
        Self.requests.append(url.absoluteString)
        let gateway = url.host == "10.66.66.1"
        guard gateway == Self.gatewayOnly else { throw URLError(.timedOut) }
        let json = "{\\"schema_version\\":1,\\"revision\\":\\"" + String(repeating:"a",count:64) + "\\",\\"direct_domains\\":[\\"yandex.ru\\"],\\"vpn_domains\\":[\\"youtube.com\\"]}"
        return (Data(json.utf8),HTTPURLResponse(url:url,statusCode:200,httpVersion:nil,headerFields:nil)!)
    }
}
@MainActor enum RussianServices {
    static var cacheURL:URL? = nil
METHOD
}
@main struct PolicyRouteTest {
    @MainActor static func main() async throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        RussianServices.cacheURL = url
        defer { try? FileManager.default.removeItem(at:url) }
        guard let policy = await RussianServices.ACTIVE, policy.valid, policy.enabled == true else {
            print("FAIL: VPN works but policy fetch never uses its gateway on whitelist LTE; received-list status remains absent")
            exit(1)
        }
        guard PolicyHTTP.requests.first == "http://10.66.66.1:8000/api/vpn/routing-policy" else { exit(1) }
        let cached = try Data(contentsOf:url)
        precondition(try JSONDecoder().decode(RussianRoutingPolicy.self,from:cached).valid)
        PolicyHTTP.requests = []
        PolicyHTTP.gatewayOnly = false
        guard await RussianServices.OFFLINE != nil else { exit(1) }
        guard !PolicyHTTP.requests.contains(where:{$0.contains("10.66.66.1")}) else { exit(1) }
        print("PASS: live VPN policy uses gateway first; VPN-off fetch retains public routes")
    }
}
'''.replace('MODEL', model).replace('METHOD', method).replace('ACTIVE', active).replace('OFFLINE', offline)
with tempfile.TemporaryDirectory(prefix='silent-policy-route-') as directory:
    path = Path(directory)
    swift = path / 'Policy.swift'
    swift.write_text(fixture,encoding='utf-8')
    binary = path / 'policy-test'
    subprocess.run([shutil.which('swiftc') or 'swiftc','-parse-as-library',str(swift),'-o',str(binary)],check=True,timeout=60)
    subprocess.run([str(binary)],check=True,timeout=10)
