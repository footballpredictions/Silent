"""Replay the real saved-account/bootstrap/load-account call chain on macOS.

OS VPN setup and network responses are fixtures. Production orchestration is
extracted unchanged; a virtual clock exposes serial network waits immediately.
"""
from pathlib import Path
import re
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
    'sceneDidBecomeActive',
    'loadInitialData', 'restoreSavedAccount', 'startBootstrap', 'connectBootstrap',
    'loadAccount', 'stopBootstrap', 'rememberLoginSession', 'elapsedConnectionTime',
    'loadServerConfigCache', 'cachedServerConfig', 'saveServerConfig', 'persistServerConfigCache',
    'storeSelectedServer',
])
if 'func rememberConfigSession(' in source:
    methods += '\n' + method('rememberConfigSession')
get_profile = method('getProfile', api_source)
preview_config = method('previewVpnConfig', api_source)
session_start = source.index('    var sessionDeviceId: String? {')
session_end = source.index('\n    func sessionOnline(', session_start)
session_property = source[session_start:session_end]
bootstrap_property = re.search(r'    private var bootstrapCell\s*=.*?(?=\n    (?:@|private var|private let|var|let|func))', source, re.S).group()
cache_source = (ios / 'Silent/Services/ServerConfigCache.swift').read_text(encoding='utf-8').replace('import Foundation', '', 1)

