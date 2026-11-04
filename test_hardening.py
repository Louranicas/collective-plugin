"""Executable boundary and recovery tests; no live mail or service mutation."""

from __future__ import annotations

import contextlib
import fcntl
import io
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, override
from unittest import mock

import collective as core
import heartbeat
import install_monitor as installer
from test_collective import RECIPIENT, SENDER, MonitorBackend, snapshot


class CoreTransportTests(unittest.TestCase):
    def test_real_child_json_and_text_contract(self) -> None:
        backend = core.Backend(timeout=3)
        result = backend.run([sys.executable, "-I", "-c", 'print(\'{"result":{"answer":42}}\')'])
        self.assertEqual(result, {"answer": 42})
        result = backend.run([sys.executable, "-I", "-c", "print('plain output')"], as_json=False)
        self.assertEqual(result, "plain output\n")

    def test_real_child_invalid_json_and_nonzero_exit(self) -> None:
        backend = core.Backend(timeout=3)
        for program in ("print('invalid-json')", "raise SystemExit(2)", 'print(\'{"error":{"code":"refused"}}\')'):
            with self.subTest(program=program), self.assertRaises(core.CollectiveError):
                backend.run([sys.executable, "-I", "-c", program])

    def test_real_child_timeout_and_unavailable_executable(self) -> None:
        backend = core.Backend(timeout=0.05)
        with self.assertRaises(core.TransportUncertain):
            backend.run([sys.executable, "-I", "-c", "import time; time.sleep(2)"])
        with self.assertRaises(core.CollectiveError):
            backend.run(["/nonexistent/collective-fixture-executable"])

    def test_snapshot_refuses_restart_between_reads(self) -> None:
        backend = core.Backend()
        with (
            mock.patch.object(
                backend,
                "tuios",
                side_effect=[
                    {"boot_id": "before"},
                    {"agents": []},
                    {"boot_id": "after"},
                ],
            ),
            self.assertRaises(core.CollectiveError),
        ):
            backend.snapshot("work")
        with self.assertRaises(core.CollectiveError):
            backend.snapshot("remote:work")

    def test_metadata_adapters_do_not_return_bodies(self) -> None:
        backend = core.Backend()
        with mock.patch.object(backend, "run", return_value="time | host | exit=0 | cwd\n") as run:
            result = backend.history("/fixture/project")
        self.assertFalse(result["command_bodies"])
        self.assertEqual(run.call_args.args[0][-2:], ["--cwd", "/fixture/project"])
        with mock.patch.object(
            backend,
            "run",
            return_value={
                "events": [
                    {"id": "event-1", "body": "NEVER-RETURN-THIS-BODY", "type": "status"},
                ]
            },
        ) as run:
            result = backend.memory("event-previous")
        self.assertNotIn("NEVER-RETURN", json.dumps(result))
        self.assertEqual(run.call_args.args[0][-2:], ["--since-event-id", "event-previous"])

    def test_ssh_observation_does_not_connect(self) -> None:
        backend = core.Backend()
        with mock.patch.object(
            backend,
            "run",
            side_effect=[
                "Id=fixture.service\nActiveState=active\n",
                {"Peer": {"p": {"HostName": "fixture", "Online": False, "LastSeen": "dated"}}},
            ],
        ) as run:
            result = backend.ssh_health()
        self.assertEqual(result["peers"][0]["online"], False)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0][0], "systemctl")


