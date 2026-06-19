"""Упаковка keystore и прочих секретов для build-agent на VPS."""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
MONOREPO = BACKEND_ROOT.parent
DEST = BACKEND_ROOT / "build-agent" / "secrets"
ANDROID_KEYSTORE = MONOREPO / "android" / "keystore"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not ANDROID_KEYSTORE.is_dir():
        raise SystemExit(f"Не найден {ANDROID_KEYSTORE}")

    props = ANDROID_KEYSTORE / "keystore.properties"
    keystore = ANDROID_KEYSTORE / "silent-release.keystore"
    if not props.is_file() or not keystore.is_file():
        raise SystemExit("Нужны keystore.properties и silent-release.keystore в android/keystore/")

    out = DEST / "android" / "keystore"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ANDROID_KEYSTORE, out, ignore=shutil.ignore_patterns("*.example"))

    print(f"OK: secrets -> {out}")
    print("Деплой: python scripts/deploy_build_agent.py")


if __name__ == "__main__":
    main()
