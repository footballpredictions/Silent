#!/usr/bin/env python3
"""Cross-compile real Keenetic agent and Silent transport, then package installers."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "aarch64": ("arm64", {}),
    "armv7": ("arm", {"GOARM": "7"}),
    "armv5": ("arm", {"GOARM": "5"}),
    "mipsel": ("mipsle", {"GOMIPS": "softfloat"}),
    "mips": ("mips", {"GOMIPS": "softfloat"}),
    "x86_64": ("amd64", {}),
    "i386": ("386", {}),
}

def prepare_sources():
    # Assets are an independent snapshot; runtime never references OpenWrt files.
    domains = ROOT.parent / "openwrt/files/usr/lib/silent-vpn/ru-direct.domains"
    (ROOT / "files/ru-direct.domains").write_text(domains.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    for path in [*ROOT.glob("*.sh"), *ROOT.glob("files/*")]:
        if path.is_file():
            path.write_text(path.read_text(encoding="utf-8-sig"), encoding="utf-8", newline="\n")

def collect_licenses():
    texts = []
    seen = set()
    decoder = json.JSONDecoder()
    for source in (ROOT / "agent", ROOT.parent / "pc/wdtt-go"):
        raw = subprocess.check_output(["go", "list", "-m", "-json", "all"], cwd=source, text=True)
        while raw.strip():
            module, consumed = decoder.raw_decode(raw.lstrip())
            raw = raw.lstrip()[consumed:]
            name = module["Path"]
            if name in seen or module.get("Main"):
                continue
            seen.add(name)
            directory = Path(module.get("Dir", ".missing"))
            candidates = [p for p in directory.glob("*") if p.is_file() and p.name.upper().startswith(("LICENSE", "COPYING", "COPYRIGHT"))]
            for path in sorted(candidates):
                texts.append(f"=== {name} {module.get('Version', '')}: {path.name} ===\n" + path.read_text(encoding="utf-8", errors="replace"))
    if not any("golang.zx2c4.com/wireguard" in text for text in texts):
        raise RuntimeError("Missing WireGuard license")
    licenses = "\n".join(line.rstrip() for line in "\n\n".join(texts).splitlines()).rstrip()+"\n"
    (ROOT / "THIRD_PARTY_LICENSES.txt").write_text(licenses, encoding="utf-8", newline="\n")

def elf_check(path: Path, name: str):
    data = path.read_bytes()
    head = data[:64]
    expected = {"aarch64": (2, 1, 183), "armv7": (1, 1, 40), "armv5": (1, 1, 40),
                "mipsel": (1, 1, 8), "mips": (1, 2, 8), "x86_64": (2, 1, 62), "i386": (1, 1, 3)}[name]
    actual = (head[4], head[5], int.from_bytes(head[18:20], "little" if head[5] == 1 else "big"))
    if head[:4] != b"\x7fELF" or actual != expected:
        raise ValueError(f"Wrong ELF target: {path} {actual} != {expected}")
    endian = "little" if head[5] == 1 else "big"
    if head[4] == 1:
        offset = int.from_bytes(head[28:32], endian)
        size, count = int.from_bytes(head[42:44], endian), int.from_bytes(head[44:46], endian)
    else:
        offset = int.from_bytes(head[32:40], endian)
        size, count = int.from_bytes(head[54:56], endian), int.from_bytes(head[56:58], endian)
    if any(int.from_bytes(data[offset+i*size:offset+i*size+4], endian) == 3 for i in range(count)):
        raise ValueError(f"Dynamic interpreter found in {path}")

def package(dest: Path, selected: list[str], version: str):
    prefix = f"silent-vpn-keenetic-{version}"
    with tarfile.open(dest, "w:gz", compresslevel=9) as archive:
        items = [ROOT/"install.sh", ROOT/"uninstall.sh", ROOT/"VERSION", ROOT/"README.md", ROOT/"RESEARCH.md", ROOT/"THIRD_PARTY_LICENSES.txt"]
        items += sorted((ROOT/"files").glob("*"))
        items += [ROOT/"build/bin"/name/binary for name in selected for binary in ("silent-keenetic", "spass")]
        for path in items:
            rel = path.relative_to(ROOT)
            if rel.parts[0] == "build": rel = Path(*rel.parts[1:])
            info = archive.gettarinfo(str(path), f"{prefix}/{rel.as_posix()}")
            info.uid = info.gid = 0; info.uname = info.gname = "root"; info.mtime = 0
            info.mode = 0o755 if path.suffix == ".sh" or path.name.startswith("S99") or rel.parts[0] == "bin" else 0o644
            with path.open("rb") as source: archive.addfile(info, source)

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--target", choices=TARGETS, action="append"); parser.add_argument("--package-only", action="store_true")
    args = parser.parse_args(); selected = args.target or list(TARGETS)
    prepare_sources(); collect_licenses(); version = (ROOT/"VERSION").read_text().strip()
    if not args.package_only:
        for name in selected:
            goarch, extra = TARGETS[name]
            env = os.environ.copy(); env.update(GOOS="linux", GOARCH=goarch, CGO_ENABLED="0", GOTOOLCHAIN="local", **extra)
            for binary, source in (("silent-keenetic", ROOT/"agent"), ("spass", ROOT.parent/"pc/wdtt-go")):
                path = ROOT/"build/bin"/name/binary; path.parent.mkdir(parents=True, exist_ok=True)
                print(f"Building {name}/{binary}", flush=True)
                subprocess.run(["go", "build", "-trimpath", "-ldflags=-s -w -checklinkname=0", "-o", str(path), "."], cwd=source, env=env, check=True)
                elf_check(path, name)
    for name in selected:
        for binary in ("silent-keenetic", "spass"): elf_check(ROOT/"build/bin"/name/binary, name)
    dist = ROOT/"dist"; dist.mkdir(exist_ok=True)
    outputs = []
    for name in selected:
        dest = dist/f"silent-vpn-keenetic-{version}-{name}.tar.gz"; package(dest, [name], version); outputs.append(dest)
    dest = dist/f"silent-vpn-keenetic-{version}.tar.gz"; package(dest, selected, version); outputs.append(dest)
    manifest = [{"file":p.name, "size":p.stat().st_size, "sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in outputs]
    (dist/"manifest.json").write_text(json.dumps({"version":version,"architectures":selected,"artifacts":manifest}, indent=2)+"\n", encoding="utf-8")
    (dist/"SHA256SUMS").write_text("".join(f"{x['sha256']}  {x['file']}\n" for x in manifest), encoding="utf-8")
    print(json.dumps(manifest, indent=2), flush=True)

if __name__ == "__main__": main()
