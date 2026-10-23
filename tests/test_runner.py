import concurrent.futures
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from wintaskcheck.runner import run

ROOT = Path(__file__).resolve().parents[1]
PROBE = str(ROOT / "wintaskcheck" / "_probe.py")
PYTHON = str(Path(sys.executable).with_name("python.exe"))


@unittest.skipUnless(os.name == "nt", "Requires real Windows process APIs")
class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="task-check 汉字 & ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def execute(self, args, **options):
        return run(args, output_dir=self.root / "runs", **options)

    def test_literal_arguments_console_cwd_stdin_and_logs(self):
        arguments = ["", "汉字", "a & b", "$x; 'quoted'", 'a"b', "space \\", "tail\\", "%PATH%", "line\nbreak"]
        result = self.execute([PYTHON, PROBE, "report", "37", *arguments], cwd=self.root, timeout=20)
        self.assertEqual((result["state"], result["exit_code"]), ("completed", 37))
        observed = json.loads(Path(result["stdout"]).read_text())
        self.assertEqual(observed, {"console_handle": 0, "cwd": str(self.root), "args": arguments, "stdin_eof": True})
        self.assertIn("synthetic stderr", Path(result["stderr"]).read_text())
        self.assertEqual(json.loads(Path(result["receipt"]).read_text()), result)

    def test_real_pythonw_entrypoint_and_exit_code(self):
        pythonw = Path(PYTHON).with_name("pythonw.exe")
        self.assertTrue(pythonw.exists())
        result = subprocess.run([str(pythonw), "-m", "wintaskcheck", "run", "--output-dir", str(self.root),
                                 "--timeout", "20", "--", PYTHON, PROBE, "report", "37", "literal"],
                                cwd=ROOT, timeout=30, capture_output=True)
        self.assertEqual(result.returncode, 37, result.stderr)
        receipt = json.loads(next(self.root.glob("*/result.json")).read_text())
        self.assertEqual(receipt["state"], "completed")
        self.assertEqual(json.loads(Path(receipt["stdout"]).read_text())["console_handle"], 0)

    def test_unsigned_windows_exit_code_is_preserved(self):
        code = 0xC0000005
        result = self.execute([PYTHON, "-c", f"import ctypes; ctypes.windll.kernel32.ExitProcess({code})"])
        self.assertEqual(result["exit_code"], code)
        cli = subprocess.run([PYTHON, "-m", "wintaskcheck", "run", "--output-dir", str(self.root),
                              "--", PYTHON, "-c", f"import ctypes; ctypes.windll.kernel32.ExitProcess({code})"],
                             cwd=ROOT, capture_output=True, timeout=30)
        self.assertEqual(cli.returncode, code)

    def test_launcher_error_and_timeout_are_distinct_from_child_codes(self):
        for code in (124, 125, 130):
            with self.subTest(code=code):
                result = self.execute([PYTHON, "-c", f"raise SystemExit({code})"])
                self.assertEqual((result["state"], result["exit_code"]), ("completed", code))
        missing = self.execute([str(self.root / "missing.exe")])
        self.assertEqual((missing["state"], missing["exit_code"]), ("launcher_error", 125))
        timed = self.execute([PYTHON, "-c", "import time; time.sleep(30)"], timeout=0.1)
        self.assertEqual((timed["state"], timed["exit_code"]), ("timed_out", 124))

    def test_invalid_input_does_not_execute(self):
        for args, options in [([], {}), ("python.exe", {}), ([PYTHON, "\0"], {}),
                              ([PYTHON], {"timeout": 0}), ([PYTHON], {"timeout": float("nan")}),
                              ([PYTHON], {"timeout": float("inf")}),
                              ([PYTHON], {"cwd": self.root / "missing"})]:
            with self.subTest(args=args, options=options):
                result = self.execute(args, **options)
                self.assertEqual(result["state"], "launcher_error")
                self.assertIsNone(result["pid"])

    def test_batch_file_is_not_implicitly_executed(self):
        batch = self.root / "do not run.cmd"
        marker = self.root / "marker.txt"
        batch.write_text(f'echo dangerous > "{marker}"')
        result = self.execute([str(batch)])
        self.assertEqual(result["state"], "launcher_error")
        self.assertFalse(marker.exists())

    def test_no_implicit_current_directory_executable_search(self):
        fake = self.root / "unexpected.exe"
        fake.write_bytes(b"not an executable")
        with patch.dict(os.environ, {"PATH": ";.;"}):
            result = self.execute(["unexpected.exe"], cwd=self.root)
        self.assertEqual(result["error"]["type"], "FileNotFoundError")

    def test_environment_is_inherited_but_arguments_and_env_are_not_in_receipt(self):
        marker = "synthetic-sensitive-value-for-test-only"
        with patch.dict(os.environ, {"TASK_CHECK_SYNTHETIC": marker}):
            result = self.execute([PYTHON, "-c", "import os; print(os.environ['TASK_CHECK_SYNTHETIC'])", marker])
        self.assertEqual(Path(result["stdout"]).read_text().strip(), marker)
        self.assertNotIn(marker, Path(result["receipt"]).read_text())

    def test_large_binary_logs_do_not_deadlock_or_decode(self):
        size = 1024 * 1024
        code = f"import sys; sys.stdout.buffer.write(bytes(range(256))*{size // 256}); sys.stderr.buffer.write(b'E'*{size})"
        result = self.execute([PYTHON, "-c", code], timeout=20)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(Path(result["stdout"]).read_bytes(), bytes(range(256)) * (size // 256))
        self.assertEqual(Path(result["stderr"]).stat().st_size, size)

    def test_parallel_runs_do_not_overwrite_each_other(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: self.execute([PYTHON, "-c", f"print({i})"]), range(8)))
        self.assertEqual(len({r["receipt"] for r in results}), 8)
        self.assertEqual([Path(r["stdout"]).read_text().strip() for r in results], list(map(str, range(8))))

    def test_timeout_kills_real_descendants(self):
        from wintaskcheck._windows import process_alive
        ready = self.root / "ready.json"
        result = self.execute([PYTHON, PROBE, "tree", str(ready)], timeout=3)
        self.assertEqual(result["state"], "timed_out")
        pids = json.loads(ready.read_text())
        self.assertTrue(all(not process_alive(pid) for pid in pids.values()))

    def test_success_also_cleans_up_detached_descendants(self):
        from wintaskcheck._windows import process_alive
        ready = self.root / "ready.json"
        result = self.execute([PYTHON, PROBE, "detach", str(ready)], timeout=20)
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(all(not process_alive(pid) for pid in json.loads(ready.read_text()).values()))

    def test_killing_launcher_closes_job_and_kills_descendants(self):
        from wintaskcheck._windows import process_alive
        ready = self.root / "ready.json"
        launcher = subprocess.Popen([PYTHON, "-m", "wintaskcheck", "run", "--output-dir", str(self.root / "runs"),
                                     "--", PYTHON, PROBE, "tree", str(ready)], cwd=ROOT,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + 15
            while not ready.exists() and launcher.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists())
            pids = json.loads(ready.read_text())
            launcher.kill()
            launcher.wait(timeout=10)
            deadline = time.monotonic() + 5
            while any(process_alive(pid) for pid in pids.values()) and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(all(not process_alive(pid) for pid in pids.values()))
        finally:
            if launcher.poll() is None:
                launcher.kill()
                launcher.wait(timeout=10)

    def test_ctrl_c_cleanup_path_terminates_tree(self):
        from wintaskcheck._windows import ProcessTree, process_alive
        with patch.object(ProcessTree, "wait", side_effect=KeyboardInterrupt):
            result = self.execute([PYTHON, "-c", "import time; time.sleep(30)"])
        self.assertEqual((result["state"], result["exit_code"]), ("interrupted", 130))
        self.assertFalse(process_alive(result["pid"]))

    def test_launch_failure_releases_handles(self):
        from wintaskcheck._windows import K, W, _bind
        count = _bind("GetProcessHandleCount", [W.HANDLE, ctypes.POINTER(W.DWORD)])
        process = K.GetCurrentProcess()
        before, after = W.DWORD(), W.DWORD()
        count(process, ctypes.byref(before))
        malformed = self.root / "invalid.exe"
        malformed.write_bytes(b"not executable")
        for _ in range(12):
            self.assertEqual(self.execute([str(malformed)])["state"], "launcher_error")
        count(process, ctypes.byref(after))
        self.assertLessEqual(after.value, before.value + 2)

    def test_cleanup_error_is_recorded_even_during_interrupt(self):
        from wintaskcheck._windows import ProcessTree, process_alive
        with patch.object(ProcessTree, "wait", side_effect=KeyboardInterrupt), patch.object(ProcessTree, "terminate", side_effect=OSError):
            result = self.execute([PYTHON, "-c", "import time; time.sleep(30)"])
        self.assertEqual(result["state"], "launcher_error")
        self.assertEqual(result["error"]["stage"], "cleanup")
        self.assertEqual(json.loads(Path(result["receipt"]).read_text()), result)
        deadline = time.monotonic() + 5
        while process_alive(result["pid"]) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(process_alive(result["pid"]))

    @unittest.skipUnless(shutil.which("node.exe"), "Optional Node interpreter not installed")
    def test_actual_node_interpreter_and_literal_arguments(self):
        node = shutil.which("node.exe")
        args = ["汉字 & $x;", "", 'quote"tail\\']
        result = self.execute([node, "-e", "process.stdout.write(JSON.stringify(process.argv.slice(1))); process.exitCode=37", *args])
        self.assertEqual(result["exit_code"], 37)
        self.assertEqual(json.loads(Path(result["stdout"]).read_text(encoding="utf-8")), args)


if __name__ == "__main__":
    unittest.main()
