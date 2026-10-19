"""Run the actual compiled LAN collector against the API 29 framework shape.

SDK data/api-versions.xml and Android docs identify DHCP getter as API 30.
The JVM fixture omits it below 30, reproducing method linkage, not mocking
the production collector or merely asserting on source strings.
"""
from pathlib import Path
import subprocess,os,sys,tempfile,shutil

ROOT=Path(__file__).resolve().parents[1]
_temporary=tempfile.TemporaryDirectory(prefix="silent-lan-api-")
WORK=Path(_temporary.name)
JAVA=Path(os.environ['JAVA_HOME'])/'bin' if os.environ.get('JAVA_HOME') else Path(shutil.which('javac') or '').parent
if os.name=='nt':
    javac=JAVA/'javac.exe';java=JAVA/'java.exe'
else:
    javac=JAVA/'javac';java=JAVA/'java'
PRODUCTION=ROOT/'app/build/tmp/kotlin-classes/debug'
cache=Path(os.environ.get('GRADLE_USER_HOME',Path.home()/'.gradle'))/'caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-stdlib'
stdlib=next(cache.glob('2.*/*/kotlin-stdlib-*.jar'))
sources={
'android/os/Build.java':'''package android.os; public class Build { public static class VERSION { public static int SDK_INT=29; } }''',
'android/content/Context.java':'''package android.content; public class Context { private final android.net.ConnectivityManager cm; public Context(int transport){cm=new android.net.ConnectivityManager(transport);} public <T>T getSystemService(Class<T> cls){return cls.cast(cm);} }''',
'android/net/Network.java':'''package android.net; public class Network {}''',
'android/net/NetworkCapabilities.java':'''package android.net; public class NetworkCapabilities {private final int transport; public NetworkCapabilities(int t){transport=t;} public boolean hasTransport(int t){return t==transport;} }''',
'android/net/ConnectivityManager.java':'''package android.net; public class ConnectivityManager {private final int transport; public ConnectivityManager(int t){transport=t;} public Network[] getAllNetworks(){return new Network[]{new Network()};} public NetworkCapabilities getNetworkCapabilities(Network n){return new NetworkCapabilities(transport);} public LinkProperties getLinkProperties(Network n){return new LinkProperties();} }''',
'android/net/LinkAddress.java':'''package android.net; public class LinkAddress {public java.net.InetAddress getAddress(){try{return java.net.InetAddress.getByName("192.168.1.14");}catch(Exception e){throw new RuntimeException(e);}} public int getPrefixLength(){return 24;} }''',
'android/net/RouteInfo.java':'''package android.net; public class RouteInfo {public java.net.InetAddress getGateway(){try{return java.net.InetAddress.getByName("192.168.1.1");}catch(Exception e){throw new RuntimeException(e);}} }''',
'android/net/LinkProperties.java':'''package android.net; public class LinkProperties {public java.util.List<LinkAddress> getLinkAddresses(){return java.util.List.of(new LinkAddress());} public java.util.List<RouteInfo> getRoutes(){return java.util.List.of(new RouteInfo());} DHCP }''',
'LanLinkageHarness.java':'''import android.os.Build; import android.content.Context; import com.silent.vpn.vpn.LanBypassRoutes; public class LanLinkageHarness {public static void main(String[] args){Build.VERSION.SDK_INT=Integer.parseInt(args[0]); int transport=Integer.parseInt(args[1]); java.util.List<String> result=LanBypassRoutes.INSTANCE.underlayLanCidrs(new Context(transport)); if(transport!=0 && !result.contains("192.168.1.14/24")) throw new AssertionError("Wi-Fi prefix lost"); System.out.println("PASS API="+Build.VERSION.SDK_INT+" transport="+transport+" LAN="+result);}}''',
}
failed=False
for api,transport in ((29,0),(29,1),(29,3),(28,1),(30,1)):
    folder=WORK/f'api{api}-{transport}'
    paths=[]
    dhcp='public java.net.Inet4Address getDhcpServerAddress(){try{return (java.net.Inet4Address)java.net.InetAddress.getByName("192.168.1.1");}catch(Exception e){throw new RuntimeException(e);}}' if api>=30 else ''
    for rel,source in sources.items():
        p=folder/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(source.replace('DHCP',dhcp));paths.append(str(p))
    subprocess.run([str(javac),'-cp',os.pathsep.join((str(PRODUCTION),str(stdlib))),'-d',str(folder),*paths],check=True,capture_output=True)
    result=subprocess.run([str(java),'-cp',os.pathsep.join((str(folder),str(PRODUCTION),str(stdlib))),'LanLinkageHarness',str(api),str(transport)],capture_output=True,text=True)
    if result.returncode:
        failed=True;print('FAIL API='+str(api)+' transport='+str(transport));print('\n'.join(result.stderr.splitlines()[:5]))
    else: print(result.stdout.strip())
_temporary.cleanup()
sys.exit(1 if failed else 0)
