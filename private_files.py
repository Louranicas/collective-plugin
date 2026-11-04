"""Bounded Linux file readers with two fixed local ownership policies.

The parent directory is opened and validated before opening its leaf by dir_fd.
Readers return bytes from that opened inode, not a guarantee that the pathname
still names it afterwards. Metadata checks detect ordinary concurrent changes;
they do not isolate an adversarial process running as the same Unix user.
O_NONBLOCK avoids FIFO peer waits; it is not full protection from device drivers.
"""

from __future__ import annotations

import json
import os
import stat
from enum import Enum, auto
from pathlib import Path

DEFAULT_LIMIT = 65536
MAX_LIMIT = 2_000_000
READ_CHUNK = 65536
PRIVATE_PARENT_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
UNSAFE_WRITE_MODE = 0o022


class _Policy(Enum):
    PRIVATE_STATE = auto()
    OWNED_FILE = auto()


def _check_limit(limit: int) -> None:
    if type(limit) is not int or not 0 < limit <= MAX_LIMIT:
        raise ValueError(f"File byte limit must be an integer in 1..{MAX_LIMIT}")


def _check_parent(metadata: os.stat_result, policy: _Policy) -> None:
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise ValueError("Parent must be a directory owned by the current user")
    mode = stat.S_IMODE(metadata.st_mode)
    if policy is _Policy.PRIVATE_STATE:
        if mode != PRIVATE_PARENT_MODE:
            raise ValueError("Private-state parent must have mode 0700")
    elif mode & UNSAFE_WRITE_MODE:
        raise ValueError("Owned-file parent must not be group or other writable")


def _check_leaf(metadata: os.stat_result, policy: _Policy, limit: int) -> None:
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_nlink != 1:
        raise ValueError("File must be regular, owned by the current user and singly linked")
    mode = stat.S_IMODE(metadata.st_mode)
    if policy is _Policy.PRIVATE_STATE:
        if mode != PRIVATE_FILE_MODE:
            raise ValueError("Private-state file must have mode 0600")
    elif mode & UNSAFE_WRITE_MODE:
        raise ValueError("Owned-file file must not be group or other writable")
    if metadata.st_size < 0 or metadata.st_size > limit:
        raise ValueError("File exceeds its byte limit")


def _identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)


def _read_inode(fd: int, policy: _Policy, limit: int) -> bytes:
    before = os.fstat(fd)
    _check_leaf(before, policy, limit)
    data = bytearray()
    while len(data) <= limit:
        chunk = os.read(fd, min(READ_CHUNK, limit + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
    if len(data) > limit:
        raise ValueError("File grew beyond its byte limit during the read")
    after = os.fstat(fd)
    _check_leaf(after, policy, limit)
    if _identity(before) != _identity(after) or len(data) != before.st_size:
        raise ValueError("File changed during the read")
    return bytes(data)


def _read(path: str | os.PathLike[str], policy: _Policy, limit: int) -> bytes:
    _check_limit(limit)
    target = Path(path)
    if not target.name or target.name in {".", ".."}:
        raise ValueError("An explicit file leaf is required")
    parent_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        _check_parent(os.fstat(parent_fd), policy)
        fd = os.open(
            target.name,
            os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )
        try:
            return _read_inode(fd, policy, limit)
        finally:
            os.close(fd)
    finally:
        os.close(parent_fd)


def read_private_json(path: str | os.PathLike[str], *, limit: int = DEFAULT_LIMIT) -> object:
    """Read bounded UTF-8 JSON from an owned 0600 single-link file in an owned 0700 parent.

    Missing files and OS refusals remain FileNotFoundError/OSError. Unsafe policy,
    overflow, concurrent changes, invalid UTF-8 and invalid JSON raise ValueError.
    """
    return parse_json(_read(path, _Policy.PRIVATE_STATE, limit))


def parse_json(data: str | bytes | bytearray) -> object:
    """Parse untrusted JSON text; every malformed, non-UTF-8 or too-deep input raises ValueError.

    This is the one JSON boundary for files and transport output, so parser recursion
    limits surface as ordinary malformed data instead of escaping as RecursionError.
    """
    text = data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else data
    try:
        return json.loads(text)
    except RecursionError as exc:
        raise ValueError("JSON nesting exceeds the supported parser depth") from exc


def read_owned_bytes(path: str | os.PathLike[str], *, limit: int = DEFAULT_LIMIT) -> bytes:
    """Read bounded bytes from an owned single-link file with no group/other write on file or parent.

    Used for user units, job source hashing and mail-plan text input. Readable modes
    such as 0644/0755 are permitted; a symlink leaf or symlink immediate parent is
    never followed. Ancestor paths remain caller trust.
    """
    return _read(path, _Policy.OWNED_FILE, limit)
