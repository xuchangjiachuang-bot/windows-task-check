"""Synthetic acceptance fixture, also executable by absolute script path."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    mode = sys.argv[1]
    if mode == "report":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetConsoleWindow.restype = ctypes.c_void_p
        print(json.dumps({"console_handle": kernel.GetConsoleWindow() or 0,
                          "cwd": os.getcwd(), "args": sys.argv[3:],
                          "stdin_eof": sys.stdin.buffer.read() == b""}))
        print("synthetic stderr", file=sys.stderr)
        return int(sys.argv[2])
    if mode in ("tree", "detach"):
        ready = Path(sys.argv[2])
        descendant = ready.with_suffix(".child")
        child_code = "import os,time,pathlib; pathlib.Path(__import__('sys').argv[1]).write_text(str(os.getpid())); time.sleep(120)"
        child = subprocess.Popen([sys.executable, "-c", child_code, str(descendant)],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 15
        while not descendant.exists():
            if time.monotonic() >= deadline:
                return 99
            time.sleep(0.01)
        ready.write_text(json.dumps({"root": os.getpid(), "child": child.pid}), encoding="utf-8")
        if mode == "tree":
            time.sleep(120)
        return 0
    raise ValueError("Unknown synthetic mode")


if __name__ == "__main__":
    raise SystemExit(main())
