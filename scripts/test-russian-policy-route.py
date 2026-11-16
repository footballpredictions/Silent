"""Check actual provider transport wiring, injected gateway, and HTTP bytes.

Public URLSession fallbacks are replaced, but the private gateway must be
explicitly supplied by the provider's through-tunnel transport. Apple NECP
routing itself still requires an iOS device.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
provider = (root / 'SilentTunnel/PacketTunnelProvider.swift').read_text(encoding='utf-8')
transport_path = root / 'SilentTunnel/PolicyTunnelHTTP.swift'
assert transport_path.is_file(), 'Provider policy refresh lacks an explicit through-tunnel transport'
transport = transport_path.read_text(encoding='utf-8')
assert 'createTCPConnectionThroughTunnel(' in transport, 'Gateway must use the provider through-tunnel API'
assert 'PolicyTunnelHTTP.fetch(through: self)' in provider, 'Actual provider does not supply its through-tunnel transport'
assert 'RussianServices.refresh(fetchGateway:' in provider, 'Actual refresh bypasses its injected gateway transport'
assert 'URLSession' not in transport, 'Plain provider HTTP does not select its virtual interface'
source = (root / 'Shared/RussianServices.swift').read_text(encoding='utf-8')
assert 'http://10.66.66.1:8000' not in source, 'Private gateway must not be a plain URLSession fallback'
model = source[source.index('struct RussianRoutingPolicy'):source.index('enum RussianServices')]
start = source.index('    static func refresh(')
opening = source.index('{', start)
depth, end = 1, opening + 1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1
method = source[start:end].replace('URLSession(configuration:', 'PolicyHTTP(configuration:')
parser = transport[transport.index('enum PolicyHTTPResponse'):]
fixture = r'''import Foundation
MODEL
PARSER
@MainActor final class PolicyHTTP {
    static var requests:[String] = []
    static var publicWorks = false
    static let json = Data(("{\"schema_version\":1,\"revision\":\"" + String(repeating:"a",count:64) + "\",\"direct_domains\":[\"yandex.ru\"],\"vpn_domains\":[\"youtube.com\"]}").utf8)
    init(configuration: URLSessionConfiguration) {}
    func invalidateAndCancel() {}
    func data(from url:URL) async throws -> (Data,URLResponse) {
        Self.requests.append(url.absoluteString)
        guard Self.publicWorks else { throw URLError(.timedOut) }
        return (Self.json,HTTPURLResponse(url:url,statusCode:200,httpVersion:nil,headerFields:nil)!)
    }
}
@MainActor enum RussianServices {
    static var cacheURL:URL? = nil
METHOD
}
@main struct PolicyRouteTest {
    static func rejects(_ bytes: Data, complete: Bool = true) {
        do { _ = try PolicyHTTPResponse.parse(bytes, complete:complete); preconditionFailure("accepted bad HTTP") }
        catch {}
    }
    @MainActor static func main() async throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        RussianServices.cacheURL = url
        defer { try? FileManager.default.removeItem(at:url) }
        var gatewayCalls = 0
        guard let policy = await RussianServices.refresh(fetchGateway:{ gatewayCalls += 1; return PolicyHTTP.json }), policy.valid, policy.enabled == true else { exit(1) }
        precondition(gatewayCalls == 1 && PolicyHTTP.requests.isEmpty)
        let cached = try Data(contentsOf:url)
        let decoded = try JSONDecoder().decode(RussianRoutingPolicy.self,from:cached)
        precondition(decoded.valid)
        guard await RussianServices.refresh(fetchGateway:{ throw URLError(.timedOut) }) == nil else { exit(1) }
        let retained = try Data(contentsOf:url)
        precondition(retained == cached)
        precondition(!PolicyHTTP.requests.isEmpty && !PolicyHTTP.requests.contains(where:{$0.contains("10.66.66.1")}))
        PolicyHTTP.requests = []; PolicyHTTP.publicWorks = true
        guard await RussianServices.refresh() != nil else { exit(1) }
        precondition(!PolicyHTTP.requests.isEmpty)
        PolicyHTTP.requests = []
        guard await RussianServices.refresh(fetchGateway:{ throw URLError(.timedOut) }) != nil else { exit(1) }
        precondition(!PolicyHTTP.requests.isEmpty)
        let task = Task { () -> RussianRoutingPolicy? in
            await RussianServices.refresh(fetchGateway:{
                try await Task.sleep(nanoseconds:10_000_000_000)
                return PolicyHTTP.json
            })
        }
        PolicyHTTP.requests = []; task.cancel()
        let cancelled = await task.value
        precondition(cancelled == nil && PolicyHTTP.requests.isEmpty)
        let head = Data("HTTP/1.1 200 OK\r\nContent-Length: \(cached.count)\r\n\r\n".utf8)
        let partial = try PolicyHTTPResponse.parse(head + cached.dropLast(),complete:false)
        let fixed = try PolicyHTTPResponse.parse(head + cached,complete:false)
        let closed = try PolicyHTTPResponse.parse(Data("HTTP/1.0 200 OK\r\n\r\n".utf8)+cached,complete:true)
        precondition(partial == nil && fixed == cached && closed == cached)
        rejects(head+cached.dropLast())
        rejects(Data("HTTP/1.1 503 Unavailable\r\nContent-Length: 0\r\n\r\n".utf8))
        rejects(Data("HTTP/1.1 200 OK\r\nContent-Length: 262145\r\n\r\n".utf8))
        rejects(Data("HTTP/1.1 200 OK\r\nContent-Length: 0\r\nContent-Length: 0\r\n\r\n".utf8))
        rejects(Data("HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n".utf8))
        rejects(Data("HTTP/1.1 200 OK\r\n\r\n".utf8)+Data(repeating:65,count:262145))
        rejects(Data(repeating:65,count:16*1024),complete:false)
        print("PASS: provider through-tunnel gateway; success/offline/fallback/cancellation/cache/HTTP bounds")
    }
}
'''.replace('MODEL', model).replace('METHOD', method).replace('PARSER', parser)
with tempfile.TemporaryDirectory(prefix='silent-policy-route-') as directory:
    path = Path(directory)
    swift = path / 'Policy.swift'
    swift.write_text(fixture, encoding='utf-8')
    binary = path / 'policy-test'
    subprocess.run([shutil.which('swiftc') or 'swiftc', '-parse-as-library', str(swift), '-o', str(binary)], check=True, timeout=60)
    subprocess.run([str(binary)], check=True, timeout=10)

# Run the unchanged Transfer implementation with a KVO-capable connection.
# This verifies scheduling, teardown and exactly-once continuation completion,
# without pretending the stub can validate Apple's NECP routing policy.
connection_fixture = r'''
@objc enum NWTCPConnectionState: Int { case invalid, connecting, waiting, connected, disconnected, cancelled }
final class NWHostEndpoint {
    let hostname:String; let port:String
    init(hostname:String,port:String){self.hostname=hostname;self.port=port}
}
final class NWTCPConnection: NSObject {
    @objc dynamic var state:NWTCPConnectionState = .connected
    let events = NSLock()
    var chunks:[Data] = []
    var stall = false
    private(set) var requests:[Data] = []
    private(set) var cancels = 0
    var lateRead:((Data?,Error?)->Void)?
    func write(_ data:Data,completionHandler:@escaping(Error?)->Void){
        events.lock();requests.append(data);events.unlock()
        completionHandler(nil)
    }
    func readMinimumLength(_ minimum:Int,maximumLength:Int,completionHandler:@escaping(Data?,Error?)->Void){
        events.lock()
        if stall {lateRead=completionHandler;events.unlock();return}
        let data = chunks.isEmpty ? nil : chunks.removeFirst()
        events.unlock()
        completionHandler(data,nil)
    }
    func cancel(){events.lock();cancels += 1;events.unlock()}
    func writes()->Int{events.lock();defer{events.unlock()};return requests.count}
    func cancellationCount()->Int{events.lock();defer{events.unlock()};return cancels}
    func deliverLate(){
        events.lock();let callback=lateRead;lateRead=nil;events.unlock()
        callback?(Data("late".utf8),nil)
    }
}
final class NEPacketTunnelProvider {
    let connection:NWTCPConnection
    init(_ connection:NWTCPConnection){self.connection=connection}
    func createTCPConnectionThroughTunnel(to endpoint:NWHostEndpoint,enableTLS:Bool,tlsParameters:Any?,delegate:Any?)->NWTCPConnection {
        precondition(endpoint.hostname == "10.66.66.1" && endpoint.port == "8000" && !enableTLS)
        return connection
    }
}
@main struct PolicyTransferTest {
    static func main() async throws {
        let good=NWTCPConnection()
        good.chunks=[Data("HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{".utf8),Data("}".utf8)]
        let bytes=try await PolicyTunnelHTTP.fetch(through:NEPacketTunnelProvider(good))
        precondition(bytes == Data("{}".utf8) && good.writes() == 1 && good.cancellationCount() == 1)
        let closeDelimited=NWTCPConnection()
        closeDelimited.chunks=[Data("HTTP/1.0 200 OK\r\n\r\n{}".utf8)]
        let closed=try await PolicyTunnelHTTP.fetch(through:NEPacketTunnelProvider(closeDelimited))
        precondition(closed == Data("{}".utf8) && closeDelimited.cancellationCount() == 1)
        let stalled=NWTCPConnection();stalled.stall=true
        let cancelled=Task{try await PolicyTunnelHTTP.fetch(through:NEPacketTunnelProvider(stalled))}
        for _ in 0..<100 where stalled.writes() == 0 {try await Task.sleep(nanoseconds:1_000_000)}
        precondition(stalled.writes() == 1)
        cancelled.cancel()
        do{_ = try await cancelled.value;preconditionFailure("cancelled transfer completed")}catch is CancellationError{}catch{preconditionFailure("wrong cancellation error")}
        stalled.deliverLate() // Late reads and KVO after cancellation cannot resume twice.
        stalled.state = .connected
        let timeout=NWTCPConnection();timeout.stall=true
        do{_ = try await PolicyTunnelHTTP.fetch(through:NEPacketTunnelProvider(timeout));preconditionFailure("stalled transfer completed")}
        catch let error as URLError{precondition(error.code == .timedOut)}
        timeout.deliverLate()
        let invalid=NWTCPConnection();invalid.state = .invalid
        do{_ = try await PolicyTunnelHTTP.fetch(through:NEPacketTunnelProvider(invalid));preconditionFailure("invalid connection completed")}catch{}
        precondition(invalid.writes() == 0 && invalid.cancellationCount() == 1)
        try await Task.sleep(nanoseconds:10_000_000)
        print("PASS: actual Transfer KVO/write/read/EOF/deadline/cancellation/late completion")
    }
}
'''
with tempfile.TemporaryDirectory(prefix='silent-policy-transfer-') as directory:
    path = Path(directory)
    swift = path / 'Transfer.swift'
    swift.write_text(transport.replace('import NetworkExtension', '') + connection_fixture, encoding='utf-8')
    binary = path / 'transfer-test'
    subprocess.run([shutil.which('swiftc') or 'swiftc', '-parse-as-library', str(swift), '-o', str(binary)], check=True, timeout=60)
    subprocess.run([str(binary)], check=True, timeout=10)
