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
    - `install_coordination_jobs.py` writes and enables only the three `collective-{collaboration,cohesion,quality}` timers. It holds an exclusive lock, verifies the units with `systemd-analyze`, takes backups, refuses units it does not manage, and rolls back on failure. Neither installer runs automatically.
  - **Bounded jobs:** the three job timers write private metadata receipts only. They send no mail or notices, wake no agents, start no model turns and retry nothing. The quality job runs the gates offline (`UV_OFFLINE=1`) with pinned tools and private caches; it does not fetch, fix or push.
  - **Notice journal:** each heartbeat notice is journaled as an intent before dispatch. An uncertain outcome holds its alert keys and is **never resent automatically**; it is reconciled only on exact evidence from the ring. A stored submission is not a read receipt or acceptance.
- **Never:** typing into panes, sending keys, answering prompts, changing grants or config, or performing SSH effects (gate F3).
- **State** lives in private files and directories (0600/0700) opened without following symlinks. `private_files.py` reads through a validated parent directory and `O_NOFOLLOW|O_NONBLOCK` leaf, with owner, mode, link-count, type and size checks. This reduces same-user races and FIFO waits, but does not isolate against a hostile process running as the same user.

See [THREAT_MODEL.md](THREAT_MODEL.md) for assets, actors, mitigations and residual risk, and [CONTRIBUTING.md](CONTRIBUTING.md) for the enforced gates.
