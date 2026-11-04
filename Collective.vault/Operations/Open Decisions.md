---
title: Open Decisions
type: operations
status: current
created: 2026-11-04
owner: Claude (tuios pane 08651035)
tags: [collective, operations]
---

# Decisions: authorised by Luke 2026-11-04

> **Luke, verbatim:** "Team requests 1. through 4. have full authorisation and you are authed to create a public repo on github and hitlab proceed seamlessly". "hitlab" is read as GitLab.
>
> Codex 3 is the single owner of publication, activation and desktop-SSH effects (#250). Cards t8–t11 track the work. Nothing below is blocked on Luke any more, except an effect that needs his password (`sudo`) or a terminal outside tuios.

| # | Decision | Status | Owner and gates |
|---|---|---|---|
| D1 | **Commit, then publish public repos** on GitHub (`Louranicas`) and GitLab (`lukeomahoney`) | **Authorised.** In progress (t8) | Codex 3 publishes. Gate: Claude's pre-publish scan finds no secrets; infrastructure IPs redacted in Claude's notes; one SVG to re-render. After push, Codex 2 verifies a clean clone |
| D2 | **Register the plugin** | **Authorised.** In progress (t9) | Codex 3. Native `herdr plugin link`/`enable`. tuios `link`/`info`/`approve`/`enable` is documented as outside-tuios only; if refused in a pane, no bypass: Luke runs the exact command |
| D3 | **SSH relay retry loop** | **Authorised.** Codex 3's choice: **stop** the unqualified relay clients until repaired, preserving native, Tailscale and recovery paths (t10) | Codex 3 as desktop SSH writer. System units need `sudo`, which requires a password, so Luke runs the exact command. Recorded in SSH.vault |
| D4 | **Shared `kinoite-codex` name** | **Authorised.** Proposal (#250): Codex 3 keeps `kinoite-codex` as sole desktop SSH writer; session aliases `collective-codex2` (Codex 2) and `collective-claude` (Claude) in coordination metadata (t11) | Each agent changes only its own metadata. Governing AGENTS and SSH protocol blocks are untouched. Changing a MemPalace `from_agent` needs an explicit note under this authority |
| D5 | Optional builds | Not authorised; still open | tuios host link to the laptop (mail-only); `[hooks]` agent-state → MemPalace adapter; herdr→tuios mail return leg; atuin daemon/thread capture |

Outcomes are recorded in [[Decisions/ADR-001 - One collective with explicit effects]] (Codex 3).

## Status update: 2026-11-04 (supersedes the "In progress" column above; verified by Claude)

| # | Status | Evidence |
|---|---|---|
| D1 | **Repos public, protected; commit and push pending** (Codex 3, after the docs freeze) | GitHub `Louranicas/collective-plugin`: branch protection on `main` is strict, requires `gates (3.12)`, `gates (3.13)` and `gates (3.14)`, enforce_admins on. GitLab `lukeomahoney/collective-plugin`: public, `only_allow_merge_if_pipeline_succeeds`, `main` push limited to Maintainers. Scan PASS |
| D2 | **Done** | tuios `local.collective` **on** from the reviewed manifest (sha `ebb8ae9f`); herdr `local.collective` **enabled**. Read-only `capabilities` and dashboard actions exit 0 in both runtimes (`proof/plugin-activation.json`). No startup or event hooks |
| D3 | **Waiting on Luke's sudo** | The relay stop needs a password; agents refused to bypass it. The units are still in auto-restart |
| D4 | **Done (metadata)** | Codex 3 = `kinoite-codex`, sole desktop SSH writer; `collective-codex2`, `collective-claude` aliases |
