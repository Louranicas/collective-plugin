"""Boundary tests owned by Codex 2; all backends are local fakes."""

import copy
import json
import multiprocessing
import os
import selectors
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

import collective as c
import heartbeat as hb

SENDER = "11111111-1111-4111-8111-111111111111"
RECIPIENT = "22222222-2222-4222-8222-222222222222"
NOW = 1800000000


def snapshot() -> Any:
    return {
        "boot_id": "test-boot",
        "endpoint": "/tmp/collective-test.sock",
        "agents": [
            {
                "window_id": p,
                "session": "work",
                "agent_session_id": "turn-" + p,
                "foreground": "codex",
                "harness_id": "codex",
            }
            for p in (SENDER, RECIPIENT)
        ],
    }


def race_consume(path: Any, plan: Any, start: Any, results: Any) -> Any:
    start.wait(5)
    try:
        c.Journal(path).consume(plan)
        results.put("accepted")
    except c.CollectiveError:
        results.put("refused")
    except (OSError, ValueError, TypeError) as exc:
        results.put(type(exc).__name__)


class FakeBackend:
    def __init__(self, state: Any = None, error: Any = None) -> None:
        self.state = state or snapshot()
        self.error = error
        self.calls: list[Any] = []

    def snapshot(self, session: Any) -> Any:
        return copy.deepcopy(self.state)

    def tuios(self, verb: Any, params: Any) -> Any:
        self.calls.append((verb, copy.deepcopy(params)))
        if self.error:
            raise self.error
        return {"success": True, "message_id": 42}

    def run(self, argv: list[str], *, as_json: bool = True) -> Any:
        raise AssertionError("Unexpected process execution by mail fixture")

    def roster(self, session: str) -> Any:
        raise AssertionError("Unexpected roster read by mail fixture")

    def history(self, cwd: str | None = None) -> Any:
        raise AssertionError("Unexpected history read by mail fixture")

    def memory(self, since: str | None = None) -> Any:
        raise AssertionError("Unexpected memory read by mail fixture")

    def ssh_health(self) -> Any:
        raise AssertionError("Unexpected SSH read by mail fixture")


class PlanHelpers:
    def make(self, **changes: Any) -> Any:
        args = {
            "snapshot": snapshot(),
            "session": "work",
            "sender": SENDER,
            "recipient": RECIPIENT,
            "subject": "Review result",
            "text": "Fixture body",
            "now": NOW,
        }
        args.update(changes)
        return c.make_mail_plan(**args)

    def validate(self, plan: Any, state: Any = None, now: Any = NOW) -> Any:
        return c.validate_mail_plan(plan, state or snapshot(), c.plan_digest(plan), now=now)


