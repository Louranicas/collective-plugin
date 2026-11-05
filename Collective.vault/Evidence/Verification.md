---
title: Verification
type: evidence
status: current
created: 2026-11-04
owner: Claude (tuios pane <claude-pane>)
verifier: Claude (<claude-pane>); builder Codex 3; tester Codex 2
tags: [collective, evidence]
---

# Verification

## Receipt 2026-11-04 (Claude, independent verifier; historical, superseded by the current acceptance receipt below)

**Subject:** the frozen working tree `~/tuios-setup/collective-plugin/`, uncommitted. sha256 prefixes:

| File | sha256 prefix |
|---|---|
| `collective.py` | `fb9d36d2` |
| `heartbeat.py` | `7f54355f` |
| `test_collective.py` | `5f899b49` |
| `herdr-plugin.toml` | `ebb8ae9f` |

| Check | Command or method | Result |
|---|---|---|
| Baseline suite | `python3 -I -m unittest discover -s . -p 'test_*.py' -q` | **36 tests OK** (matches Codex 2) |
| Planted: digest compare disabled | Scratch copy, `if False:` | **FAIL** `test_wrong_confirmation_refused` |
| Planted: one-use journal disabled | Scratch copy | **FAIL** ×4: replay, process race, same nonce with a different payload, and one more |
| Planted: owner ≠ reviewer disabled | Scratch copy | Survived. It is an **equivalent mutant**, because `make_mail_plan` also refuses self-messaging; disabling both fails 2 tests |
| Manifest | read | `python3 -I`, `min_herdr_version = "0.9.3"` |
| Live write lane | #167 (Codex 3 → Claude) | Arrived, threaded; replay refused |
| Live preset | #199 handoff via `collaboration-plan` | `submitted`; plan removed |
| Native herdr exchange | Codex 3 prompted `w1:p4` and `w1:p5` | Tokens `COLLECTIVE-TACO-20261104` and `COLLECTIVE-ZEN-20261104` read back (Codex 2 verified independently) |

**Not covered:**
- Plugin registration (D2).
- The herdr→tuios mail return leg.
- Cross-machine paths.

Optional hardening for Codex 2: assert the specific error text in the self-review test.

## Priming applied

The team primed on Luke's being files and applies their transferable rules: intent before effect, bounded reads, planted red before trusting green, independent review, BLOCKED named early, no commit without named authority. No HEE gate claims are made for this Python project.

- `/var/mnt/storage/hee5-evidence/hee-v5-motivation/.claude/being/motivation.md`
- `/var/mnt/storage/hee5-evidence/hee-v5-motivation/.claude/being/volition.md`
- `/var/mnt/storage/hee5-evidence/hee-v5-motivation/.claude/being/top-tail-performance.md`

## Codex 2 receipts

Codex 2's independent negative-control receipt and artifact ids are appended here as a dated row when sent (Claude writes; Codex 2 supplies).

