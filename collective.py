#!/usr/bin/env python3
"""Collective: local, read-only observations and explicitly planned tuios mail.

Uses Python's standard library. No shell evaluation, autonomous replies, SSH
connections, plugin registration, or permission changes are performed here.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import datetime as dt
import fcntl
import hashlib
import hmac
import importlib.util
import json
import os
import select
import selectors
import shutil
import socket
import stat
import struct
import subprocess
import sys
import time
import unicodedata
import uuid
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Protocol, cast

_files_spec = importlib.util.spec_from_file_location(
    "collective_private_files", Path(__file__).with_name("private_files.py")
)
if _files_spec is None or _files_spec.loader is None:
    raise ImportError("Cannot load reviewed private file readers")
_private_files = importlib.util.module_from_spec(_files_spec)
_files_spec.loader.exec_module(_private_files)
read_owned_bytes = _private_files.read_owned_bytes
parse_json = _private_files.parse_json

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


class BackendLike(Protocol):
    """What the core needs from a backend; the real Backend and test fakes both satisfy it."""

    def tuios(self, verb: str, params: JsonDict) -> JsonDict: ...
    def snapshot(self, session: object) -> JsonDict: ...
    def run(self, argv: list[str], *, as_json: bool = True) -> Any: ...  # noqa: ANN401 - JSON value or text
    def roster(self, session: str) -> JsonDict: ...
    def history(self, cwd: str | None = None) -> JsonDict: ...
    def memory(self, since: str | None = None) -> JsonDict: ...
    def ssh_health(self) -> JsonDict: ...


type JsonDict = dict[str, Any]

TTL = 300
MAX_BODY = 8192
MAX_SUBJECT = 120
MAX_FIELD = 2048
MAX_EVIDENCE_ITEMS = 16
MAX_EVIDENCE_BYTES = 512
MAX_JOURNAL_BYTES = 8_000_000
MAX_TOOL_OUTPUT = 2_000_000
MAX_PLAN_BYTES = 65536
READ_CHUNK = 65536
RATE_LIMIT = 10
RATE_WINDOW_SECONDS = 60
REFUSAL_CODES = frozenset(
    {
        "invalid_request",
        "unknown_verb",
        "invalid_params",
        "session_not_found",
        "window_not_found",
        "forbidden",
        "not_human",
        "loop_refused",
        "rate_limited",
        "agents_disabled",
    },
)
RING_LIMIT = 100
MAIL_IDS_KEPT = 512
WATCH_SECONDS = 10
PRIVATE_FILE_MODE = 0o600
COLLABORATION_KINDS = ("intent", "milestone", "blocker", "handoff", "review")
PLAN_KEYS = {
    "schema",
    "action",
    "request_id",
    "issued_at",
    "expires_at",
    "endpoint",
    "boot_id",
    "sender_identity",
    "recipient_identity",
    "payload",
    "digest",
}
PAYLOAD_KEYS = {"session", "from", "to", "subject", "text", "reply_to"}


class CollectiveError(Exception):
    """An operation was refused or could not be completed."""


class TransportUncertain(CollectiveError):  # noqa: N818 - public API name relied on by callers and tests
    """A timeout means a submitted operation may already have happened."""


def canonical(value: object) -> str:
    """Serialise to the canonical JSON used for digests and wire requests."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def clean(value: object) -> str:
    """Render external metadata without terminal escapes or hidden controls."""
    return "".join(c if c.isprintable() or c in "\n\t" else "?" for c in str(value))


def pane_uuid(value: object) -> str:
    """Normalise a pane UUID, refusing names and the human inbox."""
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        msg = "An explicit pane UUID is required; names/human are not accepted"
        raise CollectiveError(msg) from exc


def _is_refused_char(c: str, *, multiline: bool) -> bool:
    if multiline and c in "\n\t":
        return False
    return unicodedata.category(c) in {"Cc", "Cf"}


def plain_text(value: object, limit: int, *, multiline: bool = True) -> str:
    """Return value if it is non-empty text within limit bytes and free of control and hidden characters."""
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > limit:
        msg = f"Text must contain 1..{limit} UTF-8 bytes"
        raise CollectiveError(msg)
    if any(_is_refused_char(c, multiline=multiline) for c in value):
        msg = "Control, bidi, and hidden format characters are refused"
        raise CollectiveError(msg)
    return value


def member(snapshot: JsonDict, session: str, pane: object) -> dict[str, str]:
    """Return the identity record of exactly one current agent pane in the session."""
    pane = pane_uuid(pane)
    found = [
        a for a in snapshot.get("agents", []) if a.get("window_id") == pane and a.get("session", session) == session
    ]
    if len(found) != 1 or not found[0].get("foreground"):
        msg = "Pane is not a current agent in the explicit session"
        raise CollectiveError(msg)
    a = found[0]
    return {
        "window_id": pane,
        "session": session,
        "agent_session_id": a.get("agent_session_id") or "",
        "foreground": a.get("foreground") or "",
        "harness_id": a.get("harness_id") or "",
    }


def plan_digest(plan: JsonDict) -> str:
    """Return the sha256 of the canonical plan without its digest field."""
    return hashlib.sha256(canonical({k: v for k, v in plan.items() if k != "digest"}).encode()).hexdigest()


