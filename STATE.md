# Current state

## 2026-10-23 | Initial standalone extraction verified
- Version 0.1.0 alpha: finite commands, literal arguments, per-run logs/receipts, job-based cleanup, explicit conservative PID-lock recovery; standard-library runtime and MIT license.
- Local Windows 11 x64 / CPython 3.12.10: 23 regression tests, 22 passed, one symlink privilege skip; evidence runtime/tests-final.log.
- Built wheel installed into a clean venv; isolated python and pythonw acceptance passed, including Windows PowerShell and PowerShell 7; evidence runtime/installed-console/ and runtime/installed-pythonw/.
- Actual limited interactive Task Scheduler launch returned 37, child console handle 0, temporary task removed; evidence runtime/scheduler/ and runtime/scheduler.log.
- Source and installed package validated; runtime evidence is ignored and excluded from release files. Original business source remains unchanged.
- Limits: no visual flash detection, login/reboot, service-session or uv validation. Other Python/Windows CI combinations are configured but have not run.
- Next: publish the reviewed release when requested, execute CI and collect real feedback before using this project in another grant application. No public remote or external adoption yet.
