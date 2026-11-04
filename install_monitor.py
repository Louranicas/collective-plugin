"""Review/install the ONE existing collective-heartbeat user timer.

Default prints the exact unit content and changes nothing. --install is an
explicit scheduler operation. It backs up existing units, preserves the same
state and timer identity, verifies staged units and restores on setup failure.
This does not register or enable the Herdr/tuios plugin.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("collective_core", ROOT / "collective.py")
if _spec is None or _spec.loader is None:
    raise ImportError("Cannot load reviewed collective core")
_core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_core)
CollectiveError, private_dir, write_private_json = _core.CollectiveError, _core.private_dir, _core.write_private_json
MAX_UNIT_BYTES = 65536
SERVICE = "collective-heartbeat.service"
TIMER = "collective-heartbeat.timer"
HANDOFF = {
    SERVICE: "2d5907e025dfd83484c6521c43af257db28cd1ac4231bafc558a54326c1cea14",
    TIMER: "00c3bb50f27700ebf40b8ad9d986f614ead355d6d448e360bf190139515eac79",
}


def quote_unit(value: Path | str) -> str:
    """Quote one systemd argument and escape specifier expansion."""
    return '"' + str(value).replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"') + '"'


def units(root: Path = ROOT) -> dict[str, str]:
    """Return the reviewable service and timer without changing configuration."""
    service = f"""# Managed by local.collective; desktop user scheduler, not plugin activation.
[Unit]
Description=Collective communications heartbeat (passive checks; change-only human alerts)

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -I {quote_unit(root / "heartbeat.py")}
TimeoutStartSec=90
NoNewPrivileges=yes
UMask=0077
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=%h/.local/state/collective
PrivateTmp=yes
PrivateDevices=yes
PrivateNetwork=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectKernelLogs=yes
ProtectControlGroups=yes
ProtectClock=yes
ProtectProc=invisible
ProcSubset=pid
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
MemoryDenyWriteExecute=yes
RestrictAddressFamilies=AF_UNIX
IPAddressDeny=any
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallFilter=~@privileged @resources
CapabilityBoundingSet=
AmbientCapabilities=
LimitNOFILE=128
TasksMax=32
MemoryMax=256M
CPUQuota=50%
Nice=10
"""
    timer = """# Managed by local.collective; one timer, existing state is preserved.
[Unit]
Description=Collective communications: 2-minute tick, 15-minute full checks when quiet

[Timer]
OnBootSec=3min
OnUnitActiveSec=2min
RandomizedDelaySec=15s
Persistent=false

[Install]
WantedBy=timers.target
"""
    return {SERVICE: service, TIMER: timer}


def command(argv: list[str]) -> None:
    """Run a fixed scheduler command with bounded output and a timeout."""
    p = subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=100, check=False)  # noqa: S603 - argv-only scheduler operations, no shell
    if p.returncode:
        raise CollectiveError(f"{argv[0]} failed with exit {p.returncode}; inspect the user service journal")


def atomic(path: Path, data: bytes) -> None:
    """Replace one reviewed path using a private sibling file and durable writes."""
    temporary = path.with_name(path.name + "." + str(uuid.uuid4()) + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        temporary.replace(path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def unit_originals(destination: Path) -> dict[str, bytes | None]:
    """Validate the directory and read adopted units without following symlinks."""
    destination.mkdir(parents=True, exist_ok=True)
    directory = destination.lstat()
    if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.getuid() or directory.st_mode & 0o022:
        raise CollectiveError("Refusing unsafe user unit directory")
    originals: dict[str, bytes | None] = {}
    for name in (SERVICE, TIMER):
        path = destination / name
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        except FileNotFoundError:
            originals[name] = None
            continue
        except OSError as exc:
            raise CollectiveError("Refusing inaccessible or symlink user unit") from exc
        with os.fdopen(fd, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1
                or metadata.st_size > MAX_UNIT_BYTES
                or metadata.st_mode & 0o022
            ):
                raise CollectiveError("Refusing unsafe existing user unit")
            data = stream.read(MAX_UNIT_BYTES + 1)
        if not data.startswith(b"# Managed by local.collective;") and hashlib.sha256(data).hexdigest() != HANDOFF[name]:
            raise CollectiveError("Existing unit differs from the frozen handoff; review it before adoption")
        originals[name] = data
    return originals


def rollback(destination: Path, originals: dict[str, bytes | None], *, was_enabled: bool) -> list[str]:
    """Restore files and fresh-install enablement; retain every cleanup error."""
    errors: list[str] = []
    if not was_enabled:
        try:
            command(["systemctl", "--user", "disable", "--now", TIMER])
        except (OSError, CollectiveError, subprocess.TimeoutExpired) as exc:
            errors.append(f"disable timer: {exc}")
    for name, data in originals.items():
        try:
            if data is None:
                (destination / name).unlink(missing_ok=True)
            else:
                atomic(destination / name, data)
        except OSError as exc:
            errors.append(f"restore {name}: {exc}")
    try:
        command(["systemctl", "--user", "daemon-reload"])
    except (OSError, CollectiveError, subprocess.TimeoutExpired) as exc:
        errors.append(f"daemon reload: {exc}")
    return errors


def install() -> dict[str, str]:
    """Back up and verify one scheduler, restoring files on setup failure."""
    destination = Path.home() / ".config/systemd/user"
    originals = unit_originals(destination)
    was_enabled = (destination / "timers.target.wants" / TIMER).is_symlink()
    state = private_dir(Path.home() / ".local/state/collective-plugin")
    backup = private_dir(
        state / "scheduler-backups" / (dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    )
    staged = private_dir(backup / "staged")
    for name, data in originals.items():
        if data is not None:
            atomic(backup / name, data)
    for name, content in units().items():
        atomic(staged / name, content.encode())
    command(["systemd-analyze", "--user", "verify", str(staged / SERVICE), str(staged / TIMER)])
    private_dir(Path.home() / ".local/state/collective")
    try:
        for name, content in units().items():
            atomic(destination / name, content.encode())
        command(["systemctl", "--user", "daemon-reload"])
        command(["systemctl", "--user", "enable", "--now", TIMER])
        command(["systemctl", "--user", "start", SERVICE])
    except (OSError, CollectiveError, subprocess.TimeoutExpired) as exc:
        errors = rollback(destination, originals, was_enabled=was_enabled)
        if errors:
            exc.add_note("Rollback errors: " + "; ".join(errors))
        raise
    receipt = {
        "timer": TIMER,
        "service": SERVICE,
        "backup": str(backup),
        "source": str(ROOT / "heartbeat.py"),
        "state": str(Path.home() / ".local/state/collective"),
        "cadence": "2-minute tick; full checks while active, every 15 minutes when quiet",
        "scope": "passive metadata checks and deduplicated human notices; no model turns",
        "undo": f"systemctl --user disable --now {TIMER}; restore backed-up units; systemctl --user daemon-reload",
    }
    write_private_json(state / "scheduler-install-receipt.json", receipt)
    return receipt


def main() -> int:
    """Print the exact proposal, or apply it only with --install."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(install() if args.install else units(), indent=2))
    except (CollectiveError, OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    else:
        return 0


if __name__ == "__main__":
    sys.exit(main())
