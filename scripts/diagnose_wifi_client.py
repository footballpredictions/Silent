"""Read-only ADB/HTTP probes for a Wi-Fi client using the router's VPN.

Does not reconnect Wi-Fi, change settings, clear logs, restart VPN or install apps.
Requires an already authorized physical Android device; no router credentials.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb',default=shutil.which('adb') or str(Path(os.environ.get('LOCALAPPDATA',''))/'Android/Sdk/platform-tools/adb.exe'))
    parser.add_argument('--serial')
    parser.add_argument('--router',default='192.168.1.1')
    parser.add_argument('--samples',type=int,default=1)
    parser.add_argument('--interval',type=int,default=20)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--snapshot',action='store_true',help='Capture full read-only network context even while healthy')
    args=parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    if args.samples<1 or args.samples>180 or args.interval<5:parser.error('samples 1..180, interval >=5 seconds')
    devices=subprocess.run([args.adb,'devices'],capture_output=True,text=True,timeout=10,check=True)
    available=[line.split()[0] for line in devices.stdout.splitlines()[1:] if len(line.split())==2 and line.split()[1]=='device' and not line.startswith('emulator-')]
    if not args.serial:
        if len(available)!=1:parser.error('connect exactly one authorized physical phone or specify --serial')
        args.serial=available[0]
    def shell(command):
        try:
            r=subprocess.run([args.adb,'-s',args.serial,'shell',command],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=18)
            return {'exit':r.returncode,'out':r.stdout.strip(),'error':r.stderr.strip()[:200]}
        except subprocess.TimeoutExpired:return {'exit':124,'out':'','error':'ADB timeout'}
    def phone_http(url):
        cmd="curl -4 --interface wlan0 --connect-timeout 4 --max-time 10 -sS -o /dev/null -w 'http=%{http_code} remote=%{remote_ip} seconds=%{time_total}' "+shlex.quote(url)
        result=shell(cmd)
        match=re.search(r'http=(\d+)',result['out'])
        result['reachable']=result['exit']==0 and match is not None and 100<=int(match[1])<=599
        return result
    def pc_vpn():
        try:
            with urllib.request.urlopen('https://www.youtube.com/generate_204',timeout=10) as response:return {'reachable':100<=response.status<=599,'http':response.status}
        except Exception as err:return {'reachable':False,'error':type(err).__name__}
    def router():
        try:
            req=urllib.request.Request('http://'+args.router+'/cgi-bin/silent-api/status',headers={'Host':args.router+'.silent.vpn'})
            with urllib.request.urlopen(req,timeout=5) as response:data=json.load(response)
            return {k:data.get(k) for k in ('version','connected','ru_direct')}
        except Exception as err:return {'error':type(err).__name__}
    def failure_context():
        context={name:shell(cmd) for name,cmd in {
            'router_ping':'ping -c 2 -W 2 '+shlex.quote(args.router),
            'tunnel_ping':'ping -c 2 -W 2 10.66.66.1',
            'dns_youtube':'ping -c 1 -W 2 www.youtube.com',
            'wifi_address':'ip -4 addr show wlan0',
            'gateway_neighbor':'ip neigh show '+shlex.quote(args.router),
            'private_dns_mode':'settings get global private_dns_mode',
        }.items()}
        raw=shell('dumpsys connectivity')['out']
        context['connectivity']=[line[:1800] for line in raw.splitlines() if 'Active default network' in line or 'Transports: WIFI' in line or 'Transports: VPN' in line][:5]
        # Keep network state, not identifying MAC/SSID strings or app traffic/history.
        def redact(value):
            if isinstance(value,dict):return {key:redact(item) for key,item in value.items()}
            if isinstance(value,list):return [redact(item) for item in value]
            if isinstance(value,str):
                value=re.sub(r'(?i)(?:[0-9a-f]{2}:){5}[0-9a-f]{2}','<MAC>',value)
                value=re.sub(r'SSID:.*?(?=,|\]|})','SSID:<REDACTED>',value)
            return value
        return redact(context)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    tasks={'phone_vpn_youtube':lambda:phone_http('https://www.youtube.com/generate_204'),
           'phone_vpn_example':lambda:phone_http('https://example.com/'),
           'phone_direct_ru':lambda:phone_http('https://ya.ru/'),
           'pc_vpn_control':pc_vpn,'router':router}
    failures=0
    for i in range(args.samples):
        with ThreadPoolExecutor(max_workers=len(tasks)) as pool:sample=dict(zip(tasks,pool.map(lambda f:f(),tasks.values())))
        sample['time_utc']=datetime.now(timezone.utc).isoformat()
        sample['vpn_site_failure']=not sample['phone_vpn_youtube']['reachable'] or not sample['phone_vpn_example']['reachable']
        sample['symptom_detected']=sample['vpn_site_failure'] and sample['phone_direct_ru']['reachable'] and sample['pc_vpn_control']['reachable'] and sample['router'].get('connected') is True
        if sample['vpn_site_failure'] or args.snapshot:
            sample['context']=failure_context()
            failures+=1
        with args.output.open('a',encoding='utf-8') as file:file.write(json.dumps(sample,ensure_ascii=False)+'\n')
        print(json.dumps({'sample':i+1,'phone_youtube':sample['phone_vpn_youtube']['reachable'],'phone_example':sample['phone_vpn_example']['reachable'],'phone_ru':sample['phone_direct_ru']['reachable'],'pc_youtube':sample['pc_vpn_control']['reachable'],'router_vpn':sample['router'].get('connected'),'symptom':sample['symptom_detected']}) ,flush=True)
        if sample['symptom_detected']:return 1
        if i+1<args.samples:time.sleep(args.interval)
    return 2 if failures else 0

if __name__=='__main__':raise SystemExit(main())
