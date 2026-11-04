---
type: roadmap
updated: 2026-11-04
owner: Codex 3
---

# Roadmap

Return to [[Home]] · [[Decisions/ADR-001 - One collective with explicit effects|Architecture decision]]

## Available now

- A stdlib Python prototype with a passive cross-channel dashboard, inbox metadata, Atuin metadata, MemPalace event metadata and local SSH health.
- Native Herdr's explicit Unix socket read adapter; no confusion between UUID pane addresses and native `wN:pN` addresses.
- Local tuios mail plans with exact payload binding, expiry, live-peer preflight, a private intent journal, concurrent replay refusal and unknown-outcome handling.
- Structured collaboration plans for intent, milestones, blockers, handoffs and review.
- One active systemd user timer. It ticks every two minutes, does full checks during active collaboration, and reduces full checks to fifteen-minute intervals when quiet.
- Independent tests, planted negative controls, live tuios mail/reply evidence and labelled Herdr-agent response evidence.

## Operator choices and unavailable routes

| Item | State | Next evidence needed |
|---|---|---|
| Plugin registration and dashboard pane activation | Source prepared; not registered or enabled | Owner reviews source and uses outside-tuios registration flow in the project design |
| Local baseline commit | Not created; changes prepared for review | Explicit commit authority under the user-requested volition guidance |
| Push or publication | Not requested | Explicit destination and authority |
| Native desktop/laptop tuios link | No configured tuios host | Peer online, endpoint verification, owner-approved per-side policies, traffic and refusal tests |
| Independent offsite SSH relay | Unqualified; local retry behavior observed | Current provider/route investigation and genuine independent end-to-end tests |
| Atuin scripts | Library was empty during the survey | Review a concrete procedure before creating or running it |
| Atuin threads/output/MCP registration | Capabilities surveyed; capture disabled and no registered Atuin MCP in this session | Separate configuration decision and current acceptance tests |

## Potential next increments

1. Improve the dashboard's interactive presentation without widening effects.
2. Add explicit per-session identities and independent MemPalace watcher state, after reconciling the existing shared identity protocol.
3. Add reliable resumable event observation using the correct daemon's cursor and gap semantics.
4. Evaluate a separate native Herdr write lane, if requested, with plan-bound occupant checks and no prompt/draft bypass.
5. Use tuios best-of-N worktrees for a substantial design choice after a committed, clean base and an agreed acceptance test exist. Preserve candidate evidence before cleanup.

These are planned possibilities, not background tasks or permission to act. Update this note when a current receipt changes their status.
