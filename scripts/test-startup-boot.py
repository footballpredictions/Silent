"""Replay the real saved-account/bootstrap/load-account call chain on macOS.

OS VPN setup and network responses are fixtures. Production orchestration is
extracted unchanged; a virtual clock exposes serial network waits immediately.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
ios = root if (root / 'Silent/ViewModels').is_dir() else root / 'ios'
source = (ios / 'Silent/ViewModels/MainViewModel.swift').read_text(encoding='utf-8')
api_source = (ios / 'Silent/Services/APIService.swift').read_text(encoding='utf-8')

def method(name, text=source):
    pos = text.index('func ' + name + '(')
    start = text.rfind('\n', 0, pos) + 1
    opening = text.index('{', pos)
    depth, end = 1, opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]

methods = '\n'.join(method(name) for name in [
    'loadInitialData', 'restoreSavedAccount', 'startBootstrap', 'connectBootstrap',
    'loadAccount', 'stopBootstrap', 'rememberLoginSession',
])
if 'func rememberConfigSession(' in source:
    methods += '\n' + method('rememberConfigSession')
get_profile = method('getProfile', api_source)

fixture = r'''import Foundation
enum APIError:Error { case network, unauthorized, http(Int,String), server(String), bootstrapUnavailable(String) }
enum Stage { case configuration, session, tunnel, data }
enum State { case connected, disconnected }
struct Subscription:Codable { var is_active=true }
struct DeviceInfo:Codable {var id="fixture-main-device"}
struct UserProfile:Codable { var id="fixture-startup-account";var is_admin=true;var subscription=Subscription();var current_device_id:String?;var devices=[DeviceInfo()] }
struct VpnConfig {var device_id="fixture-main-device"}
struct TunnelConfig:Codable { var deviceId="boot:fixture";var serverIP="";var hashes=["fixture-hash"];var bootstrapDuration:Int?=300;var registrationRouting:Bool?;var paymentRouting:Bool?;var dns:[String]=[] }
struct BootstrapCache:Codable {var savedAt:Date;var config:TunnelConfig}
enum LocalStore {static let preferredServer="server1"}
enum PublicApiFailover {static func serverQuery(_ path:String,fingerprint:String)->String{path}}
enum RegistrationTunnelRoute {static let internetDNS=["1.1.1.1"]}
enum KeychainHelper {static func get(_ key:String)->String?{nil};static func set(_ value:String,key:String){} }
enum BootstrapLaunch {
 static let cellHosts=["cell1","cell2"]; static let duration=300
 static func configuration(hash:String,fingerprint:String,password:String,cell:Int,registrationRouting:Bool=false)->TunnelConfig? {
    guard cellHosts.indices.contains(cell) else{return nil}
    return TunnelConfig(serverIP:cellHosts[cell],registrationRouting:registrationRouting ? true:nil)
 }
}
@MainActor final class Clock {
 var elapsed=0.0;var events:[String]=[]
 func record(_ event:String,_ duration:Double=0){events.append(event);elapsed += duration}
}
@MainActor final class VPN {
 let clock:Clock; var state=State.disconnected;let sceneDiscardCount=0
 init(_ clock:Clock){self.clock=clock}
 func isApiTunnelActive() async ->Bool{state == .connected}
 func connect(_ config:TunnelConfig,timeout:TimeInterval?=nil) async throws {
   if config.serverIP=="cell1" {clock.record("connect:cell1",timeout ?? 50);throw APIError.network}
   clock.record("connect:cell2",1.2);state = .connected
 }
 func disconnect() async {clock.record("stop");state = .disconnected}
}
@MainActor final class API {
 let vpn:VPN;let clock:Clock;let publicHealthy:Bool
 var isLoggedIn=true;let deviceFingerprint="fixture";var revokeProfile=false;var gatewayFailure=false
 init(_ vpn:VPN,_ clock:Clock,publicHealthy:Bool){self.vpn=vpn;self.clock=clock;self.publicHealthy=publicHealthy}
 func probeSavedProfile() async throws ->UserProfile? {
   try Task.checkCancellation()
   clock.record("public-probe",publicHealthy ? 0.1:3)
   return publicHealthy ? UserProfile():nil
 }
 func request<T:Decodable>(_ path:String,tunnelOnly:Bool=false) async throws ->T {
   try Task.checkCancellation()
   precondition(path == "api/users/me")
   if revokeProfile {clock.record("profile:revoked");throw APIError.unauthorized}
   if vpn.state == .connected {
      clock.record("profile:tunnel",gatewayFailure ? 5:0.1)
      if gatewayFailure {
        if !tunnelOnly {clock.record("profile:public-failover",40)}
        throw APIError.network
      }
      return try JSONDecoder().decode(T.self,from:JSONEncoder().encode(UserProfile()))
   }
   clock.record("profile:public-failover",40);throw APIError.network
 }
 func bootstrapConfig(hash:String,onAttempt:(String)->Void) async throws ->VpnConfig {
   clock.record("bootstrap:https-fallback",20);throw APIError.bootstrapUnavailable("fixture offline")
 }
 func checkTunnelGateway() async throws {clock.record("gateway",0.1)}
 func logout(){isLoggedIn=false}
GET_PROFILE
}
@MainActor final class VM {
 let api:API;let vpn:VPN;let clock:Clock
 var loggedIn=false;var authLoading=false;var launchStage:Stage? = .configuration
 var authError:String?;var authLoadingTitle="";var profile:UserProfile?;var selectedServer="server1"
 var bootstrapActive=false;var bootstrapAttempted=false;var bootstrapStarting=false
 var bootstrapFailed=false;var bootstrapMailReady=false;var bootstrapReconnecting=false
 var bootstrapCell=0;var bootstrapDeadline:Date?;let bootstrapHash="fixture-hash";let bootstrapPassword="fixture"
 let bootstrapCacheKey="fixture-cache";var configSaved=false
 init(publicHealthy:Bool,cached:Bool=false){clock=Clock();vpn=VPN(clock);api=API(vpn,clock,publicHealthy:publicHealthy);configSaved=cached}
 func logConnection(_ text:String,level:Level = .info){clock.record("log:"+text)}
 enum Level {case info,error,success}
 func loadServerConfigCache(account:String){}
 func cachedServerConfig(_ slot:String,maxAge:TimeInterval=86_400)->VpnConfig?{configSaved ? VpnConfig():nil}
 func prefetchServerConfigs(account:String,slots:[String],tunnelActive:Bool) async {clock.record("preview:tunnel",3)}
 func requestMainConfig(_ slot:String,tunnelOnly:Bool) async throws ->VpnConfig{clock.record("required-config:tunnel",0.1);configSaved=true;return VpnConfig()}
 func makeTunnel(_ config:VpnConfig,bootstrapDuration:Int)->TunnelConfig{TunnelConfig(serverIP:"cell1")}
 func scheduleServerPrefetch(){clock.record("background-prefetch")}
 func run() async {await loadInitialData()}
 func confirmedAccount() async throws {try await loadAccount(loadedProfile:UserProfile())}
 func restoreForTest() async {await restoreSavedAccount()}
METHODS
}
@main struct StartupReplay {
 @MainActor static func main() async {
   let sessionKey="vpn-session-fixture-startup-account"
   UserDefaults.standard.removeObject(forKey:sessionKey)
   defer {UserDefaults.standard.removeObject(forKey:sessionKey)}
   let direct=VM(publicHealthy:true)
   await direct.run()
   precondition(direct.loggedIn && !direct.bootstrapActive)
   precondition(!direct.clock.events.contains(where:{$0.hasPrefix("connect:")}))
   print("PASS: healthy direct profile restores account without temporary VPN")
   var failures:[String]=[]
   let cached=VM(publicHealthy:false,cached:true)
   cached.bootstrapActive=true;cached.vpn.state = .connected
   try! await cached.confirmedAccount()
   if !cached.loggedIn || cached.clock.events.contains("preview:tunnel") || cached.clock.events.contains("required-config:tunnel") {
      failures.append("valid selected config cannot leave boot waiting on optional stale-cache preview; trace=\(cached.clock.events)")
   } else { print("PASS: validated profile and usable selected cache finish without optional preview") }
   if UserDefaults.standard.string(forKey:sessionKey) != "fixture-main-device" {
      failures.append("usable cached config lost session mapping when profile current_device_id is absent")
   }
   UserDefaults.standard.removeObject(forKey:sessionKey)
   let cold=VM(publicHealthy:false)
   cold.bootstrapActive=true;cold.vpn.state = .connected
   try! await cold.confirmedAccount()
   if !cold.loggedIn || !cold.configSaved || cold.clock.events.contains("preview:tunnel") {
      failures.append("cold start makes duplicate preview before mandatory main config; trace=\(cold.clock.events)")
   }
   if UserDefaults.standard.string(forKey:sessionKey) != "fixture-main-device" {
      failures.append("cold selected config did not preserve session mapping")
   }
   if let save=cold.clock.events.firstIndex(of:"required-config:tunnel"),let stop=cold.clock.events.lastIndex(of:"stop"),save<stop {
      print("PASS: cold selected config is saved before temporary VPN stops")
   } else {failures.append("temporary VPN stopped before cold selected config persisted")}
   let gateway=VM(publicHealthy:false)
   gateway.bootstrapActive=true;gateway.vpn.state = .connected;gateway.api.gatewayFailure=true
   await gateway.restoreForTest()
   if gateway.clock.events.contains("profile:public-failover") {
      failures.append("active bootstrap profile failure escapes into blocked public failover; virtual seconds=\(gateway.clock.elapsed)")
   } else { print("PASS: profile recovery after bootstrap stays on the temporary tunnel") }
   let revoked=VM(publicHealthy:false)
   revoked.bootstrapActive=true;revoked.vpn.state = .connected;revoked.api.revokeProfile=true
   await revoked.restoreForTest()
   precondition(!revoked.loggedIn && !revoked.api.isLoggedIn && !revoked.configSaved)
   print("PASS: revoked authentication does not restore an account or config")
   let cancelled=VM(publicHealthy:false)
   let task=Task {await cancelled.run()};task.cancel();await task.value
   precondition(!cancelled.loggedIn && !cancelled.configSaved && !cancelled.bootstrapAttempted)
   print("PASS: cancelled launch does not start bootstrap or mutate saved account")
   let blocked=VM(publicHealthy:false)
   await blocked.run()
   guard blocked.loggedIn,blocked.configSaved,
         blocked.clock.events.contains("connect:cell2"),
         !blocked.clock.events.contains("bootstrap:https-fallback") else {
      failures.append("boot waits on blocked public HTTPS instead of trying working temporary cell2; virtual seconds=\(blocked.clock.elapsed), trace=\(blocked.clock.events)")
      for failure in failures {print("FAIL: "+failure)}
      exit(1)
   }
   guard let save=blocked.clock.events.firstIndex(of:"required-config:tunnel"),
         let stop=blocked.clock.events.lastIndex(of:"stop"),save<stop else {
      print("FAIL: temporary VPN stopped before account/config preparation")
      exit(1)
   }
   print("PASS: working reserve temporary cell restores profile and config before stopping the tunnel; virtual seconds=\(blocked.clock.elapsed)")
   if !failures.isEmpty {for failure in failures {print("FAIL: "+failure)};exit(1)}
 }
}
'''.replace('METHODS', methods).replace('GET_PROFILE', get_profile)

if '--emit' in sys.argv:
    path=ios.parent / '.playwright-mcp/startup-ios-replay.swift'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fixture,encoding='utf-8')
    print(path)
else:
    with tempfile.TemporaryDirectory(prefix='silent-startup-') as directory:
        path=Path(directory);swift=path/'Startup.swift';binary=path/'startup'
        swift.write_text(fixture,encoding='utf-8')
        subprocess.run([shutil.which('swiftc') or 'swiftc','-parse-as-library',str(swift),'-o',str(binary)],check=True,timeout=60)
        subprocess.run([str(binary)],check=True,timeout=10)
