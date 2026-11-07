"""Observe the real SystemUI tile across owner-process death; private emulator only.

Install assembleDebug first (contains the DUMP-protected NoDisplay fixture).
Run: python scripts/test_qs_tile_process_death.py --serial emulator-5580
Android 9 uses Windows System.Drawing to read actual tile tint; newer images use dumpsys.
No account or transport is opened; the tile list is restored after the test."""
import argparse,json,re,shlex,subprocess,sys,time
import xml.etree.ElementTree as ET
from pathlib import Path
output=Path(__file__).resolve().parents[1]/'app/build/qs-tile-process-death'
output.mkdir(parents=True,exist_ok=True)
adb=Path.home()/'AppData/Local/Android/Sdk/platform-tools/adb.exe'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--serial',default='emulator-5580')
parser.add_argument('--label',choices=('before','after'),default='after')
args=parser.parse_args()
serial=args.serial;phase=args.label
assert serial.startswith('emulator-'),'Use a private emulator, never a physical client device'
def command(*args,timeout=20):
 return subprocess.check_output([str(adb),'-s',serial,*args],timeout=timeout).decode('utf-8',errors='replace').strip()
def shell(*args,timeout=20):return command('shell',shlex.join(args),timeout=timeout)
assert shell('getprop','ro.kernel.qemu')=='1','Refusing to alter a physical Android device'
package='com.silent.vpn.debug'
assert 'package:'+package in shell('pm','list','packages',package).splitlines()
assert not re.search(r'ServiceRecord\{[^\n]*SilentVpnService\b',shell('dumpsys','activity','services',package)),'Refusing to interrupt a running VPN'
component=package+'/com.silent.vpn.service.SilentVpnTileService'
original=shell('settings','get','secure','sysui_qs_tiles')
sdk=int(shell('getprop','ro.build.version.sdk'))
def visual_state():
 # Android 9 does not dump QSTile state. Observe the actual SystemUI tint/label.
 shell('cmd','statusbar','expand-settings')
 time.sleep(.3)
 shell('uiautomator','dump','/sdcard/tile-qa-window.xml')
 tree=ET.fromstring(shell('cat','/sdcard/tile-qa-window.xml'))
 tile=next((n for n in tree.iter('node') if n.get('content-desc','').startswith('Silent VPN')
            and n.get('class') in ('android.widget.LinearLayout','android.widget.FrameLayout')),None)
 if tile is None:return None
 icon=next(n for n in tile.iter('node') if n.get('class')=='android.widget.FrameLayout')
 x1,y1,x2,y2=map(int,re.findall(r'\d+',icon.get('bounds')))
 x=int((x1+x2)/2+(x2-x1)*.22);y=(y1+y2)//2
 path=output/f'tile-observation-{phase}.png'
 path.write_bytes(subprocess.check_output([str(adb),'-s',serial,'exec-out','screencap','-p'],timeout=15))
 code=f'''Add-Type -AssemblyName System.Drawing
$b=[System.Drawing.Bitmap]::FromFile('{path.as_posix()}')
$c=$b.GetPixel({x},{y})
"$($c.R),$($c.G),$($c.B)"
$b.Dispose()
'''
 proc=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',code],capture_output=True,text=True,check=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
 r,g,b=map(float,proc.stdout.strip().split(','))
 value=2 if g-r>40 and g-b>5 else 1 if tile.get('clickable')=='true' else 0
 return value
def state():
 if sdk<=28:return visual_state()
 dump=shell('dumpsys','activity','service','com.android.systemui/.SystemUIService')
 for line in dump.splitlines():
  if 'CustomTile:' in line and ('SilentVpnTileService' in line or 'label=Silent VPN' in line):
   match=re.search(r'\bstate=(\d+)',line)
   if match:return int(match[1])
 return None
def wait_state(expected,seconds):
 deadline=time.monotonic()+seconds;seen=[]
 while time.monotonic()<deadline:
  value=state();seen.append(value)
  if value==expected:return value,seen
  time.sleep(.3)
 return value,seen
record={'phase':phase,'serial':serial,'sdk':sdk,'actual_system_ui':True,'real_vpn_started':False}
try:
 shell('settings','put','secure','sysui_qs_tiles',f'custom({component}),internet,bt')
 shell('cmd','statusbar','expand-settings')
 time.sleep(1)
 shell('cmd','statusbar','collapse')
 shell('am','start','-n',package+'/com.silent.vpn.service.TileOwnerFixtureActivity','--ez','enabled','true')
 shell('cmd','statusbar','expand-settings')
 active,seen=wait_state(2,22)
 assert active==2,('Fixture failed to activate actual tile',seen)
 record['before_death']=active
 shell('cmd','statusbar','collapse')
 # SystemUI keeps a recently used tile bound for ~30s. Killing it before unbind
 # can trigger an automatic reconnect and hide the bug that occurs later.
 deadline=time.monotonic()+45
 while True:
  services=shell('dumpsys','activity','services',package)
  if not re.search(r'ServiceRecord\{[^\n]*SilentVpnTileService',services):break
  assert time.monotonic()<deadline,'SystemUI did not release its tile binding'
  time.sleep(1)
 record['tile_service_unbound_before_death']=True
 pid=shell('pidof',package)
 assert re.fullmatch(r'\d+',pid),pid
 record['killed_owner_pid']=int(pid)
 shell('run-as',package,'kill','-9',pid)
 shell('cmd','statusbar','expand-settings')
 final,history=wait_state(1,12)
 record.update(after_death=final,observed_after_death=history,inactive_after_reopening=final==1)
 screenshot=subprocess.check_output([str(adb),'-s',serial,'exec-out','screencap','-p'],timeout=15)
 (output/f'tile-process-death-{phase}.png').write_bytes(screenshot)
 (output/f'tile-process-death-{phase}.json').write_text(json.dumps(record,indent=2)+'\n')
 print(json.dumps(record),flush=True)
 assert final==1,'VPN process is gone but the real Quick Settings tile remains active'
finally:
 shell('cmd','statusbar','collapse')
 if original=='null':shell('settings','delete','secure','sysui_qs_tiles')
 else:shell('settings','put','secure','sysui_qs_tiles',original)
