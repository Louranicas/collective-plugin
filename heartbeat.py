#!/usr/bin/env python3
"""collective heartbeat: a read-only comms health check, run by a systemd --user timer.

Original implementation: Claude (tuios docs pane), task card t4.
Current source/scheduler owner: Codex 3; reviewers: Claude and Codex 2.

Each run:
  * reads tuios agents (unread mail, needs_you, draft_held, state), the SSH relay units,
    and Tailscale peers. It reads nothing else and changes nothing.
  * writes a shared status board, ~/.local/state/collective/heartbeat.json (0600).
  * sends Luke ONE combined tuios message (-w human), only when an alert first appears or
    changes. Repeats are suppressed; the relay alert repeats at most once a day.
It never types into panes, marks mail read, replies to agents, or retries anything.
Use --dry-run to print the board and the alert without sending.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import selectors
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TypedDict, cast

MAX_BYTES = 2_000_000
MAX_BOOT_BYTES = 128
PRIVATE_MODE = 0o600

TUIOS = os.environ.get("TUIOS_BIN", str(Path("~/.local/bin/tuios").expanduser()))
STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path("~/.local/state").expanduser()))) / "collective"
STALE_MAIL_S = 30 * 60
NEEDS_YOU_S = 15 * 60
RELAY_REPEAT_S = 24 * 3600
# Reminder and obsolete keys (relay day, ring-loss boot, peer transitions) are forgotten after this.
OBSOLETE_S = 2 * RELAY_REPEAT_S
# One sweep must finish inside the unit's TimeoutStartSec=90: all reads share READ_BUDGET_S, and the
# human notice keeps its own reserved NOTICE_S so a slow read can never starve the durable outcome.
READ_CALL_S = 20.0
READ_BUDGET_S = 45.0
NATIVE_CALL_S = 10.0
NOTICE_S = 20.0
RELAY_UNITS = ("ssh-independent-relay-machine-tunnel.service", "ssh-independent-relay-machine-connector.service")
WATCH_PEERS = tuple(p.strip() for p in os.environ.get("COLLECTIVE_WATCH_PEERS", "").split(",") if p.strip())
SESSION = os.environ.get("COLLECTIVE_SESSION", "session-0")  # pinned; never sent --from a pane
# Alert keys with these prefixes are cleared when the condition resolves, so a recurrence alerts again.
RESOLVABLE = ("mail:", "needs:", "peer:", "tuios-read", "herdr-read")
# One-shot transition alerts stay pending until a notice carrying them is delivered.
TRANSIENT = ("peer:", "ring-loss:")
# FLEX cadence (Luke, 2026-11-04): the timer ticks every 2 min. A full run happens every tick while the
# collective is ACTIVE, and at most every QUIET_FULL_S while it is quiet. Alerts stay change-only.
ACTIVE_MAIL_S = 15 * 60
QUIET_FULL_S = 15 * 60
ACTIVE_STAGES = {"doing", "verify", "review", "plan"}


HERDR_SOCK = os.environ.get("HERDR_NATIVE_SOCKET", str(Path("~/.config/herdr/herdr.sock").expanduser()))


@dataclass
class ReadDeadline:
    """Monotonic end of the read phase of the current sweep; unbounded outside a sweep."""

    end: float = math.inf

    def remaining(self, limit: float) -> float:
        """Return the per-call budget clamped to what is left of the sweep's reads."""
        return min(limit, self.end - time.monotonic())


SWEEP = ReadDeadline()