class Plans(PlanHelpers, unittest.TestCase):
    def test_collaboration_fields_survive_existing_mail_gate(self) -> None:
        goal = "Review $(never-execute) and 'quoted' evidence"
        for kind in ("intent", "milestone", "blocker", "handoff", "review"):
            with self.subTest(kind=kind):
                plan = c.make_collaboration_plan(
                    snapshot(),
                    "work",
                    SENDER,
                    RECIPIENT,
                    kind,
                    goal,
                    "test_collective.py only",
                    "All boundary tests pass",
                    ["artifact:fixture-sha256"],
                    now=NOW,
                )
                payload = self.validate(plan)
                body = json.loads(payload["text"])
                self.assertEqual(body["goal"], goal)
                self.assertEqual(body["scope"], "test_collective.py only")
                self.assertEqual(body["owner"], SENDER)
                self.assertEqual(body["reviewer"], RECIPIENT)
                self.assertEqual(body["kind"], kind)
                self.assertEqual(body["definition_of_done"], "All boundary tests pass")
                self.assertEqual(body["evidence"], ["artifact:fixture-sha256"])
                self.assertEqual(plan["action"], "tuios.mail")

    def test_collaboration_rejects_self_review_and_unknown_kind(self) -> None:
        for reviewer, kind in ((SENDER, "review"), (RECIPIENT, "execute")):
            with self.subTest(reviewer=reviewer, kind=kind), self.assertRaises(c.CollectiveError):
                c.make_collaboration_plan(snapshot(), "work", SENDER, reviewer, kind, "goal", "scope", "done", now=NOW)

    def test_valid_plan_round_trip(self) -> None:
        plan = self.make()
        payload = self.validate(plan)
        self.assertEqual(payload["text"], "Fixture body")

    def test_injection_text_stays_data(self) -> None:
        body = "$(touch /tmp/NEVER-RUN); `id` 'quoted'\nsecond line"
        payload = self.validate(self.make(text=body))
        self.assertEqual(payload["text"], body)

    def test_confirmation_binds_exact_plan(self) -> None:
        plan = self.make()
        digest = c.plan_digest(plan)
        changed = copy.deepcopy(plan)
        changed["payload"]["subject"] = "Changed"
        with self.assertRaises(c.CollectiveError):
            c.validate_mail_plan(changed, snapshot(), digest, now=NOW)

    def test_wrong_confirmation_refused(self) -> None:
        with self.assertRaises(c.CollectiveError):
            c.validate_mail_plan(self.make(), snapshot(), "0" * 64, now=NOW)

    def test_expired_and_future_plans_refused(self) -> None:
        for now in (NOW - 1, NOW + 301):
            with self.subTest(now=now), self.assertRaises(c.CollectiveError):
                self.validate(self.make(), now=now)

    def test_endpoint_and_boot_change_refused(self) -> None:
        for key in ("endpoint", "boot_id"):
            state = snapshot()
            state[key] = "different"
            with self.subTest(key=key), self.assertRaises(c.CollectiveError):
                self.validate(self.make(), state)

    def test_both_member_incarnations_bound(self) -> None:
        for member in (0, 1):
            for key in ("agent_session_id", "foreground", "session", "harness_id"):
                state = snapshot()
                state["agents"][member][key] = "different"
                with self.subTest(member=member, key=key), self.assertRaises(c.CollectiveError):
                    self.validate(self.make(), state)

    def test_member_disappearance_refused(self) -> None:
        for member in (0, 1):
            state = snapshot()
            state["agents"].pop(member)
            with self.subTest(member=member), self.assertRaises(c.CollectiveError):
                self.validate(self.make(), state)

    def test_invalid_targets_refused(self) -> None:
        for recipient in (SENDER, "human", "not-a-pane", "00000000-0000-0000-0000-000000000000"):
            with self.subTest(recipient=recipient), self.assertRaises(c.CollectiveError):
                self.make(recipient=recipient)

    def test_control_and_oversized_bodies_refused(self) -> None:
        for body in ("", "x\x00y", "x\x1by", "\u202ereversed", "x" * 8193, "\u00e9" * 4097):
            with self.subTest(size=len(body)), self.assertRaises(c.CollectiveError):
                self.make(text=body)

    def test_subject_limit(self) -> None:
        with self.assertRaises(c.CollectiveError):
            self.make(subject="x" * 121)

    def test_unknown_plan_field_refused(self) -> None:
        plan = self.make()
        plan["unexpected"] = "extra authority"
        with self.assertRaises(c.CollectiveError):
            self.validate(plan)

    def test_invalid_sender_refused(self) -> None:
        for sender in ("human", "", "00000000-0000-0000-0000-000000000000"):
            with self.subTest(sender=sender), self.assertRaises(c.CollectiveError):
                self.make(sender=sender)

    def test_duplicate_members_refused(self) -> None:
        state = snapshot()
        state["agents"].append(copy.deepcopy(state["agents"][1]))
        with self.assertRaises(c.CollectiveError):
            self.make(snapshot=state)


