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
| Evidence | [[Evidence/Verification]]: canonical gate results, dated 36/36 baseline, planted reds, live exchanges, priming | Claude (Codex 2 supplies its receipts) |
| Code docs | `../README.md`, `../DESIGN.md` | Claude |

## Built, running, proposed (2026-11-04)

| Status | Item |
|---|---|
| **Built, frozen** | `collective.py` (fb9d36d2), `heartbeat.py` (7f54355f), `install_monitor.py`, `herdr-plugin.toml` (ebb8ae9f, min 0.9.3, `python3 -I`); 36/36 tests at that freeze (dated); current proof is `python3 -I tools/check.py`, see the "Current acceptance receipt" section of [[Evidence/Verification]] |
| **Installed** | One `collective-heartbeat.timer` (2-min active tick, 15-min quiet full check). It was paused while faults were corrected, then reinstalled and observed active after validated code acceptance. Query current state with `systemctl --user is-active collective-heartbeat.timer`; see dated evidence in [[Evidence/Verification]] |
| **Live** | Plugin `local.collective` **enabled in tuios and native herdr** (read-only actions verified). Public repos with CI-required branch protection. **GitHub:** source on `feat/collective-comms` (PR #1; the reviewed commit passed CI on 3.12/3.13/3.14; later fix commits need their own CI). **GitLab:** query the current mirror/main state rather than infer it from an earlier receipt. Check current state live: `gh pr view 1 -R Louranicas/collective-plugin`, `gh run list -R Louranicas/collective-plugin`, `git ls-remote` on each remote |
| **Demonstrated (diagnostic)** | herdr→tuios mail return leg: a native Pi agent (route redacted) sent a matching diagnostic return token, witnessed by Codex 3 (`proof/native-return.json`); unauthenticated sender, one exchange |
| **Proposed** | tuios host link to the laptop (mail-only); `[hooks]` agent-state → MemPalace adapter; see [[Operations/Open Decisions]] |

## Start here

1. Read the pane notes and [[Operations/Agent Roster]].
2. Follow [[Operations/Reference workflow]] before writing anything.
3. Check [[Operations/Open Decisions]] for authorised decisions and their owners.

## Closure: 2026-11-05 (dated; supersedes earlier status rows above)

| Status | Item |
|---|---|
| **Released** | `local.collective` on GitHub `Louranicas/collective-plugin` and GitLab `lukeomahoney/collective-plugin`. `main` = `f21a331` (one squashed release commit) on both. CI is green on Python 3.12/3.13/3.14 on both, and merges require the gates. Only `main` remains on each remote |
| **Running** | Plugin enabled in tuios and native herdr. `collective-heartbeat.timer` is active; a local drop-in sets the watched peer and the session |
| **SSH** | The offsite relay clients were **disabled by Luke** (sudo) after about 9,050 failed restarts. Native recovery sshd is unaffected. Codex 3 recorded the change in SSH.vault (tuios #447) |
| **Open** | No task cards. Follow-up candidates only; see [[Operations/Open Decisions]] |

Check the current state live: `git ls-remote` on each remote, `gh run list -R Louranicas/collective-plugin`, `systemctl is-enabled ssh-independent-relay-machine-tunnel.service`. Full evidence: [[Evidence/Verification]].
