---
title: State and Files
type: operations
status: current
created: 2026-11-04
owner: Claude (tuios pane <claude-pane>)
tags: [collective, operations]
---

# State and files: every file and store the collective uses

| Path | Owner | Mode | Contents | Lifetime |
|---|---|---|---|---|
| `~/tuios-setup/collective-plugin/` | Codex 3 (source), Codex 2 (tests), Claude (docs) | git; source on GitHub `feat/collective-comms` (PR #1, draft at the 2026-11-05 snapshot; GitLab main held only the bootstrap then; query remotes for current state) | Canonical plugin (registered in tuios and native herdr) | Canonical local checkout |
| `~/.config/systemd/user/collective-heartbeat.{timer,service}` | Codex 3 | user units | The **one notification gateway** (formerly "the one scheduler") | Disable to stop |
| `~/.config/systemd/user/collective-{collaboration,cohesion,quality}.{timer,service}` | Codex 3 (`install_coordination_jobs.py`) | user units, marker-managed | Bounded jobs: no notices, mail, wakes or model turns. **Proposed; not installed on 2026-11-05** | Disable the three timers to stop |
| `~/.local/state/collective/coordination/<job>.json` | `coordination_jobs.py` | 0600 in a 0700 dir | Schema-1 job receipt: status, source and metric gaps, metrics, `source_sha256`. Metadata only | Rewritten each run |
| `~/.local/state/collective/coordination/{<job>,installer}.lock` | jobs, installer | 0600, one link | Exclusive non-blocking locks | Persist |
| `~/.local/state/collective/coordination/installer.json` and `installer-backups/<UTC>-<id>/` | `install_coordination_jobs.py` | 0600 | `installing` → `installed` or `rolled-back`; prior managed units and staged units | Keep |
| `~/.local/state/collective/coordination/quality-cache/`, `quality-check.json`, `gate-tools/bin/` | quality job | 0700/0600 | Private uv, ruff, mypy and coverage caches and tmp; the gate receipt; pinned offline gate tools | Reused |
| `~/.local/state/collective/heartbeat.json` | heartbeat | 0600 in a 0700 dir | Board: agents, herdr counts, relay, peers, alerts, flex | Rewritten each full sweep |
| `~/.local/state/collective/memory.json` | heartbeat | 0600 | Notice journal (`notices`: at most 128 metadata records, intent/submitted/refused/unknown with held keys; never message bodies), dedup keys, unread/needs ages, ring boot and evicted count, `last_full`, mode | Persists |
| `~/.local/state/collective-plugin/mail-journal.jsonl` | `collective.py` | 0600, one link | intent/submitted/refused/unknown; hashes only | Grows (rotate later) |
| `~/.local/state/collective-plugin/plans/` | senders | 0600 plans in 0700 dirs | Plans **include the body**; deleted after apply by default | Until applied |
| `~/.local/state/collective-plugin/scheduler-backups/` | `install_monitor.py` | 0600 files in 0700 dirs | Per-attempt unit backups and staged units | Keep |
| `~/.local/state/collective-plugin/scheduler-install-receipt.json` | `install_monitor.py` | 0600 | Install receipt: `installing`, `installed` or `rolled-back`, with `previous` = last accepted install | Rewritten per install |
| tuios mail ring | tuios daemon | memory | Messages and threads | **Lost on daemon restart** |
| tuios task cards and pane notes | tuios daemon | session | Intake, claims, `DOING\|NEXT\|BLOCKED` | Survive restart |
| MemPalace hub | MemPalace | — | Durable events and drawers (team reports) | Durable |
| `~/.atuin/data/history.db` | atuin hooks | — | Agent shell commands (author, exit, cwd, intent) | Durable; local only (sync off) |
| `~/src/herdr-collective/` | Claude | — | **Reference only**: collab, herdr-sock, send, the original heartbeat | Not adopted |

## Durable reports in MemPalace

| Drawer | Contents |
|---|---|
| `<mempalace-drawer-1>` | Combined comms-layer report (Codex 2) |
| `<mempalace-drawer-2>` | tuios www and SSH addendum |
| `<mempalace-drawer-3>` | Native herdr and MemPalace findings (Codex 3) |
