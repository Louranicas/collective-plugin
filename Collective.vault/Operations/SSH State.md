---
title: SSH State
type: operations
status: current
created: 2026-11-04
owner: Claude (tuios pane <claude-pane>)
source: SSH.vault/Operations + live read 2026-11-04
tags: [collective, operations]
---

# SSH state (cross-machine)

> Addresses are redacted for publication. Real endpoints, pins and keys live only in the private `SSH.vault` under the SSH team protocol.

```mermaid
flowchart LR
    subgraph Desktop["<desktop-host> <desktop-tailnet-ip> / <desktop-lan-ip>"]
        KC["kinoite-codex<br/>(desktop SSH owner)"]
        SN["sshd-native-recovery<br/>:22 LAN + loopback · active"]
        RT["relay-machine-tunnel/connector<br/>auto-restart ~8.7k ×"]
    end

    subgraph Laptop["<laptop-host> <laptop-tailnet-ip> / <laptop-lan-ip>"]
        DB["Daybreak<br/>(laptop owner)"]
        CD[("~/.local/state/ssh-hardening/<br/>coordination/")]
    end

    VPS["VPS relay<br/><relay-vps>:<port>"]

    KC ==>|"Tailscale SSH (PASS 10-25)<br/>now: laptop offline"| DB
    SN <-->|"native LAN SSH both ways<br/>(PASS 10-25, historical)"| Laptop
    RT -.->|"timeout: SYNs never arrive<br/>cause unresolved"| VPS
    KC -->|atomic 0600 messages| CD

    linkStyle 2 stroke:#c00,stroke-dasharray:4
```

| Path | Recorded | Now (2026-11-04) |
|---|---|---|
| Tailscale SSH desktop→laptop | PASS 2026-10-25 | Laptop offline since 06:00Z |
| Native LAN, both ways | PASS 2026-10-25 (historical) | Desktop listener active; laptop untestable |
| Offsite relay | Design deployed; public path times out | Units restart-looping (alert in the heartbeat) |
| tuios host link | Not configured | Proposed, mail-only, needs Luke + both SSH owners |

The **SSH team protocol** (CLAUDE.local.md and SSH.vault) governs. This vault only reports SSH state. The D3 relay stop is authorised but awaits Luke's `sudo`; D4 is done in metadata only. See [[Operations/Open Decisions]].
