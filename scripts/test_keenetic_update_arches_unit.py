"""Keenetic upload, seven-slot release and cross-platform preservation regressions."""
import asyncio
import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services import update_service as us, keenetic_package as pkg, github_release_service as gh


def make_package(path,arch,version="1.0.171",mutate=None):
    cls,endian,machine=pkg.ABI[arch];order="little" if endian==1 else "big"
    elf=bytearray(128);elf[:6]=b"\x7fELF"+bytes((cls,endian));elf[18:20]=machine.to_bytes(2,order)
    if cls==1:elf[28:32]=(64).to_bytes(4,order);elf[42:44]=(32).to_bytes(2,order);elf[44:46]=(1).to_bytes(2,order)
    else:elf[32:40]=(64).to_bytes(8,order);elf[54:56]=(56).to_bytes(2,order);elf[56:58]=(1).to_bytes(2,order)
    elf[64:68]=(1).to_bytes(4,order)
    meta=dict(schema_version=1,platform="keenetic",arch=arch,version=version,build_id="a"*64)
    files={"ARCH":(arch+"\n").encode(),"VERSION":(version+"\n").encode(),"PACKAGE.json":json.dumps(meta).encode(),
           "install.sh":b"#!/bin/sh\necho install\n","uninstall.sh":b"#!/bin/sh\n","README.md":b"readme","RESEARCH.md":b"sources","THIRD_PARTY_LICENSES.txt":b"license",
           "files/network.sh":b"#!/bin/sh\n","files/guard.sh":b"#!/bin/sh\n","files/100-silent-keenetic.sh":b"#!/bin/sh\n","files/S99silent-keenetic":b"#!/bin/sh\n",
           "files/ru-direct.domains":b"ru\n","files/ru-vpn.domains":b"example.com\n",f"bin/{arch}/silent-keenetic":bytes(elf),f"bin/{arch}/spass":bytes(elf)}
    if mutate:mutate(files)
    with tarfile.open(path,"w:gz") as tf:
        for name,data in files.items():
            member=tarfile.TarInfo(f"silent-vpn-keenetic-{version}/"+name);member.size=len(data);member.mode=0o755 if name.startswith("bin/") else 0o644
            tf.addfile(member,io.BytesIO(data))


class KeeneticTests(unittest.TestCase):
    def test_release_description_includes_keenetic_when_its_packages_exist(self):
        names = ["Silent.VPN.Setup.1.0.171.exe",
                 "silent-vpn-openwrt-1.0.171-aarch64.tar.gz",
                 "silent-vpn-keenetic-1.0.171-aarch64.tar.gz",
                 "silent-vpn-keenetic-1.0.171-mips.tar.gz"]
        body = gh._release_body_for_assets("1.0.171", names)
        self.assertIn("**Windows (ПК)**", body)
        self.assertIn("**OpenWrt**", body)
        self.assertEqual(body.count("**Keenetic**"), 1)
        self.assertNotIn("**Keenetic**", gh._release_body_for_assets("1.0.171", names[:2]))

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.oldbase=us._BASE;us._BASE=str(self.root/"updates")
    def tearDown(self):us._BASE=self.oldbase;self.temp.cleanup()
    def upload(self,arch,version="1.0.171",mutate=None):
        name=f"silent-vpn-keenetic-{version}-{arch}.tar.gz";path=self.root/name;make_package(path,arch,version,mutate);return us.publish_file("keenetic",name,str(path),arch=arch)
    def complete(self):
        for arch in pkg.ARCHES:self.upload(arch)
        return us.get_latest("keenetic")
    def test_all_seven_slots_and_download_contract(self):
        latest=self.complete();self.assertEqual(len(us.keenetic_binaries(latest,require_complete=True)),7)
        for arch in pkg.ARCHES:
            update=us.check_update("keenetic","1.0.170",arch)
            self.assertEqual(update["platform"],"keenetic");self.assertEqual(update["arch"],arch);self.assertEqual(len(update["sha256"]),64)
            self.assertTrue(update["tunnel_download_url"].endswith("?arch="+arch));self.assertTrue(Path(us.get_latest("keenetic",arch)["file_path"]).exists())
            self.assertIsNone(us.check_update("keenetic","1.0.171",arch))
        self.assertIsNone(us.get_latest("keenetic","mips64"));self.assertIsNone(us.check_update("keenetic","1.0.170"))
    def test_incomplete_or_mixed_release_cannot_publish(self):
        self.upload("aarch64")
        with self.assertRaises(ValueError):us.keenetic_binaries(us.get_latest("keenetic"),require_complete=True)
        self.complete();self.upload("mips","1.0.172")
        with self.assertRaises(ValueError):us.keenetic_binaries(us.get_latest("keenetic"),require_complete=True)
    def test_broken_file_after_upload_cannot_publish(self):
        latest=self.complete();path=Path(us.get_latest("keenetic","armv5")["file_path"]);path.write_bytes(b"bad")
        with self.assertRaises(ValueError):us.keenetic_binaries(latest,require_complete=True)
    def test_slot_delete_keeps_other_architectures_and_platforms(self):
        self.complete();us.ensure_dirs();us._write_manifest("openwrt",{"version":"1.0.171","filename":"old.tgz"})
        before=Path(us._manifest_path("openwrt")).read_bytes();us.delete_platform_update("keenetic","mips")
        self.assertIsNone(us.get_latest("keenetic","mips"));self.assertEqual(len(us.get_latest("keenetic")["files"]),6);self.assertEqual(Path(us._manifest_path("openwrt")).read_bytes(),before)
    def test_untrusted_packages_rejected_before_install(self):
        for mutate in (lambda f:f.update({"../../escape":b"bad"}),lambda f:f.update(ARCH=b"openwrt\n"),lambda f:f.update({"PACKAGE.json":b'{"platform":"openwrt"}'}),lambda f:f.update({"bin/aarch64/spass":b"not ELF"})):
            with self.assertRaises(ValueError):self.upload("aarch64",mutate=mutate)
    def test_pages_entry_has_full_ota_identity(self):
        latest=self.complete();entry=gh._landing_entry_from_manifest("keenetic",latest,"https://example.test/asset")
        self.assertEqual(set(entry["arches"]),set(pkg.ARCHES))
        for arch,slot in entry["arches"].items():
            self.assertEqual(slot["platform"],"keenetic");self.assertEqual(slot["arch"],arch);self.assertEqual(slot["build_id"],"a"*64)
    def test_publish_removes_only_target_platform_archives(self):
        names=["silent-vpn-openwrt-1.0.171-aarch64.tar.gz","silent-vpn-keenetic-1.0.171-aarch64.tar.gz","silent-vpn-keenetic-1.0.171-mips.tar.gz","silent-vpn-keenetic-1.0.171.tar.gz","Silent.VPN.Setup.1.0.171.exe"]
        release={"assets":[{"id":i,"name":name} for i,name in enumerate(names)]}
        for platform,expected in (("keenetic",[1,2]),("openwrt",[0])):
            with patch.object(gh,"_delete_asset",new_callable=AsyncMock) as delete:
                asyncio.run(gh._remove_platform_assets("hidden",release,platform,architectures_only=True))
                self.assertEqual([call.args[1] for call in delete.call_args_list],expected)

if __name__=="__main__":unittest.main()