def herdr_agents() -> list[dict[str, str | None]] | None:
    """Native herdr roster via its Unix socket: the read-only agent.list method only. None if unavailable."""
    try:
        st = os.lstat(HERDR_SOCK)
        if not stat.S_ISSOCK(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            return None
        limit = SWEEP.remaining(NATIVE_CALL_S)
        if limit <= 0:
            return None
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            deadline = time.monotonic() + limit
            s.settimeout(limit)
            s.connect(HERDR_SOCK)
            credentials = s.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            require(condition=struct.unpack("3i", credentials)[1] == os.getuid(), message="Herdr peer UID mismatch")
            s.sendall(b'{"id":"collective-heartbeat","method":"agent.list","params":{}}\n')
            buf = b""
            while b"\n" not in buf:
                remaining = deadline - time.monotonic()
                require(condition=remaining > 0, message="Herdr response deadline exceeded")
                s.settimeout(remaining)
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
                require(condition=len(buf) <= MAX_BYTES, message="Herdr response exceeds limit")
        response = json.loads(buf.split(b"\n", 1)[0])
        if not isinstance(response, dict) or response.get("id") != "collective-heartbeat" or response.get("error"):
            return None
        res = response.get("result") or {}
        if (
            not isinstance(res, dict)
            or not isinstance(res.get("agents"), list)
            or not all(isinstance(a, dict) for a in res["agents"])
        ):
            return None
        return [
            {
                "pane": optional_string(a.get("pane_id")),
                "agent": optional_string(a.get("agent")),
                "status": optional_string(a.get("agent_status")),
            }
            for a in res["agents"]
        ]
    except (OSError, ValueError):
        return None


def activity(agent_list: list[dict[str, object]]) -> tuple[bool, list[str]]:
    """Return (active, reasons). Uses only metadata: sent_at times, card stages, needs_you. Marks nothing read."""
    reasons = []
    if any(a.get("needs_you") for a in agent_list):
        reasons.append("needs_you")
    rc, out = run([TUIOS, "read-agent-messages", "-s", SESSION, "--limit", "20", "--json"])
    if rc == 0:
        try:
            newest = max((number(m.get("sent_at")) for m in records(out, "messages")), default=0)
            if newest and time.time() - newest / 1e9 < ACTIVE_MAIL_S:
                reasons.append("recent-mail")
        except (ValueError, TypeError):
            reasons.append("mail-unknown")
    rc, out = run([TUIOS, "task", "ls", "-s", SESSION, "--json"])
    if rc == 0:
        try:
            if any(t.get("stage") in ACTIVE_STAGES and not t.get("blocked") for t in records(out, "tasks")):
                reasons.append("cards-in-flight")
        except (ValueError, TypeError):
            reasons.append("tasks-unknown")
    return bool(reasons), reasons


def require(*, condition: bool, message: str) -> None:
    """Refuse a failed transport invariant."""
    if not condition:
        raise ValueError(message)


def require_pipe(pipe: IO[bytes] | None) -> None:
    """Require the output pipes requested from Popen."""
    require(condition=pipe is not None, message="Missing process output pipe")


def run(argv: list[str], timeout: float = READ_CALL_S, *, reserved: bool = False) -> tuple[int, str]:
    """Read bounded output with one absolute deadline inside the sweep budget; never invoke a shell."""
    limit = timeout if reserved else SWEEP.remaining(timeout)
    if limit <= 0:
        return 99, "Heartbeat sweep read deadline exceeded"
    output, errors = bytearray(), bytearray()
    deadline = time.monotonic() + limit
    try:
        with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:  # noqa: S603 - fixed argv callers, no shell
            try:
                with selectors.DefaultSelector() as poll:
                    for pipe, target in ((proc.stdout, output), (proc.stderr, errors)):
                        require_pipe(pipe)
                        os.set_blocking(cast("IO[bytes]", pipe).fileno(), False)
                        poll.register(cast("IO[bytes]", pipe), selectors.EVENT_READ, target)
                    while poll.get_map():
                        remaining = deadline - time.monotonic()
                        require(condition=remaining > 0, message="Heartbeat command deadline exceeded")
                        for key, _ in poll.select(remaining):
                            chunk = os.read(key.fd, 65536)
                            if not chunk:
                                poll.unregister(key.fileobj)
                                continue
                            key.data.extend(chunk)
                            require(
                                condition=len(output) + len(errors) <= MAX_BYTES,
                                message="Heartbeat command output limit",
                            )
                    proc.wait(timeout=max(0.001, deadline - time.monotonic()))
            except BaseException:
                proc.kill()
                proc.wait()
                raise
        return proc.returncode, output.decode("utf-8", errors="replace")
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return 99, str(exc)


def number(value: object) -> float:
    """Require finite numeric metadata and reject booleans."""
    if type(value) not in (int, float):
        return 0
    try:
        numeric = float(cast("int | float", value))
    except OverflowError:
        return 0
    return numeric if math.isfinite(numeric) else 0


def optional_string(value: object) -> str | None:
    """Keep only strings from external metadata."""
    return metadata(value) if isinstance(value, str) else None


def metadata(value: object, limit: int = 64) -> str:
    """Bound untrusted labels and remove control, bidi and format characters."""
    return "".join(c for c in str(value) if not unicodedata.category(c).startswith("C"))[:limit]


def records(text: str, key: str) -> list[dict[str, object]]:
    """Validate a JSON object containing an array of metadata objects."""
    value: object = json.loads(text)
    if not isinstance(value, dict) or not isinstance(value.get(key), list):
        raise TypeError("Malformed metadata response")
    rows = value[key]
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("Malformed metadata row")
    return cast("list[dict[str, object]]", rows)


def secure_state_dir() -> None:
    """STATE must be a real directory owned by us with mode 0700; refuse symlinks and loose modes."""
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = os.lstat(STATE)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        sys.exit(f"heartbeat: refusing state dir {STATE}: symlink, not a directory, or not ours")
    if st.st_mode & 0o077:
        sys.exit(f"heartbeat: refusing state dir {STATE}: mode {oct(st.st_mode & 0o777)}; chmod 700 it")


def load[T](name: str, default: T) -> T:
    """Load a bounded private regular state file or a missing-file default."""
    try:
        fd = os.open(STATE / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return default
    with os.fdopen(fd) as fh:
        st = os.fstat(fh.fileno())
        if (
            not stat.S_ISREG(st.st_mode)
            or st.st_uid != os.getuid()
            or stat.S_IMODE(st.st_mode) != PRIVATE_MODE
            or st.st_nlink != 1
            or st.st_size > MAX_BYTES
        ):
            raise ValueError("heartbeat: state file must be private, owned, regular and singly linked")
        try:
            return cast("T", json.load(fh))
        except (ValueError, TypeError):
            return default


def save(name: str, obj: object) -> None:
    """Atomic write via an unpredictable O_EXCL temp file in the private dir, then rename."""
    fd, tmp = tempfile.mkstemp(dir=STATE, prefix=f".{name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(obj, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        Path(tmp).chmod(0o600)
        Path(tmp).replace(STATE / name)
        directory_fd = os.open(STATE, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        if Path(tmp).exists():
            Path(tmp).unlink()
        raise


def agents() -> list[dict[str, object]] | None:
    """Return validated tuios rows, or unavailable on a failed read."""
    rc, out = run([TUIOS, "list-agents", "--all-sessions", "--json"])
    if rc != 0:
        return None
    try:
        return records(out, "agents")
    except (ValueError, TypeError):
        return None


def relay() -> dict[str, dict[str, str | None]]:
    """Read local SSH unit state without starting or connecting anything."""
    res = {}
    for u in RELAY_UNITS:
        _rc, out = run(["systemctl", "show", u, "-p", "ActiveState,SubState,NRestarts,Result"])
        kv = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
        res[u] = {k: kv.get(k) for k in ("ActiveState", "SubState", "NRestarts", "Result")}
    return res


def peers() -> dict[str, bool]:
    """Read observed Tailscale peer availability only."""
    rc, out = run(["tailscale", "status", "--json"])
    if rc != 0:
        return {}
    try:
        d = json.loads(out)
    except (ValueError, TypeError):
        return {}
    if not isinstance(d, dict) or not isinstance(d.get("Peer"), dict):
        return {}
    return {
        p["HostName"]: bool(p.get("Online"))
        for p in d["Peer"].values()
        if isinstance(p, dict) and isinstance(p.get("HostName"), str)
    }


class MemoryState(TypedDict):
    """Private scheduler state; peer data is never executable."""

    unread_since: dict[str, float]
    needs_since: dict[str, float]
    sent: dict[str, float]
    pending: dict[str, str]
    peers: dict[str, bool]
    last_full: float
    mode: str
    notice_attempt: float
    notice_failures: int
    notice_rc: int
    ring_boot: str
    ring_evicted: int


def memory_state(value: object) -> MemoryState:
    """Refuse malformed private state before any notification effect."""
    if not isinstance(value, dict):
        raise TypeError("Malformed heartbeat memory")
    maps: dict[str, dict[str, float]] = {}
    for name in ("unread_since", "needs_since", "sent"):
        entries = value.get(name, {})
        if not isinstance(entries, dict) or not all(
            isinstance(k, str) and type(v) in (int, float) for k, v in entries.items()
        ):
            raise ValueError("Malformed heartbeat timestamp map")
        maps[name] = {k: number(v) for k, v in entries.items()}
    peer_values = value.get("peers", {})
    if not isinstance(peer_values, dict) or not all(
        isinstance(k, str) and type(v) is bool for k, v in peer_values.items()
    ):
        raise ValueError("Malformed heartbeat peers")
    pending = value.get("pending", {})
    if not isinstance(pending, dict) or not all(
        isinstance(k, str) and k.startswith(TRANSIENT) and isinstance(v, str) for k, v in pending.items()
    ):
        raise ValueError("Malformed heartbeat pending alerts")
    return {
        "unread_since": maps["unread_since"],
        "needs_since": maps["needs_since"],
        "sent": maps["sent"],
        "pending": pending,
        "peers": peer_values,
        "last_full": number(value.get("last_full")),
        "mode": "starting",
        "notice_attempt": number(value.get("notice_attempt")),
        "notice_failures": max(0, int(number(value.get("notice_failures")))),
        "notice_rc": int(number(value.get("notice_rc"))),
        "ring_boot": str(value.get("ring_boot", ""))[:MAX_BOOT_BYTES],
        "ring_evicted": max(0, int(number(value.get("ring_evicted")))),
    }


def main() -> int:
    """Run one heartbeat with a private nonblocking process lock."""
    dry = "--dry-run" in sys.argv
    secure_state_dir()
    lock_fd = os.open(STATE / "heartbeat.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    lock_stat = os.fstat(lock_fd)
    if (
        not stat.S_ISREG(lock_stat.st_mode)
        or lock_stat.st_uid != os.getuid()
        or stat.S_IMODE(lock_stat.st_mode) != PRIVATE_MODE
        or lock_stat.st_nlink != 1
    ):
        os.close(lock_fd)
        raise ValueError("heartbeat: invalid private lock file")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_fd)
        print("heartbeat: another run holds the lock; skipping")
        return 0
    try:
        SWEEP.end = time.monotonic() + READ_BUDGET_S
        return sweep(dry=dry)
    finally:
        SWEEP.end = math.inf
        os.close(lock_fd)


def agent_rows(
    ag: list[dict[str, object]] | None, mem: MemoryState, now: float, alerts: list[tuple[str, str]]
) -> tuple[list[dict[str, object]], set[str]]:
    """Collect tuios metadata and update age tracking without reading bodies."""
    rows: list[dict[str, object]] = []
    if ag is None:
        alerts.append(
            (
                "tuios-read",
                "heartbeat could not read tuios; mail and agent state UNKNOWN (not proof of delivery failure)",
            )
        )
        known = mem["unread_since"].keys() | mem["needs_since"].keys()
        return rows, {k for k in known if not k.startswith("hblocked:")}
    live: set[str] = set()
    for a in ag:
        wid = optional_string(a.get("window_id")) or ""
        live.add(wid)
        unread = int(number(a.get("unread")))
        needs = bool(a.get("needs_you"))
        if unread:
            mem["unread_since"].setdefault(wid, now)
        else:
            mem["unread_since"].pop(wid, None)
        if needs:
            mem["needs_since"].setdefault(wid, now)
        else:
            mem["needs_since"].pop(wid, None)
        label = f"{metadata(a.get('harness_id') or a.get('foreground') or '?')} {wid[:8]}"
        u_age = now - mem["unread_since"].get(wid, now)
        n_age = now - mem["needs_since"].get(wid, now)
        if unread and u_age >= STALE_MAIL_S:
            alerts.append((f"mail:{wid}", f"{label}: {unread} unread tuios message(s) for {int(u_age // 60)} min"))
        if needs and n_age >= NEEDS_YOU_S:
            alerts.append((f"needs:{wid}", f"{label}: waiting on you (approval/question) for {int(n_age // 60)} min"))
        rows.append(
            {
                "pane": wid,
                "harness": a.get("harness_id"),
                "state": a.get("state"),
                "unread": unread,
                "needs_you": needs,
                "draft_held": bool(a.get("draft_held")),
            }
        )
    return rows, live


def native_alerts(
    ha: list[dict[str, str | None]] | None, mem: MemoryState, now: float, alerts: list[tuple[str, str]]
) -> set[str]:
    """Track native blocked panes and retain only active pane ages."""
    live: set[str] = set()
    if ha is None:
        alerts.append(("herdr-read", "heartbeat could not read the native herdr socket; herdr agent state UNKNOWN"))
        live = {k for k in mem["needs_since"] if k.startswith("hblocked:")}
    else:
        for h in ha:
            key = f"hblocked:{h['pane']}"
            if h["status"] == "blocked":
                mem["needs_since"].setdefault(key, now)
                age = now - mem["needs_since"][key]
                if age >= NEEDS_YOU_S:
                    alerts.append(
                        (
                            f"needs:{key}",
                            f"herdr {h['agent']} {h['pane']}: blocked (approval/question) for {int(age // 60)} min",
                        )
                    )
            else:
                mem["needs_since"].pop(key, None)
        live |= {f"hblocked:{h['pane']}" for h in ha}

    return live


def relay_alerts(rl: dict[str, dict[str, str | None]], alerts: list[tuple[str, str]]) -> None:
    """Report an observed retry loop without operating SSH services."""
    failing = [u for u, s in rl.items() if s.get("SubState") == "auto-restart"]
    if failing:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        n = max(int(rl[u].get("NRestarts") or 0) for u in failing)
        alerts.append(
            (
                f"relay:{day}",
                (
                    f"SSH relay still failing: {', '.join(u.split('.')[0] for u in failing)} "
                    f"auto-restart, NRestarts={n} (known, unresolved; decision pending with Luke)"
                ),
            )
        )


def peer_alerts(pr: dict[str, bool], mem: MemoryState, alerts: list[tuple[str, str]]) -> None:
    """Report observed peer transitions without asserting agent reachability."""
    for host in WATCH_PEERS:
        was, isnow = mem["peers"].get(host), pr.get(host)
        if isnow is not None and was is not None and isnow != was:
            alerts.append(
                (
                    f"peer:{host}:{isnow}",
                    f"Tailscale reports peer {host} {'online' if isnow else 'offline'} (SSH reachability unverified)",
                )
            )
        if isnow is not None:
            mem["peers"][host] = isnow


def sweep(*, dry: bool) -> int:
    """Perform one serialized observation and persist deduplication state."""
    now = time.time()
    mem = memory_state(load("memory.json", {}))
    alerts: list[tuple[str, str]] = []

    ag = agents()
    is_active, reasons = activity(ag or [])
    last_full = number(mem.get("last_full"))
    if "--full" not in sys.argv and not dry and not is_active and ag is not None and now - last_full < QUIET_FULL_S:
        mem["mode"] = "quiet-skip"
        save("memory.json", mem)
        return 0
    mem["last_full"] = now
    mem["mode"] = "active" if is_active else "quiet-full"
    previous_boot = mem["ring_boot"]
    boot = ring_alert(mem, alerts)
    if boot is not None and previous_boot and boot != previous_boot:
        forget_tuios_tracking(mem)
    rows, live = agent_rows(ag, mem, now, alerts)
    ha = herdr_agents()
    live |= native_alerts(ha, mem, now, alerts)
    mem["unread_since"] = {k: v for k, v in mem["unread_since"].items() if k in live}
    mem["needs_since"] = {k: v for k, v in mem["needs_since"].items() if k in live}
    rl = relay()
    relay_alerts(rl, alerts)
    pr = peers()
    peer_alerts(pr, mem, alerts)
    board: dict[str, object] = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "agents": rows,
        "relay": rl,
        "peers": pr,
        "herdr": None
        if ha is None
        else {
            "agents": len(ha),
            "by_status": {
                st: sum(1 for h in ha if h["status"] == st) for st in sorted({h["status"] or "?" for h in ha})
            },
            "blocked": [h["pane"] for h in ha if h["status"] == "blocked"],
        },
        "ring": {"boot": mem["ring_boot"], "evicted": mem["ring_evicted"]},
        "alerts": [t for _, t in alerts],
        "flex": {"mode": mem["mode"], "reasons": reasons, "tick_s": 120, "quiet_full_s": QUIET_FULL_S},
    }

    return finish(board, mem, alerts, now, dry=dry)


def notify(new: list[tuple[str, str]], mem: MemoryState, now: float) -> None:
    """Bound human notices and back off failures; never automatically invoke models."""
    backoff = min(3600, 300 * 2 ** min(mem["notice_failures"], 4))
    if mem["notice_failures"] and now - mem["notice_attempt"] < backoff:
        return
    selected = new[:16]
    body = (
        "Collective heartbeat: passive checks; change-only alerts.\n- "
        + "\n- ".join(metadata(text, 256) for _, text in selected)
        + f"\nAdditional pending alerts: {len(new) - len(selected)}. "
        "Full board: ~/.local/state/collective/heartbeat.json"
    )
    body = body.encode("utf-8")[:7000].decode("utf-8", errors="ignore")
    mem["notice_attempt"] = now
    # Persist intent before sending; a process interruption must also observe backoff.
    mem["notice_failures"] += 1
    save("memory.json", mem)
    rc, _ = run(
        [TUIOS, "send-agent-message", "-s", SESSION, "-w", "human", "--subject", "collective heartbeat", body],
        NOTICE_S,
        reserved=True,
    )
    mem["notice_rc"] = rc
    if rc == 0:
        mem["notice_failures"] = 0
        for key, _ in selected:
            mem["sent"][key] = now


def forget_tuios_tracking(mem: MemoryState) -> None:
    """After a verified tuios daemon restart, drop pre-restart mail/needs ages and their acknowledgements."""
    mem["unread_since"] = {}
    mem["needs_since"] = {k: v for k, v in mem["needs_since"].items() if k.startswith("hblocked:")}
    mem["sent"] = {
        k: v for k, v in mem["sent"].items() if not k.startswith(("mail:", "needs:")) or k.startswith("needs:hblocked:")
    }


def ring_alert(mem: MemoryState, alerts: list[tuple[str, str]]) -> str | None:
    """Observe ring loss once per daemon boot; return the verified boot, or None when it is unknown."""
    before_rc, before_text = run([TUIOS, "call", "list-attention", "{}"])
    ring_rc, ring_text = run([TUIOS, "read-agent-messages", "-s", SESSION, "--limit", "1", "--json"])
    after_rc, after_text = run([TUIOS, "call", "list-attention", "{}"])
    if before_rc or ring_rc or after_rc:
        return None
    try:
        before, ring, after = (json.loads(text) for text in (before_text, ring_text, after_text))
        if not all(isinstance(row, dict) for row in (before, ring, after)):
            return None
        boot = before.get("boot_id")
        if not isinstance(boot, str) or not boot or len(boot) > MAX_BOOT_BYTES or after.get("boot_id") != boot:
            return None
        evicted = max(0, int(number(ring.get("evicted"))))
        previous = mem["ring_evicted"] if mem["ring_boot"] == boot else 0
        if evicted > previous:
            alerts.append(
                (
                    f"ring-loss:{metadata(boot)}",
                    f"Tuios ring reports {evicted} evicted messages in this daemon boot; history incomplete",
                )
            )
        mem["ring_boot"], mem["ring_evicted"] = boot, evicted
    except (ValueError, TypeError):
        return None
    return boot


def finish(board: dict[str, object], mem: MemoryState, alerts: list[tuple[str, str]], now: float, *, dry: bool) -> int:
    """Deduplicate alerts and atomically publish private scheduler state."""
    fresh = {k.rsplit(":", 1)[0] for k, _ in alerts if k.startswith(TRANSIENT)}
    alerts = alerts + [(k, t) for k, t in mem["pending"].items() if k.rsplit(":", 1)[0] not in fresh]
    active = {k for k, _ in alerts}
    # Resolvable conditions keep their acknowledgement while active or tracked (including through a
    # failed read) and are forgotten on resolution, so a recurrence alerts again. Reminder and obsolete
    # keys (relay day, ring-loss boot, peer transitions) expire after OBSOLETE_S.
    tracked = {f"mail:{k}" for k in mem["unread_since"]} | {f"needs:{k}" for k in mem["needs_since"]}
    mem["sent"] = {
        k: v
        for k, v in mem["sent"].items()
        if (
            (k in active or k in tracked)
            if k.startswith(RESOLVABLE) and not k.startswith("peer:")
            else now - v < OBSOLETE_S
        )
    }
    for h in WATCH_PEERS:
        if f"peer:{h}:True" in active:
            mem["sent"].pop(f"peer:{h}:False", None)
        if f"peer:{h}:False" in active:
            mem["sent"].pop(f"peer:{h}:True", None)
    new = [(k, t) for k, t in alerts if k not in mem["sent"]]
    if dry:
        print(json.dumps(board, indent=2))
        print("WOULD SEND:" if new else "nothing new to send", *[t for _, t in new], sep="\n  ")
        return 0
    mem["pending"] = {k: t for k, t in alerts if k.startswith(TRANSIENT) and k not in mem["sent"]}
    save("heartbeat.json", board)
    if new:
        notify(new, mem, now)
        mem["pending"] = {k: t for k, t in mem["pending"].items() if k not in mem["sent"]}
    save("memory.json", mem)
    return 0


if __name__ == "__main__":
    sys.exit(main())
