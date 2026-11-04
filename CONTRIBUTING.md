# Contributing

Owner: collective-claude (card Q1). These conventions are **enforced by `tools/check.py`**. Where this page and the gate runner disagree, the gate runner wins; fix this page.

## One command

```
git config core.hooksPath .githooks      # once per clone: runs the gates before every commit
python3 -I tools/check.py                # all gates; --keep-going to see everything; --only NAME for one
```

CI on GitHub and GitLab runs the same command on Python 3.12, 3.13 and 3.14. **Enforced:** GitHub branch protection on `main` requires `gates (3.12)`, `gates (3.13)` and `gates (3.14)` (strict, admins included). GitLab merges require a passing pipeline. Verified 2026-11-04.

## The gates

| Gate | Refuses |
|---|---|
| `selftest` | A fitness rule that can no longer fire. Each rule is proven against a planted bad snippet before its green result is trusted |
| `hygiene` | Private keys, tokens, emails, and private (RFC 1918), tailnet or any routable public IPv4 address anywhere in the publish set (documentation ranges allowed) |
| `fitness` | The architecture rules below |
| `format` | Code that `ruff format` would change |
| `lint` | Any `ruff` rule (`select = ["ALL"]`) except the documented ignores in `pyproject.toml` |
| `types` | Anything `mypy --strict` rejects, plus `explicit-override`, `truthy-bool`, `redundant-expr`, `possibly-undefined` and `ignore-without-code` |
| `security` | `bandit` findings of medium severity or higher |
| `tests` / `coverage` | A failing test, or **branch** coverage below 90% |

## Architecture fitness rules (`tools/check.py`, AST-based)

| Rule | Meaning |
|---|---|
| F1 | No `os.system`, `os.popen`, `eval`, `exec`, `compile`, `pickle`, `marshal` or `tempfile.mktemp`, and no `shell=` other than a literal `False` |
| F2 | Each module spawns processes from **one audited door**: `collective.run`, `heartbeat.run`, `install_monitor.command` |
| F3 | No write-tier-W5 effect strings: `send-keys`, `send-text`, `agent.prompt`, `set-config`, `apply-config`, `set-pane-grants`, `plugin.enable` and others |
| F4 | `chmod` modes never grant group or other access |
| F5 | Sockets are `AF_UNIX` only. The collective never opens a network socket |

## Rules for changing code

1. **One writer per file.**

   | File | Owner |
   |---|---|
   | `collective.py`, `heartbeat.py`, `install_monitor.py`, `herdr-plugin.toml` | Codex 3 |
   | `test_collective.py` | Codex 2 |
   | `README.md`, `DESIGN.md`, `CONTRIBUTING.md`, `SECURITY.md`, `THREAT_MODEL.md`, `pyproject.toml`, `tools/`, CI files, the vault's Home, Operations and Evidence notes | Claude |

   Send findings to the owner; never edit another owner's file.
2. **No blanket suppressions.** A per-line `# noqa: CODE - reason` or `# type: ignore[code]` needs a reason and reviewer approval. Adding an ignore to `pyproject.toml` needs a reason in the same diff.
3. **Builder ≠ judge.** A change is accepted when someone other than the author has run the gates and planted one breach that a test catches for the named reason.
4. **Intent before effect.** Persist intent before any external effect, treat timeouts as *unknown* rather than failed, and never retry an effect blindly.
5. **Stdlib only at runtime.** `dependencies = []` is deliberate. Gate tools are pinned in CI and `tools/check.py`.
6. **Commits** say what changed and why, and cite the card (`t13: …`). End them with the co-author trailer of the agent that wrote them.
