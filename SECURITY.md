# Security policy

## Reporting

Please report vulnerabilities privately: use GitHub's "Report a vulnerability" (private advisories) on this repository, or a confidential issue on GitLab. Do not open a public issue for a vulnerability.

## Supported versions

Only the latest commit on `main` is supported. This project is a prototype.

## Design commitments

- **Runtime: Python standard library only.** No third-party runtime dependencies.
- **No network sockets.** The plugin uses Unix-domain sockets only (gate F5).
- **Effects, stated exactly:**
  - The **core mail lane** (`collective.py mail-apply`) is the only *agent-to-agent* write: local tuios mail through a reviewed, digest-confirmed, single-use plan.
  - **Scheduled notifications:** the heartbeat timer writes private state files and sends change-only alerts to the user's own tuios `human` inbox; `monitor --notify` may raise a desktop notification.
  - **Explicit installers:**
    - `install_monitor.py --install` writes and enables the heartbeat units, with backups, and only when invoked with `--install`.
    - `install_coordination_jobs.py` writes and enables only the two `collective-{collaboration,cohesion}` timers. It verifies the units with `systemd-analyze`, takes backups, refuses units it does not manage, and rolls back when a step raises. Both installers hold one shared nonblocking lock for their whole transaction. Rollback is exception recovery, not atomicity across power loss or SIGKILL. Neither installer runs automatically.
  - **Bounded jobs:** the two job timers write private metadata receipts only. They send no mail or notices, wake no agents, run no tests, start no model turns and retry nothing. There is no scheduled quality execution; the gates run only when a person, a git hook or protected CI invokes `tools/check.py`.
  - **Notice journal:** each heartbeat notice is journaled as an intent before dispatch. An unknown outcome holds its alert keys and is **never resent automatically**; it is reconciled only on exact evidence from the ring, and a key is released (with the record kept) only when its condition resolves. A documented refusal is a known pre-effect outcome and may be retried after backoff. Pre-journal state with a failed attempt holds all notices until an operator runs the documented release. A stored submission is not a read receipt or acceptance.
- **Never:** typing into panes, sending keys, answering prompts, changing grants or config, or performing SSH effects (gate F3).
- **State** lives in private files and directories (0600/0700) opened without following symlinks. `private_files.py` reads through a validated parent directory and `O_NOFOLLOW|O_NONBLOCK` leaf, with owner, mode, link-count, type and size checks. This reduces same-user races and FIFO waits, but does not isolate against a hostile process running as the same user.

See [THREAT_MODEL.md](THREAT_MODEL.md) for assets, actors, mitigations and residual risk, and [CONTRIBUTING.md](CONTRIBUTING.md) for the enforced gates.
