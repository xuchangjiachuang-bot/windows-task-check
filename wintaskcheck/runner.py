"""Public synchronous run API. Receipts never include command arguments or env."""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import time
import uuid


def write_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _error(exc, stage):
    return {"type": type(exc).__name__, "stage": stage,
            "winerror": getattr(exc, "winerror", None), "errno": getattr(exc, "errno", None)}


def executable_path(value, cwd):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("An executable is required")
    expanded = Path(value)
    if expanded.is_absolute() or expanded.parent != Path(".") or "/" in value or "\\" in value:
        result = expanded if expanded.is_absolute() else cwd / expanded
    else:
        # Do not implicitly execute a similarly named program in the work folder.
        names = [value] if Path(value).suffix else [value + ".exe"]
        result = next((Path(entry) / name
                       for entry in os.environ.get("PATH", "").split(os.pathsep)
                       if entry and Path(entry).is_absolute()
                       for name in names if (Path(entry) / name).is_file()), None)
        if not result:
            raise FileNotFoundError("Executable not found on PATH; use an absolute .exe path")
        result = Path(result)
    result = result.resolve(strict=True)
    if result.suffix.lower() != ".exe" or not result.is_file():
        raise ValueError("Use an .exe entry point; pass scripts to their interpreter explicitly")
    return str(result)


def run(argv, *, output_dir="wintask-runs", cwd=None, timeout=None):
    """Return a receipt dict, preserving DWORD exit codes. Windows 10+, synchronous.

    The direct child determines completion. Remaining descendants are terminated
    even on success; daemon/background-service workloads are not supported.
    """
    if os.name != "nt":
        raise OSError("windows-task-check requires Windows 10 or later")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    run_dir = root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex)
    run_dir.mkdir()
    result_path = run_dir / "result.json"
    result = {"schema_version": 1, "state": "starting", "started_at": _utc(),
              "exit_code": None, "child_exit_code": None, "pid": None,
              "receipt": str(result_path), "stdout": str(run_dir / "stdout.log"),
              "stderr": str(run_dir / "stderr.log"), "error": None}
    write_json(result_path, result)
    start = time.monotonic()
    tree = None
    stage = "validation"
    try:
        if not argv or isinstance(argv, (str, bytes)) or any(not isinstance(arg, str) or "\x00" in arg for arg in argv):
            raise ValueError("argv must be a nonempty sequence of strings without NUL characters")
        if timeout is not None and (not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("timeout must be a finite positive number")
        directory = Path(cwd).resolve(strict=True) if cwd is not None else Path.cwd()
        if not directory.is_dir():
            raise NotADirectoryError("cwd must be a directory")
        command = [executable_path(argv[0], directory), *argv[1:]]
        result["executable"] = Path(command[0]).name
        from ._windows import ProcessTree
        stage = "launch"
        with open(os.devnull, "rb") as input_stream, open(result["stdout"], "wb") as output, open(result["stderr"], "wb") as error:
            tree = ProcessTree(command, str(directory), input_stream, output, error)
            result.update(state="running", pid=tree.pid)
            write_json(result_path, result)
            stage = "wait"
            code = tree.wait(timeout)
            stage = "cleanup"
            if code is None:
                tree.terminate(124)
                result.update(state="timed_out", exit_code=124)
            else:
                result["child_exit_code"] = code
                tree.terminate(125)  # Finite task contract: no detached descendants.
                result.update(state="completed", exit_code=code)
    except KeyboardInterrupt:
        result.update(state="interrupted", exit_code=130)
        try:
            if tree:
                tree.terminate(130)
        except OSError as exc:
            result.update(state="launcher_error", exit_code=125, error=_error(exc, "cleanup"))
    except (OSError, ValueError, TypeError) as exc:
        # Do not put the exception text in receipts: it may contain secret args.
        result.update(state="launcher_error", exit_code=125,
                      error=_error(exc, stage))
    finally:
        if tree:
            tree.close()
    result.update(finished_at=_utc(), duration_seconds=round(time.monotonic() - start, 6))
    write_json(result_path, result)
    return result
