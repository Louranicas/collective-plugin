# Collective plugin: design

- Status: **prototype; enabled locally in tuios and native herdr (read-only actions verified 2026-11-04); public repos with CI-required branch protection.**
- Finalised 2026-11-04 against the frozen source (`collective.py` fb9d36d2, `heartbeat.py` 7f54355f, `herdr-plugin.toml` ebb8ae9f). The suite passes **36/36**, run by Codex 2 and independently by Claude (§8).
- Requested by Luke: "broaden and build on the read-only collective plugin (consider write also)".

| File | Owner (one writer per file) |
|---|---|
| `collective.py`, `herdr-plugin.toml`, monitor installer | Codex 3 (tuios pane `<codex3-pane>`), coordinator |
| `test_collective.py` | Codex 2 (`<codex2-pane>`) |
| `README.md`, `DESIGN.md` | Claude (`<claude-pane>`) |

A separate reference root, `~/src/herdr-collective/`, belongs to Claude (local only; not published in this repository). It holds the earlier wrappers, the interim heartbeat and `herdr-sock`, and is not part of this plugin.

Reference vault: [Collective.vault/Home.md](Collective.vault/Home.md), which covers architecture (Codex 2), decisions and roadmap (Codex 3), and operations and evidence (Claude).

## 1. Purpose

Agents on this desktop talk over five separate layers: tuios mail, native herdr, MemPalace events, atuin history and SSH. This plugin gives one **passive view** across them and **one audited write lane**, for local tuios mail. It is an adapter. It is not a new protocol, an identity system or a source of authority.

## 2. Commands (as implemented)

| Command | Effect | What it calls |
|---|---|---|
| `dashboard [--session S] [--watch]` | read | `observe()` runs roster, history, memory and ssh in parallel. `--watch` refreshes every 10 s, and `q` quits |
| `roster --session S` | read | Two `tuios call list-attention` calls (for `boot_id`) around `list-agents`. Fields: window, session, name, foreground, harness, state, agent session, unread, `draft_held`, `needs_you`. Adds native herdr when configured, otherwise reports "not configured" |
| `inbox --session S --pane UUID [--bodies]` | read | `read-agent-messages` **without `to`**, so nothing is marked read or seen. Metadata by default; subject and text only with `--bodies`. Last 100 ring entries; reports `evicted` |
| `history [--cwd PATH]` | read | `atuin search --author '$all-agent' --limit 10`, formatted as `{time} \| {host} \| exit={exit} \| {directory}`. No command bodies or intent |
| `memory [--since-event-id ID]` | read | `mempalace logstream list --to-agent kinoite-codex`, 50 entries, metadata fields only. Cursor by event id |
| `ssh-health` | read | `systemctl show` on the recovery sshd, the unix socket and both relay units, plus `tailscale status --json`. Local state only; no SSH, no probes |
| `capabilities` | read | A static statement of read, write, excluded and limits |
| `monitor [--state-dir D] [--notify]` | passive sweep | One `observe()`, plus the unread ids in the ring. Writes `latest.json` and `monitor-state.json`. On new unread ids since the last sweep, with the same daemon boot, it can send a desktop notification (`notify-send`) carrying a count only |
| `mail-plan …` | write, step 1 | Writes a private plan and prints the digest |
| `collaboration-plan --sender S --reviewer R --kind intent\|milestone\|blocker\|handoff\|review --goal G --scope S --done DOD [--evidence E]… --output P` | write, step 1 | The **first-class collaboration preset**. Builds a structured JSON body: owner, reviewer, goal, scope, definition of done, evidence (up to 16), and authority note. It is planned to the reviewer through the **same** mail gate. Owner and reviewer must be distinct current panes |
| `coordination_jobs.py --job collaboration\|cohesion` | bounded job (timer-driven, §4.1) | Reads roster, ring and tasks; writes one private metadata receipt. Exit 1 on `failed` or `degraded`. Runs no tests |
| `install_coordination_jobs.py` | operator install (Codex 3) | Verifies, backs up and enables the two job timers under the shared installation lock; rolls back when a step raises |
| `mail-apply --plan P --confirm SHA256 [--journal J] [--keep-plan]` | write, step 2 | `tuios call send-agent-message`. **Deletes the plan after a successful submission by default** (`--keep-plan` retains it). A failed cleanup never turns success into a retry |

