# Windows Task Check

Run a finite Windows task without allocating a console, preserve its exit code,
and retain evidence of what happened. Includes executable acceptance checks for
Python, PowerShell, literal arguments and process-tree timeouts.

**Status: 0.1.0 alpha, prepared for an initial open-source release.** Windows 10+
and CPython 3.10+ are the intended targets. There are no runtime dependencies.
This repository is not yet published to PyPI; install from a local checkout.

## Quick start

In PowerShell, from the checkout:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m wintaskcheck check --output-dir .\runtime\checks
```

Use a real interpreter path. Prefer a script file so the invoking shell does not
have to quote inline Python source:

```powershell
Set-Content -LiteralPath .\runtime\hello.py -Value 'print("hello")' -Encoding UTF8
.\.venv\Scripts\python.exe -m wintaskcheck run --timeout 30 --output-dir .\runtime\runs -- .\.venv\Scripts\python.exe .\runtime\hello.py
```

For a windowless entry point launched by Task Scheduler, use the **absolute path
to `pythonw.exe`** in that same environment, with `-m wintaskcheck run ...` as its
arguments. The regular `wintaskcheck` console entry point is useful interactively;
it cannot hide the console used to start it. `pythonw` produces no terminal output,
so read the result files. Set an explicit output directory and working directory.

## Run commands

```text
pythonw.exe -m wintaskcheck run --cwd "C:\My Job" --timeout 60 --output-dir "C:\My Job\runs" -- "C:\Python312\python.exe" "C:\My Job\job.py" "literal argument"
pythonw.exe -m wintaskcheck run --timeout 60 --output-dir "C:\My Job\runs" -- "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -File "C:\My Job\job.ps1"
```

Use actual paths for your machine. All options for this tool go **before `--`**.
The remaining arguments belong to the executable. `.ps1`, `.py`, `.cmd` and `.bat`
are not implicit executable entry points: supply their interpreter explicitly.
For batch files, invoke `cmd.exe /d /c` and apply cmd's quoting rules yourself;
shell metacharacters are then interpreted by that shell. Passing paths/arguments
from untrusted sources to a shell is outside this tool's literal-argument guarantee.

Bare executable names are resolved from absolute PATH entries, without an implicit
current-directory search. Relative executable paths resolve against `--cwd`.
Environment variables are inherited; no shell expansion is performed by the runner.
Standard input is EOF. Standard output and standard error go directly to separate
binary files, preserving the child's encoding and avoiding pipe-buffer deadlocks.

Python API:

```python
from wintaskcheck.runner import run

result = run([r"C:\Python312\python.exe", r"C:\My Job\job.py"],
             cwd=r"C:\My Job", output_dir=r"C:\My Job\runs", timeout=60)
