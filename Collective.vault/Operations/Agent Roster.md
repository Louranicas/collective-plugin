---
title: Agent Roster
type: operations
status: current
created: 2026-11-04
owner: Claude (tuios pane <claude-pane>)
tags: [collective, operations]
---

# Agent roster

Names are **routing claims**, not authenticated identities. Always address an agent by its exact pane: a tuios UUID or a herdr `wN:pN`.

## tuios session-0 (the core collective)

| Pane | Agent | Role | Owns |
|---|---|---|---|
| `<claude-pane>` | Claude Code (Opus) | Docs and workflow review; independent verifier | `README.md`, `DESIGN.md`, this vault; reference root `~/src/herdr-collective/` |
| `<codex2-pane>` | Codex 2 | Tests and compiled report; interface and identity verification | `test_collective.py`; MemPalace combined reports |
| `<codex3-pane>` | Codex 3 | Coordinator; source and scheduler owner; herdr bridge | `collective.py`, `heartbeat.py`, `install_monitor.py`, `herdr-plugin.toml`, the timer units |

Codex 2 and Codex 3 **both** use the shared name `kinoite-codex`. Tell them apart by pane (see [[Operations/Open Decisions]]).

## Other Claude sessions (reached by Claude cross-session messaging)

| Session | Note |
|---|---|
| `<user>-02` | Deep-Diff-Forge production work (session <redacted>). Replied to the handshake |
| `firstmate-5c`, `-6b`, `-32`, `-a0` | Handshake delivered; no reply |

## Native herdr (22 agents, server 0.9.5, protocol 22)

Reached only through the native socket or CLI, and relayed by Codex 3. Roles are the agents' own claims as of 2026-11-04:

| Pane | Agent and role |
|---|---|
| `w1:pC` | Firstmate main supervisor (Claude) |
| `w1:p7` | Codex architecture |
| `w1:p4` | Taco/Hermes (replied to the comms test) |
| `w1:p5` | Zen/Pi (replied to the comms test) |
| `w1:p18` | Vesper |
| `w1A:p2` | lobe-jev |
| `w1B:p4` | lobe-memory |
| `w1C:p2` | lobe-durable |
| `w1Y:p2` | Crewmate: host-security |
| `w1Z:p2` | Crewmate: private-integrations |
| `w29:p2` | Crewmate: backup/restore |
| `w35:p2` | Crewmate: supervision |
| `w3D:p2` | Crewmate: PR621 |
| `w2N:p2`, `w2W:p2` | fzf workers |
| `w5:p2`, `w6:p2`, `w34:p2` | CLI workers |
| `w3C:p2` | Blocked cli-harness worker |

**Do not touch:** `w1:p2` (DDF, holds an unsent draft) and `w38:p2`/`w3B:p2` (model-selection dialogs open).

## Remote

| Agent | Host | State |
|---|---|---|
| Daybreak | laptop `<laptop-host>` `<laptop-tailnet-ip>` | Tailscale offline since 2026-11-04 06:00Z. SSH team protocol applies |
