"""Selection cannot turn a narrow deployment into a whole-tree or outside-root upload."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_stable import _selected_python_paths


class SelectionTests(unittest.TestCase):
    def test_existing_payment_file_only_and_deduplicated(self):
        self.assertEqual(_selected_python_paths(["app/services/payment_service.py"] * 2), ["app/services/payment_service.py"])

    def test_reject_traversal_absolute_non_python_and_other_trees(self):
        for name in ("app/../scripts/deploy_stable.py", "/app/services/payment_service.py", "docker-compose.yml", "scripts/deploy_stable.py", "app/services", "app/missing.py"):
            with self.subTest(path=name), self.assertRaises(ValueError):
                _selected_python_paths([name])


if __name__ == "__main__":
    unittest.main()