def make_mail_plan(  # noqa: PLR0913, PLR0917 - every parameter is a plan field; callers pass them positionally
    snapshot: JsonDict,
    session: object,
    sender: object,
    recipient: object,
    subject: str,
    text: str,
    reply_to: int | None = None,
    now: object = None,
    request_id: str | None = None,
) -> JsonDict:
    """Build a private, digest-sealed plan for one local tuios message. Nothing is sent."""
    now = int(time.time()) if now is None else now
    if type(now) is not int or not isinstance(session, str) or not session or ":" in session:
        msg = "Local session and integer timestamp required"
        raise CollectiveError(msg)
    sender, recipient = pane_uuid(sender), pane_uuid(recipient)
    if sender == recipient:
        msg = "Self messaging is refused"
        raise CollectiveError(msg)
    plain_text(subject, MAX_SUBJECT, multiline=False)
    plain_text(text, MAX_BODY)
    if reply_to is not None and (type(reply_to) is not int or reply_to <= 0):
        msg = "Reply ID must be a positive integer"
        raise CollectiveError(msg)
    if not isinstance(snapshot.get("boot_id"), str) or not snapshot["boot_id"]:
        msg = "A current daemon boot ID is required"
        raise CollectiveError(msg)
    if not isinstance(snapshot.get("endpoint"), str) or not snapshot["endpoint"]:
        msg = "An explicit transport endpoint is required"
        raise CollectiveError(msg)
    payload: JsonDict = {"session": session, "from": sender, "to": recipient, "subject": subject, "text": text}
    if reply_to is not None:
        payload["reply_to"] = reply_to
    plan: JsonDict = {
        "schema": 1,
        "action": "tuios.mail",
        "request_id": pane_uuid(request_id or str(uuid.uuid4())),
        "issued_at": now,
        "expires_at": now + TTL,
        "endpoint": snapshot["endpoint"],
        "boot_id": snapshot["boot_id"],
        "sender_identity": member(snapshot, session, sender),
        "recipient_identity": member(snapshot, session, recipient),
        "payload": payload,
    }
    plan["digest"] = plan_digest(plan)
    return plan


def validate_mail_plan(plan: object, snapshot: JsonDict, confirmation: object, now: int | None = None) -> JsonDict:
    """Return the payload only if the plan is intact, confirmed, unexpired and still matches live identities."""
    now = int(time.time()) if now is None else now
    if not isinstance(plan, dict) or set(plan) != PLAN_KEYS:
        msg = "Unknown or missing plan fields"
        raise CollectiveError(msg)
    if type(plan["schema"]) is not int or plan["schema"] != 1 or plan["action"] != "tuios.mail":
        msg = "Only schema-1 local tuios mail is supported"
        raise CollectiveError(msg)
    issued, expires = plan["issued_at"], plan["expires_at"]
    if type(issued) is not int or type(expires) is not int or expires != issued + TTL or not issued <= now < expires:
        msg = "Plan is expired, future-dated, or has an invalid lifetime"
        raise CollectiveError(msg)
    digest = plan_digest(plan)
    if not isinstance(confirmation, str) or not isinstance(plan["digest"], str):
        msg = "Exact plan digest confirmation required"
        raise CollectiveError(msg)
    if not hmac.compare_digest(digest, confirmation) or not hmac.compare_digest(digest, plan["digest"]):
        msg = "Plan digest changed or confirmation does not match"
        raise CollectiveError(msg)
    p = plan["payload"]
    if not isinstance(p, dict) or set(p) - PAYLOAD_KEYS or not PAYLOAD_KEYS - {"reply_to"} <= set(p):
        msg = "Unexpected mail payload fields"
        raise CollectiveError(msg)
    expected = make_mail_plan(
        snapshot,
        p["session"],
        p["from"],
        p["to"],
        p["subject"],
        p["text"],
        p.get("reply_to"),
        issued,
        plan["request_id"],
    )
    if expected != plan:
        msg = "Endpoint, daemon boot, or agent identity changed; prepare a new plan"
        raise CollectiveError(msg)
    return dict(p)


def make_collaboration_plan(  # noqa: PLR0913, PLR0917 - every parameter is a collaboration field; positional callers
    snapshot: JsonDict,
    session: object,
    sender: object,
    reviewer: object,
    kind: str,
    goal: str,
    scope: str,
    done: str,
    evidence: object = None,
    now: object = None,
    request_id: str | None = None,
) -> JsonDict:
    """Build a shared owner/reviewer handoff plan, delivered by the same mail gate."""
    if kind not in COLLABORATION_KINDS:
        msg = "Unknown collaboration update kind"
        raise CollectiveError(msg)
    sender, reviewer = pane_uuid(sender), pane_uuid(reviewer)
    if sender == reviewer:
        msg = "Owner and reviewer must be distinct current panes"
        raise CollectiveError(msg)
    for value in (goal, scope, done):
        plain_text(value, MAX_FIELD)
    items: list[object] = []
    if evidence is not None:
        if not isinstance(evidence, list) or len(evidence) > MAX_EVIDENCE_ITEMS:
            msg = "Evidence must be a list of at most sixteen references"
            raise CollectiveError(msg)
        items = evidence
    for item in items:
        plain_text(item, MAX_EVIDENCE_BYTES, multiline=False)
    body = json.dumps(
        {
            "collective_schema": 1,
            "kind": kind,
            "owner": sender,
            "reviewer": reviewer,
            "goal": goal,
            "scope": scope,
            "definition_of_done": done,
            "evidence": items,
            "authority": "Peer coordination data within the current user-authorized task",
        },
        indent=2,
        ensure_ascii=True,
    )
    return make_mail_plan(
        snapshot, session, sender, reviewer, f"Collective {kind}", body, now=now, request_id=request_id
    )


