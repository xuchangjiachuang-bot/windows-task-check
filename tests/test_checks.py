import json
import os
from pathlib import Path
import tempfile
import unittest

from wintaskcheck.checks import check


@unittest.skipUnless(os.name == "nt", "Acceptance requires Windows")
class AcceptanceTests(unittest.TestCase):
    def test_acceptance_command_checks_real_python_powershell_and_tree(self):
        with tempfile.TemporaryDirectory() as root:
            result = check(root)
            self.assertTrue(result["passed"], result)
            self.assertGreaterEqual(len(result["cases"]), 4)
            self.assertEqual(json.loads(Path(result["report"]).read_text(encoding="utf-8")), result)


if __name__ == "__main__":
    unittest.main()
