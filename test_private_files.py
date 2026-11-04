"""Executable policy and concurrent-change tests for the fixed safe-reader APIs."""

from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from json.scanner import py_make_scanner  # type: ignore[attr-defined]  # Runtime stdlib scanner lacks a stub.
from pathlib import Path
from typing import TYPE_CHECKING, cast, override

if TYPE_CHECKING:
    from collections.abc import Callable
from unittest import mock

import private_files as readers


class ReaderPolicies(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="collective-reader-")
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name)
        self.parent.chmod(0o700)
        self.path = self.parent / "value"

    def write(self, data: bytes, mode: int = 0o600) -> None:
        if self.path.exists():
            self.path.chmod(0o600)
        self.path.write_bytes(data)
        self.path.chmod(mode)

    def test_utf8_json_and_unit_bytes_are_returned(self) -> None:
        value = {"label": "Δοκιμή", "items": [1, None, True]}
        data = json.dumps(value, ensure_ascii=False).encode()
        self.write(data)
        self.assertEqual(readers.read_private_json(self.path), value)
        self.assertEqual(readers.read_owned_bytes(self.path), data)

    def test_unit_policy_accepts_readable_modes_private_policy_refuses_them(self) -> None:
        self.write(b"[Unit]\nDescription=fixture\n", 0o644)
        self.parent.chmod(0o755)
        self.assertEqual(readers.read_owned_bytes(self.path), self.path.read_bytes())
        with self.assertRaises(ValueError):
            readers.read_private_json(self.path)
        self.parent.chmod(0o700)
        with self.assertRaises(ValueError):
            readers.read_private_json(self.path)

    def test_missing_leaf_and_parent_preserve_file_not_found(self) -> None:
        for path in (self.path, self.parent / "missing" / "value"):
            for reader in (readers.read_private_json, readers.read_owned_bytes):
                with self.subTest(path=path, reader=reader), self.assertRaises(FileNotFoundError):
                    reader(path)

    def test_private_leaf_modes_are_exact(self) -> None:
        for mode in (0o400, 0o640, 0o644, 0o700):
            self.write(b"{}", mode)
            with self.subTest(mode=oct(mode)), self.assertRaises(ValueError):
                readers.read_private_json(self.path)

    def test_private_parent_modes_are_exact(self) -> None:
        self.write(b"{}")
        for mode in (0o500, 0o710, 0o750, 0o755):
            self.parent.chmod(mode)
            with self.subTest(mode=oct(mode)), self.assertRaises(ValueError):
                readers.read_private_json(self.path)
        self.parent.chmod(0o700)

    def test_unit_writable_file_or_parent_is_refused(self) -> None:
        for mode in (0o620, 0o602, 0o666):
            self.write(b"unit", mode)
            with self.subTest(mode=oct(mode)), self.assertRaises(ValueError):
                readers.read_owned_bytes(self.path)
        self.write(b"unit", 0o644)
        self.parent.chmod(0o775)
        with self.assertRaises(ValueError):
            readers.read_owned_bytes(self.path)
        self.parent.chmod(0o700)

    def test_foreign_parent_ownership_is_refused(self) -> None:
        self.write(b"{}")
        with mock.patch.object(os, "getuid", return_value=os.getuid() + 1), self.assertRaises(ValueError):
            readers.read_private_json(self.path)

    def test_foreign_leaf_ownership_is_refused(self) -> None:
        self.write(b"{}")
        uid = os.getuid()
        with mock.patch.object(os, "getuid", side_effect=(uid, uid + 1)), self.assertRaises(ValueError):
            readers.read_owned_bytes(self.path)

    def test_symlink_leaf_never_reads_target(self) -> None:
        target = self.parent / "target"
        target.write_bytes(b"{}")
        target.chmod(0o600)
        self.path.symlink_to(target)
        for reader in (readers.read_private_json, readers.read_owned_bytes):
            with self.subTest(reader=reader), self.assertRaises(OSError):
                reader(self.path)
        self.assertEqual(target.read_bytes(), b"{}")

    def test_symlink_immediate_parent_is_refused(self) -> None:
        self.write(b"{}")
        linked = self.parent / "linked-parent"
        linked.symlink_to(self.parent, target_is_directory=True)
        for reader in (readers.read_private_json, readers.read_owned_bytes):
            with self.subTest(reader=reader), self.assertRaises(OSError):
                reader(linked / self.path.name)

    def test_hardlink_refusal_preserves_original(self) -> None:
        self.write(b"{}")
        os.link(self.path, self.parent / "second-link")
        for reader in (readers.read_private_json, readers.read_owned_bytes):
            with self.subTest(reader=reader), self.assertRaises(ValueError):
                reader(self.path)
        self.assertEqual(self.path.read_bytes(), b"{}")

    def test_socket_and_directory_leaves_are_refused(self) -> None:
        # Bind the same filesystem leaf relatively: a private sandbox TMPDIR can
        # exceed sockaddr_un's path limit without affecting reader behavior.
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server, contextlib.chdir(self.parent):
            server.bind(self.path.name)
            self.path.chmod(0o600)
            for reader in (readers.read_private_json, readers.read_owned_bytes):
                with self.subTest(reader=reader), self.assertRaises(OSError):
                    reader(self.path)
        self.path.unlink()
        self.path.mkdir(mode=0o700)
        for reader in (readers.read_private_json, readers.read_owned_bytes):
            with self.subTest(reader=reader), self.assertRaises(ValueError):
                reader(self.path)

    def test_fifo_with_or_without_peer_is_refused_in_real_child(self) -> None:
        os.mkfifo(self.path, 0o600)
        module_dir = str(Path(readers.__file__).resolve().parent)
        for name in ("read_private_json", "read_owned_bytes"):
            for has_peer in (False, True):
                with self.subTest(reader=name, has_peer=has_peer), contextlib.ExitStack() as stack:
                    peer_fd = None
                    if has_peer:
                        peer_fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
                        stack.callback(os.close, peer_fd)
                        os.write(peer_fd, b"{}")
                    program = (
                        "import sys,json;"
                        f"sys.path.insert(0,{module_dir!r});"
                        "import private_files as p;\n"
                        "try:\n"
                        f" p.{name}({str(self.path)!r})\n"
                        "except ValueError:\n print(json.dumps({'refused':True}))\n"
                        "else:\n raise SystemExit('FIFO unexpectedly accepted')\n"
                    )
                    result = subprocess.run(  # noqa: S603 - controlled interpreter/fixture argv, no shell
                        [sys.executable, "-I", "-c", program],
                        capture_output=True,
                        text=True,
                        timeout=2,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(json.loads(result.stdout), {"refused": True})
                    if peer_fd is not None:
                        self.assertEqual(os.read(peer_fd, 2), b"{}")

    def test_exact_limits_and_preexisting_oversize(self) -> None:
        self.write(b"{}")
        self.assertEqual(readers.read_private_json(self.path, limit=2), {})
        self.assertEqual(readers.read_owned_bytes(self.path, limit=2), b"{}")
        for reader in (readers.read_private_json, readers.read_owned_bytes):
            with self.subTest(reader=reader), self.assertRaises(ValueError):
                reader(self.path, limit=1)
        self.write(b"")
        self.assertEqual(readers.read_owned_bytes(self.path), b"")
        with self.assertRaises(ValueError):
            readers.read_private_json(self.path)

    def test_invalid_limits_fail_without_creating_paths(self) -> None:
        for invalid in (0, -1, True, 1.5, readers.MAX_LIMIT + 1):
            for reader in (readers.read_private_json, readers.read_owned_bytes):
                with self.subTest(limit=invalid, reader=reader), self.assertRaises(ValueError):
                    reader(self.path, limit=cast("int", invalid))
        self.assertFalse(self.path.exists())

    def test_bad_utf8_and_invalid_json_are_value_errors(self) -> None:
        for data in (b"\xff", b"not json"):
            self.write(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                readers.read_private_json(self.path)
            self.assertEqual(readers.read_owned_bytes(self.path), data)

    def test_duplicate_json_keys_are_refused_at_any_depth(self) -> None:
        cases = (
            b'{"x":1,"x":2}',
            b'{"x":1,"x":1}',
            b'{"outer":{"x":1,"x":2}}',
            b'[{"x":1,"x":2}]',
            b'{"x":1,"\\u0078":2}',
            '{"\u0394":1,"\\u0394":2}'.encode(),
        )
        for data in cases:
            with self.subTest(data=data):
                for payload in (data, bytearray(data), data.decode()):
                    with self.assertRaisesRegex(ValueError, "Duplicate JSON"):
                        readers.parse_json(payload)
                self.write(data)
                with self.assertRaisesRegex(ValueError, "Duplicate JSON"):
                    readers.read_private_json(self.path)
                self.assertEqual(self.path.read_bytes(), data)

    def test_nonfinite_json_numbers_are_refused_including_overflow(self) -> None:
        cases = (
            b"NaN",
            b"Infinity",
            b"-Infinity",
            b"1e999",
            b"-1e999",
            b'{"value":NaN}',
            b'{"outer":{"value":Infinity}}',
            b"[-Infinity]",
            b"[1E+9999]",
        )
        for data in cases:
            with self.subTest(data=data):
                for payload in (data, bytearray(data), data.decode()):
                    with self.assertRaisesRegex(ValueError, "Non-finite JSON"):
                        readers.parse_json(payload)
                self.write(data)
                with self.assertRaisesRegex(ValueError, "Non-finite JSON"):
                    readers.read_private_json(self.path)
                self.assertEqual(self.path.read_bytes(), data)

    def test_strict_json_preserves_unicode_finite_numbers_and_types(self) -> None:
        data = (
            '{"label":"Δοκιμή","integer":12345678901234567890,"float":1.25,"large":1e308,'
            '"small":5e-324,"underflow":1e-999,"boolean":true,"empty":null,'
            '"nested":[{"x":1},{"x":2}],"x":3}'
        ).encode()
        expected = {
            "label": "Δοκιμή",
            "integer": 12345678901234567890,
            "float": 1.25,
            "large": 1e308,
            "small": 5e-324,
            "underflow": 0.0,
            "boolean": True,
            "empty": None,
            "nested": [{"x": 1}, {"x": 2}],
            "x": 3,
        }
        for payload in (data, bytearray(data), data.decode()):
            self.assertEqual(readers.parse_json(payload), expected)
        self.write(data)
        value = readers.read_private_json(self.path)
        self.assertEqual(value, expected)
        assert isinstance(value, dict)
        self.assertIs(type(value["integer"]), int)
        self.assertIs(type(value["float"]), float)
        self.assertIs(type(value["boolean"]), bool)
        self.assertIsNone(value["empty"])

    def test_deep_json_array_is_a_bounded_value_error_with_cause(self) -> None:
        depth = sys.getrecursionlimit() * 2
        self.write(b"[" * depth + b"0" + b"]" * depth)
        # Python 3.14's C scanner is stackless; exercise the real stdlib recursive
        # scanner so this test proves exception translation on either runtime.
        decoder = json.JSONDecoder()
        decoder.scan_once = py_make_scanner(decoder)  # type: ignore[attr-defined]  # Runtime JSONDecoder scanner hook.
        with (
            mock.patch.object(json, "_default_decoder", decoder),
            mock.patch.object(json.scanner, "make_scanner", py_make_scanner),
            self.assertRaisesRegex(ValueError, "JSON nesting") as caught,
        ):
            readers.read_private_json(self.path)
        self.assertIsInstance(caught.exception.__cause__, RecursionError)
        self.assertLess(self.path.stat().st_size, readers.DEFAULT_LIMIT)

    def test_explicit_leaf_is_required(self) -> None:
        for path in ("", ".", ".."):
            with self.subTest(path=path), self.assertRaises(ValueError):
                readers.read_owned_bytes(path)

    def test_growth_truncation_and_same_size_changes_are_refused(self) -> None:
        for change in ("grow", "truncate", "rewrite", "mode", "link"):
            self.write(b'{"v":0}')
            original_read = os.read
            changed = False

            def read_and_change(
                fd: int, length: int, read: Callable[[int, int], bytes] = original_read, selected: str = change
            ) -> bytes:
                nonlocal changed
                chunk = read(fd, length)
                if not changed:
                    changed = True
                    if selected == "grow":
                        with self.path.open("ab") as stream:
                            stream.write(b" ")
                    elif selected == "truncate":
                        self.path.write_bytes(b"")
                    elif selected == "rewrite":
                        before = self.path.stat()
                        self.path.write_bytes(b'{"v":1}')
                        os.utime(self.path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
                    elif selected == "mode":
                        self.path.chmod(0o644)
                    else:
                        os.link(self.path, self.parent / "concurrent-link")
                return chunk

            with (
                self.subTest(change=change),
                mock.patch.object(os, "read", side_effect=read_and_change),
                self.assertRaises(ValueError),
            ):
                readers.read_private_json(self.path)
            (self.parent / "concurrent-link").unlink(missing_ok=True)

    def test_growth_read_is_capped_at_limit_plus_one(self) -> None:
        self.write(b"{}")
        original_read = os.read
        received = 0
        changed = False

        def read_and_grow(fd: int, length: int) -> bytes:
            nonlocal received, changed
            chunk = original_read(fd, length)
            received += len(chunk)
            if not changed:
                changed = True
                with self.path.open("ab") as stream:
                    stream.write(b"x" * 1000)
            return chunk

        with mock.patch.object(os, "read", side_effect=read_and_grow), self.assertRaises(ValueError):
            readers.read_owned_bytes(self.path, limit=16)
        self.assertEqual(received, 17)

    def test_directory_fd_anchors_leaf_after_parent_rename(self) -> None:
        actual_parent = self.parent / "actual"
        actual_parent.mkdir(mode=0o700)
        path = actual_parent / "value"
        path.write_bytes(b"original")
        path.chmod(0o600)
        replacement = self.parent / "replacement"
        replacement.mkdir(mode=0o700)
        (replacement / "value").write_bytes(b"different")
        moved = self.parent / "moved"
        original_open = os.open
        swapped = False

        def open_and_rename(
            name: str | os.PathLike[str], flags: int, mode: int = 0o777, *, dir_fd: int | None = None
        ) -> int:
            nonlocal swapped
            if dir_fd is not None and not swapped:
                swapped = True
                actual_parent.rename(moved)
                actual_parent.symlink_to(replacement, target_is_directory=True)
            return original_open(name, flags, mode, dir_fd=dir_fd)

        with mock.patch.object(os, "open", side_effect=open_and_rename):
            self.assertEqual(readers.read_owned_bytes(path), b"original")


if __name__ == "__main__":
    unittest.main()
