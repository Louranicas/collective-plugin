---
title: Verification
type: evidence
status: current
created: 2026-11-04
owner: Claude (tuios pane 08651035)
verifier: Claude (08651035); builder Codex 3; tester Codex 2
tags: [collective, evidence]
---

# Verification

## Receipt 2026-11-04 (Claude, independent verifier)

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
| 2026-11-04 | Codex 2 (858221a3), independent of the builder | Code: `collective.py` fb9d36d2, `heartbeat.py` 7f54355f, `test_collective.py` 5f899b49 | Malformed-shape test **seen red** (messages #193/#195), then green: **36 PASS** | Test-patch correlation `collective-plugin-tests-20261104`; MemPalace verification drawer `77d51a93d65b3279c317029b` |
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

`proof/native-return.json` retains the exact selected message #288 metadata witnessed by Codex 3 and a fresh native terminal readback. The mail carried no authenticated sender. `proof/plugin-activation.json` records successful capabilities **and dashboard** actions in both runtimes; roster, Atuin, MemPalace and local SSH observations returned successfully. `proof/runtime-sandbox.json` records named kernel refusal probes and the timer/service acceptance.

The public source candidate still requires the independent no-mistakes pipeline and remote CI; local green checks are not a claim that remote validation has run.
