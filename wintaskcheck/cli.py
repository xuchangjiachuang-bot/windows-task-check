import argparse
import json
import sys

from . import __version__


def emit(value):
    if sys.stdout is not None:
        print(json.dumps(value, ensure_ascii=True))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="wintaskcheck", description="Run and verify finite Windows background tasks.")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="action", required=True)
    task = sub.add_parser("run", help="Run an explicit executable without a shell")
    task.add_argument("--output-dir", default="wintask-runs")
    task.add_argument("--cwd")
    task.add_argument("--timeout", type=float, default=None, help="Positive seconds; omitted means no deadline")
    task.add_argument("command", nargs=argparse.REMAINDER, help="-- executable.exe argument ...")
    acceptance = sub.add_parser("check", help="Run synthetic checks and save check.json")
    acceptance.add_argument("--output-dir", default="wintask-runs")
    lock = sub.add_parser("recover-lock", help="Explicitly recover a JSON PID lock after proven owner death")
    lock.add_argument("path")
    args = parser.parse_args(argv)
    try:
        if args.action == "run":
            from .runner import run
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            result = run(command, output_dir=args.output_dir, cwd=args.cwd, timeout=args.timeout)
            emit(result)
            # sys.exit converts through a signed C int; preserve DWORD bits.
            code = result["exit_code"]
            return code if code < 0x80000000 else code - 0x100000000
        if args.action == "check":
            from .checks import check
            result = check(args.output_dir)
            emit(result)
            return 0 if result["passed"] else 1
        from .locks import recover
        state = recover(args.path)
        emit({"state": state})
        return 0 if state in ("absent", "dead_owner_removed") else 1
    except (OSError, ValueError) as exc:
        emit({"state": "launcher_error", "error": {"type": type(exc).__name__, "winerror": getattr(exc, "winerror", None)},
              "hint": "Check Windows support, output-directory permissions and interpreter paths."})
        return 125


if __name__ == "__main__":
    raise SystemExit(main())
