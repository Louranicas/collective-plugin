# Threat model

Owner: collective-claude (card Q1). Scope: `local.collective` (the collective.py CLI and plugin, `heartbeat.py`, the user timer) on one Linux desktop with tuios 0.12 and native herdr 0.9.5.

## Assets

| Asset | Why it matters |
|---|---|
| Agent panes and their prompts | Typed input can answer an approval prompt or merge into a draft, so it acts with the user's authority |
| Mail bodies | May contain private task detail |
| The user's tuios `human` inbox | Trusted channel to Luke; spoofing or flooding it erodes that trust |
| Plan and journal state | The single-use guarantee and the audit trail |
| SSH and relay topology | Infrastructure detail useful to an attacker |

## Actors

1. **A confused or compromised peer agent** sends instructions as data, floods mail, or impersonates another pane.
2. **A malicious repository contributor** adds code that types into panes, opens a network socket, or weakens a gate.
3. **A local process under the same uid** tampers with plans, the journal or state files.
4. **The public**, once published, reads the repository for infrastructure detail.

## Boundaries and mitigations

| Threat | Mitigation | Enforced or tested by |
|---|---|---|
| Typing into panes, approvals, raw keys | Write lane is tuios **mail only** (W1); W5 effects absent by design | Fitness F3; `capabilities` statement; tests |
| Network exposure | Unix sockets only; no listeners | Fitness F5 |
| Shell injection | argv-only subprocess through one door per module; no `shell=` | Fitness F1/F2; bandit; ruff S |
| Peer impersonation (`--from`) | Plans rebuild sender and recipient identity (live pane, session, foreground, harness, boot id) before apply | `validate_mail_plan` tests; planted red (digest) |
| Replay or double send | One-use journal under `flock`; intent journaled before submit; any ambiguous outcome (see DESIGN §3 Apply) means unknown with no resend | Journal tests; planted red (replay ×4) |
| Plan tampering | sha256 digest over the canonical plan, compared in constant time against both the confirmation and the stored digest | Planted red (digest) |
| Symlink and permission attacks on state | 0700 directories, 0600 files, `O_NOFOLLOW`, owner, nlink and regular-file checks | Fitness F4; tests |
| Hidden or deceptive text | Every Unicode control (`Cc`) and format (`Cf`) character, including bidi and zero-width, refused in subjects and bodies (newline and tab allowed in bodies only); output passed through `clean()` | Tests |
| Flooding | 10 intents per sender per minute (plus tuios's own cap); the heartbeat alerts only on change | Journal tests; heartbeat dedup tests |
| Malformed herdr replies | Response id, shape and size bounds; failures read as *unknown* | Malformed-shape tests (seen red, then green) |
| Plugin code changing after approval | tuios approval is bound to the **manifest** only, so commits are reviewed and pinned | CONTRIBUTING; branch protection |
| Infrastructure leakage | Publish-set scan for IPs, keys, tokens and emails | `hygiene` gate |
| Scheduled jobs doing work or spamming | Jobs are metadata-only and descriptive: no mail, wakes, model turns or retries. Only the heartbeat notifies. Each job has its own lock, timeout and memory bound | `coordination_jobs.py` tests; F2 door `_run` |
| Corrupt or truncated private state | Missing `memory.json` is a first run; a malformed one halts the heartbeat before any read or notice and is preserved, so held `unknown` keys cannot be dropped by a silent reset and resent | `test_hardening.test_corrupt_existing_notice_memory_refuses_before_reads_or_effects` |
| A lost or duplicated notice | A journaled intent comes before dispatch. An unknown outcome holds its keys and is never resent; resolution releases the keys and keeps the record. Reconciliation needs exactly one matching ring entry in the same boot | `notice_state` tests (pure transitions) |
| Unattended test execution | Removed: no scheduled job runs tests; `--job quality` is refused. Gates run only explicitly, in hooks or protected CI | Job CLI refusal test |
| Installer clobbering units | One lock shared by both installers for the whole transaction, `systemd-analyze verify`, backups, a refusal for unmanaged units, rollback of each timer's enabled and active state when a step raises (not power-loss or SIGKILL atomicity) | Installer tests, cross-installer re-entry test |
| Timer escalation | User unit with systemd hardening; exposure measured with `systemd-analyze --user security` | Card Q2 |

## Out of scope and residual risk

- **Same-uid code execution:** an attacker running as the user can do anything the user can. The plugin does not sandbox itself from its own uid.
- **`--from` is a claim**, not cryptographic identity. Revalidation reduces confusion; it does not authenticate.
- **Cross-machine paths are not live.** SSH remains governed by the private SSH team protocol.
