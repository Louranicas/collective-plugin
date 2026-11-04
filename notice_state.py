"""Pure, bounded state transitions for fixed-route heartbeat notifications.

These records track submission evidence, never human reads or acceptance. A
persisted intent becomes unknown on load and holds its alert keys against retry.
An empty boot ID explicitly means unknown generation; a caller must not use it
to reconcile a notice. No operation here sends, reads files, or authenticates a
peer. Callers supply confirmed submission evidence before finishing submitted.
"""

from __future__ import annotations

import json
import math
from typing import Literal, TypedDict, cast
from uuid import UUID

MAX_RECORDS = 128
MAX_KEYS = 16
MAX_KEY_CHARS = 256
MAX_BOOT_CHARS = 128
MAX_ENDPOINT_CHARS = 512
MAX_BYTES = 65536
DIGEST_CHARS = 64
type NoticeStatus = Literal["intent", "submitted", "refused", "unknown"]
_STATUSES = {"intent", "submitted", "refused", "unknown"}
_TERMINAL = {"submitted", "refused"}


class NoticeRecord(TypedDict):
    """Metadata-only audit outcome and the unresolved keys currently held."""

    request_id: str
    digest: str
    keys: list[str]
    held_keys: list[str]
    boot_id: str
    endpoint: str
    created_at: float
    status: NoticeStatus
    message_id: int | None


_FIELDS = set(NoticeRecord.__annotations__)


def _text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"Invalid notice {name}")
    return value


def _request_id(value: object) -> str:
    identifier = _text(value, "request ID", 36)
    try:
        canonical = str(UUID(identifier))
    except ValueError as exc:
        raise ValueError("Notice request ID must be a canonical UUID") from exc
    if identifier != canonical:
        raise ValueError("Notice request ID must be a canonical UUID")
    return identifier


def _digest(value: object) -> str:
    digest = _text(value, "digest", DIGEST_CHARS)
    if len(digest) != DIGEST_CHARS or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("Notice digest must be a lowercase SHA-256")
    return digest


def _keys(value: object, *, original: bool) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_KEYS:
        raise ValueError("Notice keys must be a bounded list")
    keys = [_text(key, "alert key", MAX_KEY_CHARS) for key in value]
    if (original and not keys) or len(set(keys)) != len(keys):
        raise ValueError("Notice keys must be unique; original keys cannot be empty")
    return keys


