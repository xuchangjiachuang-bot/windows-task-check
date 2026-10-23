import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from wintaskcheck.locks import recover


@unittest.skipUnless(os.name == "nt", "Requires Windows file/process handles")
class LockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "task.lock"

    def test_dead_owner_removed_and_missing_is_idempotent(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"], creationflags=subprocess.CREATE_NO_WINDOW)
        child.wait(timeout=10)
        self.path.write_text(json.dumps({"pid": child.pid}))
        self.assertEqual(recover(self.path), "dead_owner_removed")
        self.assertFalse(self.path.exists())
        self.assertEqual(recover(self.path), "absent")

    def test_live_owner_and_open_file_preserved(self):
        self.path.write_text(json.dumps({"pid": os.getpid()}))
        self.assertEqual(recover(self.path), "owner_alive")
        with self.path.open("rb"):
            self.assertEqual(recover(self.path), "busy_or_unavailable")
        self.assertTrue(self.path.exists())

    def test_invalid_and_oversized_locks_preserved(self):
        for value in [b"[]", b"null", b"{}", b"invalid", b"\xff", b"x" * 4097,
                      b'{"pid":true}', b'{"pid":-1}', b'{"pid":0}', b'{"pid":4294967296}']:
            with self.subTest(value=value[:40]):
                self.path.write_bytes(value)
                self.assertEqual(recover(self.path), "invalid_lock")
                self.assertEqual(self.path.read_bytes(), value)

    def test_unknown_owner_preserved(self):
        self.path.write_text(json.dumps({"pid": os.getpid()}))
        with patch("wintaskcheck._windows.process_alive", side_effect=PermissionError):
            self.assertEqual(recover(self.path), "owner_unknown")
        self.assertTrue(self.path.exists())

    def test_reparse_point_preserved_when_symlink_available(self):
        target = self.path.with_suffix(".json")
        target.write_text(json.dumps({"pid": 4294967295}))
        try:
            self.path.symlink_to(target)
        except OSError:
            self.skipTest("Creating symbolic links requires developer mode or privilege")
        self.assertEqual(recover(self.path), "invalid_lock")
        self.assertTrue(self.path.is_symlink())
        self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
