# Contributing

Owner: collective-claude (card Q1). These conventions are **enforced by `tools/check.py`**. Where this page and the gate runner disagree, the gate runner wins; fix this page.

## One command

```
git config core.hooksPath .githooks      # once per clone: gates before every commit; strict history scan before every push
python3 -I tools/check.py                # all gates; --keep-going to see everything; --only NAME for one
```

CI on GitHub and GitLab runs the same command on Python 3.12, 3.13 and 3.14. **Enforced:** GitHub branch protection on `main` requires `gates (3.12)`, `gates (3.13)` and `gates (3.14)` (strict, admins included). GitLab merges require a passing pipeline. Verified 2026-11-04.

## The gates

| Gate | Refuses |
|---|---|
| `selftest` | A fitness rule that can no longer fire. Each rule is proven against a planted bad snippet before its green result is trusted |
| `hygiene` | Private keys, tokens, emails, and private (RFC 1918), tailnet or any routable public IPv4 address anywhere in the publish set (documentation ranges allowed) |
| `history` | Secrets in **any blob, commit message or tag message a push would publish**, even if a later commit deleted them. Under the pre-push hook it scans every outgoing ref (branches, tags, new refs) with its **entire** history (no exclusion for what some remote holds: an unrelated mirror may hold a secret the target never had); otherwise `COLLECTIVE_PUSH_BASE..HEAD`, then `@{upstream}..HEAD`, then all of `HEAD` (CI). A shallow clone, an unresolvable base or unparseable hook input **fails** |
| `diagrams` | Each Mermaid diagram (``` or ~~~ fence) needs exactly one receipt per 1-based index; source and SVG must be regular, non-symlinked files inside the vault (SVGs under `Assets/`), with matching hashes, and no SVG may be reused. A missing or malformed receipt fails when any diagram exists |
| `fitness` | The architecture rules below |
| `format` | Code that `ruff format` would change |
| `lint` | Any `ruff` rule (`select = ["ALL"]`) except the documented ignores in `pyproject.toml` |
| `types` | Anything `mypy --strict` rejects, plus `explicit-override`, `truthy-bool`, `redundant-expr`, `possibly-undefined` and `ignore-without-code` |
| `security` | `bandit` findings of medium severity or higher |
| `tests` / `coverage` | A failing test, or **branch** coverage below 90% in aggregate or in any one runtime module. Coverage selects files by path (`source = ["."]`, tests and tools omitted), because modules load each other under private names and a module-name selection silently drops them |

## Architecture fitness rules (`tools/check.py`, AST-based)

| Rule | Meaning |
|---|---|
| F0 | `SOURCES` in `tools/check.py` lists exactly the top-level runtime modules: a listed file that is missing, or a non-test `*.py` that is not listed, fails. A new module cannot skip the gates |
| F1 | No `os.system`, `os.popen`, `eval`, `exec`, `compile`, `pickle`, `marshal` or `tempfile.mktemp`, and no `shell=` other than a literal `False` |
| F2 | Each module spawns processes from **one audited door**: `collective.run`, `heartbeat.run`, `install_monitor.command`, `coordination_jobs._run` |
| F3 | No write-tier-W5 effect strings: `send-keys`, `send-text`, `agent.prompt`, `set-config`, `apply-config`, `set-pane-grants`, `plugin.enable` and others |
| F4 | `chmod` modes never grant group or other access |
| F5 | Sockets are `AF_UNIX` only. The collective never opens a network socket |
| F6 | Every `os.open` must **provably** carry `O_NONBLOCK`, `O_CREAT\|O_EXCL` or `O_DIRECTORY`. Opening an existing path otherwise blocks forever on a FIFO (M1). Write the flags as one `os.O_* \| ...` expression or one plain assignment before the call; reassignment, `\|=`, parameters, loop variables and any operator other than `\|` prove nothing, and a conditional counts only if both branches set the flag. Eight planted negative controls guard the analyser. Open non-blocking, `fstat` for `S_ISREG`, then `set_blocking(True)`. F6 is a **policy guard on open calls**, not proof that every filesystem operation is bounded |
| F7 | Runtime modules never call the high-level opens `open`, `io.open`, `.open()`, `.read_bytes()`, `.read_text()`, `.write_bytes()` or `.write_text()`: they cannot carry `O_NONBLOCK`. Read through the `private_files` readers or `os.open` (F6). Five planted negative controls guard it. It sees only calls spelled this way; opens inside library internals (such as `importlib` loading a sibling module) are outside it |

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
5. **Stdlib only at runtime.** `dependencies = []` is deliberate. Gate tools are pinned in CI and `tools/check.py`. `tools/check.py` uses a PATH tool only when the first version token in its `--version` output equals the exact pin and fails closed otherwise; with no PATH tool it runs the pin through `uv tool run --from`. It does not verify tool artifact hashes.
6. **Commits** say what changed and why, and cite the card (`t13: …`). End them with the co-author trailer of the agent that wrote them.