def private_dir(path: str | os.PathLike[str]) -> Path:
    """Create or accept a directory owned by the current user with mode 0700; refuse symlinks."""
    path = Path(path)
    if path.is_symlink():
        msg = "Symlink state directories are refused"
        raise CollectiveError(msg)
    if not path.parent.exists():
        private_dir(path.parent)
    path.mkdir(mode=0o700, exist_ok=True)
    st = path.stat()
    if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
        msg = "State directory must be owned by you and mode 0700"
        raise CollectiveError(msg)
    return path


def _is_private_regular(st: os.stat_result) -> bool:
    return (
        stat.S_ISREG(st.st_mode)
        and st.st_uid == os.getuid()
        and stat.S_IMODE(st.st_mode) == PRIVATE_FILE_MODE
        and st.st_nlink == 1
    )


@contextlib.contextmanager
def locked_private_file(path: str | os.PathLike[str], *, blocking: bool = True) -> Iterator[IO[str]]:
    """Open a private, single-link regular file under an exclusive flock; fsync on clean exit."""
    path = Path(path)
    private_dir(path.parent)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK, PRIVATE_FILE_MODE)
    try:
        if not _is_private_regular(os.fstat(fd)):
            msg = "Journal must be an owned, private regular file with one link"
            raise CollectiveError(msg)
        with os.fdopen(fd, "r+", encoding="utf-8") as f:
            fd = -1
            try:
                fcntl.flock(f, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError as exc:
                msg = "A communications sweep is already running"
                raise CollectiveError(msg) from exc
            yield f
            f.flush()
            os.fsync(f.fileno())
    finally:
        if fd != -1:
            os.close(fd)


def _journal_rows(f: IO[str]) -> list[JsonDict]:
    try:
        rows = [parse_json(line) for line in f if line.strip()]
    except ValueError as exc:
        msg = "Journal is corrupt; refuse writes until reviewed"
        raise CollectiveError(msg) from exc
    if not all(isinstance(r, dict) for r in rows):
        msg = "Journal is corrupt; refuse writes until reviewed"
        raise CollectiveError(msg)
    return rows


class Journal:
    """Append-only, one-use record of mail intents and outcomes (hashes only, never bodies)."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)

    def consume(self, plan: JsonDict) -> None:
        """Record intent BEFORE submission; refuse a reused plan or a sender over the rate limit."""
        with locked_private_file(self.path) as f:
            f.seek(0)
            if os.fstat(f.fileno()).st_size > MAX_JOURNAL_BYTES:
                msg = "Journal exceeds 8 MB; archive under operator review before further writes"
                raise CollectiveError(msg)
            rows = _journal_rows(f)
            if any(r.get("digest") == plan["digest"] or r.get("request_id") == plan["request_id"] for r in rows):
                msg = "Plan already consumed; never automatically resend"
                raise CollectiveError(msg)
            p = plan["payload"]
            now = time.time()
            recent = [
                r
                for r in rows
                if r.get("outcome") == "intent"
                and r.get("sender") == p["from"]
                and r.get("time", 0) > now - RATE_WINDOW_SECONDS
            ]
            if len(recent) >= RATE_LIMIT:
                msg = "Local rate limit: at most ten mail intents per sender per minute"
                raise CollectiveError(msg)
            f.write(
                canonical(
                    {
                        "time": now,
                        "outcome": "intent",
                        "digest": plan["digest"],
                        "request_id": plan["request_id"],
                        "session": p["session"],
                        "sender": p["from"],
                        "recipient": p["to"],
                        "body_sha256": hashlib.sha256(p["text"].encode()).hexdigest(),
                        "body_bytes": len(p["text"].encode()),
                    },
                )
                + "\n",
            )

    def record(self, digest: str, outcome: str) -> None:
        """Append one outcome line for a consumed plan."""
        with locked_private_file(self.path) as f:
            f.write(canonical({"time": int(time.time()), "digest": digest, "outcome": outcome}) + "\n")


def _require_confirmed_receipt(result: object) -> JsonDict:
    if (
        not isinstance(result, dict)
        or ("success" in result and result["success"] is not True)
        or result.get("error") is not None
        or type(result.get("message_id")) is not int
        or result["message_id"] <= 0
    ):
        msg = "Mail receipt is not a confirmed submission; inspect inbox before a new plan"
        raise TransportUncertain(msg)
    return result


MAIL_OUTCOME_UNKNOWN = (
    "mail submission outcome unknown and it may already be delivered; "
    "inspect recipient inbox before any new plan and never resend blindly"
)


def _record_outcome(journal: Journal, digest: str, outcome: str) -> str:
    """Persist the final outcome; on failure return a note instead of masking the delivery result."""
    try:
        journal.record(digest, outcome)
    except (OSError, CollectiveError) as exc:
        return f"; final journal recording failed ({type(exc).__name__}); plan stays consumed"
    return ""


def apply_mail_plan(
    plan: object,
    confirmation: object,
    backend: BackendLike,
    journal: Journal,
    now: int | None = None,
) -> JsonDict:
    """Validate, journal intent, submit once; a timeout or unconfirmed receipt is UNKNOWN, never retried."""
    if not isinstance(plan, dict) or not isinstance(plan.get("payload"), dict):
        msg = "Malformed plan"
        raise CollectiveError(msg)
    session = plan["payload"].get("session")
    payload = validate_mail_plan(plan, backend.snapshot(session), confirmation, now)
    journal.consume(plan)  # Durable intent is committed BEFORE submission.
    digest = plan["digest"]
    try:
        result = _require_confirmed_receipt(backend.tuios("send-agent-message", payload))
    except TransportUncertain as exc:
        note = _record_outcome(journal, digest, "unknown")
        msg = f"{exc}; {MAIL_OUTCOME_UNKNOWN}{note}"
        raise TransportUncertain(msg) from exc
    except CollectiveError as exc:
        note = _record_outcome(journal, digest, "refused")
        if note:
            msg = f"{exc}{note}"
            raise CollectiveError(msg) from exc
        raise
    except Exception as exc:
        note = _record_outcome(journal, digest, "unknown")
        msg = f"{MAIL_OUTCOME_UNKNOWN}{note}"
        raise TransportUncertain(msg) from exc
    receipt: JsonDict = {
        "outcome": "submitted",
        "digest": digest,
        "receipt": result,
        "acknowledgement": "Submission is not a peer reply or acceptance",
    }
    note = _record_outcome(journal, digest, "submitted")
    if note:
        receipt["journal"] = note.removeprefix("; ")
    return receipt


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        msg = "Command timed out"
        raise TransportUncertain(msg)
    return remaining


def _check_output_cap(output: bytearray, errors: bytearray) -> None:
    if len(output) + len(errors) > MAX_TOOL_OUTPUT:
        msg = "Tool output exceeded 2 MB"
        raise TransportUncertain(msg)


def _check_native_peer(s: socket.socket) -> None:
    if hasattr(socket, "SO_PEERCRED"):
        credentials = s.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _, peer_uid, _ = struct.unpack("3i", credentials)
        if peer_uid != os.getuid():
            msg = "Herdr socket peer must be owned by the current user"
            raise CollectiveError(msg)


def _recv_frame(s: socket.socket, deadline: float) -> bytearray:
    response = bytearray()
    while b"\n" not in response:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            msg = "Herdr socket response deadline exceeded"
            raise CollectiveError(msg)
        s.settimeout(remaining)
        part = s.recv(READ_CHUNK)
        if not part:
            msg = "Herdr socket closed before its response"
            raise CollectiveError(msg)
        if len(response) + len(part) > MAX_TOOL_OUTPUT:
            msg = "Herdr socket response too large"
            raise CollectiveError(msg)
        response.extend(part)
    if response.split(b"\n", 1)[1].strip():
        raise CollectiveError("Herdr socket returned trailing data")
    # Inspect bytes already queued, without waiting for hypothetical future traffic.
    s.settimeout(0.0)
    while True:
        _remaining(deadline)
        try:
            part = s.recv(READ_CHUNK)
        except BlockingIOError:
            break
        if not part:
            break
        if len(response) + len(part) > MAX_TOOL_OUTPUT or part.strip():
            raise CollectiveError("Herdr socket returned excess or trailing data")
        response.extend(part)
    return response


def _refusal_code(value: object) -> str | None:
    """Recognize documented request rejections, never generic tool failures."""
    error = value.get("error") if isinstance(value, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) and code in REFUSAL_CODES else None


def _parse_tool_result(
    argv: list[str],
    returncode: int,
    output: bytearray,
    errors: bytearray,
    *,
    as_json: bool,
) -> Any:  # noqa: ANN401 - JSON value or text by flag
    stdout = output.decode("utf-8", errors="replace")
    if returncode:
        envelope: object = None
        with contextlib.suppress(ValueError):
            envelope = parse_json(stdout or errors.decode("utf-8", errors="replace"))
        code = _refusal_code(envelope)
        if code is not None:
            msg = f"{Path(argv[0]).name}: {code} (exit {returncode})"
            raise CollectiveError(msg)
        msg = f"{Path(argv[0]).name}: command_failed (exit {returncode})"
        raise TransportUncertain(msg)
    if not as_json:
        return stdout
    try:
        value = parse_json(stdout)
    except ValueError as exc:
        # The process ran and exited 0, so any write it carried may already have happened: UNKNOWN, not refused.
        msg = "Tool returned non-JSON data"
        raise TransportUncertain(msg) from exc
    if isinstance(value, dict) and value.get("error") is not None:
        if _refusal_code(value) is not None:
            msg = "Daemon refused request"
            raise CollectiveError(msg)
        msg = "Daemon returned an error"
        raise TransportUncertain(msg)
    if isinstance(value, dict) and "success" in value and value["success"] is not True:
        raise TransportUncertain("Tool did not confirm success")
    return value.get("result", value) if isinstance(value, dict) else value


class Backend:
    """The only door to external tools: argv-only subprocesses and the read-only herdr socket."""

    def __init__(
        self,
        tuios_bin: str | None = None,
        native_herdr: str | None = None,
        timeout: float = 12,
        native_socket: str | None = None,
    ) -> None:
        self.tuios_bin = str(Path(tuios_bin or shutil.which("tuios") or "tuios").absolute())
        self.native_herdr = native_herdr
        self.timeout = timeout
        self.native_socket = native_socket
        self.server = os.environ.get("TUIOS_SERVER", "")
        self.endpoint = canonical({"binary": str(Path(self.tuios_bin).resolve()), "server": self.server})

    def run(self, argv: list[str], *, as_json: bool = True) -> Any:  # noqa: ANN401 - JSON value or text by flag
        """Run argv (never a shell) with a deadline and a 2 MB output cap; return parsed JSON or text."""
        output = bytearray()
        errors = bytearray()
        deadline = time.monotonic() + self.timeout
        try:
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # noqa: S603 - argv list, no shell; the audited door
        except OSError as exc:
            msg = f"Command unavailable: {Path(argv[0]).name}"
            raise CollectiveError(msg) from exc
        try:
            with proc:
                try:
                    with selectors.DefaultSelector() as poll:
                        for pipe, target in ((proc.stdout, output), (proc.stderr, errors)):
                            stream = cast("IO[bytes]", pipe)
                            os.set_blocking(stream.fileno(), False)
                            poll.register(stream, selectors.EVENT_READ, target)
                        while poll.get_map():
                            remaining = _remaining(deadline)
                            for key, _ in poll.select(remaining):
                                chunk = os.read(key.fd, READ_CHUNK)
                                if not chunk:
                                    poll.unregister(key.fileobj)
                                    continue
                                key.data.extend(chunk)
                                _check_output_cap(output, errors)
                        proc.wait(timeout=max(0.001, deadline - time.monotonic()))
                except BaseException:
                    proc.kill()
                    proc.wait()
                    raise
                returncode = proc.returncode
        except subprocess.TimeoutExpired as exc:
            msg = "Command timed out"
            raise TransportUncertain(msg) from exc
        except OSError as exc:
            msg = f"Command I/O failed after start: {Path(argv[0]).name}"
            raise TransportUncertain(msg) from exc
        return _parse_tool_result(argv, returncode, output, errors, as_json=as_json)

    def tuios(self, verb: str, params: JsonDict) -> JsonDict:
        """Call one tuios control verb with canonical JSON params; the reply must be an object."""
        argv = [self.tuios_bin]
        if self.server:
            argv += ["--server", self.server]
        value = self.run([*argv, "call", verb, canonical(params)])
        if not isinstance(value, dict):
            # Dispatched and answered with something unusable: the effect is UNKNOWN.
            msg = "Tuios returned a non-object response"
            raise TransportUncertain(msg)
        return value

    def snapshot(self, session: object) -> JsonDict:
        """Read the roster between two boot-id reads so a daemon restart cannot slip in unnoticed."""
        if not isinstance(session, str) or not session or ":" in session:
            msg = "An explicit local session is required"
            raise CollectiveError(msg)
        before = self.tuios("list-attention", {})
        roster = self.tuios("list-agents", {"session": session})
        after = self.tuios("list-attention", {})
        if (
            not all(isinstance(v, dict) for v in (before, roster, after))
            or not isinstance(roster.get("agents"), list)
            or not all(isinstance(a, dict) for a in roster["agents"])
        ):
            msg = "Malformed daemon roster"
            raise CollectiveError(msg)
        if not before.get("boot_id") or before.get("boot_id") != after.get("boot_id"):
            msg = "Daemon restarted during observation"
            raise CollectiveError(msg)
        return {"endpoint": self.endpoint, "boot_id": after["boot_id"], "agents": roster.get("agents", [])}

    def roster(self, session: str) -> JsonDict:
        """Return the tuios roster, plus the native herdr roster when a socket or binary is configured."""
        snap = self.snapshot(session)
        fields = (
            "window_id",
            "session",
            "name",
            "foreground",
            "harness_id",
            "state",
            "agent_session_id",
            "unread",
            "draft_held",
            "needs_you",
        )
        result: JsonDict = {
            "tuios": {"boot_id": snap["boot_id"], "agents": [{k: a.get(k) for k in fields} for a in snap["agents"]]},
        }
        try:
            if self.native_socket:
                identity = self.native_request("ping", {})
                native = self.native_request("agent.list", {})
                result["native_herdr"] = {
                    "identity": identity,
                    "transport": "explicit Unix socket",
                    "agents": self.native_agents(native),
                }
            elif self.native_herdr:
                native = self.run([self.native_herdr, "agent", "list"])
                result["native_herdr"] = {"transport": "explicit CLI", "agents": self.native_agents(native)}
            else:
                result["native_herdr"] = {"status": "not configured; set --native-herdr or --native-socket"}
        except CollectiveError as exc:
            result["native_herdr"] = {"available": False, "error": clean(str(exc))}
        return result

    @staticmethod
    def native_agents(data: object) -> list[JsonDict]:
        """Project the native roster to its non-sensitive identity and state fields."""
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("agents"), list)
            or not all(isinstance(a, dict) for a in data["agents"])
        ):
            msg = "Malformed native roster"
            raise CollectiveError(msg)
        keys = ("pane_id", "agent", "agent_status", "interactive_ready", "launch_pending", "workspace_id")
        return [{k: a.get(k) for k in keys} for a in data.get("agents", [])]

    def native_request(self, method: str, params: JsonDict) -> JsonDict:
        """Explicit read-only native/compatible protocol adapter, never PTY writes."""
        if method not in {"ping", "agent.list"} or params:
            msg = "Socket adapter only permits ping and agent.list"
            raise CollectiveError(msg)
        if not self.native_socket or not Path(self.native_socket).is_absolute():
            msg = "Explicit absolute Herdr socket path required"
            raise CollectiveError(msg)
        request_id = "collective-" + str(uuid.uuid4())
        request = {"id": request_id, "method": method, "params": params}
        try:
            metadata = os.lstat(self.native_socket)
            if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
                raise CollectiveError("Herdr socket must be private and owned by the current user")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                deadline = time.monotonic() + self.timeout
                s.settimeout(self.timeout)
                s.connect(self.native_socket)
                _check_native_peer(s)
                s.sendall((canonical(request) + "\n").encode())
                response = _recv_frame(s, deadline)
            value = parse_json(response.split(b"\n", 1)[0])
        except (OSError, ValueError) as exc:
            msg = "Herdr Unix socket unavailable or incompatible"
            raise CollectiveError(msg) from exc
        if (
            not isinstance(value, dict)
            or value.get("id") != request_id
            or value.get("error")
            or not isinstance(value.get("result"), dict)
        ):
            msg = "Herdr socket refused the read or returned an unrelated response"
            raise CollectiveError(msg)
        return cast("JsonDict", value["result"])

    def inbox(self, session: str, pane: object, *, bodies: bool = False) -> JsonDict:
        """Read the session ring WITHOUT naming an inbox, so nothing is marked read or seen."""
        pane = pane_uuid(pane)
        data: object = self.tuios("read-agent-messages", {"session": session, "limit": RING_LIMIT})
        fields = ["id", "thread_id", "reply_to", "from", "to", "sent_at", "read_at", "seen_at", "kind"]
        if bodies:
            fields += ["text", "subject"]
        if (
            not isinstance(data, dict)
            or not isinstance(data.get("messages"), list)
            or not all(isinstance(m, dict) for m in data["messages"])
        ):
            msg = "Malformed inbox response"
            raise CollectiveError(msg)
        rows = [
            {k: m.get(k) for k in fields} for m in data.get("messages", []) if m.get("to") == pane or not m.get("to")
        ]
        return {
            "messages": rows,
            "passive": True,
            "evicted": data.get("evicted", 0),
            "untrusted_peer_content": bool(bodies),
            "limit": RING_LIMIT,
            "note": "Ring snapshot, not a complete durable inbox; no receipts changed",
        }

    def history(self, cwd: str | None = None) -> JsonDict:
        """Return agent shell-history metadata only: time, host, exit and directory, never commands."""
        argv = [
            shutil.which("atuin") or "atuin",
            "search",
            "--author",
            "$all-agent",
            "--limit",
            "10",
            "--format",
            "{time} | {host} | exit={exit} | {directory}",
        ]
        if cwd:
            argv += ["--cwd", cwd]
        return {"metadata": self.run(argv, as_json=False).splitlines(), "command_bodies": False}

    def memory(self, since: str | None = None) -> JsonDict:
        """Return MemPalace event metadata for the shared identity, cursor-resumable by event id."""
        argv = [
            shutil.which("mempalace") or "mempalace",
            "logstream",
            "list",
            "--to-agent",
            "kinoite-codex",
            "--order",
            "asc" if since else "desc",
            "--limit",
            "50",
            "--json",
        ]
        if since:
            argv += ["--since-event-id", since]
        data: object = self.run(argv)
        events = data.get("events", []) if isinstance(data, dict) else None
        if not isinstance(events, list) or not all(isinstance(e, dict) for e in events):
            msg = "Malformed MemPalace event response"
            raise CollectiveError(msg)
        fields = ("id", "type", "from_agent", "to_agent", "correlation_id", "status", "created_at")
        return {
            "events": [{k: e.get(k) for k in fields} for e in events],
            "identity": "kinoite-codex (shared; exact pane and correlation must distinguish peers)",
            "cursor": since,
            "limit": 50,
        }

    def ssh_health(self) -> JsonDict:
        """Report local SSH unit state and Tailscale peers; no SSH connection or remote probe."""
        units = [
            "sshd-native-recovery.service",
            "sshd-unix-local.socket",
            "ssh-independent-relay-machine-tunnel.service",
            "ssh-independent-relay-machine-connector.service",
        ]
        text = self.run(
            [
                "systemctl",
                "show",
                *units,
                *("-p", "Id", "-p", "ActiveState", "-p", "SubState", "-p", "NRestarts", "-p", "ExecMainStatus"),
            ],
            as_json=False,
        )
        data: object = self.run([shutil.which("tailscale") or "tailscale", "status", "--json"])
        peers = data.get("Peer", {}) if isinstance(data, dict) else None
        if not isinstance(peers, dict) or not all(isinstance(p, dict) for p in peers.values()):
            msg = "Malformed Tailscale status response"
            raise CollectiveError(msg)
        return {
            "units": text.splitlines(),
            "peers": [
                {"host": p.get("HostName"), "online": p.get("Online"), "last_seen": p.get("LastSeen")}
                for p in peers.values()
            ],
            "meaning": "Local state only; no SSH authentication, remote probe, or recovery acceptance",
        }


def state_root() -> Path:
    """Return the plugin state directory (HERDR_PLUGIN_STATE_DIR, else XDG state)."""
    root = os.environ.get("HERDR_PLUGIN_STATE_DIR")
    if root:
        return Path(root)
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "collective-plugin"


def write_private_json(path: str | os.PathLike[str], value: object, *, exclusive: bool = False) -> None:
    """Write JSON to a private (0600, single-link, non-symlink) file, validating the inode before truncation."""
    path = Path(path)
    private_dir(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | (os.O_EXCL if exclusive else 0)
    fd = os.open(path, flags, PRIVATE_FILE_MODE)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        if not _is_private_regular(os.fstat(f.fileno())):
            msg = "Output file must be mode 0600"
            raise CollectiveError(msg)
        os.ftruncate(f.fileno(), 0)
        json.dump(value, f, indent=2, ensure_ascii=True)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def read_private_json(path: str | os.PathLike[str]) -> Any:  # noqa: ANN401 - arbitrary JSON, validated by callers
    """Read bounded private single-link JSON through the shared opened-inode policy."""
    try:
        return _private_files.read_private_json(path, limit=MAX_PLAN_BYTES)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise
    except ValueError as exc:
        raise CollectiveError(f"Unsafe private JSON input: {exc}") from exc


def observe(backend: BackendLike, session: str) -> JsonDict:
    """Run the four passive reads in parallel; a failing source is reported unavailable, never fatal."""
    tasks: dict[str, Callable[[], JsonDict]] = {
        "roster": lambda: backend.roster(session),
        "history": backend.history,
        "memory": backend.memory,
        "ssh": backend.ssh_health,
    }
    result: JsonDict = {"observed_at": dt.datetime.now(dt.UTC).isoformat(), "session": session}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {k: pool.submit(f) for k, f in tasks.items()}
        for k, fut in futures.items():
            try:
                result[k] = {"available": True, "data": fut.result()}
            except Exception as exc:  # noqa: BLE001 - any failing source becomes "unavailable", by design
                result[k] = {"available": False, "error": clean(str(exc))}
    return result


def _mail_status(
    backend: BackendLike, session: str, snapshot: JsonDict, previous: JsonDict
) -> tuple[JsonDict, set[str]]:
    ring = backend.tuios("read-agent-messages", {"session": session, "limit": RING_LIMIT})
    roster = snapshot.get("roster", {}).get("data", {}).get("tuios", {})
    members = {a["window_id"] for a in roster.get("agents", [])}
    current_ids = {
        str(m["id"])
        for m in ring.get("messages", [])
        if not m.get("read_at") and (m.get("to") in members or not m.get("to"))
    }
    boot = roster.get("boot_id")
    seen = set(previous.get("mail_ids", [])) if previous.get("boot_id") == boot else set()
    fresh = current_ids - seen
    status = {
        "boot_id": boot,
        "mail_ids": sorted(seen | current_ids, key=int)[-MAIL_IDS_KEPT:],
        "new_unread_count": len(fresh),
        "observed_at": snapshot["observed_at"],
    }
    snapshot["mail"] = {
        "new_unread_count": len(fresh),
        "unread_count": len(current_ids),
        "passive": True,
        "evicted": ring.get("evicted", 0),
        "limit": RING_LIMIT,
    }
    return status, fresh


def monitor(backend: BackendLike, session: str, directory: str | os.PathLike[str], *, notify: bool = False) -> JsonDict:
    """One passive sweep. No mail sends, read receipts, model turns or replies."""
    if not Path(directory).is_absolute():
        # A relative path resolves against the caller's cwd and can plant private state in a checkout.
        msg = "Explicit absolute state directory required"
        raise CollectiveError(msg)
    directory = private_dir(directory)
    lock = directory / "monitor.lock"
    with locked_private_file(lock, blocking=False):
        # systemd oneshot serialization plus this lock covers manual invocations.
        previous_path = directory / "monitor-state.json"
        previous = read_private_json(previous_path) if previous_path.exists() else {}
        snapshot = observe(backend, session)
        try:
            status, fresh = _mail_status(backend, session, snapshot, previous)
        except Exception as exc:  # noqa: BLE001 - a failed mail read is reported, the sweep still completes
            status = previous
            snapshot["mail"] = {"available": False, "error": clean(str(exc))}
            fresh = set()
        # Replace atomically; files contain metadata only, never message bodies.
        for name, data in [("monitor-state.json", status), ("latest.json", snapshot)]:
            tmp = directory / (name + "." + str(uuid.uuid4()) + ".tmp")
            write_private_json(tmp, data, exclusive=True)
            tmp.replace(directory / name)
        notifier = shutil.which("notify-send")
        if fresh and notify and notifier:
            try:
                backend.run(
                    [
                        notifier,
                        "Collective communications",
                        f"{len(fresh)} new unread messages. Open tuios; no messages were marked read.",
                    ],
                    as_json=False,
                )
                snapshot["notification"] = "sent to desktop notification service"
            except CollectiveError:
                snapshot["notification"] = "desktop notification unavailable; see latest.json"
        return snapshot


CAPABILITIES = {
    "read": [
        "tuios roster",
        "passive inbox metadata",
        "Atuin metadata-only history",
        "MemPalace event metadata",
        "local SSH unit/peer state",
        "optional native Herdr roster",
    ],
    "write": [
        "local tuios mail: exact private plan + digest + expiry + one-use journal",
        "optional local desktop notification: monitor --notify, count only",
    ],
    "collaboration": [
        "Structured intent/milestone/blocker/handoff/review plans with owner, reviewer, scope, evidence and DoD",
    ],
    "excluded": [
        "raw PTY/queued prompts",
        "broadcast",
        "human impersonation/approval",
        "SSH effects",
        "grants/config changes",
        "script execution",
        "automatic replies",
    ],
    "limits": [
        "Pane IDs are routing claims, not authenticated model identities",
        "Plan digest is review acknowledgement, not authentication",
        "Revalidation is a preflight, not an atomic daemon transaction",
        "Monitor is passive, not a background AI turn; gaps remain possible in bounded rings",
        (
            "A pane with an empty agent_session_id (seen on some Codex panes) is revalidated by window, session,"
            " foreground and harness only, so a model restart in the same pane is not detected"
        ),
    ],
}


def parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", action="store_true")
    p.add_argument("--native-herdr", default=os.environ.get("COLLECTIVE_NATIVE_HERDR_BIN"))
    p.add_argument("--native-socket", default=os.environ.get("COLLECTIVE_NATIVE_HERDR_SOCKET"))
    sub = p.add_subparsers(dest="command", required=True)
    for name in ["dashboard", "roster", "inbox", "mail-plan", "collaboration-plan", "monitor"]:
        s = sub.add_parser(name)
        s.add_argument("--session", default=os.environ.get("TUIOS_SESSION", "session-0"))
        if name == "dashboard":
            s.add_argument("--watch", action="store_true")
        if name == "inbox":
            s.add_argument("--pane", required=True)
            s.add_argument("--bodies", action="store_true")
        if name == "mail-plan":
            s.add_argument("--sender", required=True)
            s.add_argument("--to", required=True)
            s.add_argument("--subject", required=True)
            s.add_argument("--text-file", required=True)
            s.add_argument("--reply-to", type=int)
            s.add_argument("--output", required=True)
        if name == "collaboration-plan":
            s.add_argument("--sender", required=True)
            s.add_argument("--reviewer", required=True)
            s.add_argument("--kind", choices=list(COLLABORATION_KINDS), required=True)
            s.add_argument("--goal", required=True)
            s.add_argument("--scope", required=True)
            s.add_argument("--done", required=True)
            s.add_argument("--evidence", action="append", default=[])
            s.add_argument("--output", required=True)
        if name == "monitor":
            s.add_argument("--state-dir", default=str(state_root()))
            s.add_argument("--notify", action="store_true")
    sub.add_parser("capabilities")
    sub.add_parser("ssh-health")
    h = sub.add_parser("history")
    h.add_argument("--cwd")
    m = sub.add_parser("memory")
    m.add_argument("--since-event-id")
    a = sub.add_parser("mail-apply")
    a.add_argument("--plan", required=True)
    a.add_argument("--confirm", required=True)
    a.add_argument("--journal", default=str(state_root() / "mail-journal.jsonl"))
    a.add_argument(
        "--keep-plan",
        action="store_true",
        help="Retain the private message-body plan after successful submission",
    )
    return p


def _plan_command(args: argparse.Namespace, backend: Backend) -> JsonDict:
    if args.command == "mail-plan":
        raw = read_owned_bytes(args.text_file, limit=2 * MAX_BODY).decode("utf-8")
        text = raw.replace("\r\n", "\n").replace("\r", "\n")
        plan = make_mail_plan(
            backend.snapshot(args.session),
            args.session,
            args.sender,
            args.to,
            args.subject,
            text,
            args.reply_to,
        )
        effect = "No message sent. Review the exact private plan before mail-apply."
    else:
        plan = make_collaboration_plan(
            backend.snapshot(args.session),
            args.session,
            args.sender,
            args.reviewer,
            args.kind,
            args.goal,
            args.scope,
            args.done,
            args.evidence,
        )
        effect = "No message sent. Review this owner/reviewer update before mail-apply."
    write_private_json(args.output, plan, exclusive=True)
    return {"plan": args.output, "digest": plan["digest"], "expires_at": plan["expires_at"], "effect": effect}


def _apply_command(args: argparse.Namespace, backend: Backend) -> JsonDict:
    result = apply_mail_plan(read_private_json(args.plan), args.confirm, backend, Journal(args.journal))
    if not args.keep_plan:
        # Removal is privacy cleanup only: never change a successful outcome
        # into a retryable-looking error if cleanup fails.
        try:
            Path(args.plan).unlink()
            result["plan_removed"] = True
        except OSError:
            result["plan_removed"] = False
            result["cleanup"] = "Submission succeeded; remove the private plan manually, do not resend"
    return result


def _dashboard(args: argparse.Namespace, backend: Backend) -> JsonDict | None:
    """Return one observation, or None when the interactive watch loop was quit with q."""
    while True:
        result = observe(backend, args.session)
        if not args.watch:
            return result
        if sys.stdout.isatty():
            print("\033[2J\033[H", end="")
        print("Collective — passive local status | q / Ctrl+C to close")
        print(clean(json.dumps(result, indent=2, ensure_ascii=True)), flush=True)
        if sys.stdin.isatty() and select.select([sys.stdin], [], [], WATCH_SECONDS)[0]:
            if sys.stdin.readline().strip().lower() == "q":
                return None
        elif not sys.stdin.isatty():
            time.sleep(WATCH_SECONDS)


def _dispatch(args: argparse.Namespace, backend: Backend) -> JsonDict | None:
    simple: dict[str, Callable[[], JsonDict]] = {
        "capabilities": lambda: CAPABILITIES,
        "roster": lambda: backend.roster(args.session),
        "inbox": lambda: backend.inbox(args.session, args.pane, bodies=args.bodies),
        "history": lambda: backend.history(args.cwd),
        "memory": lambda: backend.memory(args.since_event_id),
        "ssh-health": backend.ssh_health,
        "monitor": lambda: monitor(backend, args.session, args.state_dir, notify=args.notify),
        "mail-plan": lambda: _plan_command(args, backend),
        "collaboration-plan": lambda: _plan_command(args, backend),
        "mail-apply": lambda: _apply_command(args, backend),
    }
    if args.command in simple:
        return simple[args.command]()
    return _dashboard(args, backend)


def main(argv: list[str] | None = None) -> int:
    """Run one CLI command and print its JSON result; errors print JSON to stderr with exit 2."""
    args = parser().parse_args(argv)
    backend = Backend(native_herdr=args.native_herdr, native_socket=args.native_socket)
    try:
        result = _dispatch(args, backend)
        if result is None:
            return 0
        rendered = json.dumps(result, indent=2, ensure_ascii=True)
        print(rendered if args.json else clean(rendered))
    except (CollectiveError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"error": clean(str(exc)), "effect": "No automatic retry"}), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
