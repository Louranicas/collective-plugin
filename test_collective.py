"""Boundary tests owned by Codex 2; all backends are local fakes."""

import copy
import json
import multiprocessing
import os
import socket
import struct
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
    def backend(self) -> Any:
        return c.Backend(tuios_bin="/fixture/tuios", native_socket="/fixture/herdr.sock")

    def exchange(self, wrong_id: Any = False, timeout: Any = False) -> Any:
        sock = mock.MagicMock()
        sock.__enter__.return_value = sock
        sock.getsockopt.return_value = struct.pack("3i", os.getpid(), os.getuid(), os.getgid())

        def response(_: Any) -> Any:
            if timeout:
                raise TimeoutError("fixture timeout")
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

    def test_invalid_json_response_shape_is_a_bounded_error(self) -> None:
        sock = self.exchange()
        sock.recv.side_effect = None
        sock.recv.return_value = b"[]\n"
        with mock.patch.object(socket, "socket", return_value=sock), self.assertRaises(c.CollectiveError):
            self.backend().native_request("ping", {})

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
            sock.recv.return_value = (json.dumps(response) + "\n").encode()
            with (
                self.subTest(response=response),
                mock.patch.object(os, "lstat", return_value=metadata),
                mock.patch.object(socket, "socket", return_value=sock),
            ):
                self.assertIsNone(hb.herdr_agents())

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


if __name__ == "__main__":
    unittest.main()
