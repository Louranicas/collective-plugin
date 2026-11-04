---
type: decision
status: accepted-for-prototype
date: 2026-11-04
owner: Codex 3
reviewers: [Codex 2, Claude]
---

# One collective with explicit effects

Return to [[Home]] · [[../Roadmap|Roadmap]] · [[../Communication Map.canvas|Communication Map]]

The collective coordinates several independent agent sessions. It shares evidence and tasks; it does not share an authenticated model identity or obtain new authority from agreement between agents.

The canonical implementation and this vault live together in `/var/home/louranicas/tuios-setup/collective-plugin`. Each file has one writer, with separate test and workflow reviewers. Earlier experiments in `~/src/herdr-collective` remain separate reference artifacts.

## Adopted boundaries

| Concern | Decision | Why |
|---|---|---|
| Default operation | Passive observations and metadata | A status view must not read-acknowledge another agent's inbox or execute its content |
| First write lane | Local tuios mail only, exact plan then explicit digest apply | One reviewable effect with a five-minute lifetime and a one-use journal |
| Collaboration messages | Intent, milestone, blocker, handoff and review carry owner, reviewer, scope, evidence and definition of done | Coordination has a common contract instead of repeated role proposals |
| Native Herdr | Explicit CLI or Unix socket; socket adapter permits only `ping` and `agent.list` | Keep the native daemon distinct from tuios's compatibility shim |
| Evidence store | MemPalace for durable outcomes; this vault for architecture and runbooks | tuios's mail ring and queue disappear with the daemon |
| Atuin | Metadata-first command evidence; scripts remain reviewed procedures | Recorded commands are not authorization or a message-delivery protocol |
| Scheduler | One existing `collective-heartbeat.timer`, adopted into this repository | Preserve alert deduplication and avoid competing jobs |
| Remote transport | Existing SSH team protocol and dated acceptance records govern | Local service activity is not proof of authenticated remote reachability |
| Plugin activation | Explicit review of pinned source, then owner-run registration outside tuios | Plugin code runs with the user's rights; manifest approval does not approve later source edits |

## Write receipt, not a claim of exactly-once delivery

The journal persists intent before submitting one mail request. The same plan cannot be submitted again through that journal. If the transport times out, the outcome is unknown and the operator inspects the inbox before deciding what to do. This prevents blind retries; it does not promise distributed exactly-once delivery.

Pane identity is checked immediately before submission against the current daemon boot, session and reported occupant. This is a preflight, not an atomic daemon-side condition. A digest records review of a particular plan; it is not a secret credential or proof that the human approved it.

## What stays outside this version

No native socket prompt/write method is exposed by the plugin. The separately authorized, labelled Herdr-agent tests exercised native prompts through a diagnostic client and are recorded as test evidence, not as a shipped write feature.

No plugin method changes SSH, credentials, grants, daemon configuration, host links, model sessions or stored Atuin scripts. The scheduler is a passive observer with deduplicated human notices; it does not continue an AI turn.

## Review triggers

Revisit this decision before adding queued prompts, broadcasts, remote writes, MemPalace writes or agent launches. Each needs a concrete effect contract, an owner and reviewer, refusal tests, current runtime schema checks and authority for that effect.
