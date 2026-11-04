---
title: Open Decisions
type: operations
status: current
created: 2026-11-04
owner: Claude (tuios pane <claude-pane>)
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
| D5 | Optional builds | Not authorised; still open | tuios host link to the laptop (mail-only); `[hooks]` agent-state → MemPalace adapter; atuin daemon/thread capture |

Outcomes are recorded in [[Decisions/ADR-001 - One collective with explicit effects]] (Codex 3).

## Status update: 2026-11-04 (supersedes the "In progress" column above; verified by Claude)

| # | Status | Evidence |
|---|---|---|
| D1 | **Repos public, protected; local baseline and review fix commits exist; source push pending** the outer test, document, lint, push, PR and CI steps (only an empty bootstrap is pushed) | GitHub `Louranicas/collective-plugin`: branch protection on `main` is strict, requires `gates (3.12)`, `gates (3.13)` and `gates (3.14)`, enforce_admins on. GitLab `lukeomahoney/collective-plugin`: public, `only_allow_merge_if_pipeline_succeeds`, `main` push limited to Maintainers. Scan PASS |
| D2 | **Done** | tuios `local.collective` **on** from the reviewed manifest (sha `ebb8ae9f`); herdr `local.collective` **enabled**. Read-only `capabilities` and dashboard actions exit 0 in both runtimes (`proof/plugin-activation.json`). No startup or event hooks |
| D3 | **Waiting on Luke's sudo** | The relay stop needs a password; agents refused to bypass it. The units are still in auto-restart |
| D4 | **Done (metadata)** | Codex 3 = `kinoite-codex`, sole desktop SSH writer; `collective-codex2`, `collective-claude` aliases. The aliases are not authentication and do not fix shared-name watcher suppression |

## Publication snapshot: 2026-11-05 before main merges (supersedes the D1 row above)

| Item | Recorded fact at this snapshot | Live check |
|---|---|---|
| D1 publication | Source is **pushed to GitHub** `feat/collective-comms` with PR #1. CI for the reviewed commit passed on 3.12/3.13/3.14; the newer fix commit awaits its own CI. GitLab still holds only the bootstrap commit | `gh pr view 1 -R Louranicas/collective-plugin`; `gh run list -R Louranicas/collective-plugin` |
| GitLab `main` protection | push **No one**, merge Maintainers, force-push off; merge only if the pipeline succeeds | `glab api projects/lukeomahoney%2Fcollective-plugin/protected_branches` |
| D5 return leg | Removed from optional builds: demonstrated as a diagnostic (#288, `proof/native-return.json`) | — |

## Closure: 2026-11-05 (dated; all D1–D4 resolved)

| # | Outcome | Verified by |
|---|---|---|
| D1 | **Released.** PR #1 squash-merged; `main` = `f21a331` on GitHub and GitLab (MR !1). CI green on both. Feature and release branches deleted by Luke; both remotes are `main`-only | Claude (tree equal to the reviewed `a697ab8`; fresh clones pass 9/9 gates, 107 tests), Codex 2 |
| D2 | **Done.** Plugin enabled in tuios and native herdr | Codex 3 (`proof/plugin-activation.json`), Claude |
| D3 | **Done.** Luke ran `sudo systemctl disable --now` on both relay units; they are disabled and inactive, and `sshd-native-recovery` is still active. Re-enable only after the relay path is repaired | Claude, Codex 2; SSH.vault record by Codex 3 (#447) |
| D4 | **Done (metadata).** Codex 3 = `kinoite-codex`, the sole desktop SSH writer; aliases `collective-codex2` and `collective-claude` | — |

**Accepted residual (low):** GitHub's PR #1 refs still hold the early commits containing pane IDs and the local username (no credentials). `main`'s history is clean.

**Follow-up candidates (not authorised, not started):**

1. A heartbeat alert when a pane has unread mail **and** `draft_held` for more than 60 minutes ("wake blocked by draft").
2. Report upstream that tuios's `draft_held` is a false positive on the empty "Ask Codex to do anything" placeholder. It blocked both Codex panes' mail-wake for about 7 hours on 2026-11-05.
3. Stale daemon-owned queue items `q2`/`q7` can only be removed by Luke, from outside a pane (`tuios queue rm`). They are harmless.
