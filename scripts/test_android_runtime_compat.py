"""Run the pinned Android Go runtime with real vendor uname responses.

Requires qemu-arm[-static] and qemu-i386[-static]. On Windows they run in WSL.
No Android device, VPN, root access or network connection is used by the probe.
"""
from pathlib import Path
import argparse
import json
import os
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
RELEASES = ("4.9.170", "3.14.29_AMLOGIC", "4.9.113_AMLOGIC",
            "3.4.35_hi3535", "6.12.87_1", "5.10.0-android12", "3.10")


def linux_path(path):
    value = Path(path).resolve()
    if os.name == "nt":
        return "/mnt/" + value.drive[0].lower() + value.as_posix()[2:]
    return str(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qemu-dir", required=True, help="Linux directory containing QEMU user binaries")
    parser.add_argument("--wsl-distro", default="Ubuntu-24.04")
    parser.add_argument("--check-jni", action="store_true", help="Also reject stale/wrong-ABI native libraries")
    args = parser.parse_args()
    source = (ROOT / "app/build_android_go.bat").read_text(encoding="utf-8")
    toolchain = re.search(r'set "GOTOOLCHAIN=(go[0-9.]+)"', source).group(1)
    scripts = [ROOT / "app/site-router/build.ps1", ROOT / "app/site-router/build.sh"]
    agent = ROOT.parent / "backend/build-agent/build_android_go.sh"
    if agent.is_file():
        scripts.append(agent)
    for script in scripts:
        pins = re.findall(r"GOTOOLCHAIN=['\"]?(go[0-9.]+)", script.read_text(encoding="utf-8"))
        assert pins and set(pins) == {toolchain}, f"Android toolchain differs in {script.name}"
    work = ROOT / "app/build/runtime-startup-compat"
    work.mkdir(parents=True, exist_ok=True)
    results = []
    for arch, qemu_name in (("arm", "qemu-arm-static"), ("386", "qemu-i386-static")):
        binary = work / ("probe-" + arch)
        env = dict(os.environ, GOTOOLCHAIN=toolchain, GOOS="linux", GOARCH=arch,
                   CGO_ENABLED="0", GOARM="7" if arch == "arm" else "", GO386="sse2")
        subprocess.run(["go", "build", "-o", str(binary), str(ROOT / "scripts/runtime-startup-probe/main.go")],
                       cwd=ROOT / "app/wdtt-go", env=env, check=True)
        qemu = args.qemu_dir.rstrip("/") + "/" + qemu_name
        prefix = ["wsl", "-d", args.wsl_distro, "--exec"] if os.name == "nt" else []
        for release in RELEASES:
            trace = ["-strace"] if release == "4.9.113_AMLOGIC" else []
            result = subprocess.run([*prefix, qemu, *trace, "-r", release, linux_path(binary)],
                                    capture_output=True, text=True, timeout=45)
            passed = result.returncode == 0 and "runtime-started " + arch in result.stdout
            row = {"toolchain": toolchain, "arch": arch, "uname": release,
                   "passed": passed, "exit_code": result.returncode}
            if not passed:
                row["failure"] = result.stderr.splitlines()[0] if result.stderr else "main was not reached"
            elif trace:
                # Old Android seccomp must never see these Linux 5.1 syscalls.
                assert "futex_time64" not in result.stderr and "timer_settime64" not in result.stderr
                row["legacy_time_syscalls_verified"] = True
            results.append(row)
            print(json.dumps(row), flush=True)
    (work / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    assert all(row["passed"] for row in results), "Go runtime fails before VPN main on a supported 32-bit ABI"
    if args.check_jni:
        for abi, arch in (("armeabi-v7a", "arm"), ("arm64-v8a", "arm64"), ("x86", "386"), ("x86_64", "amd64")):
            for name in ("libclient.so", "libsite-router.so"):
                library = ROOT / "app/src/main/jniLibs" / abi / name
                info = subprocess.check_output(["go", "version", "-m", str(library)], text=True)
                assert info.splitlines()[0].endswith(": " + toolchain), f"Stale runtime in {abi}/{name}"
                for setting in ("GOOS=android", "GOARCH=" + arch, "CGO_ENABLED=1"):
                    assert setting in info, f"Wrong target {setting}: {abi}/{name}"
        print(json.dumps({"native_libraries": 8, "toolchain": toolchain, "targets_verified": True}))


if __name__ == "__main__":
    main()