Global flags:

- `--json`
- `--native-herdr BIN`, which uses the CLI `agent list`
- `--native-socket ABS_PATH`, which uses the Unix-socket adapter and permits **only** `ping` and `agent.list`

These also come from the environment as `COLLECTIVE_NATIVE_HERDR_BIN` and `COLLECTIVE_NATIVE_HERDR_SOCKET`. Inside tuios panes `HERDR_*` points at the **tuios shim**, so native herdr must be named explicitly, for example `--native-socket ~/.config/herdr/herdr.sock`. Claude verified direct socket reads on 2026-11-04: server 0.9.5, protocol 22, 22 agents.

## 3. The write lane: local tuios mail only

**Why mail only:** mail is queued in the mailbox and never typed into a pane. So it cannot answer a prompt, merge into an unsent draft, or interrupt a turn.

**Excluded by design:**

- raw PTY input and queued prompts;
- broadcast (`select`) and the `human` inbox;
- approvals, SSH effects, grants and config, and script execution;
- automatic replies.

### Plan shape (as implemented)

`mail-plan --session S --sender UUID --to UUID --subject TEXT --text-file PATH [--reply-to ID] --output PATH`

It writes a plan file with mode 0600, created exclusively (`O_EXCL`, `O_NOFOLLOW`). The file holds exactly these keys:

```
schema=1, action="tuios.mail", request_id (uuid4), issued_at, expires_at = issued_at + 300,
endpoint {tuios binary, server}, boot_id,
sender_identity  {window_id, session, agent_session_id, foreground, harness_id},
recipient_identity {…same…},
payload {session, from, to, subject, text, [reply_to]},
digest = sha256(canonical JSON of everything except digest)
```

- **The message text is inline in the plan.** This is intentional: the plan is the exact private artifact a reviewer checks. `mail-apply` removes it after a successful submission unless `--keep-plan` is given. The journal never stores the body.
- Subject: at most 120 bytes, single line. Text: at most 8192 bytes. Both refuse C0 and DEL characters (newline and tab are allowed in text), plus bidi and zero-width characters.
- The session must be local, so `HOST:SESSION` is refused. Sender and recipient must be distinct UUIDs, each **exactly one current agent pane** in that session with a foreground program.

### Apply (as implemented)

`mail-apply --plan P --confirm DIGEST` runs these steps in order:

1. Reads the plan, which must be an owned, 0600, regular, non-symlink file of at most 64 KiB.
2. Checks the key set exactly, schema 1, `issued_at <= now < expires_at`, and the digest against both `--confirm` and the plan, compared in constant time.
3. **Rebuilds the plan** from a fresh snapshot. Any change to the endpoint, daemon `boot_id`, or either pane's agent session, foreground program or harness means **refused, prepare a new plan**.
4. Journal, under `flock`: refuses a digest or request id seen before (**one-use**), and refuses past 10 intents per sender per minute. Then it appends an `intent` line **before** submitting. The line holds digest, request id, sender, recipient, body SHA-256 and byte count; no body.
5. Submits through `tuios call send-agent-message` with argv JSON and no shell. It records the outcome as `submitted`, `refused` or `unknown`. Only a failure to launch the tool, or an error carrying a documented refusal code (`REFUSAL_CODES` in `collective.py`), counts as **refused**. A timeout, the output cap, a nonzero exit or error envelope without such a code, and any I/O failure after the child starts all count as **unknown**: the mail may already be delivered, so check the recipient's inbox and **never** resend automatically. If recording the final outcome fails, the delivery result is still reported with a journal note, and the consumed intent still refuses replay.

A submission is not a reply or an acceptance. The only acknowledgement between agents is a `--reply-to` answer.

Stated limits, from `capabilities`:

- A pane with an **empty `agent_session_id`** (observed on some Codex panes) is revalidated by window, session, foreground and harness only. A model restart inside the same pane is therefore not detected for those panes.

- Pane IDs are routing claims, not authenticated identities.
- The digest is a review acknowledgement, not authentication.
- Revalidation is a preflight check, not an atomic daemon transaction.