print(result["state"], result["exit_code"], result["receipt"])
```

## Results and completion

Each run gets a unique subdirectory containing `stdout.log`, `stderr.log` and
`result.json`. Receipts are atomically replaced on state changes. A validation or
launch failure may have no log files. If the output directory itself is unusable,
no receipt can be written; run with `python.exe` for the CLI error response.
Errors include a stage (`validation`, `launch`, `wait`, `cleanup`) and exception/
Windows error codes, without exception messages that could expose arguments.

| State | Runner exit code | Meaning |
| --- | --- | --- |
| `completed` | Child's original 32-bit Windows code | Direct child exited; remaining descendants were cleaned up |
| `timed_out` | 124 | Deadline elapsed and the job was terminated |
| `launcher_error` | 125 | Validation, launch, or cleanup failed |
| `interrupted` | 130 | Python handled KeyboardInterrupt and cleaned up |

A child can itself return 124, 125 or 130: use `state` and `child_exit_code` to tell
these apart. `completed` does not mean successful; check its code. JSON retains
unsigned DWORD values such as 3221225477. The CLI preserves their Windows exit bits.
The timeout covers execution after launch, not file setup; cleanup can take up to
10 additional seconds. Omitting `--timeout` means no deadline. An external forced
kill may leave a receipt marked `starting` or `running`; it is not a success marker.

**Finite tasks only:** completion of the direct child ends the run. Remaining
ordinary descendants are terminated even if the direct child succeeded. Do not use
this runner for daemons, services, installers that detach work, or commands intended
to leave background workers alive. Logs are not rotated automatically; set retention
outside the tool and ensure sufficient disk space.
Output buffering belongs to the child; use its unbuffered/flush options when
needed, since forced termination can discard data still in the child's buffers.

## Acceptance checks

`python -m wintaskcheck check --output-dir runtime/checks` creates synthetic work
only. It saves `check.json` with pass/fail results and individual receipts. It tests:

- Real console handles, literal arguments including empty/Unicode values, cwd and EOF stdin.
- Success and nonzero exit propagation, plus separate output/error logs.
- Windows PowerShell; also PowerShell 7 when installed.
- A timeout that terminates a real parent and its child.

The broader test suite additionally exercises Node when installed, concurrent runs,
large binary output, unsigned exit codes, forced launcher termination, invalid inputs,
handle cleanup after launch errors and lock recovery:

```powershell
python -m unittest discover -s tests -v
```

To test **actual Task Scheduler execution**, install the package, then explicitly run:

```powershell
powershell.exe -NoProfile -File .\tools\check-scheduler.ps1 -Python (Resolve-Path .\.venv\Scripts\python.exe).Path
```

This opt-in script registers one uniquely named limited interactive task without
triggers, runs it once via `pythonw`, checks the scheduler's final result (37) and
the child's console handle, then removes that exact task in `finally`. It creates
no recurring tasks and asks for no credentials or elevation. Local policy may deny
registration; that is a failed/unverified scheduler check, not a passing result.

## Lock recovery

```powershell
python -m wintaskcheck recover-lock "C:\My Job\task.lock"
```

This is an **explicit** operation for a small JSON file such as `{"pid": 1234}`.
It removes the file only after obtaining exclusive access and proving that its PID
is no longer alive. Malformed, oversized, occupied or inaccessible files remain;
reparse points are refused. PID reuse blocks recovery conservatively. A live PID
does not prove that it still owns the lock. Lock producers must use a compatible
locking protocol; this command does not acquire locks and is never called by `run`.

## Limits and design

The runner uses `CREATE_NO_WINDOW` and a Windows Job Object with kill-on-close.
It attaches the child to the job at process creation using the Windows 10 job-list
attribute. This avoids a gap in which a newly created process could escape cleanup.
Only the standard I/O handles are passed through the explicit handle list.
See Microsoft's [job object documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
and [job-list creation explanation](https://devblogs.microsoft.com/oldnewthing/20230209-00/?p=107812).

This is process management, not a security sandbox. A program can still display
its own GUI or create a new console. Work delegated through WMI, a service, an
already-running process or another external broker is not contained by the job.
Arguments follow Windows C-runtime quoting; applications with their own parsers
may differ. Restrictive enclosing jobs can reject creation; the runner fails rather
than launching without containment. GUI input, elevation and UAC are unsupported.

Initial validation on 2026-10-23: Windows 11 x64, CPython 3.12.10; 22 regression
tests passed and one symlink test was skipped for missing creation privilege.
The built wheel passed acceptance from an isolated virtual environment using
both `python.exe` and `pythonw.exe`, including Windows PowerShell and PowerShell 7.
An on-demand limited interactive Task Scheduler test returned 37, recorded a zero
child console handle, and removed its temporary task afterward.

Other Windows/Python
versions in the CI matrix are intended coverage, not evidence of successful runs
until CI actually executes. Visual flash detection, login/reboot behavior, service
sessions and uv launcher re-execution remain unverified. Run `check` with the exact
interpreter/environment you intend to deploy. This alpha has no verified external
adoption yet and is not endorsed by any upstream project or grant program.

Receipts omit command arguments and environment values. They contain local paths
and process identifiers. Child output may contain anything the child prints,
including secrets; review and redact files before sharing. This tool does not
automatically collect, upload or send logs.

## 中文说明

这是一个从实际后台自动化脚本整理出的 Windows 小工具：运行命令、保留退出码、
记录日志，并用真实 Python/PowerShell 进程验证行为。运行时仅依赖 Python 标准库。
建议先按 Quick start 安装，再执行 `check` 查看当前机器的验收结果。

计划任务入口使用虚拟环境中的 `pythonw.exe`，参数使用 `-m wintaskcheck run ...`，
并填写绝对路径。普通命令行入口无法隐藏启动它的控制台。工具适合会结束的任务；
父命令退出后会清理残留子进程，不适合常驻服务。`result.json` 中的状态和退出码要
一起看，不能只看是否产生了文件。验收不等于保证任何程序都不会主动弹窗。

## Contributing and provenance

The initial launcher/lock-recovery ideas and regression cases come from the
maintainer's existing Windows automation scripts. This extraction replaces their
business-specific entry points with a general runner and adds job-based lifetime
control. No production configuration, customer data or private repository history
is included. The Win32 adapter is newly implemented for this extraction; no upstream
project implementation was copied. MIT license; contributions should be compatible
with that license.

Useful reports include OS/Python versions, the executable family, a minimal synthetic
reproducer and redacted `check.json`. Please run tests before proposing changes.
Maintenance scope is small fixes, documentation and issue feedback; broader scheduler
or service-manager features are outside the initial scope. For sensitive reports,
use the repository's private vulnerability reporting if enabled; otherwise remove
sensitive material and report only a synthetic reproducer in a public issue.
