# Decisions

- 2026-10-23 | User authorized extraction of existing Windows background-launch/testing scripts into an independent project, general features and tests, prepared for open source.
- 2026-10-23 | Use a standard-library Python runtime, explicit executable argument arrays and per-run output directories; avoid scheduler/platform scope.
- 2026-10-23 | Use Windows 10 job-list process creation plus kill-on-close; terminate remaining descendants when the direct child exits. This gives finite tasks a defined lifecycle.
- 2026-10-23 | Proposed MIT license, consistent with the maintainer's prior delegated license choice; no copied third-party implementation or private Git history.
- 2026-10-23 | Keep lock recovery manual and conservative; do not infer death from lock age or delete inaccessible locks.