## 4. Ongoing comms: the scheduler

There is no `crontab` on Fedora Kinoite, so scheduling uses a **systemd user timer**. There is **one notification gateway**, `collective-heartbeat.timer`, owned by **Codex 3** since the handoff on 2026-11-04 (#189: active, first run OK; historical). It was paused by root during hardening and observed active again after host acceptance on 2026-11-05 (dated evidence in `Collective.vault/Evidence/Verification.md`); query current state with `systemctl --user is-active collective-heartbeat.timer`. On 2026-11-05 it was paused again for the zero-touch release and stays paused until host acceptance. No second notifier exists. The bounded jobs in §4.1 never notify.

| Item | Detail |
|---|---|
| Units | `~/.config/systemd/user/collective-heartbeat.timer` and `.service`. The service runs `ExecStart=/usr/bin/python3 -I ~/tuios-setup/collective-plugin/heartbeat.py` with `TimeoutStartSec=90` |
| Installer | `install_monitor.py` (Codex 3) repoints the same units. Private unit backups go under `~/.local/state/collective-plugin/scheduler-backups/`; the receipt is `~/.local/state/collective-plugin/scheduler-install-receipt.json` (`installing` → `installed`, or `rolled-back` with the original error and `previous` = last accepted install) |
| Cadence (FLEX, Luke 2026-11-04) | 2-min tick. A full sweep every tick while the collective is **active**: `needs_you`, mail sent in the last 15 min, or an unblocked card in plan/doing/verify/review. Otherwise a full sweep at most every 15 min |
| Sweep | tuios roster (unread age, `needs_you`, `draft_held`); native herdr `agent.list` (`blocked` for more than 15 min); relay units; Tailscale peers. Writes a private board, `~/.local/state/collective/heartbeat.json`. The existing dedup state was retained |
| Alerts | Change-only messages to Luke's tuios `human` inbox. A resolved alert re-arms. The relay alert is sent at most once a day; `ring-loss:<boot>` reminds at most once per 48 h. A verified daemon restart resets tuios mail/needs ages and acknowledgements. Every notice is journaled (§4.2). An unknown outcome holds its alert keys and is **never resent automatically**; a documented refusal may be retried after backoff. Reads share a 45 s budget and the notice keeps a reserved 20 s, inside `TimeoutStartSec=90` |
| Off switch | `systemctl --user disable --now collective-heartbeat.timer` |

### 4.1 Bounded coordination jobs (Codex 3 decision #582, 2026-11-05)

Two separate user timers run `coordination_jobs.py --job collaboration|cohesion`. Collaboration runs every 10 min and cohesion every 30 min, both starting 3 min after boot, each with a 90 s and 256 MB bound. Each timer adds a random delay of up to 30 s. Each job:

- takes its own non-blocking lock, and skips if one is already running;
- reads the roster, the ring (256 entries, marked `complete_history: false`) and task cards, read-only, 20 s each;
- writes one schema-1, 0600 metadata receipt to `~/.local/state/collective/coordination/<job>.json`.

Jobs never send mail, notify, wake agents or retry effects. Their metrics are descriptive. **Acceptance is never inferred** from submission, read flags, replies, owner names or task stages. The heartbeat reads the receipts and alerts `jobs:<name>` on a failed, degraded, unknown or stale receipt (stale after 30 min and 90 min respectively). A missing receipt reads `awaiting-first-run` (not a pass) for 180 s after install, then becomes `unknown`. A malformed, too-deep or unreadable receipt is `unknown` immediately. The job hashes its own source through the bounded owned-file reader, so a FIFO in its place fails promptly without a receipt.

**No scheduled quality execution.** The first candidate also had a daily `quality` job running `tools/check.py` unattended. The Vesper review found it ran mutable checkout tests with live `HOME` and Unix-socket access and that its tool pins were observed rather than enforced, so it was removed before release; `--job quality` is refused and the heartbeat ignores any leftover quality receipt. Quality runs only explicitly: by people, the git hooks and protected CI. No automatic quality result is claimed.

`install_coordination_jobs.py` (Codex 3) installs the units under the one installation lock it shares with `install_monitor.py` for the whole transaction. It runs `systemd-analyze --user verify` and backs up any prior managed units. It writes an `installing` / `installed` / `rolled-back` receipt, and when a step raises it restores each timer's enabled and active state. Rollback is exception recovery, not atomicity across power loss or SIGKILL. It refuses to overwrite units it does not manage. **On 2026-11-05 the jobs are proposed and not installed.** Operator detail is in the vault Scheduler Runbook.

### 4.2 Notice journal

`notice_state.py` holds pure, bounded transitions; it does no I/O. The heartbeat reserves each human notice as a durable **intent** before dispatch, recording a request id, a body digest, its alert keys, the boot id and the endpoint. It finishes the notice as `submitted`, `refused` or `unknown`. A persisted intent loads as `unknown`. Only a documented refusal (a known pre-effect outcome) releases the keys for a later attempt, with a backoff from 5 min to 1 h. An `unknown` notice is never resent: it keeps its keys held and is reconciled to `submitted` only when exactly one matching ring entry is found in the same daemon boot. When a held key's condition resolves, the key is released and the `unknown` record stays as audit, so a recurrence alerts once more. Pre-journal memory with a failed attempt cannot be reconciled; it holds every notice until an operator inspects the inbox and runs `heartbeat.py --release-legacy-notice-hold`, which backs up memory and acknowledges nothing (vault Scheduler Runbook). A stored submission is not a read receipt or acceptance.

### 4.3 Private file reads

`private_files.py` opens the parent directory first, then the leaf by `dir_fd`, with `O_NOFOLLOW|O_NONBLOCK`. It checks owner, mode, link count and type, and bounds each read (64 KiB by default, 2 MB at most). Two policies exist: private state (0700 directory, 0600 file) and owned units. It reduces same-user races and FIFO waits; it does not isolate against an adversarial process running as the same user.

A sweep is passive: it sends no replies, marks nothing read and starts no model turns. Each agent keeps its own session check where its harness allows one. Claude checks about every 7 minutes, session-only, expiring after 7 days. Codex sessions have no in-session scheduler and rely on tuios mail-wake plus this timer. `collective.py monitor` is the plugin's own one-shot sweep, for manual or future use; no timer runs it.

Scheduled sweeps are passive. They do **not** make any agent think. Each agent keeps its own in-session check:

- Claude: about every 7 min, session-only, expiring after 7 days.
- When quiet, the check records one line and stops.

## 5. Trust and identity

- Names are claims. That includes the shared `kinoite-codex` identity, tuios `from`, atuin `author` and herdr labels. Rows carry the exact pane UUID or `wN:pN`.
- External strings go through `clean()`, which replaces non-printable characters and so strips terminal escapes.
- Delivery, wake, read and reply are four separate states.
- SSH is governed by the SSH team protocol. The plugin only reports local SSH state.

## 6. Registration (Luke only, from a terminal outside tuios)

> **Done 2026-11-04** under Luke's D2 authorisation (Codex 3): tuios `local.collective` is on and herdr `local.collective` is enabled; see `proof/plugin-activation.json`. The steps below remain the procedure for re-registration after a manifest change.

1. Review every file at a **pinned commit** (check the verification receipt in §8).
2. tuios:

   ```
   tuios plugins link ~/tuios-setup/collective-plugin   # listed, stays off
   tuios plugins info local.collective    # what tuios will run
   tuios plugins approve local.collective # or --deny
   tuios plugins enable local.collective
   ```

3. Native herdr: `herdr plugin link <PATH>`, then `herdr plugin enable local.collective`. Herdr has no approval step and no sandbox.

> **Caveats:**
> - tuios re-asks for approval **only when the manifest changes**. Edits to `collective.py` alone are not re-approved, so keep the repo writable only by Luke and re-review on every commit.
> - The manifest sets `min_herdr_version = "0.9.3"` so that the tuios shim (`0.9.3+tuios`) qualifies. Confirm with `tuios plugins info` at registration; this is untested until then.
> - Manifest commands run `python3 -I collective.py …` from the plugin directory, so `PYTHONPATH` and the user site are ignored.

## 7. Development process

**Ownership.** Each file has one writer. Changes go to the owner as findings, and the owner applies them. Every merge needs passing tests (`test_collective.py`) and a peer review.

**Updates.**

- Keep your tuios pane note current: `tuios note set -w SELF 'DOING … | NEXT … | BLOCKED …'`.
- Mail is only for a **milestone, failure or handoff**, one message per event and threaded with `--reply-to`.
- There are no acknowledgement loops.

**Best-of-N with tuios fan-out** (Luke, 2026-11-04). This is a selective tool, for substantial changes with real design alternatives. Don't use it for routine edits.

1. The file owner writes the spec and its acceptance check, then commits. Fan-out needs a committed, clean base.
2. The owner runs:

   ```
   tuios fan 3 '<spec + definition of done>' --agent claude,codex,codex --grants read --name <topic>
   ```

   - Each attempt works in its own git worktree with the same definition of done.
   - `--grants read` limits only what an attempt may do **through tuios**: no mail, no typing into panes, no fan-out. It is **not** a filesystem or process sandbox, because the candidate code runs as Luke.
3. `tuios fan verify <session> -- python3 -I -m unittest discover -s . -p 'test_*.py' -q` runs the same check in every attempt. The suite uses the standard library's `unittest`, not pytest; the tests judge.
4. Before trusting a green fan, plant one breach in the winner and confirm a test fails for the named reason (see §8).
5. `tuios fan compare <session>` and `tuios fan diff A B` show the alternatives side by side. The reviewer judges them independently.
6. The owner integrates the winner into the canonical file, and the reviewer re-runs the tests.
7. **Preserve the evidence before cleanup.** `tuios fan keep` removes the other attempts. It refuses to discard uncommitted work unless forced, so never force it. Record or commit the losing attempts' diffs first, and run `keep` only after the owner and reviewer agree.

Each attempt is a new agent with its own token cost. Start a fan only for substantial changes on a **committed, clean base**, when the owner and Luke's scope allow it. A reminder alone launches nothing, and a nearly finished shared candidate does not need a fan.

### Front door

The one canonical collaboration front door is `collective.py collaboration-plan`, followed by `mail-apply` (Codex 3, #190/#197). Claude's `~/src/herdr-collective/bin/collab` is a **reference companion only. It is not adopted and is not part of this plugin.**

## 8. Verification receipt (Claude, independent verifier, 2026-11-04)

> Historical and superseded: current proof is the current acceptance receipt in `Collective.vault/Evidence/Verification.md`.

The subject was the frozen working tree (then uncommitted), sha256 prefixes:

| File | sha256 prefix |
|---|---|
| `collective.py` | `fb9d36d2` |
| `heartbeat.py` | `7f54355f` |
| `test_collective.py` | `5f899b49` |
| `herdr-plugin.toml` | `ebb8ae9f` |

| Check | Result |
|---|---|
| Baseline: `python3 -I -m unittest discover -s . -p 'test_*.py' -q` | **36 tests OK**. This independently matches Codex 2's 36/36 |
| Planted red: digest compare disabled | **FAILED** `test_wrong_confirmation_refused`, the named reason |
| Planted red: one-use journal check disabled | **FAILED** 4 tests: replay, process race, same nonce with a different payload, and one more |
| Planted red: owner ≠ reviewer guard disabled | **Survived**, because `make_mail_plan` independently refuses self-messaging (defence in depth). Disabling both guards fails 2 tests, so the survivor is an equivalent mutant, not a gap. Optional hardening: assert the specific error text in the self-review test |

Plants ran on a scratch copy; the canonical tree was not modified. Builder Codex 3, tester Codex 2 and verifier Claude are distinct agents.

## 9. Open items

- Live evidence, 2026-11-04:
  - Codex 3 sent message #167 to Claude through `mail-plan`/`mail-apply`. It arrived with `from` set to the sender's pane UUID (a claim), its subject intact and its own thread. Claude confirmed in #178.
  - Codex 3 reports that replaying the same plan was refused. Claude saw no duplicate arrive.
- Herdr `[[events]]` hook names. Native `events.wait` supports **only** pane agent-status matches (verified: `unsupported_event_wait_match` for output events), so subscriptions are the route for anything else.
- A tuios host link to the laptop (mail-only policy, over existing SSH): new scope under the SSH protocol, owned by kinoite-codex and Daybreak.
