"""Review or transactionally install two bounded metadata-only user coordination timers.

Default prints exact unit proposals. --install changes only the four named user
units, their timer enablement/activity, external private backups and receipt.
It never modifies the existing heartbeat or starts a model turn.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import os
import stat
import subprocess
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

ROOT = Path(__file__).resolve().parent
MARKER = "# Managed by local.collective coordination jobs;"
JOBS = ("collaboration", "cohesion")
CONTROL_SPACE = 32
DELETE_CHARACTER = 127


def _local_monitor() -> Any:  # noqa: ANN401 - audited local module, never a user-controlled path
    spec = importlib.util.spec_from_file_location("coordination_install_monitor", ROOT / "install_monitor.py")
    if spec is None or spec.loader is None:
        raise ImportError("Cannot load local scheduler helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if TYPE_CHECKING:
    import install_monitor as monitor
else:
    monitor = _local_monitor()


def units(root: Path = ROOT) -> dict[str, str]:
    """Return the four exact proposals with existing reviewed sandbox controls."""
    if not root.is_absolute() or any(ord(c) < CONTROL_SPACE or ord(c) == DELETE_CHARACTER for c in str(root)):
        raise ValueError("Unit source root must be absolute and contain no control characters")
    result: dict[str, str] = {}
    for job in JOBS:
        name = f"collective-{job}"
        replacements = {
            "ExecStart": f"/usr/bin/python3 -I -B {monitor.quote_unit(root / 'coordination_jobs.py')} --job {job}",
            "TimeoutStartSec": "90",
            "ReadWritePaths": "%h/.local/state/collective/coordination",
            "MemoryMax": "256M",
            "Description": f"Collective {job} (bounded; no notifications or model turns)",
        }
        lines = [MARKER + " independent bounded jobs."]
        for line in monitor.units(root)[monitor.SERVICE].splitlines()[1:]:
            key = line.split("=", 1)[0]
            lines.append(f"{key}={replacements[key]}" if key in replacements else line)
        lines += [
            f"WorkingDirectory={str(root).replace(chr(37), chr(37) * 2)}",
            "Environment=XDG_STATE_HOME=%h/.local/state",
            "Environment=PYTHONDONTWRITEBYTECODE=1",
        ]
        result[name + ".service"] = "\n".join(lines) + "\n"
        schedule = f"OnBootSec=3min\nOnUnitActiveSec={'10' if job == 'collaboration' else '30'}min"
        result[name + ".timer"] = f"""{MARKER} one timer per named job.
[Unit]
Description=Collective {job} schedule (no automatic agent work)

[Timer]
{schedule}
RandomizedDelaySec=30s
Persistent=false

[Install]
WantedBy=timers.target
"""
    return result


def _originals(destination: Path, names: list[str]) -> dict[str, bytes | None]:
    destination.mkdir(parents=True, exist_ok=True)
    metadata = destination.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o022:
        raise ValueError("Unsafe user unit directory")
    originals: dict[str, bytes | None] = {}
    for name in names:
        try:
            data = monitor.read_owned_bytes(destination / name, limit=monitor.MAX_UNIT_BYTES)
        except FileNotFoundError:
            originals[name] = None
            continue
        if not data.startswith(MARKER.encode()):
            raise ValueError("Existing coordination unit is not managed by this installer")
        originals[name] = data
    return originals


def _rollback(destination: Path, originals: dict[str, bytes | None], previous: dict[str, dict[str, bool]]) -> list[str]:
    errors: list[str] = []
    for timer, before in previous.items():
        verbs = ("stop",) if before["enabled"] else ("stop", "disable")
        for verb in verbs:
            try:
                monitor.command(["systemctl", "--user", verb, timer])
            except (OSError, monitor.CollectiveError, subprocess.TimeoutExpired) as exc:
                errors.append(f"{verb} {timer}: {type(exc).__name__}")
    for name, content in originals.items():
        try:
            if content is None:
                (destination / name).unlink(missing_ok=True)
            else:
                monitor.atomic(destination / name, content)
        except OSError as exc:
            errors.append(f"restore {name}: {type(exc).__name__}")
    try:
        monitor.command(["systemctl", "--user", "daemon-reload"])
    except (OSError, monitor.CollectiveError, subprocess.TimeoutExpired) as exc:
        errors.append(f"daemon reload: {type(exc).__name__}")
    for timer, before in previous.items():
        for state, verb in (("enabled", "enable"), ("active", "start")):
            if not before[state]:
                continue
            try:
                monitor.command(["systemctl", "--user", verb, timer])
            except (OSError, monitor.CollectiveError, subprocess.TimeoutExpired) as exc:
                errors.append(f"{verb} {timer}: {type(exc).__name__}")
    return errors


def install() -> dict[str, object]:
    """Hold the installation lock shared with the heartbeat installer from originals through rollback."""
    with monitor.installation_lock():
        return _install()


def _install() -> dict[str, object]:
    """Verify, back up and activate only these timers; restore state on failure."""
    proposed = units()
    destination = Path.home() / ".config/systemd/user"
    originals = _originals(destination, list(proposed))
    state = monitor.private_dir(Path.home() / ".local/state/collective/coordination")
    backup = monitor.private_dir(
        state / "installer-backups" / (dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    )
    staged = monitor.private_dir(backup / "staged")
    for name, content in originals.items():
        if content is not None:
            monitor.atomic(backup / name, content)
    for name, text in proposed.items():
        monitor.atomic(staged / name, text.encode())
    monitor.command(["systemd-analyze", "--user", "verify", *[str(staged / name) for name in proposed]])
    previous: dict[str, dict[str, bool]] = {}
    for job in JOBS:
        timer = f"collective-{job}.timer"
        previous[timer] = {
            key: monitor.command(["systemctl", "--user", verb, "--quiet", timer], check=False) == 0
            for key, verb in (("enabled", "is-enabled"), ("active", "is-active"))
        }
    receipt_path = state / "installer.json"
    accepted = monitor.accepted_receipt(receipt_path)
    receipt: dict[str, object] = {
        "status": "installing",
        "generated_utc": dt.datetime.now(dt.UTC).isoformat(),
        "backup": str(backup),
        "units": list(proposed),
        "previous_state": previous,
        "previous": accepted,
    }
    monitor.write_private_json(receipt_path, receipt)
    try:
        for name, text in proposed.items():
            monitor.atomic(destination / name, text.encode())
        monitor.command(["systemctl", "--user", "daemon-reload"])
        for timer in previous:
            monitor.command(["systemctl", "--user", "enable", "--now", timer])
        receipt["status"] = "installed"
        monitor.write_private_json(receipt_path, receipt)
    except (OSError, ValueError, monitor.CollectiveError, subprocess.TimeoutExpired) as exc:
        errors = _rollback(destination, originals, previous)
        receipt.update(status="rolled-back", error=type(exc).__name__, rollback_errors=errors)
        try:
            monitor.write_private_json(receipt_path, receipt)
        except (OSError, ValueError, monitor.CollectiveError) as receipt_error:
            errors.append(f"record rollback: {type(receipt_error).__name__}")
        if errors:
            exc.add_note("Rollback errors: " + "; ".join(errors))
        raise
    return receipt


def main() -> int:
    """Print exact proposals by default; install only with an explicit flag."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(install() if args.install else units(), indent=2))
    except (OSError, ValueError, monitor.CollectiveError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
