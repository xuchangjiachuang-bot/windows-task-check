"""Opt-in local acceptance checks; never register tasks or inspect real jobs."""
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import uuid

from .runner import run, write_json


def python_console():
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    if not executable.is_file():
        raise FileNotFoundError("Use an installed CPython/venv interpreter")
    return str(executable)


def check(output_dir="wintask-runs"):
    from ._windows import process_alive

    root = Path(output_dir).resolve() / ("check-" + uuid.uuid4().hex)
    root.mkdir(parents=True)
    work = root / "unicode 汉字 & $literal; 'quoted'"
    work.mkdir()
    cases = []
    literal = ["汉字", "", "a & b", "$literal; 'quoted'", 'embedded"quote', "trailing\\"]
    probe = str(Path(__file__).with_name("_probe.py"))
    python = python_console()
    for code in (0, 37):
        result = run([python, probe, "report", str(code), *literal], cwd=work, output_dir=root, timeout=30)
        try:
            observed = json.loads(Path(result["stdout"]).read_text(encoding="utf-8"))
            passed = (result["state"] == "completed" and result["exit_code"] == code
                      and observed["console_handle"] == 0 and observed["args"] == literal
                      and observed["cwd"] == str(work) and observed["stdin_eof"]
                      and "synthetic stderr" in Path(result["stderr"]).read_text())
        except (OSError, ValueError, KeyError):
            passed = False
        cases.append({"name": f"python_exit_{code}_console_arguments_logs", "passed": passed, "receipt": result["receipt"]})
    # Windows PowerShell is a mandatory acceptance target; missing is a failure.
    powershell = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    engines = [powershell]
    pwsh = shutil.which("pwsh.exe")
    if pwsh:
        engines.append(Path(pwsh))
    script = work / "probe.ps1"
    script.write_text('''param([string]$Value)
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class TaskConsoleProbe { [DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow(); }'
$r = @{console_handle=[TaskConsoleProbe]::GetConsoleWindow().ToInt64(); value=$Value}
[Console]::WriteLine(($r | ConvertTo-Json -Compress))
exit 37
''', encoding="utf-8-sig")
    for engine in engines:
        result = run([str(engine), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Value", "a & $literal; 'quoted'"], cwd=work, output_dir=root, timeout=45)
        try:
            observed = json.loads(Path(result["stdout"]).read_text(encoding="utf-8-sig"))
            passed = result["exit_code"] == 37 and observed["console_handle"] == 0 and observed["value"] == "a & $literal; 'quoted'"
        except (OSError, ValueError, KeyError):
            passed = False
        cases.append({"name": engine.name + "_console_arguments_exit", "passed": passed, "receipt": result["receipt"]})
    ready = work / "tree.json"
    result = run([python, probe, "tree", str(ready)], output_dir=root, timeout=3)
    try:
        pids = json.loads(ready.read_text())
        passed = result["state"] == "timed_out" and not any(process_alive(pid) for pid in pids.values())
    except (OSError, ValueError):
        passed = False
    cases.append({"name": "timeout_terminates_root_and_child", "passed": passed, "receipt": result["receipt"]})
    summary = {"schema_version": 1, "passed": all(case["passed"] for case in cases),
               "platform": platform.platform(), "python": platform.python_version(), "cases": cases,
               "not_tested": ["visual flash detection", "Task Scheduler logon/reboot",
                              "service sessions", "uv launcher re-execution"],
               "report": str(root / "check.json")}
    write_json(root / "check.json", summary)
    return summary