fixture = r'''import Foundation
enum APIError:Error { case network, unauthorized, http(Int,String), server(String), bootstrapUnavailable(String) }
enum Stage { case configuration, session, tunnel, data, complete }
enum State { case connected, disconnected }
struct Subscription:Codable { var is_active=true }
struct DeviceInfo:Codable {var id="fixture-main-device"}
struct UserProfile:Codable { var id="fixture-startup-account";var is_admin=true;var subscription=Subscription();var current_device_id:String?;var devices=[DeviceInfo()] }
struct VpnConfig:Codable {var device_id="fixture-main-device";var selected_server:String?="server1";var wg_private_key="fixture-private";var server_ip="127.0.0.1";var server_port=56000;var wdtt_password="fixture";var vk_hashes=["fixture-hash"]}
struct TunnelConfig:Codable { var deviceId="boot:fixture";var serverIP="";var hashes=["fixture-hash"];var bootstrapDuration:Int?=300;var registrationRouting:Bool?;var paymentRouting:Bool?;var dns:[String]=[] }
struct BootstrapCache:Codable {var savedAt:Date;var config:TunnelConfig}
enum AppIdentity {static func readTunnelConfig()->TunnelConfig?{TunnelConfig()}}
SERVER_CACHE
enum LocalStore {static var preferredServer="server1"}
struct ServerSlot {let key:String}
enum PublicApiFailover {
 static let tunnelAPI="http://10.66.66.1:8000";static let paymentPublicBases=["https://fixture.invalid"]
 static func serverQuery(_ path:String,fingerprint:String,preferred:String?=nil)->String{preferred.map{path+"?preferred_server="+$0} ?? path}
}
enum RegistrationTunnelRoute {static let internetDNS=["1.1.1.1"]}
enum KeychainHelper {static var values:[String:String]=[:];static func get(_ key:String)->String?{values[key]};static func set(_ value:String,key:String){values[key]=value} }
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
 var configRequests:[String]{events.filter{$0.hasPrefix("config-preview:") || $0.hasPrefix("config-main:")}}
}
@MainActor final class VPN {
 let clock:Clock; var state=State.disconnected;let sceneDiscardCount=0;var cachePersisted:(()->Bool)?
 init(_ clock:Clock){self.clock=clock}
 func prepareForegroundScene() async {}
 func refresh() async {}
 func isApiTunnelActive() async ->Bool{state == .connected}
 func connect(_ config:TunnelConfig,timeout:TimeInterval?=nil) async throws {
   if config.serverIP=="cell1" {clock.record("connect:cell1",timeout ?? 50);throw APIError.network}
   clock.record("connect:cell2",1.2);state = .connected
 }
 func disconnect() async {if cachePersisted?() == true {clock.record("cache-persisted-before-stop")};clock.record("stop");state = .disconnected}
}
@MainActor final class API {
 let vpn:VPN;let clock:Clock;let publicHealthy:Bool
 var isLoggedIn=true;let deviceFingerprint="fixture";var revokeProfile=false;var gatewayFailure=false;var previewError:Error?
 var previewRefreshFlags:[Bool]=[];var previewSameBaseFlags:[Bool]=[];var previewRequestedPaths:[String]=[]
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
 func requestOnce(_ path:String,method:String,body:Any?,auth:Bool,base:String,
                  allowRefresh:Bool,verifyTLS:Bool,timeout:TimeInterval,refreshOnSameBase:Bool=false) async throws ->Data {
   precondition(path.hasPrefix("api/vpn/config-preview"));previewRequestedPaths.append(path)
   clock.record(base == PublicApiFailover.tunnelAPI ? "config-preview:tunnel":"config-preview:public",0.1)
   previewRefreshFlags.append(allowRefresh);previewSameBaseFlags.append(refreshOnSameBase)
   if let previewError {throw previewError}
   return try JSONEncoder().encode(VpnConfig())
 }
GET_PROFILE
PREVIEW_CONFIG
}
@MainActor final class VM {
 let api:API;let vpn:VPN;let clock:Clock
 var loggedIn=false;var authLoading=false;var launchStage:Stage? = .configuration
 var didStartInitialData=false;var paymentTunnelActive=false;let paymentRestoreKey="fixture-payment"
 var restartExpiredLoginOnOpen=false;var bootstrapExpired=false;var forgotSent=false
 var authError:String?;var authLoadingTitle="";var profile:UserProfile?;var selectedServer="server1"
 var servers=(1...5).map{ServerSlot(key:"server\($0)")}
 var bootstrapActive=false;var bootstrapAttempted=false;var bootstrapStarting=false
 var bootstrapFailed=false;var bootstrapMailReady=false;var bootstrapReconnecting=false
BOOTSTRAP_PROPERTY
 var bootstrapDeadline:Date?;let bootstrapHash="fixture-hash";let bootstrapPassword="fixture"
 let bootstrapCacheKey="fixture-cache";var requiredConfigError:Error?
 private var serverConfigCache:ServerConfigCache?;private let serverConfigCacheKey="ios-server-configs-v1"
 var configSaved:Bool {
   guard let encoded=KeychainHelper.get(serverConfigCacheKey),let bytes=Data(base64Encoded:encoded),
         let stored=try? JSONDecoder().decode(ServerConfigCache.self,from:bytes) else {return false}
   return stored.account=="fixture-startup-account" && stored.fingerprint==api.deviceFingerprint && stored.slots["server1"] != nil
 }
 init(publicHealthy:Bool,cached:Bool=false){
   clock=Clock();vpn=VPN(clock);api=API(vpn,clock,publicHealthy:publicHealthy)
   KeychainHelper.values=[:]
   if cached {
      var cache=ServerConfigCache(account:"fixture-startup-account",fingerprint:api.deviceFingerprint)
      cache.save(VpnConfig(),for:"server1",now:Date().addingTimeInterval(-3600))
      let bytes=try! JSONEncoder().encode(cache)
      KeychainHelper.set(bytes.base64EncodedString(),key:serverConfigCacheKey)
   }
   vpn.cachePersisted={ [weak self] in self?.configSaved == true }
 }
 func logConnection(_ text:String,level:Level = .info,key:String?=nil){clock.record("log:"+text)}
 func beginVPNLogSession(){}
 func dismissRegistrationConfirmation(){authError=nil}
 enum Level {case info,error,success}
 func prefetchServerConfigs(account:String,slots:[String],tunnelActive:Bool) async {clock.record("preview:tunnel",3)}
 func requestMainConfig(_ slot:String,tunnelOnly:Bool) async throws ->VpnConfig{
   clock.record(tunnelOnly ? "config-main:tunnel":"config-main:public",0.1)
   if let requiredConfigError {throw requiredConfigError}
   var config=VpnConfig();config.selected_server=slot
   saveServerConfig(config,slot:slot);return config
 }
 func makeTunnel(_ config:VpnConfig,bootstrapDuration:Int)->TunnelConfig{TunnelConfig(serverIP:"cell1")}
 func scheduleServerPrefetch(){clock.record("background-prefetch")}
 func finishPaymentTunnel(account:String?) async {preconditionFailure("unexpected payment cleanup")}
 func loadAppearanceAndServers() async {clock.record("appearance")}
 func run() async {await loadInitialData()}
 func confirmedAccount() async throws {try await loadAccount(loadedProfile:UserProfile())}
 func restoreForTest() async {await restoreSavedAccount()}
SESSION_PROPERTY
METHODS
}
@main struct StartupReplay {
 @MainActor static func main() async {
   let sessionKey="vpn-session-fixture-startup-account"
   let serverKey="vpn-server-fixture-startup-account"
   let bootstrapKey="ios-bootstrap-cell-host"
   let storedBootstrapHost=UserDefaults.standard.object(forKey:bootstrapKey)
   let storedServer=UserDefaults.standard.object(forKey:serverKey)
   UserDefaults.standard.removeObject(forKey:sessionKey)
   UserDefaults.standard.removeObject(forKey:serverKey)
   UserDefaults.standard.removeObject(forKey:bootstrapKey)
   defer {UserDefaults.standard.removeObject(forKey:sessionKey);UserDefaults.standard.set(storedBootstrapHost,forKey:bootstrapKey);UserDefaults.standard.set(storedServer,forKey:serverKey)}
   let direct=VM(publicHealthy:true)
   await direct.run()
   precondition(direct.loggedIn && !direct.bootstrapActive)
   precondition(!direct.clock.events.contains(where:{$0.hasPrefix("connect:")}))
   print("PASS: healthy direct profile restores account without temporary VPN")
   var failures:[String]=[]
   let background=VM(publicHealthy:false)
   _ = try! await background.api.previewVpnConfig(server:"server1",tunnelActive:true)
   if background.api.previewRefreshFlags != [false] || background.api.previewSameBaseFlags != [false] {
      failures.append("background preview unexpectedly refreshes authentication")
   } else {print("PASS: background preview retains its read-only no-refresh default")}
   UserDefaults.standard.set("fixture-main-device",forKey:sessionKey)
   let cached=VM(publicHealthy:false,cached:true)
   cached.bootstrapActive=true;cached.vpn.state = .connected
   try! await cached.confirmedAccount()
   if !cached.loggedIn || cached.clock.events.contains("preview:tunnel") || !cached.clock.configRequests.isEmpty {
      failures.append("valid selected config cannot leave boot waiting on optional stale-cache preview; trace=\(cached.clock.events)")
   } else { print("PASS: validated profile and usable selected cache finish without optional preview") }
   if UserDefaults.standard.string(forKey:sessionKey) != "fixture-main-device" {
      failures.append("usable cached config lost session mapping when profile current_device_id is absent")
   }
   UserDefaults.standard.removeObject(forKey:sessionKey)
   let unboundCache=VM(publicHealthy:false,cached:true)
   unboundCache.bootstrapActive=true;unboundCache.vpn.state = .connected
   try! await unboundCache.confirmedAccount()
   if unboundCache.clock.configRequests != ["config-preview:tunnel"] ||
      UserDefaults.standard.string(forKey:sessionKey) != "fixture-main-device" {
      failures.append("cached payload without device identity was treated as a usable cache hit")
   } else {print("PASS: cached payload without identity remains a cache miss and requests its selected config")}
   UserDefaults.standard.removeObject(forKey:sessionKey)
   let cold=VM(publicHealthy:false)
   cold.bootstrapActive=true;cold.vpn.state = .connected
   try! await cold.confirmedAccount()
   if !cold.loggedIn || !cold.configSaved || cold.clock.events.contains("preview:tunnel") ||
      cold.clock.configRequests != ["config-preview:tunnel"] || cold.api.previewRefreshFlags != [true] || cold.api.previewSameBaseFlags != [true] {
      failures.append("cold start must receive one preview config on the temporary tunnel with same-base token refresh; trace=\(cold.clock.events)")
   }
   if UserDefaults.standard.string(forKey:sessionKey) != "fixture-main-device" {
      failures.append("cold selected config did not preserve session mapping")
   }
   if let save=cold.clock.events.firstIndex(of:"cache-persisted-before-stop"),let stop=cold.clock.events.lastIndex(of:"stop"),save<stop {
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
   let configCancelled=VM(publicHealthy:false)
   configCancelled.bootstrapActive=true;configCancelled.vpn.state = .connected
   configCancelled.api.previewError=CancellationError()
   await configCancelled.restoreForTest()
   if configCancelled.loggedIn || configCancelled.configSaved || !configCancelled.api.isLoggedIn || configCancelled.clock.events.contains("background-prefetch") {
      failures.append("cancellation during mandatory config was swallowed and completed login")
   } else {print("PASS: config cancellation cannot complete login or revoke saved authentication")}
   let configRefusals:[(String,APIError)]=[("unauthorized",.unauthorized),("401",.http(401,"fixture revoked"))]
   for (label,error) in configRefusals {
      let refused=VM(publicHealthy:false)
      refused.bootstrapActive=true;refused.vpn.state = .connected;refused.api.previewError=error
      await refused.restoreForTest()
      if refused.loggedIn || refused.api.isLoggedIn || refused.configSaved || refused.clock.events.contains("background-prefetch") {
         failures.append("mandatory config \(label) was swallowed and restored an unauthorized account")
      } else {print("PASS: mandatory config \(label) revokes login without completing boot as authenticated")}
   }
   let configOffline=VM(publicHealthy:false)
   configOffline.bootstrapActive=true;configOffline.vpn.state = .connected
   configOffline.api.previewError=APIError.network
   await configOffline.restoreForTest()
   if !configOffline.loggedIn || !configOffline.api.isLoggedIn || configOffline.configSaved || configOffline.bootstrapAttempted ||
      configOffline.clock.events.contains("profile:public-failover") ||
      configOffline.clock.events.contains("config-preview:public") || configOffline.clock.events.contains("config-main:public") ||
      configOffline.clock.events.contains("bootstrap:https-fallback") ||
      configOffline.clock.configRequests != ["config-preview:tunnel"] ||
      configOffline.clock.events.filter({$0=="stop"}).count != 1 ||
      !configOffline.clock.events.contains(where:{$0.hasPrefix("log:Не удалось сохранить стартовый конфиг")}) {
      failures.append("config network failure retried public/bootstrap routes, blocked confirmed login, or was not logged; trace=\(configOffline.clock.events)")
   } else {print("PASS: config network failure is logged once; confirmed login completes without bootstrap/public retry")}
   UserDefaults.standard.removeObject(forKey:sessionKey)
   let legacy=VM(publicHealthy:false)
   legacy.bootstrapActive=true;legacy.vpn.state = .connected;legacy.api.previewError=APIError.http(404,"fixture old server")
   await legacy.restoreForTest()
   if !legacy.loggedIn || !legacy.configSaved || legacy.clock.configRequests != ["config-preview:tunnel","config-main:tunnel"] ||
      !legacy.clock.events.contains("cache-persisted-before-stop") || UserDefaults.standard.string(forKey:sessionKey) != "fixture-main-device" {
      failures.append("missing preview endpoint did not use the compatible main-config fallback before stopping temporary VPN; trace=\(legacy.clock.events)")
   } else {print("PASS: HTTP404 preview uses main-config compatibility fallback and persists config before stop")}
   UserDefaults.standard.set("server2",forKey:serverKey)
   let serverFallback=VM(publicHealthy:false)
   serverFallback.bootstrapActive=true;serverFallback.vpn.state = .connected
   await serverFallback.restoreForTest()
   if !serverFallback.loggedIn || !serverFallback.configSaved || serverFallback.selectedServer != "server1" ||
      UserDefaults.standard.string(forKey:serverKey) != "server1" || LocalStore.preferredServer != "server1" ||
      serverFallback.clock.configRequests != ["config-preview:tunnel"] ||
      serverFallback.api.previewRequestedPaths != ["api/vpn/config-preview?preferred_server=server2"] ||
      !serverFallback.clock.events.contains("cache-persisted-before-stop") {
      failures.append("legitimate server2 to server1 fallback lost its confirmed config/selection or issued extra HTTP; trace=\(serverFallback.clock.events)")
   } else {print("PASS: legitimate server fallback persists confirmed server1 config and updates selection after one server2 preview request")}
   let blocked=VM(publicHealthy:false)
   await blocked.run()
   guard blocked.loggedIn,blocked.configSaved,
         blocked.clock.events.contains("connect:cell2"),
         !blocked.clock.events.contains("bootstrap:https-fallback") else {
      failures.append("boot waits on blocked public HTTPS instead of trying working temporary cell2; virtual seconds=\(blocked.clock.elapsed), trace=\(blocked.clock.events)")
      for failure in failures {print("FAIL: "+failure)}
      exit(1)
   }
   guard let save=blocked.clock.events.firstIndex(of:"cache-persisted-before-stop"),
         let stop=blocked.clock.events.lastIndex(of:"stop"),save<stop else {
      print("FAIL: temporary VPN stopped before account/config preparation")
      exit(1)
   }
   print("PASS: working reserve temporary cell restores profile and config before stopping the tunnel; virtual seconds=\(blocked.clock.elapsed)")
   let nextLaunch=VM(publicHealthy:false)
   await nextLaunch.run()
   if !nextLaunch.loggedIn || !nextLaunch.clock.events.contains("connect:cell2") ||
      nextLaunch.clock.events.contains("connect:cell1") || nextLaunch.clock.events.contains("bootstrap:https-fallback") {
      failures.append("next launch retries the dead first cell instead of remembering successful cell2; trace=\(nextLaunch.clock.events)")
   } else {print("PASS: next launch starts with remembered working cell2 without retrying cell1 or public HTTPS")}
   let reopened=VM(publicHealthy:false)
   reopened.api.isLoggedIn=false
   reopened.didStartInitialData=true
   reopened.bootstrapExpired=true
   reopened.bootstrapAttempted=true
   await reopened.sceneDidBecomeActive()
   precondition(reopened.bootstrapExpired && reopened.clock.events.isEmpty)
   reopened.restartExpiredLoginOnOpen=true
   await reopened.sceneDidBecomeActive()
   precondition(!reopened.bootstrapExpired && reopened.bootstrapDeadline != nil)
   print("PASS: a new scene restarts the expired login, foregrounding preserves the expiry panel")
   if !failures.isEmpty {for failure in failures {print("FAIL: "+failure)};exit(1)}
 }
}
'''.replace('METHODS', methods).replace('GET_PROFILE', get_profile).replace('PREVIEW_CONFIG',preview_config).replace('SESSION_PROPERTY',session_property).replace('BOOTSTRAP_PROPERTY',bootstrap_property).replace('SERVER_CACHE',cache_source)

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
