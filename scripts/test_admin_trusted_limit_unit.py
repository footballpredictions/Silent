"""Unit: admin trusted device slot limit config."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402


def test_trusted_devices_max_default_two():
    assert int(settings.ADMIN_TRUSTED_DEVICES_MAX) == 2


if __name__ == "__main__":
    test_trusted_devices_max_default_two()
    print("ok")
