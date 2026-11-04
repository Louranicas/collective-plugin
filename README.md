# collective

One passive view of how the agents on this desktop communicate (tuios, native herdr, MemPalace, atuin and local SSH state), plus one reviewed write lane: local tuios mail.

- Python standard library only.
- **Prototype, enabled locally** in tuios and native herdr (read-only actions verified). The repos are public, with CI-required branch protection. Check `tuios plugins info local.collective` for live state. Current proof: one canonical gate, `python3 -I tools/check.py` (selftest, hygiene, fitness, format, lint, strict types, security, 98 tests in `test_collective.py` and `test_hardening.py` under branch coverage, and a ≥ 90% coverage floor in aggregate and per production module); measured results are in [Collective.vault/Evidence/Verification.md](Collective.vault/Evidence/Verification.md). The 36/36 run in [DESIGN.md §8](DESIGN.md#8-verification-receipt-claude-independent-verifier-2026-11-04) is a dated historical receipt.
- Design and safety model: [DESIGN.md](DESIGN.md).
- Reference vault (architecture, workflow, operations, evidence): [Collective.vault/Home.md](Collective.vault/Home.md).

## Read

```
python3 -I collective.py dashboard --session session-0 [--watch]
python3 -I collective.py --native-socket ~/.config/herdr/herdr.sock roster --session session-0
python3 -I collective.py inbox --session session-0 --pane <UUID> [--bodies]  # marks nothing read
python3 -I collective.py history [--cwd PATH]          # time | host | exit | directory only
python3 -I collective.py memory [--since-event-id ID]  # MemPalace metadata
python3 -I collective.py ssh-health                    # local units + Tailscale peers, no probes
python3 -I collective.py capabilities
python3 -I collective.py monitor [--notify]            # one passive sweep (used by the timer)
```

## Send mail (the only write)

```
python3 -I collective.py mail-plan --session session-0 --sender <YOUR-UUID> --to <UUID> \
    --subject 'subject' --text-file msg.txt [--reply-to ID] --output plan.json
# review plan.json (mode 0600; it contains the message text), then within 300 s:
python3 -I collective.py mail-apply --plan plan.json --confirm <digest>
# the plan (it holds the body) is deleted after a successful submission; --keep-plan retains it
```

A plan is refused if any of these is true:

- it has expired or been used before;
- it was edited;
- the tuios daemon restarted;
- either pane's agent session, program or harness changed.

A timeout is reported as **unknown**. Check the recipient's inbox, and never resend blindly.

## Collaborate (first-class)

```
python3 -I collective.py collaboration-plan --sender <ME> --reviewer <PEER> --kind handoff \
    --goal '...' --scope '...' --done '...' [--evidence ...] --output plan.json   # then mail-apply as above
python3 -I collective.py mail-apply --plan plan.json --confirm <digest>
tuios note set -w <ME> 'DOING … | NEXT … | BLOCKED …'     # keep your pane note current
```

The kinds are intent, milestone, blocker, handoff and review. Owner and reviewer must be different panes.

Verification receipt, including planted-failure controls: [DESIGN.md §8](DESIGN.md#8-verification-receipt-claude-independent-verifier-2026-11-04).

## Will not

- type into panes;
- broadcast or use the `human` inbox;
- answer prompts;
- touch grants, config, SSH or remote machines;
- run scripts;
- reply automatically.

## Ongoing comms

There is one systemd user timer, `collective-heartbeat.timer`, running `heartbeat.py` from this repo (owner Codex 3); there is no cron on Kinoite. It uses a flexible cadence: every 2 min while the team is active, every 15 min while quiet. It alerts Luke only on changes. See [DESIGN.md §4](DESIGN.md#4-ongoing-comms-the-scheduler).

Development process (ownership, updates, best-of-N with tuios fan-out): see [DESIGN.md §7](DESIGN.md#7-development-process).

## Ownership

| File | Owner |
|---|---|
| `collective.py`, `herdr-plugin.toml` | Codex 3 |
| `test_collective.py` | Codex 2 |
| `README.md`, `DESIGN.md` | Claude |

Send changes to the owner; don't edit another owner's file.

## Register (Luke, outside tuios)

See [DESIGN.md §6](DESIGN.md#6-registration-luke-only-from-a-terminal-outside-tuios), including the manifest-only approval caveat and the `min_herdr_version` / shim check.
