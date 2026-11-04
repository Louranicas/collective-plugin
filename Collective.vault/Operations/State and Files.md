---
title: State and Files
type: operations
status: current
created: 2026-11-04
owner: Claude (tuios pane 08651035)
tags: [collective, operations]
---

# State and files: every file and store the collective uses

| Path | Owner | Mode | Contents | Lifetime |
|---|---|---|---|---|
| `~/tuios-setup/collective-plugin/` | Codex 3 (source), Codex 2 (tests), Claude (docs) | git, uncommitted | Canonical plugin | Until commit/registration |
| `~/.config/systemd/user/collective-heartbeat.{timer,service}` | Codex 3 | user units | The **one** scheduler | Disable to stop |
| `~/.local/state/collective/heartbeat.json` | heartbeat | 0600 in a 0700 dir | Board: agents, herdr counts, relay, peers, alerts, flex | Rewritten each full sweep |
| `~/.local/state/collective/memory.json` | heartbeat | 0600 | Dedup keys, unread/needs ages, `last_full`, mode | Persists |
| `~/.local/state/collective-plugin/mail-journal.jsonl` | `collective.py` | 0600, one link | intent/submitted/refused/unknown; hashes only | Grows (rotate later) |
| `~/.local/state/collective-plugin/plans/` | senders | 0600 plans in 0700 dirs | Plans **include the body**; deleted after apply by default | Until applied |
| `~/.local/state/collective-plugin/scheduler-backups/` | `install_monitor.py` | private | Unit backups and install receipt | Keep |
| tuios mail ring | tuios daemon | memory | Messages and threads | **Lost on daemon restart** |
| tuios task cards and pane notes | tuios daemon | session | Intake, claims, `DOING\|NEXT\|BLOCKED` | Survive restart |
| MemPalace hub | MemPalace | — | Durable events and drawers (team reports) | Durable |
| `~/.atuin/data/history.db` | atuin hooks | — | Agent shell commands (author, exit, cwd, intent) | Durable; local only (sync off) |
| `~/src/herdr-collective/` | Claude | — | **Reference only**: collab, herdr-sock, send, the original heartbeat | Not adopted |

## Durable reports in MemPalace

| Drawer | Contents |
|---|---|
| `drawer_b471a3474e95b9cbabbbea1d` | Combined comms-layer report (Codex 2) |
| `drawer_herdr_habitat_operations_7414165c64c0e1e5d86e71ee` | tuios www and SSH addendum |
| `drawer_herdr_habitat_operations_49bb4cde53852d803f3bd0f5` | Native herdr and MemPalace findings (Codex 3) |
