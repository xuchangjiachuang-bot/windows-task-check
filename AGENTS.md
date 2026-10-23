# Windows Task Check

- Independent Windows finite-task runner and acceptance kit, intended for open source.
- Read STATE.md and DECISIONS.md first. Current user instructions take precedence.
- Runtime code: wintaskcheck/. Synthetic tests: tests/. Optional scheduled-task check: tools/.
- Run: python -m unittest discover -s tests -v; python -m wintaskcheck check --output-dir runtime/checks.
- Standard-library runtime only. Target Windows 10+, CPython 3.10+; test claims must match evidence.
- Keep child exit codes, literal arguments, process-tree cleanup and failure receipts intact.
- Do not use production jobs, credentials or personal/customer data in examples or tests.
- The scheduler harness creates/removes only its own temporary task. Do not edit unrelated tasks.
- Never include runtime/, logs or local environment paths in release archives.
- Local implementation and packaging are authorized; publishing is a separate step.
- Maintain AGENTS.md, STATE.md and DECISIONS.md as the internal project documents.
