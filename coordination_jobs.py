"""Bounded metadata-only coordination jobs; never send mail, wake agents, run tests or retry effects.

One invocation produces one private receipt. Ring observations are bounded,
volatile transport evidence; owner names and replies are claims, not identity
proof, task acceptance or completion. Existing heartbeat owns all notifications.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
import selectors
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, TypeGuard, cast

if TYPE_CHECKING:
    from collections.abc import Iterator

ROOT = Path(__file__).resolve().parent
MAX_OUTPUT = 2_000_000
READ_TIMEOUT = 20.0
PRIVATE_MODE = 0o600
JOBS = ("collaboration", "cohesion")
MAX_SOURCE_BYTES = 262144
SOURCES = ("roster", "ring", "tasks")
MAX_ROWS = 4096
MAX_LABEL = 64
MAX_GROUPS = 128

type JsonDict = dict[str, Any]


def _local_module(name: str) -> Any:  # noqa: ANN401 - audited local modules, no caller-supplied module name
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load local helper {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


if TYPE_CHECKING:
    import install_monitor as monitor
    import private_files
else:
    monitor = _local_module("install_monitor")
    private_files = _local_module("private_files")


@dataclass
class CommandResult:
    """Bounded process outcome; untrusted stderr never becomes receipt content."""

    status: str
    code: int | None
    output: bytes = b""


def state_dir() -> Path:
    """Return the private job state directory, creating private missing ancestors."""
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return cast("Path", monitor.private_dir(base / "collective/coordination"))


def _kill(proc: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)
    proc.wait()


def _pipe_fd(pipe: IO[bytes] | None) -> int:
    if pipe is None:
        raise OSError("Missing process output pipe")
    return pipe.fileno()


def _run(argv: list[str], *, timeout: float) -> CommandResult:
    """Run fixed internal argv with bounded output and total duration."""
    output, errors = bytearray(), bytearray()
    deadline = time.monotonic() + timeout
    try:
        with subprocess.Popen(  # noqa: S603 - internal fixed read argv; no shell or caller command
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            umask=0o077,
        ) as proc:
            try:
                with selectors.DefaultSelector() as poll:
                    for pipe, target in ((proc.stdout, output), (proc.stderr, errors)):
                        fd = _pipe_fd(pipe)
                        os.set_blocking(fd, False)
                        poll.register(fd, selectors.EVENT_READ, target)
                    while poll.get_map():
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            _kill(proc)
                            return CommandResult("timeout", None)
                        for key, _ in poll.select(remaining):
                            chunk = os.read(key.fd, 65536)
                            if not chunk:
                                poll.unregister(key.fileobj)
                                continue
                            if len(output) + len(errors) + len(chunk) > MAX_OUTPUT:
                                _kill(proc)
                                return CommandResult("output_limit", None)
                            key.data.extend(chunk)
                    proc.wait(timeout=max(0.001, deadline - time.monotonic()))
            except BaseException:
                _kill(proc)
                raise
        return CommandResult("ok" if proc.returncode == 0 else "nonzero", proc.returncode, bytes(output))
    except subprocess.TimeoutExpired:
        return CommandResult("timeout", None)
    except OSError:
        return CommandResult("unavailable", None)


def _source(name: str, session: str) -> tuple[list[JsonDict], JsonDict]:
    methods = {
        "roster": ("list-agents", "agents"),
        "ring": ("read-agent-messages", "messages"),
        "tasks": ("list-tasks", "tasks"),
    }
    verb, key = methods[name]
    params: JsonDict = {"session": session}
    if name == "ring":
        params["limit"] = 256
    binary = os.environ.get("TUIOS_BIN", str(Path.home() / ".local/bin/tuios"))
    argv = [binary, "call", verb, json.dumps(params, separators=(",", ":"))]
    if name == "tasks":
        argv = [binary, "task", "ls", "-s", session, "--json"]
    outcome = _run(argv, timeout=READ_TIMEOUT)
    if outcome.status != "ok":
        return [], {"status": outcome.status, "count": 0}
    try:
        value: Any = private_files.parse_json(outcome.output)
        if isinstance(value, dict) and "result" in value:
            value = value["result"]
        rows = value.get(key) if isinstance(value, dict) and not value.get("error") else None
        if not isinstance(rows, list) or len(rows) > MAX_ROWS or not all(isinstance(row, dict) for row in rows):
            return [], {"status": "malformed", "count": 0}
        metadata: JsonDict = {"status": "ok", "count": len(rows)}
        if name == "ring":
            count = value.get("evicted")
            metadata["evicted"] = count if type(count) is int and count >= 0 else None
            metadata["complete_history"] = False
    except ValueError:
        return [], {"status": "malformed", "count": 0}
    return rows, metadata


def _valid_label(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and 0 < len(value) <= MAX_LABEL and value.isprintable()


def _counts(rows: list[JsonDict], field: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        value = row.get(field)
        key = value if _valid_label(value) else "unknown"
        if key not in result and len(result) >= MAX_GROUPS - 1:
            key = "other_groups"
        result[key] = result.get(key, 0) + 1
    return result


def _task_metrics(tasks: list[JsonDict]) -> tuple[JsonDict, list[str]]:
    """Measure actual task holder/block objects; keep unavailable ownership explicit."""
    normalized: list[JsonDict] = []
    gaps: set[str] = set()
    evidence = {"reported": 0, "absent": 0, "invalid": 0}
    blocked = unknown_blocked = 0
    for task in tasks:
        owner = task.get("owner")
        if _valid_label(owner):
            evidence["reported"] += 1
        else:
            evidence["absent" if owner is None else "invalid"] += 1
            if owner is not None:
                gaps.add("tasks.owner")
            owner = None
        holder = task.get("holder")
        if "holder" in task and holder is None:
            holder_claim = "unheld"
        elif isinstance(holder, dict) and _valid_label(holder.get("window")):
            holder_claim = holder["window"]
        else:
            holder_claim = None
            gaps.add("tasks.holder")
        if "blocked" not in task or (task["blocked"] is not None and not isinstance(task["blocked"], dict)):
            unknown_blocked += 1
            gaps.add("tasks.blocked")
        else:
            blocked += isinstance(task["blocked"], dict)
        normalized.append({"owner": owner, "holder": holder_claim})
    return {
        "task_owners": _counts(normalized, "owner"),
        "task_owner_evidence": evidence,
        "task_owner_measurement": "Optional explicit owner claims only; absent fields remain unmeasured",
        "task_holders": _counts(normalized, "holder"),
        "blocked_tasks": blocked,
        "blocked_tasks_unknown": unknown_blocked,
    }, sorted(gaps)


def _metrics(observed: dict[str, list[JsonDict]]) -> JsonDict:
    agents, messages, tasks = (observed[name] for name in SOURCES)
    threads: dict[int, int] = {}
    delivered = read = replies = stalled = 0
    response_threads: set[int] = set()
    for message in messages:
        identifier = message.get("thread_id") or message.get("id")
        if type(identifier) is int and identifier > 0:
            threads[identifier] = threads.get(identifier, 0) + 1
        delivered += type(message.get("id")) is int and message["id"] > 0
        read += type(message.get("read_at")) is int and message["read_at"] > 0
        is_reply = type(message.get("reply_to")) is int and message["reply_to"] > 0
        replies += is_reply
        if is_reply and type(identifier) is int and identifier > 0:
            response_threads.add(identifier)
        stalled += message.get("kind") == "stalled" or message.get("status") == "stalled"
    return {
        "observed_agents": len(agents),
        "agent_states": _counts(agents, "state"),
        "draft_held": sum(a.get("draft_held") is True for a in agents),
        "needs_you": sum(a.get("needs_you") is True for a in agents),
        **_task_metrics(tasks)[0],
        "task_stages": _counts(tasks, "stage"),
        "ring_stored": delivered,
        "ring_marked_read": read,
        "reply_links": replies,
        "threads_observed": len(threads),
        "threads_with_reply_links": len(response_threads),
        "threads_without_reply_links": len(threads.keys() - response_threads),
        "threads_with_multiple_entries": sum(n > 1 for n in threads.values()),
        "explicit_stalled_entries": stalled,
        "acceptance": "Not inferred from submission, read flags, replies, owner names or task stage claims",
    }


def _metadata_job(session: str) -> JsonDict:
    observed: dict[str, list[JsonDict]] = {}
    sources: JsonDict = {}
    for name in SOURCES:
        observed[name], sources[name] = _source(name, session)
    metric_gaps = _task_metrics(observed["tasks"])[1] if sources["tasks"]["status"] == "ok" else []
    gaps = [name for name in SOURCES if sources[name]["status"] != "ok"] + metric_gaps
    return {
        "status": "degraded" if gaps else "ok",
        "sources": sources,
        "source_gaps": gaps,
        "metric_gaps": metric_gaps,
        "metrics": _metrics(observed),
        "history": "Bounded volatile ring snapshot; no completeness or delivery guarantee",
        "observation_atomic": False,
        "metric_group_limit": MAX_GROUPS,
    }


@contextlib.contextmanager
def _job_lock(path: Path) -> Iterator[bool]:
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, PRIVATE_MODE)
    try:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != PRIVATE_MODE
            or metadata.st_nlink != 1
        ):
            raise ValueError("Invalid private job lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            yield True
    finally:
        os.close(fd)


def run_job(job: str) -> JsonDict:
    """Run one named fixed job and atomically save its metadata-only private receipt."""
    if job not in JOBS:
        raise ValueError("Unknown coordination job")
    directory = state_dir()
    with _job_lock(directory / f"{job}.lock") as claimed:
        if not claimed:
            return {"job": job, "status": "skipped", "reason": "already_running"}
        session = os.environ.get("COLLECTIVE_SESSION", "session-0")
        if not session or ":" in session:
            raise ValueError("An explicit local session is required")
        started = time.monotonic()
        result = _metadata_job(session)
        receipt = {
            "schema": 1,
            "job": job,
            "generated_utc": dt.datetime.now(dt.UTC).isoformat(),
            "source_sha256": hashlib.sha256(
                private_files.read_owned_bytes(ROOT / "coordination_jobs.py", limit=MAX_SOURCE_BYTES)
            ).hexdigest(),
            "duration_s": round(time.monotonic() - started, 3),
            **result,
        }
        monitor.atomic(directory / f"{job}.json", (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode())
        return receipt


def main() -> int:
    """Execute a bounded named job; report failure without exposing external output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", choices=JOBS, required=True)
    args = parser.parse_args()
    try:
        receipt = run_job(args.job)
        print(json.dumps({"job": args.job, "status": receipt["status"]}))
    except (OSError, ValueError, monitor.CollectiveError) as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}), file=sys.stderr)
        return 1
    return 1 if receipt["status"] in {"failed", "degraded"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
