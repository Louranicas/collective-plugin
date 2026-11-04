---
title: Collective
type: home
status: current
created: 2026-11-04
owner: Claude (tuios pane <claude-pane>)
tags: [collective, home]
---

# Collective

This is the ongoing reference for the agent collective on Luke's desktop (`<desktop-host>`). The canonical vault is versioned with the code in `~/tuios-setup/collective-plugin/`. **The source governs:** where a note disagrees with the code, the code wins, and the note gets a dated correction.

## Overview

![[Assets/overview.png]]

*Rendered overview (Codex 3; see `Assets/render-receipt.json`). The per-diagram SVGs are in `Assets/`.*

## Map

| Area | Note | Owner |
|---|---|---|
| Overview | [[Communication Map.canvas\|Communication Map (Canvas)]] · [[Assets/overview.png\|overview image]] | Codex 3 |
| Architecture | [[Architecture/Communication layers]] · [[Architecture/Write lifecycle]] · [[Architecture/Runtime and recovery]] | Codex 2 |
| Decisions | [[Decisions/ADR-001 - One collective with explicit effects]] · [[Roadmap]] | Codex 3 |
| Workflow | [[Operations/Reference workflow]]: comms rules ("hive mind mode"), collaboration lifecycle, best-of-N fan-out | Claude |
| Operations | [[Operations/Agent Roster]] · [[Operations/Scheduler Runbook]] · [[Operations/SSH State]] · [[Operations/State and Files]] · [[Operations/Open Decisions]] | Claude |
| Evidence | [[Evidence/Verification]]: 36/36, planted reds, live exchanges, priming | Claude (Codex 2 supplies its receipts) |
| Code docs | `../README.md`, `../DESIGN.md` | Claude |

## Built, running, proposed (2026-11-04)

| Status | Item |
|---|---|
| **Built, frozen** | `collective.py` (fb9d36d2), `heartbeat.py` (7f54355f), `install_monitor.py`, `herdr-plugin.toml` (ebb8ae9f, min 0.9.3, `python3 -I`); 36/36 tests |
| **Running** | `collective-heartbeat.timer`, the one collective timer (2-min flex tick; owner Codex 3); tuios mail lane in daily use (#167 onward) |
| **Live** | Plugin `local.collective` **enabled in tuios and native herdr** (read-only actions verified); public GitHub and GitLab repos with CI-required branch protection; commit/push pending the docs freeze; relay stop awaits Luke's sudo. See [[Operations/Open Decisions]] |
| **Proposed** | tuios host link to the laptop (mail-only); `[hooks]` agent-state → MemPalace adapter; herdr→tuios mail return leg; see [[Operations/Open Decisions]] |

## Start here

1. Read the pane notes and [[Operations/Agent Roster]].
2. Follow [[Operations/Reference workflow]] before writing anything.
3. Check [[Operations/Open Decisions]] for authorised decisions and their owners.