class CoreCliTests(unittest.TestCase):
    def invoke(self, args: Any, backend: Any) -> Any:
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(core, "Backend", return_value=backend),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            status = core.main(args)
        return status, stdout.getvalue(), stderr.getvalue()

    def test_read_commands_dispatch_to_backend(self) -> None:
        backend = mock.Mock()
        cases: list[Any] = [
            (["roster", "--session", "work"], "roster"),
            (["inbox", "--session", "work", "--pane", RECIPIENT], "inbox"),
            (["history", "--cwd", "/fixture"], "history"),
            (["memory", "--since-event-id", "event-1"], "memory"),
            (["ssh-health"], "ssh_health"),
        ]
        for args, method in cases:
            backend.reset_mock()
            getattr(backend, method).return_value = {"fixture": method}
            with self.subTest(args=args):
                status, output, _ = self.invoke(["--json", *args], backend)
                self.assertEqual(status, 0)
                self.assertEqual(json.loads(output), {"fixture": method})
                getattr(backend, method).assert_called_once()

    def test_cli_plan_apply_and_successful_cleanup(self) -> None:
        backend = mock.Mock()
        backend.snapshot.return_value = snapshot()
        backend.tuios.return_value = {"success": True, "message_id": 9}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body, plan = root / "body.txt", root / "plan.json"
            body.write_text("Reviewed fixture message", encoding="utf-8")
            status, output, _ = self.invoke(
                [
                    "--json",
                    "mail-plan",
                    "--session",
                    "work",
                    "--sender",
                    SENDER,
                    "--to",
                    RECIPIENT,
                    "--subject",
                    "fixture",
                    "--text-file",
                    str(body),
                    "--output",
                    str(plan),
                ],
                backend,
            )
            self.assertEqual(status, 0)
            self.assertTrue(plan.exists())
            backend.tuios.assert_not_called()
            digest = json.loads(output)["digest"]
            status, output, _ = self.invoke(
                [
                    "--json",
                    "mail-apply",
                    "--plan",
                    str(plan),
                    "--confirm",
                    digest,
                    "--journal",
                    str(root / "journal.jsonl"),
                ],
                backend,
            )
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output)["outcome"], "submitted")
            self.assertFalse(plan.exists())
            backend.tuios.assert_called_once()

    def test_cli_refusal_keeps_plan_and_does_not_submit(self) -> None:
        backend = mock.Mock()
        backend.snapshot.return_value = snapshot()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            plan = core.make_mail_plan(snapshot(), "work", SENDER, RECIPIENT, "fixture", "body")
            core.write_private_json(path, plan, exclusive=True)
            status, _, error = self.invoke(
                ["mail-apply", "--plan", str(path), "--confirm", "0" * 64, "--journal", str(Path(tmp) / "journal")],
                backend,
            )
            self.assertEqual(status, 2)
            self.assertIn("error", json.loads(error))
            self.assertTrue(path.exists())
            backend.tuios.assert_not_called()

    def test_collaboration_cli_only_creates_a_plan(self) -> None:
        backend = mock.Mock()
        backend.snapshot.return_value = snapshot()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            status, output, _ = self.invoke(
                [
                    "--json",
                    "collaboration-plan",
                    "--session",
                    "work",
                    "--sender",
                    SENDER,
                    "--reviewer",
                    RECIPIENT,
                    "--kind",
                    "handoff",
                    "--goal",
                    "fixture",
                    "--scope",
                    "tests only",
                    "--done",
                    "checks pass",
                    "--evidence",
                    "artifact:fixture",
                    "--output",
                    str(path),
                ],
                backend,
            )
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output)["plan"], str(path))
            body = json.loads(core.read_private_json(path)["payload"]["text"])
            self.assertEqual(body["evidence"], ["artifact:fixture"])
            backend.tuios.assert_not_called()