class JournalAndDelivery(PlanHelpers, unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "journal.jsonl"

    def test_exactly_one_send_and_replay_refused(self) -> None:
        backend = FakeBackend()
        plan = self.make()
        journal = c.Journal(self.path)
        c.apply_mail_plan(plan, c.plan_digest(plan), backend, journal, now=NOW)
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(backend.calls[0][0], "send-agent-message")
        with self.assertRaises(c.CollectiveError):
            c.apply_mail_plan(plan, c.plan_digest(plan), backend, c.Journal(self.path), now=NOW)
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("Fixture body", self.path.read_text())

    def test_timeout_consumes_intent_and_never_retries(self) -> None:
        backend = FakeBackend(error=TimeoutError("uncertain delivery"))
        plan = self.make()
        with self.assertRaises(c.TransportUncertain):
            c.apply_mail_plan(plan, c.plan_digest(plan), backend, c.Journal(self.path), now=NOW)
        self.assertEqual(len(backend.calls), 1)
        with self.assertRaises(c.CollectiveError):
            c.apply_mail_plan(plan, c.plan_digest(plan), backend, c.Journal(self.path), now=NOW)
        self.assertEqual(len(backend.calls), 1)

    def test_changed_live_snapshot_does_not_consume_or_send(self) -> None:
        state = snapshot()
        state["boot_id"] = "restarted"
        backend = FakeBackend(state)
        plan = self.make()
        with self.assertRaises(c.CollectiveError):
            c.apply_mail_plan(plan, c.plan_digest(plan), backend, c.Journal(self.path), now=NOW)
        self.assertEqual(backend.calls, [])

    def test_symlink_journal_refused(self) -> None:
        target = Path(self.tmp.name) / "unrelated"
        target.write_text("preserve me")
        self.path.symlink_to(target)
        with self.assertRaises((c.CollectiveError, OSError)):
            c.Journal(self.path).consume(self.make())
        self.assertEqual(target.read_text(), "preserve me")

    def test_process_race_consumes_only_once(self) -> None:
        ctx = multiprocessing.get_context("fork")
        start, results = ctx.Event(), ctx.Queue()
        plan = self.make()
        children = [ctx.Process(target=race_consume, args=(self.path, plan, start, results)) for _ in range(4)]
        for child in children:
            child.start()
        start.set()
        try:
            observed = [results.get(timeout=10) for _ in children]
            self.assertEqual(observed.count("accepted"), 1, observed)
            self.assertEqual(observed.count("refused"), 3, observed)
        finally:
            for child in children:
                child.join(2)
                if child.is_alive():
                    child.terminate()
                    child.join(2)

    def test_same_nonce_with_different_payload_refused(self) -> None:
        first = self.make()
        second = self.make(request_id=first["request_id"], text="different payload")
        journal = c.Journal(self.path)
        journal.consume(first)
        with self.assertRaises(c.CollectiveError):
            journal.consume(second)

    def test_nonprivate_and_hardlinked_journals_refused(self) -> None:
        self.path.write_text("")
        self.path.chmod(0o644)
        with self.assertRaises(c.CollectiveError):
            c.Journal(self.path).consume(self.make())
        self.path.chmod(0o600)
        alias = Path(self.tmp.name) / "hardlink"
        alias.hardlink_to(self.path)
        with self.assertRaises(c.CollectiveError):
            c.Journal(self.path).consume(self.make())
        self.assertEqual(self.path.read_text(), "")

    def test_private_json_refuses_before_truncating_existing_file(self) -> None:
        target = Path(self.tmp.name) / "existing.json"
        target.write_text("preserve original bytes")
        target.chmod(0o644)
        with self.assertRaises(c.CollectiveError):
            c.write_private_json(target, {"replacement": True})
        self.assertEqual(target.read_text(), "preserve original bytes")
        target.chmod(0o600)
        alias = Path(self.tmp.name) / "existing-alias"
        alias.hardlink_to(target)
        with self.assertRaises(c.CollectiveError):
            c.write_private_json(target, {"replacement": True})
        self.assertEqual(alias.read_text(), "preserve original bytes")


class MonitorBackend:
    def __init__(self) -> None:
        self.boot = "boot-A"
        self.calls: list[Any] = []
        self.fail_ring = False

    def roster(self, session: Any) -> Any:
        return {"tuios": {"boot_id": self.boot, "agents": snapshot()["agents"]}}

    def history(self, cwd: str | None = None) -> Any:
        return {"metadata": []}

    def memory(self, since: str | None = None) -> Any:
        return {"events": []}

    def ssh_health(self) -> Any:
        return {"units": [], "peers": []}

    def tuios(self, verb: Any, params: Any) -> Any:
        self.calls.append((verb, params))
        if self.fail_ring:
            raise c.CollectiveError("unavailable")
        return {
            "messages": [
                {"id": 1, "to": RECIPIENT, "text": "PRIVATE BODY", "subject": "PRIVATE SUBJECT"},
                {"id": 2, "to": RECIPIENT, "read_at": 12, "text": "already read"},
                {"id": 3, "to": SENDER, "text": "other inbox"},
                {"id": 4, "text": "session notice"},
            ],
            "evicted": 0,
        }

    def snapshot(self, session: object) -> Any:
        raise AssertionError("Unexpected snapshot read by monitor fixture")

    def run(self, argv: list[str], *, as_json: bool = True) -> Any:
        raise AssertionError("Unexpected process execution by monitor fixture")


class PassiveReads(unittest.TestCase):
    def test_socket_wrapper_passes_json_as_single_argument(self) -> None:
        backend = c.Backend(tuios_bin="/fixture/tuios")
        text = "$(never-run); 'quotes'\nline2"
        with mock.patch.object(backend, "run", return_value={"success": True}) as run:
            backend.tuios("send-agent-message", {"text": text})
        argv = run.call_args.args[0]
        self.assertEqual(json.loads(argv[-1]), {"text": text})
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_inbox_filters_metadata_without_receipts(self) -> None:
        backend = c.Backend(tuios_bin="/does/not/run")
        fake = MonitorBackend()
        with mock.patch.object(backend, "tuios", side_effect=fake.tuios):
            result = backend.inbox("work", RECIPIENT)
        self.assertEqual([m["id"] for m in result["messages"]], [1, 2, 4])
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertTrue(result["passive"])
        self.assertNotIn("to", fake.calls[0][1])
        self.assertNotIn("unread", fake.calls[0][1])

    def test_monitor_dedup_restart_and_no_body_persistence(self) -> None:
        backend: Any = MonitorBackend()
        with tempfile.TemporaryDirectory() as tmp:
            first = c.monitor(backend, "work", tmp)
            second = c.monitor(backend, "work", tmp)
            self.assertEqual(first["mail"]["new_unread_count"], 3)
            self.assertEqual(second["mail"]["new_unread_count"], 0)
            backend.boot = "boot-B"
            restarted = c.monitor(backend, "work", tmp)
            self.assertEqual(restarted["mail"]["new_unread_count"], 3)
            self.assertNotIn("PRIVATE", (Path(tmp) / "latest.json").read_text())
            self.assertTrue(all("to" not in params for _, params in backend.calls))

    def test_monitor_failure_preserves_previous_cursor(self) -> None:
        backend: Any = MonitorBackend()
        with tempfile.TemporaryDirectory() as tmp:
            c.monitor(backend, "work", tmp)
            previous = (Path(tmp) / "monitor-state.json").read_text()
            backend.fail_ring = True
            failed = c.monitor(backend, "work", tmp)
            self.assertFalse(failed["mail"]["available"])
            self.assertEqual((Path(tmp) / "monitor-state.json").read_text(), previous)


class NativeSocket(unittest.TestCase):
    @override
    def setUp(self) -> None:
        metadata = mock.Mock(st_mode=0o140600, st_uid=os.getuid())
        self.enterContext(mock.patch.object(os, "lstat", return_value=metadata))

    def backend(self) -> Any:
        return c.Backend(tuios_bin="/fixture/tuios", native_socket="/fixture/herdr.sock")

    def exchange(self, wrong_id: Any = False, timeout: Any = False) -> Any:
        sock = mock.MagicMock()
        sock.__enter__.return_value = sock
        sock.getsockopt.return_value = struct.pack("3i", os.getpid(), os.getuid(), os.getgid())

        replied = False

        def response(_: Any) -> Any:
            nonlocal replied
            if timeout:
                raise TimeoutError("fixture timeout")
            if replied:
                raise BlockingIOError("no more queued bytes")
            replied = True
            request = json.loads(sock.sendall.call_args.args[0])
            return (
                json.dumps({"id": "wrong" if wrong_id else request["id"], "result": {"agents": []}}) + "\n"
            ).encode()

        sock.recv.side_effect = response
        return sock

    def test_read_request_uses_correlated_json_frame(self) -> None:
        sock = self.exchange()
        with mock.patch.object(socket, "socket", return_value=sock):
            self.assertEqual(self.backend().native_request("agent.list", {}), {"agents": []})
        request = json.loads(sock.sendall.call_args.args[0])
        self.assertEqual(request["method"], "agent.list")
        self.assertEqual(request["params"], {})
        self.assertTrue(sock.sendall.call_args.args[0].endswith(b"\n"))
        sock.connect.assert_called_once_with("/fixture/herdr.sock")
        sock.sendall.assert_called_once()
        self.assertEqual(sock.recv.call_count, 2)

    def test_write_and_extra_params_refused_before_connect(self) -> None:
        with mock.patch.object(socket, "socket") as factory:
            for method, params in [("pane.send_text", {}), ("agent.list", {"unexpected": True})]:
                with self.subTest(method=method), self.assertRaises(c.CollectiveError):
                    self.backend().native_request(method, params)
        factory.assert_not_called()

    def test_wrong_response_id_and_timeout_refused(self) -> None:
        for wrong, timeout in [(True, False), (False, True)]:
            sock = self.exchange(wrong_id=wrong, timeout=timeout)
            with (
                mock.patch.object(socket, "socket", return_value=sock),
                self.subTest(wrong=wrong, timeout=timeout),
                self.assertRaises(c.CollectiveError),
            ):
                self.backend().native_request("ping", {})
            self.assertEqual(sock.connect.call_count, 1)
            sock.sendall.assert_called_once()
            self.assertEqual(sock.recv.call_count, 1 if timeout else 2)

    def test_invalid_json_response_shape_is_a_bounded_error(self) -> None:
        sock = self.exchange()
        sock.recv.side_effect = [b"[]\n", BlockingIOError("no more queued bytes")]
        with mock.patch.object(socket, "socket", return_value=sock), self.assertRaises(c.CollectiveError):
            self.backend().native_request("ping", {})
        sock.sendall.assert_called_once()
        self.assertEqual(sock.recv.call_count, 2)

    def test_native_failure_keeps_tuios_roster(self) -> None:
        backend = self.backend()
        with (
            mock.patch.object(backend, "snapshot", return_value=snapshot()),
            mock.patch.object(backend, "native_request", side_effect=c.CollectiveError("unavailable")),
        ):
            result = backend.roster("work")
        self.assertEqual(len(result["tuios"]["agents"]), 2)
        self.assertFalse(result["native_herdr"]["available"])


class HeartbeatActivity(unittest.TestCase):
    def test_native_malformed_shapes_become_unavailable(self) -> None:
        cases: list[Any] = [
            [],
            {"id": "collective-heartbeat", "result": []},
            {"id": "collective-heartbeat", "result": {"agents": ["bad-row"]}},
        ]
        metadata = mock.Mock(st_mode=0o140600, st_uid=os.getuid())
        for response in cases:
            sock = mock.MagicMock()
            sock.__enter__.return_value = sock
            sock.getsockopt.return_value = struct.pack("3i", os.getpid(), os.getuid(), os.getgid())
            sock.recv.side_effect = [
                (json.dumps(response) + "\n").encode(),
                BlockingIOError("no more queued bytes"),
            ]
            with (
                self.subTest(response=response),
                mock.patch.object(os, "lstat", return_value=metadata),
                mock.patch.object(socket, "socket", return_value=sock),
            ):
                self.assertIsNone(hb.herdr_agents())
            sock.sendall.assert_called_once()
            self.assertEqual(sock.recv.call_count, 2)

    def test_activity_inputs_are_metadata_and_passive(self) -> None:
        cases: list[Any] = [
            ([], [], [], False),
            ([], [{"sent_at": NOW * 1_000_000_000}], [], True),
            ([], [], [{"stage": "review", "blocked": False}], True),
            ([], [], [{"stage": "review", "blocked": True}], False),
            ([{"needs_you": True}], [], [], True),
        ]
        for agents, messages, tasks, expected in cases:
            calls: list[Any] = []

            def run(
                argv: Any, timeout: Any = 20, calls: Any = calls, messages: Any = messages, tasks: Any = tasks
            ) -> Any:
                calls.append(argv)
                data = {"messages": messages} if "read-agent-messages" in argv else {"tasks": tasks}
                return 0, json.dumps(data)

            with (
                self.subTest(expected=expected, messages=bool(messages), tasks=tasks),
                mock.patch.object(hb, "run", side_effect=run),
                mock.patch.object(time, "time", return_value=NOW),
            ):
                active, _ = hb.activity(agents)
                self.assertEqual(active, expected)
            self.assertTrue(all("-w" not in argv and "--window" not in argv for argv in calls))

    def test_private_state_refuses_permissive_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(hb, "STATE", Path(tmp)):
            p = Path(tmp) / "memory.json"
            p.write_text("{}")
            p.chmod(0o644)
            with self.assertRaises(ValueError):
                hb.load("memory.json", {})
            self.assertEqual(p.read_text(), "{}")


class MonitorStateDirectory(unittest.TestCase):
    def test_relative_state_dir_is_refused_before_any_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                with self.assertRaisesRegex(c.CollectiveError, "absolute state directory"):
                    c.monitor(FakeBackend(), "session-0", "relative-state")
                self.assertFalse(Path(tmp, "relative-state").exists())
            finally:
                os.chdir(cwd)


class MailReceiptContracts(unittest.TestCase):
    TOOL = """import json, sys
from pathlib import Path
root = Path(__file__).parent
mode = json.loads((root / 'mode.json').read_text())
verb = sys.argv[2]
with (root / 'calls').open('a') as log:
    log.write(verb + '\\n')
if verb == 'list-attention':
    value = {'boot_id': 'test-boot'}
elif verb == 'list-agents':
    value = {'agents': mode['agents']}
elif verb == 'send-agent-message':
    rows = [json.loads(line) for line in Path(mode['journal']).read_text().splitlines()]
    assert any(row.get('digest') == mode['digest'] and row.get('outcome') == 'intent' for row in rows)
    marker = root / 'dispatches'
    marker.write_text(marker.read_text() + 'sent\\n' if marker.exists() else 'sent\\n')
    value = mode['envelope']
else:
    raise AssertionError(verb)
print(json.dumps(value))
"""

    def cli_case(self, envelope: Any, accepted: bool) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "bin"
            binary.mkdir(mode=0o700)
            tool = binary / "tuios"
            tool.write_text(f"#!{sys.executable}\n{self.TOOL}", encoding="utf-8")
            tool.chmod(0o700)
            env = {**os.environ, "HOME": str(root), "PATH": str(binary), "TUIOS_SERVER": ""}
            with mock.patch.dict(os.environ, env):
                backend = c.Backend()
                state = snapshot()
                state["endpoint"] = backend.endpoint
                plan = c.make_mail_plan(state, "work", SENDER, RECIPIENT, "receipt contract", "owned fake only")
            plan_path, journal = root / "plan.json", root / "journal.jsonl"
            c.write_private_json(plan_path, plan, exclusive=True)
            (binary / "mode.json").write_text(
                json.dumps(
                    {"agents": state["agents"], "envelope": envelope, "journal": str(journal), "digest": plan["digest"]}
                ),
                encoding="utf-8",
            )
            argv = [
                sys.executable,
                "-I",
                "-B",
                str(Path(c.__file__)),
                "--json",
                "mail-apply",
                "--plan",
                str(plan_path),
                "--confirm",
                plan["digest"],
                "--journal",
                str(journal),
                "--keep-plan",
            ]
            first = subprocess.run(  # noqa: S603 - real CLI with private fake tuios as the only PATH entry
                argv, env=env, capture_output=True, text=True, timeout=10, check=False
            )
            self.assertEqual(first.returncode, 0 if accepted else 2, first.stdout + first.stderr)
            if accepted:
                self.assertEqual(json.loads(first.stdout)["outcome"], "submitted")
            else:
                self.assertIn("outcome unknown", json.loads(first.stderr)["error"])
            rows = [json.loads(line) for line in journal.read_text().splitlines()]
            self.assertEqual([row["outcome"] for row in rows], ["intent", "submitted" if accepted else "unknown"])
            before = journal.read_bytes()
            replay = subprocess.run(  # noqa: S603 - exact consumed plan; fake dispatch marker proves no resend
                argv, env=env, capture_output=True, text=True, timeout=10, check=False
            )
            self.assertEqual(replay.returncode, 2)
            self.assertIn("already consumed", json.loads(replay.stderr)["error"])
            self.assertEqual((binary / "dispatches").read_text(), "sent\n")
            self.assertEqual(journal.read_bytes(), before)

    def test_public_cli_keeps_outer_and_inner_failure_evidence(self) -> None:
        cases = [
            ({"message_id": 42}, True),
            ({"success": True, "error": None, "result": {"success": True, "message_id": 42}}, True),
            ({"success": False, "result": {"message_id": 42}}, False),
            ({"success": False, "result": {"success": True, "message_id": 42}}, False),
            ({"success": 0, "result": {"message_id": 42}}, False),
            ({"success": "false", "result": {"message_id": 42}}, False),
            ({"success": True, "error": [], "result": {"message_id": 42}}, False),
            ({"success": True, "error": False, "result": {"message_id": 42}}, False),
            ({"success": True, "result": {"success": False, "message_id": 42}}, False),
            ({"success": True, "result": {"success": 0, "message_id": 42}}, False),
            ({"success": True, "result": {"error": {}, "message_id": 42}}, False),
        ]
        for envelope, accepted in cases:
            with self.subTest(envelope=envelope):
                self.cli_case(envelope, accepted)

    def test_direct_receipt_rejects_non_boolean_success_and_malformed_error(self) -> None:
        success_values: list[Any] = [0, "false", None, [], {}]
        error_values: list[Any] = [False, "", [], {}]
        values = [{"success": value, "message_id": 42} for value in success_values] + [
            {"error": value, "message_id": 42} for value in error_values
        ]
        for receipt in values:
            with self.subTest(receipt=receipt), tempfile.TemporaryDirectory() as tmp:
                backend = FakeBackend()
                plan = c.make_mail_plan(snapshot(), "work", SENDER, RECIPIENT, "receipt", "fake", now=NOW)
                journal = c.Journal(Path(tmp) / "journal.jsonl")
                with mock.patch.object(backend, "tuios", return_value=receipt) as send:
                    with self.assertRaises(c.TransportUncertain):
                        c.apply_mail_plan(plan, plan["digest"], backend, journal, now=NOW)
                    with self.assertRaisesRegex(c.CollectiveError, "already consumed"):
                        c.apply_mail_plan(plan, plan["digest"], backend, journal, now=NOW)
                    self.assertEqual(send.call_count, 1)
                rows = [json.loads(line) for line in journal.path.read_text().splitlines()]
                self.assertEqual([row["outcome"] for row in rows], ["intent", "unknown"])

    def test_fractional_rolling_minute_does_not_admit_an_early_eleventh_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            journal = c.Journal(Path(tmp) / "journal.jsonl")
            backend = FakeBackend()
            first_time = NOW + 0.9
            with mock.patch.object(time, "time", return_value=first_time):
                for i in range(10):
                    plan = c.make_mail_plan(snapshot(), "work", SENDER, RECIPIENT, f"intent {i}", "fake", now=NOW)
                    c.apply_mail_plan(plan, plan["digest"], backend, journal, now=NOW)
            plan = c.make_mail_plan(snapshot(), "work", SENDER, RECIPIENT, "eleventh", "fake", now=NOW)
            with (
                mock.patch.object(time, "time", return_value=NOW + 60.0),
                self.assertRaisesRegex(c.CollectiveError, "rate limit"),
            ):
                c.apply_mail_plan(plan, plan["digest"], backend, journal, now=NOW + 60)
            self.assertEqual(len(backend.calls), 10)
            with mock.patch.object(time, "time", return_value=first_time + 60):
                result = c.apply_mail_plan(plan, plan["digest"], backend, journal, now=NOW + 61)
            self.assertEqual(result["outcome"], "submitted")
            self.assertEqual(len(backend.calls), 11)


class MailTextContracts(unittest.TestCase):
    def plan_case(self, subject: str, body: str, accepted: bool) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "bin"
            binary.mkdir(mode=0o700)
            tool = binary / "tuios"
            tool.write_text(f"#!{sys.executable}\n{MailReceiptContracts.TOOL}", encoding="utf-8")
            tool.chmod(0o700)
            (binary / "mode.json").write_text(json.dumps({"agents": snapshot()["agents"]}), encoding="utf-8")
            text_file, plan_path = root / "body.txt", root / "plan.json"
            text_file.write_text(body, encoding="utf-8")
            text_file.chmod(0o600)
            argv = [
                sys.executable,
                "-I",
                "-B",
                str(Path(c.__file__)),
                "--json",
                "mail-plan",
                "--session",
                "work",
                "--sender",
                SENDER,
                "--to",
                RECIPIENT,
                "--subject",
                subject,
                "--text-file",
                str(text_file),
                "--output",
                str(plan_path),
            ]
            result = subprocess.run(  # noqa: S603 - public planner and isolated owned fake tuios only
                argv,
                env={**os.environ, "HOME": str(root), "PATH": str(binary), "TUIOS_SERVER": ""},
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0 if accepted else 2, result.stdout + result.stderr)
            self.assertEqual(plan_path.exists(), accepted)
            if accepted:
                plan = c.read_private_json(plan_path)
                self.assertEqual(plan["payload"]["subject"], subject)
                self.assertEqual(plan["payload"]["text"], body)
            else:
                self.assertIn("refused", json.loads(result.stderr)["error"])
            calls = (binary / "calls").read_text() if (binary / "calls").exists() else ""
            self.assertNotIn("send-agent-message", calls)
            self.assertFalse((binary / "dispatches").exists())

    def test_public_planner_refuses_c1_and_hidden_format_controls(self) -> None:
        for control in ("\u0085", "\u009b", "\u061c", "\u2060", "\u00ad"):
            for field in ("subject", "body"):
                with self.subTest(codepoint=hex(ord(control)), field=field):
                    subject = "before" + control + "after" if field == "subject" else "readable subject"
                    body = "before" + control + "after" if field == "body" else "readable body"
                    self.plan_case(subject, body, False)

    def test_public_planner_preserves_visible_unicode_combining_marks_and_body_whitespace(self) -> None:
        self.plan_case("Café e\u0301 — 中文", "Line one\n\tCafé e\u0301 — 中文 🦉\n", True)


class DashboardWatchOutput(unittest.TestCase):
    def test_small_piped_frame_is_visible_while_first_wait_is_still_running(self) -> None:
        program = (
            "import argparse, sys, threading\n"
            f"sys.path.insert(0, {str(Path(c.__file__).parent)!r})\n"
            "import collective\n"
            "collective.observe = lambda *_: {'fixture': 'small frame'}\n"
            "def wait(_):\n"
            "    print('FIRST_WAIT', file=sys.stderr, flush=True)\n"
            "    threading.Event().wait(10)\n"
            "collective.time.sleep = wait\n"
            "collective._dashboard(argparse.Namespace(session='work', watch=True), object())\n"
        )
        proc = subprocess.Popen(  # noqa: S603 - fixed local child over isolated fake read backend
            [sys.executable, "-I", "-B", "-c", program],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        received = {"stdout": bytearray(), "stderr": bytearray()}
        try:
            assert proc.stdout is not None
            assert proc.stderr is not None
            deadline = time.monotonic() + 3
            with selectors.DefaultSelector() as poll:
                for pipe, name in ((proc.stdout, "stdout"), (proc.stderr, "stderr")):
                    os.set_blocking(pipe.fileno(), False)
                    poll.register(pipe, selectors.EVENT_READ, name)
                while poll.get_map() and time.monotonic() < deadline:
                    for key, _ in poll.select(max(0, deadline - time.monotonic())):
                        chunk = os.read(key.fd, 4096)
                        if not chunk:
                            poll.unregister(key.fileobj)
                        else:
                            received[key.data].extend(chunk)
                    if b"FIRST_WAIT" in received["stderr"] and b'"small frame"' in received["stdout"]:
                        break
            self.assertIsNone(proc.poll(), "fixture must remain alive, not flush only on exit")
            self.assertIn(b"FIRST_WAIT", received["stderr"], bytes(received["stderr"]))
            output = received["stdout"].decode()
            self.assertIn('"small frame"', output, "piped dashboard frame was buffered during the first wait")
            self.assertLess(len(output.encode()), 4096, "fixture must be too small to fill the output buffer")
            self.assertEqual(json.loads(output.split("\n", 1)[1]), {"fixture": "small frame"})
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.communicate(timeout=2)


if __name__ == "__main__":
    unittest.main()