| Date | Verifier | Subject | Result | Artifacts |
|---|---|---|---|---|
| 2026-11-04 | Codex 2 (<codex2-pane>), independent of the builder | Code: `collective.py` fb9d36d2, `heartbeat.py` 7f54355f, `test_collective.py` 5f899b49 | Malformed-shape test **seen red** (messages #193/#195), then green: **36 PASS** | Test-patch correlation `collective-plugin-tests-20261104`; MemPalace verification drawer `<mempalace-drawer-id>` |
| 2026-11-04 | Codex 2 | This vault at the time of the check | 13 Markdown notes; **12/12** Mermaid blocks render with `tuios mermaid`; **54** local and wiki links resolve, 0 broken; Canvas JSON ids unique, edges valid; 12 SVGs parse as XML | Reported in tuios #238 |

> Counts are point-in-time. Claude's #233 figure ("14 notes + canvas") and Codex 2's 13 differ only by counting method and date. Cite the dated row, not a hard-coded total.

## Hardening round: "make it really hard to write bad code" (2026-11-04)

Luke, verbatim: "team keep working until the full end to end stack of your amazing project is complete ensure all testing (maintain conventions and standards) alongside security hardening are completed to the highest level you can achieve iterate as indicated and test present proof … MAKE IT REALLY HARD TO WRITE BAD CODE".

| Gate (one command: `python3 -I tools/check.py`) | Baseline (frozen 36-test tree) | Latest measured |
|---|---|---|
| ruff, `select = ALL` minus documented ignores | 371 (strict set) / 1001 (ALL) | **0** in all source modules; tests lint-clean |
| mypy `--strict` + extra codes | 156 | **0** in source and tools; test files still being typed (Codex 2) |
| bandit, medium or higher | 0 | **0** |
| Branch coverage (`fail_under = 90`) | 48% | **≥ 90% PASS** (core about 92%, heartbeat about 87%, installer about 85%; Codex 2) |
| Tests | 36 | **75+** |
| Fitness F1–F5 (AST architecture rules) | — | **PASS**. The selftest proves every rule fires on a planted snippet; a checker with a rule removed went RED |
| Hygiene (publish-set secrets and IPs) | IPs in 4 files | **PASS** (redacted notes, re-rendered SVG, generic public-IPv4 rule) |
| `systemd-analyze --user security collective-heartbeat.service` | **9.2 UNSAFE** | **0.6** (scheduler-hardening helper) |

### collective.py typing pass (Claude; behaviour proven unchanged)

- The same test files were run against the original and the typed module at each step. The failure sets were identical; only timing differed.
- Intentional behaviour change, requested by owner Codex 3 (#282): after dispatch, malformed or non-object replies are **unknown**, not refused.
- Frozen at sha256 `95a96488324e5e7eb4a98b68727615bd791b7362b4bb7a0442db718fa10cc749`. Ownership returned to Codex 3.

### Planted red on the final core (12 plants)

| Result | Plants |
|---|---|
| **Killed (9)** | digest compare; one-use journal; bidi guard; receipt check; socket allowlist; TTL; peer UID; rate limit; boot-id race |
| **Survived (3), assigned to Codex 2 as test gaps** | output cap; unknown classification; symlinked state directory (not equivalent: a symlink to an owned 0700 directory would be accepted) |

### Guards observed refusing real mistakes during this session

- The 8 KiB body guard refused a message bloated by an accidental shell expansion.
- The bidi guard refused a message that carried a literal U+202E.
- The hygiene gate caught infrastructure IPs in a rendered SVG.

### Comms limit observed

The tuios mail ring (256 messages / 512 KiB) overflowed repeatedly: more than 100 unread messages were evicted across the session. Durable outcomes therefore live in MemPalace and this vault, never in mail alone.

### Final verification: all gates green (Claude, independent, 2026-11-04)

**Subject:** gate receipt tree sha256 `2ad4d15904d5890b…`. File sha8:

| File | sha8 |
|---|---|
| `collective.py` | `95a96488` |
| `heartbeat.py` | `9b4059cb` |
| `install_monitor.py` | `9680820b` |
| `test_collective.py` | `610287fb` |
| `test_hardening.py` | `301d6c13` |
| `tools/check.py` | `52a73a6c` |
| `pyproject.toml` | `905c194e` |

| Gate | Result |
|---|---|
| selftest · hygiene · fitness · format · lint · types · security · tests · coverage | **ALL PASS** (`python3 -I tools/check.py --keep-going`) |
| Tests | **82 OK** |
| Branch coverage | **93%** overall: `collective.py` 93%, `heartbeat.py` 93%, `install_monitor.py` 96% |
| Planted red (12) | **12/12 KILLED**: digest, journal (14 tests), bidi, receipt, output cap, socket allowlist, TTL, peer UID, unknown classification, rate limit, boot-id race, symlink dir |
| systemd exposure | **0.6 SAFE** (was 9.2 UNSAFE) |

**Not yet proven:**
- CI on the remotes: there are no commits pushed yet.
- Branch protection: not installed.
- Plugin registration.
- The relay stop (needs Luke's sudo).
- The herdr→tuios mail return leg.

### Superseding facts, verified by Claude later on 2026-11-04 (the "not yet proven" list above is history)

| Claim | Verified how | Result |
|---|---|---|
| Plugin registration | `tuios plugins info local.collective`; `herdr plugin list` | **On / enabled**, manifest `ebb8ae9f`. Read-only actions exit 0 (`proof/plugin-activation.json`) |
| GitHub branch protection | `gh api …/branches/main/protection` | strict; checks `gates (3.12/3.13/3.14)`; enforce_admins **true** |
| GitLab | `glab api projects/…` | public; merge only if pipeline succeeds; `main` push limited to Maintainers |
| Timer sandbox | `proof/runtime-sandbox.json` (Codex 3 / helper) | no_new_privileges, inet socket refused, home write refused, state writable. Its limits: no user-level IP firewall; named refusals only |
| herdr→tuios return leg | Reported by Codex 3 (#288, native Pi agent → tuios mail) | Reported; Claude did not re-verify (the message was evicted from the ring before it was read) |

**Finding (low):** `~/.local/state/collective-plugin/sandbox-proof-receipt.json` is mode 644, and `plugin-activation-backups/` and `scheduler-backups/` are 755. That contradicts the private-state contract (0600/0700). Mitigated by the parent `~/.local/state` being 700. Sent to the owner.


### Root final local acceptance, 2026-11-04

The low private-directory finding above is corrected: existing private proof/backup modes were repaired to 0600/0700. A new behavioral regression first failed on a newly created intermediate directory (0755), then passed after `private_dir` created each missing ancestor privately while preserving existing ancestor modes. The suite now contains **83 tests**; all nine local gates pass. Earlier source hashes and mutation counts remain dated receipts, not claims about later revisions.

`proof/native-return.json` retains the selected message #288 metadata witnessed by Codex 3, with pane, user, timestamp and MemPalace event identifiers replaced by placeholders for publication, and a fresh native terminal readback. The mail carried no authenticated sender. `proof/plugin-activation.json` records successful capabilities **and dashboard** actions in both runtimes; roster, Atuin, MemPalace and local SSH observations returned successfully. `proof/runtime-sandbox.json` records named kernel refusal probes and the timer/service acceptance.

The public source candidate still requires the independent no-mistakes pipeline and remote CI; local green checks are not a claim that remote validation has run.

Publication redaction (2026-11-04): pane UUIDs, host names, the local user name, absolute home paths, session and MemPalace identifiers were replaced with placeholders across the vault, docs and proof. `ssh-state-1.svg` was re-rendered from the redacted `Operations/SSH State.md` with `tuios mermaid "Operations/SSH State.md" --diagram 1`, and `Assets/render-receipt.json` binds that output. Re-running `tuios mermaid <source> --diagram <n>` for all 12 receipt rows reproduces every recorded SVG sha256 byte for byte. Redacted fields appear as labelled placeholders (for example `<laptop-host>`), not as substituted identifiers; the private original receipts are kept locally and are not published. The redaction commit does not rewrite earlier commits, so identifiers from before the redaction remain in this branch's history (`be90af1`) until that history is rewritten or left unpublished.

### Current acceptance receipt, 2026-11-04 (supersedes the 82- and 83-test counts above)

> Superseded on 2026-11-05 by [Soak and release acceptance: 26a2ae11](#soak-and-release-acceptance-26a2ae11-2026-11-04t2303z-to-2026-11-05t0013z) (237 tests, 11 gates). The source hashes and counts below are historical.

Measured 2026-11-04T13:27:43Z (UTC; Australia/ACT is the following calendar day). This is the current local source-bound receipt. Earlier 82-, 83-, 98- and 101-test records are historical snapshots. A later source or test edit requires fresh validation.

| File | sha256 prefix (16 hex) |
|---|---|
| `collective.py` | `e0f839049bd9532e` |
| `heartbeat.py` | `04e66690a95ba215` |
| `install_monitor.py` | `d4c1a9d8a595e818` |
| `test_collective.py` | `d983994f52b30d04` |
| `test_hardening.py` | `09e4259a2073ed43` |
| `tools/check.py` | `22d4b4f3ff3dc9c5` |
| `pyproject.toml` | `905c194eaf63ce7c` |

| Gate | Result |
|---|---|
| Canonical nine gates | **ALL PASS**: `python3 -I tools/check.py --keep-going` |
| Tests | **107 OK**: 36 in `test_collective.py`, 71 in `test_hardening.py` |
| Branch-instrumented coverage, pinned coverage 7.17.1 | **94%** aggregate; core **94%**, heartbeat **94%**, installer **95%**; aggregate and every production module meet the 90% floor |
| New delivery controls | Whole-alert UTF-8 batching retains its footer and drains omitted alerts on later sweeps. Only included alerts are acknowledged. Ambiguous process exits/error envelopes journal **unknown** and cannot replay; documented request refusals remain **refused**. |

The two delivery defects were independently reproduced against the previous public draft revision, with temporary effects and mocked notification transport. The follow-up adds those behavioral regressions plus a malformed/error-code matrix. No source-text assertions substitute for those effects.

The `collective.py` hash above includes two later changes. First, wording only: shared tool-failure, timeout and output-limit messages read "outcome unknown" because read-only commands share that transport path (measured then at 101 OK). Second, the mail write-phase boundary: only a failure to launch the process is **refused** ("Command unavailable"); any I/O, selector or cleanup failure after the child starts is **unknown** and cannot replay. Once submission is attempted, `mail-apply` says the mail may already be delivered, to inspect the recipient inbox before any new plan and never resend blindly. If final journal recording fails, the delivery result is still reported (an acknowledged receipt stays `submitted` with a `journal` note) and the consumed intent still refuses replay. `MailWritePhaseBoundary` covers these with a real child that writes an effect marker before an injected post-readiness selector failure, plus injected journal failures; five of its six tests failed on the previous revision.

**Release state at this measurement:** the prior revision `ed065371` passed the first pipeline and GitHub's Python 3.12/3.13/3.14 CI, but PR #1 remains **draft**. These follow-up hashes still require a new full pipeline and remote CI before merge/deployment. GitLab main still contains only the empty bootstrap. The heartbeat timer is paused during hardening; the plugin remains registered. Earlier commits retain nonsecret diagnostic labels and test routing identifiers; no history-scrub claim is made.

### Historical 98-test acceptance before the delivery follow-up

This was the accepted local snapshot before the delivery follow-up; it is retained as dated history. The 82- and 83-test entries above are dated history. This receipt binds to the source files below; any later edit to them invalidates it until the gate is re-run.

**Subject:** file sha256 prefixes (16 hex):

| File | sha256 |
|---|---|
| `collective.py` | `960760aea9ff6334` |
| `heartbeat.py` | `34582f51fd957364` |
| `install_monitor.py` | `d4c1a9d8a595e818` |
| `test_collective.py` | `d983994f52b30d04` |
| `test_hardening.py` | `63210472708fe19f` |
| `tools/check.py` | `22d4b4f3ff3dc9c5` |
| `pyproject.toml` | `905c194eaf63ce7c` |

| Gate | Result |
|---|---|
| selftest · hygiene · fitness · format · lint · types · security · tests · coverage | **ALL GATES PASS**: all 9 (`python3 -I tools/check.py --keep-going`, exit 0) |
| Tests | **98 OK**: 36 in `test_collective.py`, 62 in `test_hardening.py` (`coverage run -m unittest discover -s . -p 'test_*.py'`) |
| Branch coverage (`coverage==7.17.1`, `branch = true`) | **94%** aggregate: `collective.py` 93%, `heartbeat.py` 94%, `install_monitor.py` 95%. Every production module is above the 90% floor |

**Limitations:** this is a local run. The source is not yet pushed to either public repo (only an empty bootstrap is), and the heartbeat timer is paused during hardening. The tool environment was redirected to temporary uv cache and tool directories, because the sandbox mounts the user's uv directories read-only; the pinned tool versions were unchanged. The planted-red mutation count was not re-run for this receipt beyond what the gates themselves execute. Remote CI results are recorded by the pipeline, not here. History is not scrubbed: identifiers from before the redaction remain in `be90af1`.

### Correction 2026-11-05 (dated; earlier rows are history)

- GitLab `main` protection now reads push **No one**, merge Maintainers, force-push off. This supersedes "push limited to Maintainers" above.
- For current counts and hashes, cite the latest receipt rather than any figure in this note: `python3 -I tools/check.py --keep-going --receipt R.json`, the CI run for the head SHA, and Codex 2's review artifacts.
- The "Historical 98-test acceptance" sentence "the source is not yet pushed to either public repo" was true when that receipt was measured. That receipt's hashes (`collective.py` `960760ae`, `test_hardening.py` `63210472`) match revision `ed065371`. The sentence was later superseded when `ed065371` was pushed to GitHub (`feat/collective-comms`, PR #1) and passed CI; GitLab held only the bootstrap.

### Host acceptance of code revision `42bf838` (2026-11-05 Australia/ACT)

This is a dated code/runtime receipt, independent of later documentation edits. GitHub CI run [41839937370](https://github.com/Louranicas/collective-plugin/actions/runs/41839937370) passed the 3.12, 3.13 and 3.14 jobs for this revision. Both independent reviewers accepted fresh anonymous clones and replayed the original delivery regressions.

- Real tuios mail: a private reviewed plan was submitted once, a matching single threaded peer token was read back, and consumed-plan replay returned exit 2. The private journal contains one intent and one submitted outcome. Routing evidence only; sender claims are not authentication.
- Actual hardened user service: install returned `installed`, service `Result=success`, `ExecMainStatus=0`, and the one timer was active. The local watched-peer configuration is private, outside the repository.
- Actual systemd deadline probe: a controlled dependency sleeping 120 seconds was run through the heartbeat CLI in a separate state directory with the same sandbox template. The service finished successfully in **66.21 seconds**, wrote its durable board and explicitly reported UNKNOWN; the notification attempt recorded failure rather than success. The temporary unit and hanging executable were removed.
- The named kernel refusal probe and static 0.6 exposure score in `proof/runtime-sandbox.json` apply to the unchanged sandbox template; this does not claim arbitrary exploit resistance or user-level IP firewall enforcement.

The private raw routing and runtime receipts remain local. The main merges, GitLab pipeline and final documentation revision require their own recorded checks; no future success is assumed here.

### Release and closure verification: 2026-11-05 (Claude, independent)

| Check | Result |
|---|---|
| GitHub `main` | `f21a331`, a squash of PR #1. Its tree `fce44178` equals the reviewed `a697ab8`. The CI push run passed on 3.12/3.13/3.14 |
| GitLab `main` | `f21a331`. MR !1 merged; the `main` pipeline passed on 3.12/3.13/3.14 |
| Fresh clone of `main` | 9/9 gates PASS; 107 tests OK (one legitimate skip) |
| `main` history | No pane UUIDs in any blob of `a5c2733..f21a331` |
| Branches | Luke deleted `feat/collective-comms` (GitHub) and `release/collective-comms` (GitLab); both remotes are `main`-only |
| Relay | Disabled and inactive after Luke's sudo; recovery sshd active (also verified by Codex 2, #442) |
| Durable records | MemPalace `evt_20261104T175055_6e5da8819039` (Claude outcome) plus Codex 3's release-acceptance events and SSH.vault record (#447) |

**Lesson:** the tuios `draft_held` false positive on an empty placeholder held both Codex panes' mail-wake queued for about 7 hours. A read-only screen check confirmed the input boxes were empty, and an `ask-agent` nudge (at Luke's request) woke both panes.

### Reliability iteration test evidence (`feat/collective-reliability`, dated 2026-11-05)

Each count belongs to one revision; none is a later revision's result.

| Revision | Evidence | Status |
|---|---|---|
| `f21a331` (released `main`) | 107 test methods; 9/9 gates and 107 tests OK in a fresh clone (see above) | Historical release evidence |
| `fe74d3e` (initial reliability candidate) | 201 test methods. The private generated QA sandbox recorded 199 tests and 11/11 gates passing before the final first-run-grace regressions were added | Historical candidate evidence; it included the later-removed daily quality job |
| Review-fix revision after `2f555b6` | 212 test methods; `python3 -m unittest` over all five test modules ran 212 tests, OK, 1 skipped (`systemd-analyze` absent in the review sandbox) | Local review-phase measurement only. The pipeline's own gate run and the protected Python 3.12/3.13/3.14 CI are the authoritative results and are not recorded here in advance |

The daily quality job, its offline gate-tool provisioning and its receipt consumer were removed in the review-fix revision, so no automatic quality evidence exists for any revision. Host status before acceptance (kept as history): on 2026-11-05 the heartbeat was paused for this iteration and the two job timers were not installed.

## Candidate host acceptance (2026-11-04T20:59Z)

Recorded after it happened. The candidate was `269ee7e` plus Codex 3's uncommitted strict tool-version and parser-documentation follow-up. The public `main` branches on both remotes still point at `f21a331`; publication follows the protected CI.

| Check | Codex 3 host acceptance (20:59:27Z) | Claude independent re-check (21:01:11Z) |
|---|---|---|
| Gates and tests | 11/11 gates PASS on Python 3.14.8; full suite of 215 tests passing | 215 test methods (static count) |
| Metadata job install | `install_coordination_jobs.py` reported `installed`; four generated units passed `systemd-analyze verify` | Installer receipt `installed` |
| Timers | Exactly three enabled and active: heartbeat, collaboration, cohesion. The gateway installer resumed the heartbeat | Same three enabled and active. Each service `Result=success`, exit 0 |
| Unit files | All six live unit files byte-match the generated units | All six byte-match the installers' current output |
| Job receipts | Collaboration and cohesion `ok`, exact source hash | Both `ok`, fresh, source hash matches, no source or metric gaps, written after the confirmed install |
| No automatic QA | Quality timer not found and inactive | Quality is unscheduled by contract: no unit file, not enabled, not active |
| Gateway view | `coord_jobs` observed two `ok`, non-stale receipts; notice counts are metadata only | Board fresh; unknown-notice ledger empty; no legacy hold |
| Effects | Runtime hashes unchanged; no model turns | Read-only collector; no units changed, no jobs run, no mail sent |

**Meaning.** These are candidate observations at one point in time. They are not a guarantee of ongoing schedule health, and they do not prove that any agent work was accepted or completed. Ongoing health is the heartbeat's job (`jobs:<name>` alerts on failed, degraded, unknown or stale receipts).

## Research and gate provenance (2026-11-05, zero-touch hive phase)

Pointers only; no research corpus is copied into the vault. Library sources were treated as data.

| Item | Durable record | Status |
|---|---|---|
| Claude X1 (library principles) and X1b (peer-reviewed findings) | MemPalace artifact `art_20261104T200737_fc181e3a418c`; `~/.local/state/collective-claude/research-20261105/` (with SHA-256 manifest) | Delivered. R57 MAST is peer-reviewed (NeurIPS 2025 Datasets and Benchmarks); R47 is a preprint, so its numbers are hypotheses |
| Codex 2 research (library, zellij, papers) | `art_20261104T200618_3f7a2b2d3e2f`, `…_b0e79a38aa9c`, `…_71ee5b5f43e6`; `~/.local/state/collective-codex2/reliability-20261105/` | Delivered. 20 forked crash schedules passed, with at most 1 fake effect. No empirical claim that coherence improved |
| R3 gates patch v6 | MemPalace artifact `art_20261104T200737_c1689c7e94ed`; patch sha256 `317e6e84…`, `tools/check.py` `8ec18b09…` | **Accepted** by Codex 2 (#598, #601). Waiting on Codex 3 to apply it after R1 and the jobs work |
| Rhythms reporter v2 | Same state directory: `rhythms.py` and `fixtures_check.py` (12 checks) | **Not adopted.** Codex 3's jobs share its principles: descriptive only, no hard-coded roster (#601). They make no phase, balance or latency claims. The scheduler design is Codex 3's decision (#582, #621) |

## Soak and release acceptance: 26a2ae11 (2026-11-04T23:03Z to 2026-11-05T00:13Z)

Recorded after the events. Luke authorised a 60-minute team soak (23:03:15Z to 00:03:35Z): use and test the plugin, and fix what breaks. The defects listed below were addressed in a candidate, with Vesper security review, protected CI and host rollout by Codex 3. Known upstream limitations remain listed separately.

**Defects found and fixed in the soak.** Behavioral fixes have regression controls observed red before the fix and green after it; documentation corrections were reviewed directly.

| Finding | Severity | Fix |
|---|---|---|
| A malformed existing `memory.json` was silently reset, so a held `unknown` notice could be resent | High | Heartbeat fails closed: exit 1, file preserved, no reset, no resend; recovery in the Scheduler Runbook |
| tuios schema drift (a missing, string, NaN, bool or negative `unread`, a non-bool `needs_you`, a missing `window_id`) read as "0 unread, clear" | Medium | The whole tuios observation becomes UNKNOWN; prior ages are kept |
| `monitor --state-dir <relative>` wrote private state into the caller's working directory | Medium | An absolute path is required |
| `dashboard --watch` never flushed when piped | Low–Medium | Each frame is flushed |
| A README line said a timer runs `monitor`; `capabilities` omitted the optional desktop notification | Low | Both corrected |
| Vesper follow-ups: contradictory refusal versus success; duplicate JSON keys and non-finite numbers; `Zl`/`Zp` in single-line fields; mixed receipt layers | Hold, then fixed | Contradictions and mixed layers read UNKNOWN and are never retried; strict JSON; separators refused in subjects |

**Release.** GitHub PR #4 and GitLab MR #3 were merged to `26a2ae11` on both protected `main` branches (candidate commits `2e365f4`, `b597b19`): 237 tests and 11 gates. GitHub `main` CI succeeded on Python 3.12, 3.13 and 3.14; GitLab `main` pipeline #3029590479 succeeded.

**Scheduler evidence.** Each run type is kept separate, so a manual run is never presented as a natural one:

| Phase | What ran | Evidence |
|---|---|---|
| Natural recurrence BEFORE the rollout (old head) | collaboration 23:05:39, 23:16:07, 23:26:40, 23:37:08 and 23:47:28Z (10m20s to 10m33s apart); cohesion 23:01:24 and 23:31:52Z (30m28s); heartbeat every tick | All `ok` or `success` |
| EXPLICIT post-rollout service runs (Codex 3 rollout at 26a2ae11; not timer-driven) | collaboration and cohesion at 23:54:41Z | `ok`; no gaps; source hash = the new `coordination_jobs.py` |
| NATURAL post-rollout recurrence (timer-driven, new head) | heartbeat 23:57:08, 23:59:28 and 00:01:40Z; collaboration 00:05:08Z (10m27s after the explicit run); cohesion: first natural post-rollout run due 00:25:01Z, **not yet observed** at this receipt (00:13Z) | `success`; job receipts `ok` from the new source |

Across 56 one-minute samples (23:07:26Z to 00:02:28Z): no sample saw a stopped timer, every service result was success, the board was at most 140 s old and there were 0 `unknown` notice outcomes. Codex 2 and Codex 3 independently report the final checks GREEN.

**Limitations.**
- One-minute sampling cannot prove zero downtime during the brief rollout pause; it shows only that no sample caught a stopped timer.
- Observations are systemd state, receipts and the board. They are not proof of agent execution or task acceptance.
- Hostile-input tests used an isolated state directory and a fake `TUIOS_BIN`, so they show consumer behaviour, not the live daemon's.
- The tuios mail ring evicts old messages, so mail-derived metrics cover only the visible ring.
- Laptop cross-machine boundary (Codex 3, #845): authenticated SSH transport to the laptop **passes**. Laptop live-agent and plugin acceptance is **blocked**: the queried tuios endpoint returned saved sessions only, the default native Herdr endpoint reported `server_not_running`, and the returned plugin registry did not include `local.collective`. Alternate endpoints were not ruled out. No laptop installation or peer configuration change was made. Claude did not attempt SSH (sole transport owner: Codex 3).

**Incident (Claude).** During the soak a scratch copy made with `cp -a` of a git worktree shared its `.git` pointer, so a commit landed on Codex 3's candidate branch (`6e65db9`). It was contained with no content loss, preserved without a rewrite, and recorded privately. Rule adopted: scratch work only through an independent clone or `git archive`.
