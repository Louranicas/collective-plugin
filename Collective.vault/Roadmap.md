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
- One systemd user timer, installed and enabled. It was paused by root during the hardening pipeline and observed active again after host acceptance on 2026-11-05 ([[Evidence/Verification]]). Check with `systemctl --user is-active collective-heartbeat.timer`. When running it ticks every two minutes, does full checks during active collaboration, and reduces full checks to fifteen-minute intervals when quiet.
- Independent tests, planted negative controls, live tuios mail/reply evidence and labelled Herdr-agent response evidence.

## Operator choices and unavailable routes

| Item | State | Next evidence needed |
|---|---|---|
| Plugin registration (D2) | Enabled in tuios and native herdr; read-only capabilities and dashboard actions passed in both (`proof/plugin-activation.json`) | Re-register after any manifest change; check with `tuios plugins info local.collective` and `herdr plugin list` |
| Local baseline commit (D1) | Created; the review-pipeline fix commits follow it | Current proof: the current acceptance receipt in [[Evidence/Verification]] |
| Push or publication (D1) | Authorised. Public GitHub and GitLab repos exist with merge checks configured; at the 2026-11-05 snapshot the source was on GitHub `feat/collective-comms` (PR #1, draft) and GitLab held only the bootstrap; see [[Operations/Open Decisions]] and the live checks below | The source candidate passes the outer test, document, lint, push, PR and CI steps; no remote CI result is claimed here |
| Unqualified relay stop (D3) | Authorised; blocked on the owner's `sudo` password, which agents do not bypass | Luke runs the exact command |
| Shared `kinoite-codex` name (D4) | Done in coordination metadata only | Aliases do not fix shared-name watcher suppression; address agents by pane |
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


## Live publication and runtime checks

Earlier build-stage rows are dated snapshots. Query the current accepted heads and pipeline status in the [GitHub repository](https://github.com/Louranicas/collective-plugin) and [GitLab mirror](https://gitlab.com/lukeomahoney/collective-plugin); use `git ls-remote <remote> refs/heads/main` and the hosts' CI views. Current source-bound local measurements and dated host acceptance are in [[Evidence/Verification]]. The code and reviewed mail path are implemented; publication uses protected main branches. The SSH relay stop still needs local owner authentication.
