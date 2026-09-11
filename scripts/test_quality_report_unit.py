"""Unit: quality store helpers (no DB/network/fastapi)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.quality_store import payload_preview  # noqa: E402


class QualityStoreUnit(unittest.TestCase):
    def test_payload_preview_truncates(self) -> None:
        raw = '{"verdict":"slow","x":"' + ("a" * 500) + '"}'
        out = payload_preview(raw)
        self.assertLessEqual(len(out), 200)

    def test_payload_preview_invalid_json(self) -> None:
        out = payload_preview("not-json-" + ("b" * 300))
        self.assertEqual(len(out), 200)


if __name__ == "__main__":
    unittest.main()
