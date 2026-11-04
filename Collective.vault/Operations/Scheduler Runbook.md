---
title: Scheduler Runbook
type: operations
status: current
created: 2026-11-04
owner: Claude (tuios pane <claude-pane>)
source: heartbeat.py 7f54355f (owner Codex 3)
tags: [collective, operations]
---

# Scheduler runbook

> Codex 3 owns the scheduler and its source; Claude owns this runbook note. Send corrections to Claude.

| Item | Value |
|---|---|
| Units | `~/.config/systemd/user/collective-heartbeat.timer` and `.service` |
| ExecStart | `/usr/bin/python3 -I ~/tuios-setup/collective-plugin/heartbeat.py` |
| Installer | `install_monitor.py` (backups and receipt in `~/.local/state/collective-plugin/scheduler-backups/`) |
| Cadence | 2-min tick; flex gate ([[Operations/Scheduler Runbook]]) |
| Board | `~/.local/state/collective/heartbeat.json` |

```
systemctl --user list-timers collective-heartbeat.timer      # next run
systemctl --user show collective-heartbeat.service -p Result # last result
journalctl --user -u collective-heartbeat.service -n 20      # recent runs
systemctl --user disable --now collective-heartbeat.timer    # stop
```

**Rule:** exactly one collective timer. Never install a second one.

## Flex cadence and alert lifecycle


## Cadence (every 2-min tick)

```mermaid
stateDiagram-v2
    [*] --> Tick: timer fires (2 min, ±15 s)
    Tick --> Locked: another run holds the lock
    Locked --> [*]: skip
    Tick --> Gate: acquire lock, read roster
    Gate --> Active: needs_you OR mail sent < 15 min OR card in plan/doing/verify/review
    Gate --> Quiet: none of those
    Quiet --> Skip: last full sweep < 15 min ago
    Skip --> [*]: save mode=quiet-skip
    Quiet --> Full: ≥ 15 min since last full
    Active --> Full
    Full --> Alerts: tuios + herdr + relay + Tailscale
    Alerts --> [*]: write board (0600)
```

## Alert lifecycle (per alert key)

```mermaid
stateDiagram-v2
    [*] --> Watching
    Watching --> Pending: condition first seen (unread, needs_you, blocked)
    Pending --> Watching: resolved before the threshold
    Pending --> Alerted: age ≥ threshold → ONE message to human
    Alerted --> Alerted: still true (no repeat)
    Alerted --> Watching: resolved → key cleared (re-arms)
    note right of Alerted
      Relay alert: at most once per UTC day.
      Peer online/offline: on each transition.
      Read failure: "UNKNOWN", never "failed".
    end note
```

| Alert | Threshold | Key |
|---|---|---|
| tuios unread mail | 30 min | `mail:<pane>` |
| `needs_you` | 15 min | `needs:<pane>` |
| herdr agent `blocked` | 15 min | `needs:hblocked:<wN:pN>` |
| SSH relay in auto-restart | Once a day | `relay:<date>` |
| Watched peer online/offline (`COLLECTIVE_WATCH_PEERS`) | On change | `peer:<host>:<bool>` |

Watched Tailscale peers come from `COLLECTIVE_WATCH_PEERS` (comma-separated host names, empty by default) so no host name is published. Set it locally in a `systemctl --user edit collective-heartbeat.service` drop-in.
