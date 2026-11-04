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
  - **Explicit installer:** `install_monitor.py --install` writes and enables the user's systemd units, with backups, and only when invoked with `--install`.
- **Never:** typing into panes, sending keys, answering prompts, changing grants or config, or performing SSH effects (gate F3).
- **State** lives in private files and directories (0600/0700) opened without following symlinks.

See [THREAT_MODEL.md](THREAT_MODEL.md) for assets, actors, mitigations and residual risk, and [CONTRIBUTING.md](CONTRIBUTING.md) for the enforced gates.