class InstallerTests(unittest.TestCase):
    def test_preview_has_no_side_effects(self) -> None:
        output = io.StringIO()
        with (
            mock.patch.object(sys, "argv", ["install_monitor.py"]),
            mock.patch.object(installer, "install") as install,
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(installer.main(), 0)
        self.assertEqual(set(json.loads(output.getvalue())), {installer.SERVICE, installer.TIMER})
        install.assert_not_called()

    def test_success_preserves_state_and_uses_existing_unit_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            unit_dir = home / ".config/systemd/user"
            unit_dir.mkdir(parents=True)
            original = b"# Managed by local.collective;\n[Unit]\nDescription=old\n"
            for name in (installer.SERVICE, installer.TIMER):
                (unit_dir / name).write_bytes(original)
            with (
                mock.patch.object(Path, "home", return_value=home),
                mock.patch.object(installer, "command") as commands,
            ):
                receipt = installer.install()
                expected_units = installer.units()
            self.assertEqual(receipt["timer"], installer.TIMER)
            backup = Path(receipt["backup"])
            self.assertEqual((backup / installer.SERVICE).read_bytes(), original)
            self.assertEqual((backup / installer.TIMER).read_bytes(), original)
            for name, content in expected_units.items():
                self.assertEqual((unit_dir / name).read_text(), content)
            self.assertEqual(commands.call_args_list[0].args[0][0], "systemd-analyze")
            self.assertEqual(commands.call_args_list[-1].args[0], ["systemctl", "--user", "start", installer.SERVICE])
            self.assertTrue((home / ".local/state/collective-plugin/scheduler-install-receipt.json").exists())

    def test_failed_activation_restores_existing_units(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            unit_dir = home / ".config/systemd/user"
            unit_dir.mkdir(parents=True)
            original = b"# Managed by local.collective;\n[Unit]\nDescription=old\n"
            for name in (installer.SERVICE, installer.TIMER):
                (unit_dir / name).write_bytes(original)

            def command(argv: Any) -> Any:
                if argv[-2:] == ["start", installer.SERVICE]:
                    raise installer.CollectiveError("fixture activation refused")

            with (
                mock.patch.object(Path, "home", return_value=home),
                mock.patch.object(installer, "command", side_effect=command),
                self.assertRaises(installer.CollectiveError),
            ):
                installer.install()
            for name in (installer.SERVICE, installer.TIMER):
                self.assertEqual((unit_dir / name).read_bytes(), original)

    def test_unrecognized_and_symlink_units_are_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            unit_dir = home / ".config/systemd/user"
            unit_dir.mkdir(parents=True)
            path = unit_dir / installer.SERVICE
            path.write_text("unrelated unit", encoding="utf-8")
            with mock.patch.object(Path, "home", return_value=home), mock.patch.object(installer, "command") as command:
                with self.assertRaises(installer.CollectiveError):
                    installer.install()
                command.assert_not_called()
            self.assertEqual(path.read_text(), "unrelated unit")
            path.unlink()
            target = home / "unrelated"
            target.write_text("keep", encoding="utf-8")
            path.symlink_to(target)
            with mock.patch.object(Path, "home", return_value=home), self.assertRaises(installer.CollectiveError):
                installer.install()
            self.assertEqual(target.read_text(), "keep")


class HeartbeatTests(unittest.TestCase):
    def test_command_errors_are_unknown_not_success(self) -> None:
        for error in (OSError("missing"), subprocess.TimeoutExpired("fixture", 1)):
            with (
                self.subTest(error=type(error).__name__),
                mock.patch.object(subprocess, "Popen", side_effect=error),
            ):
                self.assertEqual(heartbeat.run(["fixture"])[0], 99)

    def test_native_and_state_unavailable_paths(self) -> None:
        with mock.patch.object(os, "lstat", side_effect=FileNotFoundError):
            self.assertIsNone(heartbeat.herdr_agents())
        with mock.patch.object(heartbeat, "run", return_value=(1, "unavailable")):
            self.assertIsNone(heartbeat.agents())
            self.assertEqual(heartbeat.peers(), {})
        with mock.patch.object(heartbeat, "run", return_value=(0, "not json")):
            self.assertIsNone(heartbeat.agents())
            self.assertEqual(heartbeat.peers(), {})

    def test_private_state_roundtrip_and_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(heartbeat, "STATE", Path(tmp)):
            heartbeat.secure_state_dir()
            heartbeat.save("memory.json", {"fixture": True})
            self.assertEqual(heartbeat.load("memory.json", {}), {"fixture": True})
            self.assertEqual(heartbeat.load("absent.json", {"default": True}), {"default": True})
            path = Path(tmp) / "memory.json"
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            path.write_text("bad-json", encoding="utf-8")
            self.assertEqual(heartbeat.load("memory.json", {"fallback": True}), {"fallback": True})


if __name__ == "__main__":
    unittest.main()


class AdversarialBoundaries(unittest.TestCase):
    def test_combined_child_output_is_bounded(self) -> None:
        program = "import os; os.write(1,b'x'*1100000); os.write(2,b'y'*1100000)"
        with self.assertRaisesRegex(core.TransportUncertain, "Tool output exceeded 2 MB"):
            core.Backend(timeout=3).run([sys.executable, "-I", "-c", program])
        self.assertEqual(heartbeat.run([sys.executable, "-I", "-c", program], timeout=3)[0], 99)

    def test_receipt_must_prove_submission_and_invalid_receipt_cannot_retry(self) -> None:
        receipts: list[Any] = [
            None,
            [],
            {},
            {"success": False},
            {"message_id": True},
            {"message_id": 0},
            {"message_id": "42"},
        ]
        for receipt in receipts:
            with self.subTest(receipt=receipt), tempfile.TemporaryDirectory() as tmp:
                backend = mock.Mock()
                backend.snapshot.return_value = snapshot()
                backend.tuios.return_value = receipt
                plan = core.make_mail_plan(snapshot(), "work", SENDER, RECIPIENT, "fixture", "body")
                journal = core.Journal(Path(tmp) / "journal.jsonl")
                with self.assertRaises(core.CollectiveError):
                    core.apply_mail_plan(plan, core.plan_digest(plan), backend, journal)
                with self.assertRaises(core.CollectiveError):
                    core.apply_mail_plan(plan, core.plan_digest(plan), backend, journal)
                self.assertEqual(backend.tuios.call_count, 1)
                self.assertNotIn('"outcome":"submitted"', (Path(tmp) / "journal.jsonl").read_text())

    def test_nonobject_tuios_response_is_refused(self) -> None:
        backend = core.Backend()
        invalid_values: list[Any] = [None, [], "bad", True]
        for value in invalid_values:
            with (
                self.subTest(value=value),
                mock.patch.object(backend, "run", return_value=value),
                self.assertRaises(core.CollectiveError),
            ):
                backend.tuios("list-agents", {})

    def test_fresh_install_failure_removes_units_and_disables_timer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            seen = []

            def command(argv: Any) -> Any:
                seen.append(argv)
                if argv[-2:] == ["start", installer.SERVICE]:
                    raise installer.CollectiveError("original activation failure")

            with (
                mock.patch.object(Path, "home", return_value=home),
                mock.patch.object(installer, "command", side_effect=command),
                self.assertRaisesRegex(installer.CollectiveError, "original activation failure"),
            ):
                installer.install()
            for name in (installer.SERVICE, installer.TIMER):
                self.assertFalse((home / ".config/systemd/user" / name).exists())
            self.assertTrue(any("disable" in argv and installer.TIMER in argv for argv in seen))

    def test_heartbeat_alert_sanitizes_and_bounds_peer_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(heartbeat, "STATE", Path(tmp)):
            mem = heartbeat.memory_state({"needs_since": {"hblocked:pane": 1}})
            alerts: list[tuple[str, str]] = []
            heartbeat.native_alerts(
                [{"pane": "pane", "agent": "untrusted" + chr(0x202E) + "x" * 20000, "status": "blocked"}],
                mem,
                10000,
                alerts,
            )
            with mock.patch.object(heartbeat, "run", return_value=(0, "")) as run:
                heartbeat.finish({}, mem, alerts, 10000, dry=False)
            body = run.call_args.args[0][-1]
            self.assertLessEqual(len(body.encode()), 8192)
            self.assertNotIn(chr(0x202E), body)

    def test_nonfinite_numeric_metadata_cannot_break_observation(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                rows, _ = heartbeat.agent_rows(
                    [{"window_id": "pane", "unread": value}], heartbeat.memory_state({}), 10000, []
                )
                self.assertEqual(rows[0]["unread"], 0)

    def test_malformed_activity_metadata_is_unknown(self) -> None:
        for payload in ("[]", '{"messages":["bad"]}', '{"messages":{}}'):

            def run(argv: Any, payload: Any = payload) -> Any:
                return 0, payload if "read-agent-messages" in argv else '{"tasks":[]}'

            with self.subTest(payload=payload), mock.patch.object(heartbeat, "run", side_effect=run):
                active, reasons = heartbeat.activity([])
                self.assertTrue(active)
                self.assertIn("mail-unknown", reasons)

    def test_private_oversize_state_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(heartbeat, "STATE", Path(tmp)):
            path = Path(tmp) / "memory.json"
            path.write_text(" " * (heartbeat.MAX_BYTES + 1))
            path.chmod(0o600)
            with self.assertRaises(ValueError):
                heartbeat.load("memory.json", {})


class HeartbeatLifecycle(unittest.TestCase):
    @override
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(heartbeat, "STATE", self.state))
        self.stack.enter_context(mock.patch.object(sys, "argv", ["heartbeat.py", "--full"]))
        self.clock = self.stack.enter_context(mock.patch.object(time, "time", return_value=10000))
        self.agents = self.stack.enter_context(mock.patch.object(heartbeat, "agents", return_value=[]))
        self.native = self.stack.enter_context(mock.patch.object(heartbeat, "herdr_agents", return_value=[]))
        self.relay = self.stack.enter_context(mock.patch.object(heartbeat, "relay", return_value={}))
        self.peers = self.stack.enter_context(mock.patch.object(heartbeat, "peers", return_value={"omarchy": True}))
        self.stack.enter_context(mock.patch.object(heartbeat, "activity", return_value=(True, ["fixture-active"])))
        self.send = mock.Mock(return_value=(0, ""))

        def transport(argv: Any) -> Any:
            if "send-agent-message" in argv:
                return self.send(argv)
            return 0, json.dumps({"boot_id": "fixture-boot", "evicted": 0})

        self.stack.enter_context(mock.patch.object(heartbeat, "run", side_effect=transport))

    def test_full_sweeps_age_alert_once_resolve_and_recur(self) -> None:
        self.agents.return_value = [{"window_id": "pane", "unread": 3, "needs_you": True, "harness_id": "fixture"}]
        self.assertEqual(heartbeat.main(), 0)
        self.send.assert_not_called()
        self.clock.return_value += heartbeat.STALE_MAIL_S + 1
        self.assertEqual(heartbeat.main(), 0)
        self.assertIn("unread", self.send.call_args.args[0][-1])
        self.assertIn("waiting on you", self.send.call_args.args[0][-1])
        self.assertEqual(heartbeat.main(), 0)
        self.assertEqual(self.send.call_count, 1)
        self.agents.return_value = []
        self.assertEqual(heartbeat.main(), 0)
        memory: dict[str, Any] = heartbeat.load("memory.json", {})
        self.assertEqual(memory["needs_since"], {})
        self.assertEqual(memory["unread_since"], {})
        self.agents.return_value = [{"window_id": "pane", "unread": 1}]
        self.assertEqual(heartbeat.main(), 0)
        self.clock.return_value += heartbeat.STALE_MAIL_S + 1
        self.assertEqual(heartbeat.main(), 0)
        self.assertEqual(self.send.call_count, 2)
        board: dict[str, Any] = heartbeat.load("heartbeat.json", {})
        self.assertEqual(board["flex"]["mode"], "active")

    def test_peer_transition_and_native_unknown_are_change_only(self) -> None:
        self.assertEqual(heartbeat.main(), 0)
        self.peers.return_value = {"omarchy": False}
        self.native.return_value = None
        self.agents.return_value = None
        self.assertEqual(heartbeat.main(), 0)
        body = self.send.call_args.args[0][-1]
        self.assertIn("offline", body)
        self.assertIn("UNKNOWN", body)
        self.assertIn("SSH reachability unverified", body)
        self.assertEqual(heartbeat.main(), 0)
        self.assertEqual(self.send.call_count, 1)

    def test_quiet_tick_skips_expensive_collectors(self) -> None:
        with (
            mock.patch.object(heartbeat, "activity", return_value=(False, [])),
            mock.patch.object(sys, "argv", ["heartbeat.py"]),
        ):
            self.assertEqual(heartbeat.main(), 0)
            self.native.reset_mock()
            self.clock.return_value += 120
            self.assertEqual(heartbeat.main(), 0)
            self.native.assert_not_called()
            memory: dict[str, Any] = heartbeat.load("memory.json", {})
            self.assertEqual(memory["mode"], "quiet-skip")
            self.clock.return_value += heartbeat.QUIET_FULL_S
            self.assertEqual(heartbeat.main(), 0)
            self.native.assert_called_once()

    def test_dry_run_reads_but_does_not_persist_or_send(self) -> None:
        self.native.return_value = None
        with (
            mock.patch.object(sys, "argv", ["heartbeat.py", "--dry-run"]),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(heartbeat.main(), 0)
        self.assertIn("WOULD SEND", output.getvalue())
        self.send.assert_not_called()
        self.assertFalse((self.state / "memory.json").exists())
        self.assertFalse((self.state / "heartbeat.json").exists())

    def test_existing_lock_and_invalid_lock_never_sweep(self) -> None:
        with (
            mock.patch.object(fcntl, "flock", side_effect=BlockingIOError),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(heartbeat.main(), 0)
        self.agents.assert_not_called()
        (self.state / "heartbeat.lock").chmod(0o644)
        with self.assertRaises(ValueError):
            heartbeat.main()
        self.agents.assert_not_called()

    def test_untrusted_memory_schema_is_refused_before_effect(self) -> None:
        values: list[Any] = [[], {"sent": []}, {"needs_since": {"pane": True}}, {"peers": {"host": "true"}}]
        for value in values:
            with self.subTest(value=value):
                heartbeat.save("memory.json", value)
                with self.assertRaises((ValueError, TypeError)):
                    heartbeat.main()
        self.send.assert_not_called()


class RefusalAndRecovery(unittest.TestCase):
    def test_plan_construction_rejects_incomplete_identity_and_reply(self) -> None:
        for changes in ({"now": True}, {"session": "remote:work"}, {"reply_to": 0}, {"reply_to": True}):
            with self.subTest(changes=changes), self.assertRaises(core.CollectiveError):
                core.make_mail_plan(
                    snapshot(),
                    "work" if "session" not in changes else changes.pop("session"),
                    SENDER,
                    RECIPIENT,
                    "fixture",
                    "body",
                    **changes,
                )
        for key in ("boot_id", "endpoint"):
            state = snapshot()
            state.pop(key)
            with self.subTest(key=key), self.assertRaises(core.CollectiveError):
                core.make_mail_plan(state, "work", SENDER, RECIPIENT, "fixture", "body")
        with self.assertRaises(core.CollectiveError):
            core.make_collaboration_plan(
                snapshot(), "work", SENDER, RECIPIENT, "review", "goal", "scope", "done", evidence=["x"] * 17
            )

    def test_plan_validation_rejects_schema_confirmation_and_extra_payload(self) -> None:
        plan = core.make_mail_plan(snapshot(), "work", SENDER, RECIPIENT, "fixture", "body")
        for key, value in (("schema", 2), ("action", "other")):
            altered = dict(plan, **{key: value})
            with self.subTest(key=key), self.assertRaises(core.CollectiveError):
                core.validate_mail_plan(altered, snapshot(), core.plan_digest(altered))
        with self.assertRaises(core.CollectiveError):
            core.validate_mail_plan(plan, snapshot(), None)
        plan["payload"]["unexpected"] = "data"
        plan["digest"] = core.plan_digest(plan)
        with self.assertRaises(core.CollectiveError):
            core.validate_mail_plan(plan, snapshot(), plan["digest"])

    def test_journal_corrupt_oversized_and_rate_limited_refuse_before_send(self) -> None:
        for contents in ("invalid-json\n", "[]\n", " " * (core.MAX_JOURNAL_BYTES + 1)):
            with self.subTest(size=len(contents)), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "journal"
                path.write_text(contents)
                path.chmod(0o600)
                backend = mock.Mock()
                backend.snapshot.return_value = snapshot()
                plan = core.make_mail_plan(snapshot(), "work", SENDER, RECIPIENT, "fixture", "body")
                with self.assertRaises(core.CollectiveError):
                    core.apply_mail_plan(plan, plan["digest"], backend, core.Journal(path))
                backend.tuios.assert_not_called()
        with tempfile.TemporaryDirectory() as tmp:
            journal = core.Journal(Path(tmp) / "journal")
            for _ in range(core.RATE_LIMIT):
                journal.consume(core.make_mail_plan(snapshot(), "work", SENDER, RECIPIENT, "fixture", "body"))
            with self.assertRaises(core.CollectiveError):
                journal.consume(core.make_mail_plan(snapshot(), "work", SENDER, RECIPIENT, "fixture", "body"))

    def test_native_socket_deadline_peer_uid_eof_and_size(self) -> None:
        for case in ("deadline", "wrong-uid", "eof", "size", "relative"):
            sock = mock.MagicMock()
            sock.__enter__.return_value = sock
            sock.getsockopt.return_value = struct.pack(
                "3i", os.getpid(), os.getuid() + (case == "wrong-uid"), os.getgid()
            )
            sock.recv.return_value = b"x" * (core.MAX_TOOL_OUTPUT + 1) if case == "size" else b""
            backend = core.Backend(native_socket="relative" if case == "relative" else "/fixture/socket")
            with (
                self.subTest(case=case),
                mock.patch.object(socket, "socket", return_value=sock),
                mock.patch.object(
                    time, "monotonic", side_effect=[1, 999] if case == "deadline" else None, return_value=1
                ),
                self.assertRaises(core.CollectiveError),
            ):
                backend.native_request("ping", {})
            if case == "wrong-uid":
                sock.sendall.assert_not_called()

    def test_native_roster_success_projects_fields_without_content(self) -> None:
        backend = core.Backend(native_socket="/fixture/socket")
        with (
            mock.patch.object(backend, "snapshot", return_value=snapshot()),
            mock.patch.object(
                backend,
                "native_request",
                side_effect=[
                    {"version": "fixture"},
                    {"agents": [{"pane_id": "peer", "agent": "fixture", "secret": "NO"}]},
                ],
            ),
        ):
            result = backend.roster("work")
        self.assertEqual(result["native_herdr"]["agents"][0]["pane_id"], "peer")
        self.assertNotIn("secret", json.dumps(result))
        backend = core.Backend(native_herdr="/fixture/herdr")
        with (
            mock.patch.object(backend, "snapshot", return_value=snapshot()),
            mock.patch.object(backend, "run", return_value={"agents": []}),
        ):
            self.assertEqual(backend.roster("work")["native_herdr"]["agents"], [])
        invalid_rows: list[Any] = [[], {"agents": {}}, {"agents": ["bad"]}]
        for data in invalid_rows:
            with self.subTest(data=data), self.assertRaises(core.CollectiveError):
                backend.native_agents(data)

    def test_snapshot_and_inbox_schema_refusal_and_untrusted_body_label(self) -> None:
        backend = core.Backend()
        with (
            mock.patch.object(
                backend, "tuios", side_effect=[{"boot_id": "boot"}, {"agents": ["bad"]}, {"boot_id": "boot"}]
            ),
            self.assertRaises(core.CollectiveError),
        ):
            backend.snapshot("work")
        for data in ({}, {"messages": ["bad"]}, {"messages": None}):
            with (
                self.subTest(data=data),
                mock.patch.object(backend, "tuios", return_value=data),
                self.assertRaises(core.CollectiveError),
            ):
                backend.inbox("work", SENDER)
        with mock.patch.object(backend, "tuios", return_value={"messages": [{"to": SENDER, "text": "untrusted"}]}):
            result = backend.inbox("work", SENDER, bodies=True)
        self.assertTrue(result["untrusted_peer_content"])
        self.assertEqual(result["messages"][0]["text"], "untrusted")

    def test_observation_failure_and_desktop_notification_are_explicit(self) -> None:
        backend: Any = MonitorBackend()
        backend.history = mock.Mock(side_effect=core.CollectiveError("unavailable"))
        backend.run = mock.Mock(side_effect=core.CollectiveError("notification refused"))
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(shutil, "which", return_value="/fixture/notify"),
        ):
            result = core.monitor(backend, "work", tmp, notify=True)
        self.assertFalse(result["history"]["available"])
        self.assertIn("unavailable", result["notification"])
        backend.run.assert_called_once()
        backend.run = mock.Mock(return_value="")
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(shutil, "which", return_value="/fixture/notify"),
        ):
            result = core.monitor(backend, "work", tmp, notify=True)
        self.assertIn("sent", result["notification"])

    def test_private_path_refusal_and_invalid_plan_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            unsafe = root / "unsafe"
            unsafe.mkdir(mode=0o755)
            with self.assertRaises(core.CollectiveError):
                core.private_dir(unsafe)
            unsafe.chmod(0o700)
            link = root / "link"
            link.symlink_to(unsafe)
            with self.assertRaises(core.CollectiveError):
                core.private_dir(link)
            path = root / "plan"
            path.write_text("{}")
            with self.assertRaises(core.CollectiveError):
                core.read_private_json(path)


class SchedulerRecoveryPaths(unittest.TestCase):
    def test_notification_failure_backoff_and_pending_batch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(heartbeat, "STATE", Path(tmp)):
            memory = heartbeat.memory_state({})
            pending = [(f"mail:{n}", "fixture") for n in range(20)]
            with mock.patch.object(heartbeat, "run", return_value=(99, "private error body")) as run:
                heartbeat.finish({}, memory, pending, 10000, dry=False)
                self.assertEqual(memory["notice_failures"], 1)
                self.assertEqual(memory["notice_rc"], 99)
                heartbeat.finish({}, memory, pending, 10120, dry=False)
                self.assertEqual(run.call_count, 1)
                persisted: dict[str, Any] = heartbeat.load("memory.json", {})
                self.assertNotIn("private error body", json.dumps(persisted))
            with mock.patch.object(heartbeat, "run", return_value=(0, "")) as run:
                heartbeat.finish({}, memory, pending, 11000, dry=False)
                self.assertEqual(len(memory["sent"]), 16)
                heartbeat.finish({}, memory, pending, 11001, dry=False)
                self.assertEqual(len(memory["sent"]), 20)
                self.assertEqual(run.call_count, 2)

    def test_ring_eviction_boot_change_and_bad_read(self) -> None:
        memory = heartbeat.memory_state({})
        alerts: list[tuple[str, str]] = []
        with mock.patch.object(
            heartbeat, "run", side_effect=[(0, '{"boot_id":"A"}'), (0, '{"evicted":3}'), (0, '{"boot_id":"A"}')] * 2
        ):
            heartbeat.ring_alert(memory, alerts)
            heartbeat.ring_alert(memory, alerts)
        self.assertEqual(len(alerts), 1)
        self.assertIn("history incomplete", alerts[0][1])
        for replies in (
            [(99, "")] * 3,
            [(0, "[]")] * 3,
            [(0, "bad-json")] * 3,
            [(0, '{"boot_id":"A"}'), (0, '{"evicted":4}'), (0, '{"boot_id":"B"}')],
        ):
            with self.subTest(replies=replies), mock.patch.object(heartbeat, "run", side_effect=replies):
                heartbeat.ring_alert(memory, alerts)
            self.assertEqual(len(alerts), 1)
        with mock.patch.object(
            heartbeat, "run", side_effect=[(0, '{"boot_id":"B"}'), (0, '{"evicted":1}'), (0, '{"boot_id":"B"}')]
        ):
            heartbeat.ring_alert(memory, alerts)
        self.assertEqual(len(alerts), 2)

    def test_relay_peer_and_card_metadata_reads(self) -> None:
        with mock.patch.object(
            heartbeat,
            "run",
            return_value=(0, "ActiveState=activating\nSubState=auto-restart\nNRestarts=2\nResult=exit-code\n"),
        ):
            result = heartbeat.relay()
        alerts: list[tuple[str, str]] = []
        heartbeat.relay_alerts(result, alerts)
        self.assertEqual(len(alerts), 1)
        self.assertIn("NRestarts=2", alerts[0][1])
        for text in ("bad-json", "[]", '{"Peer":[]}'):
            with self.subTest(text=text), mock.patch.object(heartbeat, "run", return_value=(0, text)):
                self.assertEqual(heartbeat.peers(), {})
        with mock.patch.object(
            heartbeat, "run", return_value=(0, '{"Peer":{"a":{"HostName":"fixture","Online":true},"b":"bad"}}')
        ):
            self.assertEqual(heartbeat.peers(), {"fixture": True})
        with mock.patch.object(heartbeat, "run", side_effect=[(0, '{"messages":[]}'), (0, '{"tasks":["bad"]}')]):
            self.assertIn("tasks-unknown", heartbeat.activity([])[1])

    def test_rollback_failures_preserve_original_activation_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            failed = False

            def command(argv: Any) -> Any:
                nonlocal failed
                if argv[-2:] == ["start", installer.SERVICE]:
                    failed = True
                    raise installer.CollectiveError("original activation failure")
                if failed:
                    raise installer.CollectiveError("cleanup failure")

            with (
                mock.patch.object(Path, "home", return_value=home),
                mock.patch.object(installer, "command", side_effect=command),
                self.assertRaisesRegex(installer.CollectiveError, "original activation failure") as caught,
            ):
                installer.install()
            self.assertIn("Rollback errors", " ".join(caught.exception.__notes__))
            for name in (installer.SERVICE, installer.TIMER):
                self.assertFalse((home / ".config/systemd/user" / name).exists())

    def test_unsafe_unit_directory_and_unit_modes_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            destination = home / ".config/systemd/user"
            target = home / "target"
            target.mkdir()
            destination.parent.mkdir(parents=True)
            destination.symlink_to(target)
            with mock.patch.object(Path, "home", return_value=home), self.assertRaises(installer.CollectiveError):
                installer.install()
            destination.unlink()
            destination.mkdir()
            unit = destination / installer.SERVICE
            unit.write_text("# Managed by local.collective;\n")
            unit.chmod(0o666)
            with mock.patch.object(Path, "home", return_value=home), self.assertRaises(installer.CollectiveError):
                installer.install()

    def test_installer_command_failure_and_main_error_exit(self) -> None:
        with (
            mock.patch.object(subprocess, "run", return_value=mock.Mock(returncode=1)),
            self.assertRaises(installer.CollectiveError),
        ):
            installer.command(["systemctl"])
        with (
            mock.patch.object(sys, "argv", ["install_monitor.py", "--install"]),
            mock.patch.object(installer, "install", side_effect=installer.CollectiveError("fixture")),
            contextlib.redirect_stderr(io.StringIO()) as error,
        ):
            self.assertEqual(installer.main(), 2)
        self.assertEqual(json.loads(error.getvalue()), {"error": "fixture"})


class DeliveryOutcomeClassification(unittest.TestCase):
    def test_ambiguous_process_receipt_is_unknown_explicit_refusal_is_refused(self) -> None:
        for program, outcome in (
            ("print('invalid-json')", "unknown"),
            ("print('[]')", "unknown"),
            ('print(\'{"error":{"code":"forbidden"}}\'); raise SystemExit(2)', "refused"),
        ):
            with self.subTest(outcome=outcome, program=program), tempfile.TemporaryDirectory() as tmp:
                backend = core.Backend()
                real_run = backend.run
                plan = core.make_mail_plan(snapshot(), "work", SENDER, RECIPIENT, "fixture", "body")
                journal = core.Journal(Path(tmp) / "journal")
                with (
                    mock.patch.object(backend, "snapshot", return_value=snapshot()),
                    mock.patch.object(
                        backend,
                        "run",
                        side_effect=lambda argv, run=real_run, code=program: run([sys.executable, "-I", "-c", code]),
                    ),
                ):
                    expected = core.TransportUncertain if outcome == "unknown" else core.CollectiveError
                    with self.assertRaises(expected):
                        core.apply_mail_plan(plan, plan["digest"], backend, journal)
                    with self.assertRaises(core.CollectiveError):
                        core.apply_mail_plan(plan, plan["digest"], backend, journal)
                records = [json.loads(line) for line in journal.path.read_text().splitlines()]
                self.assertEqual([record["outcome"] for record in records], ["intent", outcome])


class PrivateDirectoryCreation(unittest.TestCase):
    def test_new_intermediate_directories_are_private_existing_ancestors_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "existing"
            existing.mkdir(mode=0o755)
            target = existing / "private" / "nested"
            previous = os.umask(0o022)
            try:
                self.assertEqual(core.private_dir(target), target)
            finally:
                os.umask(previous)
            self.assertEqual(existing.stat().st_mode & 0o777, 0o755)
            self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