def _timestamp(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("Notice creation time must be a finite nonnegative number")
    try:
        timestamp = float(cast("int | float", value))
    except OverflowError as exc:
        raise ValueError("Notice creation time is too large") from exc
    if not math.isfinite(timestamp) or timestamp < 0:
        raise ValueError("Notice creation time must be a finite nonnegative number")
    return timestamp


def _message_id(value: object, status: NoticeStatus) -> int | None:
    if status == "submitted":
        if type(value) is not int or value <= 0:
            raise ValueError("Submitted notice requires a positive integer message ID")
        return value
    if value is not None:
        raise ValueError("Only a submitted notice can have a message ID")
    return None


def _record(value: object) -> NoticeRecord:
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError("Malformed notice record schema")
    keys = _keys(value["keys"], original=True)
    held = _keys(value["held_keys"], original=False)
    if not set(held).issubset(keys):
        raise ValueError("Held keys must be a subset of original keys")
    status = value["status"]
    if not isinstance(status, str) or status not in _STATUSES:
        raise ValueError("Invalid notice outcome")
    status = cast("NoticeStatus", status)
    if status in _TERMINAL and held:
        raise ValueError("Terminal notice cannot hold alert keys")
    if status == "intent" and held != keys:
        raise ValueError("Intent must hold every original alert key")
    boot = value["boot_id"]
    if not isinstance(boot, str) or len(boot) > MAX_BOOT_CHARS:
        raise ValueError("Invalid notice boot ID")
    return {
        "request_id": _request_id(value["request_id"]),
        "digest": _digest(value["digest"]),
        "keys": keys,
        "held_keys": held,
        "boot_id": boot,
        "endpoint": _text(value["endpoint"], "endpoint", MAX_ENDPOINT_CHARS),
        "created_at": _timestamp(value["created_at"]),
        "status": status,
        "message_id": _message_id(value["message_id"], status),
    }


def _size(records: list[NoticeRecord]) -> int:
    # Reserve the extra byte needed when a persisted intent becomes unknown.
    persisted = [
        {**record, "status": "unknown" if record["status"] == "intent" else record["status"]} for record in records
    ]
    return len(json.dumps(persisted, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))


def _validated(value: object) -> list[NoticeRecord]:
    if not isinstance(value, list) or len(value) > MAX_RECORDS:
        raise ValueError("Notice records must be a bounded list")
    records = [_record(item) for item in value]
    if len({record["request_id"] for record in records}) != len(records):
        raise ValueError("Notice request IDs must be unique")
    if _size(records) > MAX_BYTES:
        raise ValueError("Notice journal exceeds 64 KiB")
    return records


def load_records(value: object) -> list[NoticeRecord]:
    """Validate persisted records and turn interrupted intents into held unknowns."""
    records = _validated([] if value is None else value)
    for record in records:
        if record["status"] == "intent":
            record["status"] = "unknown"
    return _validated(records)


def held_keys(records: list[NoticeRecord]) -> set[str]:
    """Return alert keys held by unresolved or in-progress submissions."""
    return {
        key
        for record in _validated(records)
        if record["status"] in {"intent", "unknown"}
        for key in record["held_keys"]
    }


def resolve_keys(records: list[NoticeRecord], explicitly_resolved: set[str]) -> list[NoticeRecord]:
    """Release verified resolved keys without changing their recorded outcome."""
    copied = _validated(records)
    for record in copied:
        if record["status"] == "intent" and set(record["held_keys"]) & explicitly_resolved:
            raise ValueError("An in-progress intent cannot be resolved")
        record["held_keys"] = [key for key in record["held_keys"] if key not in explicitly_resolved]
    return _validated(copied)


def _prune(records: list[NoticeRecord]) -> list[NoticeRecord]:
    while len(records) > MAX_RECORDS or _size(records) > MAX_BYTES:
        candidates = [
            (record["created_at"], index) for index, record in enumerate(records) if record["status"] in _TERMINAL
        ]
        if not candidates:
            raise ValueError("Notice journal capacity exhausted; unresolved outcomes require review")
        records.pop(min(candidates)[1])
    return records


def reserve(
    records: list[NoticeRecord],
    *,
    request_id: str,
    digest: str,
    keys: list[str],
    boot_id: str,
    endpoint: str,
    now: float,
) -> list[NoticeRecord]:
    """Return a durable intent proposal; refuse held keys or exhausted capacity."""
    copied = _validated(records)
    if request_id in {record["request_id"] for record in copied}:
        raise ValueError("Notice request ID already consumed")
    record = _record(
        {
            "request_id": request_id,
            "digest": digest,
            "keys": keys,
            "held_keys": keys,
            "boot_id": boot_id,
            "endpoint": endpoint,
            "created_at": now,
            "status": "intent",
            "message_id": None,
        }
    )
    if set(record["keys"]) & held_keys(copied):
        raise ValueError("An uncertain notice already holds these alert keys; never resend automatically")
    return _validated(_prune([*copied, record]))


def finish(
    records: list[NoticeRecord], request_id: str, *, status: NoticeStatus, message_id: int | None = None
) -> list[NoticeRecord]:
    """Finish an intent or reconcile an unknown only with positive submission proof."""
    copied = _validated(records)
    matches = [record for record in copied if record["request_id"] == request_id]
    if not matches:
        raise ValueError("Unknown notice request ID")
    record = matches[0]
    if status not in {"submitted", "refused", "unknown"}:
        raise ValueError("Invalid completion outcome")
    if record["status"] != "intent" and not (record["status"] == "unknown" and status == "submitted"):
        raise ValueError("Notice transition is not permitted")
    record["message_id"] = _message_id(message_id, status)
    record["status"] = status
    if status in _TERMINAL:
        record["held_keys"] = []
    return _validated(copied)
