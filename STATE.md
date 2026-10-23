# Current state

## 2026-10-23 | Public alpha verified on hosted Windows CI
- Public MIT repository: https://github.com/xuchangjiachuang-bot/windows-task-check; version 0.1.0 alpha, standard-library runtime, no PyPI publication.
- Hosted CI passed 6/6 jobs: Windows Server 2022/2025 with CPython 3.10/3.12/3.13; each runs 23 regression tests and acceptance checks. Evidence: https://github.com/xuchangjiachuang-bot/windows-task-check/actions/runs/39911449922 (f2d03a1).
- First CI failures fixed: UTF-8 fixture reads/writes, short-path normalization, warmed handle-leak measurement, and waiting on descendant process handles before reporting completion.
- Local Windows 11 / CPython 3.12.10: 22 tests passed, one symlink-privilege skip; runtime/ci-fix-local-tests.log. Rebuilt wheel passed 5 checks each under isolated python and pythonw; runtime/release-console/ and runtime/release-pythonw/.
- Updated installed wheel passed actual limited interactive Task Scheduler check: exit 37, console handle zero, temporary task removed; runtime/release-scheduler.log.
- Limits: no visual flash, login/reboot, service-session or uv verification; no verified external adoption. Runtime evidence and personal grant information stay outside tracked source.
- Next: collect reproducible user feedback, maintain small fixes/docs, and review the separate private grant draft before any submission.
- Verified 2026-10-23 using local test/install/scheduler receipts, public GitHub metadata and completed Actions jobs; latest main checks are visible in Actions.
