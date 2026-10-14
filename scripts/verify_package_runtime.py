#!/usr/bin/env python3
"""Feed all real architecture archives to the shipped Go OTA validator via a test overlay."""
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
EXTRA=r'''
func TestActualRouterArchives(t *testing.T) {
    dist:=os.Getenv("SVK_VERIFY_DIST")
    if dist=="" { t.Fatal("Missing architecture archive directory") }
    raw,err:=os.ReadFile(filepath.Join(dist,"release-entry.json"));if err!=nil{t.Fatal(err)}
    var feed struct{ Keenetic struct{ Arches map[string]updateOffer `json:"arches"` } `json:"keenetic"` }
    if err=json.Unmarshal(raw,&feed);err!=nil{t.Fatal(err)}
    if len(feed.Keenetic.Arches)!=7{t.Fatal("Not all seven architectures were built")}
    for slot,offer:=range feed.Keenetic.Arches {
        t.Run(slot,func(t *testing.T){
            path:=filepath.Join(dist,"silent-vpn-keenetic-"+offer.Version+"-"+slot+".tar.gz")
            if err:=scanPackage(path,offer,"");err!=nil{t.Fatal(err)}
        })
    }
}
'''

def main():
    folder=ROOT/'build/runtime-verification';folder.mkdir(parents=True,exist_ok=True)
    original=ROOT/'agent/agent_test.go'
    overlay_source=folder/'agent_test.go'
    overlay_source.write_text(original.read_text(encoding='utf-8-sig')+EXTRA,encoding='utf-8',newline='\n')
    overlay=folder/'overlay.json'
    overlay.write_text(json.dumps({'Replace':{str(original):str(overlay_source)}}),encoding='utf-8')
    env=dict(os.environ,SVK_VERIFY_DIST=str(ROOT/'dist'),GOCACHE=str(ROOT/'build/go-cache'))
    subprocess.run(['go','test','-overlay',str(overlay),'-run','^TestActualRouterArchives$','-v','.'],cwd=ROOT/'agent',env=env,check=True)

if __name__=='__main__':main()
