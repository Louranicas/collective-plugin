"""Behavioral checks for bounded private coordination jobs and reviewed scheduling."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, override
from unittest import mock

import coordination_jobs as jobs
import install_coordination_jobs as installer

job_monitor: Any = vars(jobs)["monitor"]
install_monitor: Any = vars(installer)["monitor"]

PRIVATE_TEXT = "PRIVATE-MESSAGE-BODY-AND-COMMAND-OUTPUT"


class JobBehavior(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="collective-job-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.input = self.home / "inputs.json"
        self.log = self.home / "commands.jsonl"
        self.tool = self.home / "tuios"
        self.tool.write_text(
            f"#!{sys.executable}\n"
            "import json,os,pathlib,sys\n"
            "args=sys.argv[1:]\n"
            "with open(os.environ['FIXTURE_LOG'],'a') as f:f.write(json.dumps(args)+'\\n')\n"
            "name='tasks' if args[:2]==['task','ls'] else "
            "{'list-agents':'roster','read-agent-messages':'ring'}.get(args[1],'unexpected')\n"
            "data=json.loads(pathlib.Path(os.environ['FIXTURE_INPUT']).read_text())[name]\n"
            "if isinstance(data,dict) and '__raw__' in data:print(data['__raw__'])\n"
            "elif isinstance(data,dict) and '__exit__' in data:raise SystemExit(data['__exit__'])\n"
            "else:print(json.dumps(data))\n",
            encoding="utf-8",
        )
        self.tool.chmod(0o700)
        self.env = {
            "XDG_STATE_HOME": str(self.home / "state"),
            "TUIOS_BIN": str(self.tool),
            "COLLECTIVE_SESSION": "fixture-session",
            "FIXTURE_INPUT": str(self.input),
            "FIXTURE_LOG": str(self.log),
        }
        patcher = mock.patch.dict(os.environ, self.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.data: dict[str, Any] = {
            "roster": {
                "agents": [
                    {"state": "working", "draft_held": True, "needs_you": False, "text": PRIVATE_TEXT},
                    {"state": "needs_input", "draft_held": False, "needs_you": True},
                    {"state": {"untrusted": PRIVATE_TEXT}},
                ],
            },
            "ring": {
                "messages": [
                    {"id": 1, "thread_id": 1, "read_at": 0, "reply_to": 0, "text": PRIVATE_TEXT},
                    {"id": 2, "thread_id": 1, "read_at": 123, "reply_to": 1},
                    {"id": 3, "thread_id": 3, "kind": "stalled"},
                    {"id": 4, "thread_id": 4, "status": "stalled"},
                ],
                "evicted": 7,
            },
            "tasks": {
                "tasks": [
                    {
                        "owner": "writer",
                        "holder": {"window": "pane-reviewer", "name": PRIVATE_TEXT},
                        "stage": "doing",
                        "blocked": {"reason": PRIVATE_TEXT, "by": "pane-writer", "at": 1},
                    },
                    {"owner": "writer", "holder": {"window": "pane-writer"}, "stage": "doing", "blocked": None},
                    {"owner": "other", "holder": None, "stage": "review", "blocked": None, "text": PRIVATE_TEXT},
                ],
            },
        }
        self.write_inputs()

    def write_inputs(self) -> None:
        self.input.write_text(json.dumps(self.data), encoding="utf-8")
        self.input.chmod(0o600)

    def checker(self, program: str) -> Path:
        root = self.home / "fake-source"
        (root / "tools").mkdir(parents=True, exist_ok=True)
        (root / "tools/check.py").write_text(program, encoding="utf-8")
        return root

    def test_real_metadata_jobs_are_private_passive_and_explicit(self) -> None:
        for job in ("collaboration", "cohesion"):
            with self.subTest(job=job):
                receipt = jobs.run_job(job)
                self.assertEqual(receipt["status"], "ok")
                metrics = receipt["metrics"]
                self.assertEqual(metrics["observed_agents"], 3)
                self.assertEqual(metrics["draft_held"], 1)
                self.assertEqual(metrics["needs_you"], 1)
                self.assertEqual(metrics["task_owners"], {"writer": 2, "other": 1})
                self.assertEqual(metrics["task_holders"], {"pane-reviewer": 1, "pane-writer": 1, "unheld": 1})
                self.assertEqual(metrics["blocked_tasks"], 1)
                self.assertEqual(metrics["ring_stored"], 4)
                self.assertEqual(metrics["ring_marked_read"], 1)
                self.assertEqual(metrics["reply_links"], 1)
                self.assertEqual(metrics["threads_observed"], 3)
                self.assertEqual(metrics["threads_with_reply_links"], 1)
                self.assertEqual(metrics["threads_without_reply_links"], 2)
                self.assertEqual(metrics["threads_with_multiple_entries"], 1)
                self.assertEqual(metrics["explicit_stalled_entries"], 2)
                self.assertIn("Not inferred", metrics["acceptance"])
                self.assertFalse(receipt["sources"]["ring"]["complete_history"])
                self.assertEqual(receipt["sources"]["ring"]["evicted"], 7)
                self.assertEqual(receipt["source_gaps"], [])
                self.assertNotIn(PRIVATE_TEXT, json.dumps(receipt))
                self.assertEqual(receipt["source_sha256"], hashlib.sha256(Path(jobs.__file__).read_bytes()).hexdigest())
                path = jobs.state_dir() / f"{job}.json"
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
                self.assertEqual(json.loads(path.read_text()), receipt)
        commands = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(len(commands), 6)
        for command in commands:
            if command[0] == "call":
                params = json.loads(command[-1])
                self.assertNotIn("to", params)
                self.assertNotIn("from", params)
                self.assertEqual(params["session"], "fixture-session")
            else:
                self.assertEqual(command, ["task", "ls", "-s", "fixture-session", "--json"])

    def test_source_failures_are_gaps_not_success_or_private_output(self) -> None:
        responses: list[Any] = [{"__raw__": "not-json"}, {"agents": ["bad"]}, [], {"error": PRIVATE_TEXT}]
        for response in responses:
            self.data["roster"] = response
            self.data["ring"] = {"__exit__": 2}
            self.write_inputs()
            with self.subTest(response=response):
                receipt = jobs.run_job("cohesion")
                self.assertEqual(receipt["status"], "degraded")
                self.assertEqual(receipt["source_gaps"], ["roster", "ring"])
                self.assertEqual(receipt["metrics"]["observed_agents"], 0)
                self.assertEqual(receipt["metrics"]["task_owners"], {"writer": 2, "other": 1})
                self.assertNotIn(PRIVATE_TEXT, json.dumps(receipt))

    def test_actual_task_shapes_report_unknown_evidence_without_false_green(self) -> None:
        self.data["tasks"] = {
            "tasks": [
                {
                    "holder": {"window": "pane-actual", "name": PRIVATE_TEXT},
                    "blocked": {"reason": PRIVATE_TEXT, "by": "claimed-peer", "at": 123},
                    "stage": "doing",
                },
                {"owner": None, "holder": None, "blocked": None, "stage": "plan"},
                {"owner": {"untrusted": PRIVATE_TEXT}, "holder": "wrong-shape", "blocked": True, "stage": "review"},
            ]
        }
        self.write_inputs()
        receipt = jobs.run_job("collaboration")
        self.assertEqual(receipt["status"], "degraded")
        self.assertEqual(receipt["metric_gaps"], ["tasks.blocked", "tasks.holder", "tasks.owner"])
        self.assertEqual(receipt["source_gaps"], ["tasks.blocked", "tasks.holder", "tasks.owner"])
        self.assertEqual(receipt["metrics"]["task_holders"], {"pane-actual": 1, "unheld": 1, "unknown": 1})
        self.assertEqual(receipt["metrics"]["task_owners"], {"unknown": 3})
        self.assertEqual(receipt["metrics"]["blocked_tasks"], 1)
        self.assertEqual(receipt["metrics"]["blocked_tasks_unknown"], 1)
        evidence = receipt["metrics"]["task_owner_evidence"]
        self.assertEqual(evidence["reported"], 0)
        self.assertEqual(evidence["absent"] + evidence["invalid"], 3)
        self.assertGreaterEqual(evidence["absent"], 1)
        self.assertGreaterEqual(evidence["invalid"], 1)
        self.assertNotIn(PRIVATE_TEXT, json.dumps(receipt))

    def test_absent_holder_and_blocked_fields_are_explicit_gaps(self) -> None:
        self.data["tasks"] = {"tasks": [{"owner": "writer"}]}
        self.write_inputs()
        receipt = jobs.run_job("cohesion")
        self.assertEqual(receipt["status"], "degraded")
        self.assertEqual(receipt["metric_gaps"], ["tasks.blocked", "tasks.holder"])
        self.assertEqual(receipt["metrics"]["task_holders"], {"unknown": 1})
        self.assertEqual(receipt["metrics"]["blocked_tasks_unknown"], 1)

    def test_enveloped_rows_and_invalid_labels_are_bounded(self) -> None:
        self.data["roster"] = {"result": {"agents": [{"state": "x" * 65}, {"state": "hidden\u202e"}]}}
        self.data["ring"] = {"messages": [{"id": 1, "reply_to": True}], "evicted": -1}
        self.write_inputs()
        receipt = jobs.run_job("collaboration")
        self.assertEqual(receipt["metrics"]["agent_states"], {"unknown": 2})
        self.assertEqual(receipt["metrics"]["reply_links"], 0)
        self.assertIsNone(receipt["sources"]["ring"]["evicted"])
        self.assertEqual(receipt["metrics"]["threads_observed"], 1)

    def test_source_row_limit_and_unavailable_binary_are_explicit(self) -> None:
        self.data["tasks"] = {"tasks": [{}] * (jobs.MAX_ROWS + 1)}
        self.write_inputs()
        self.assertEqual(jobs.run_job("cohesion")["source_gaps"], ["tasks"])
        with mock.patch.dict(os.environ, {"TUIOS_BIN": str(self.home / "missing")}):
            receipt = jobs.run_job("collaboration")
        self.assertEqual(receipt["source_gaps"], ["roster", "ring", "tasks"])
        self.assertEqual(receipt["sources"]["roster"]["status"], "unavailable")

    def test_duplicate_lock_does_not_run_or_replace_prior_receipt(self) -> None:
        directory = jobs.state_dir()
        prior = directory / "cohesion.json"
        prior.write_text('{"prior":true}', encoding="utf-8")
        prior.chmod(0o600)
        fd = os.open(directory / "cohesion.lock", os.O_RDWR | os.O_CREAT, 0o600)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(jobs.run_job("cohesion")["status"], "skipped")
        self.assertEqual(prior.read_text(), '{"prior":true}')
        self.assertFalse(self.log.exists())

    def test_unsafe_lock_and_state_directory_are_refused(self) -> None:
        directory = jobs.state_dir()
        lock = directory / "collaboration.lock"
        lock.write_text("keep", encoding="utf-8")
        lock.chmod(0o644)
        with self.assertRaises(ValueError):
            jobs.run_job("collaboration")
        self.assertEqual(lock.read_text(), "keep")
        lock.unlink()
        lock.symlink_to(self.input)
        with self.assertRaises(OSError):
            jobs.run_job("collaboration")
        self.assertEqual(json.loads(self.input.read_text()), self.data)
        directory.chmod(0o755)
        with self.assertRaises((ValueError, job_monitor.CollectiveError)):
            jobs.run_job("cohesion")

    def test_unknown_job_and_remote_session_have_no_reads(self) -> None:
        with self.assertRaises(ValueError):
            jobs.run_job("unknown")
        for session in ("", "host:remote"):
            with mock.patch.dict(os.environ, {"COLLECTIVE_SESSION": session}), self.assertRaises(ValueError):
                jobs.run_job("collaboration")
        self.assertFalse(self.log.exists())

    def test_quality_runs_actual_checker_offline_with_private_caches(self) -> None:
        root = self.checker(
            "import json,os,pathlib,sys\n"
            "assert '--keep-going' in sys.argv\n"
            "assert os.environ['UV_OFFLINE']=='1'\n"
            "expected=pathlib.Path(os.environ['XDG_STATE_HOME'])/'collective/coordination/gate-tools/bin'\n"
            "assert os.environ['PATH'].split(os.pathsep)[0]==str(expected)\n"
            "for key in ('UV_CACHE_DIR','RUFF_CACHE_DIR','MYPY_CACHE_DIR','TMPDIR'):\n"
            " assert pathlib.Path(os.environ[key]).stat().st_mode&0o777==0o700\n"
            "path=pathlib.Path(sys.argv[sys.argv.index('--receipt')+1])\n"
            "path.write_text(json.dumps({'ok':True,'tree_sha256':'a'*64}))\n"
            f"print({PRIVATE_TEXT!r})\n",
        )
        with mock.patch.object(jobs, "ROOT", root):
            receipt = jobs.run_job("quality")
        self.assertEqual(receipt["status"], "ok")
        self.assertEqual(receipt["checker_tree_sha256"], "a" * 64)
        gate_tools = jobs.state_dir() / "gate-tools/bin"
        if gate_tools.exists():
            self.assertEqual(list(gate_tools.iterdir()), [])
        self.assertTrue(receipt["checker_report_valid"])
        self.assertFalse(receipt["output_persisted"])
        self.assertNotIn(PRIVATE_TEXT, json.dumps(receipt))
        self.assertEqual(stat.S_IMODE((jobs.state_dir() / "quality-check.json").stat().st_mode), 0o600)

    def test_quality_nonzero_missing_and_false_reports_remain_failed(self) -> None:
        for program in (
            "raise SystemExit(3)",
            "print('checker emitted no receipt')",
            "import pathlib,sys;pathlib.Path(sys.argv[-1]).write_text('{\"ok\":false}')",
            "import pathlib,sys;pathlib.Path(sys.argv[-1]).write_text('[]')",
        ):
            root = self.checker(program)
            with self.subTest(program=program), mock.patch.object(jobs, "ROOT", root):
                self.assertEqual(jobs.run_job("quality")["status"], "failed")

    def test_real_process_limits_and_deadline(self) -> None:
        for program in (
            "import sys;sys.stdout.write('x'*2100000)",
            "import sys;sys.stderr.write('x'*2100000)",
        ):
            with self.subTest(program=program):
                outcome = jobs._run([sys.executable, "-I", "-c", program], timeout=2)
                self.assertEqual(outcome.status, "output_limit")
                self.assertEqual(outcome.output, b"")
        outcome = jobs._run([sys.executable, "-I", "-c", "import time;time.sleep(5)"], timeout=0.05)
        self.assertEqual(outcome.status, "timeout")
        self.assertEqual(jobs._run([str(self.home / "absent")], timeout=1).status, "unavailable")

    def test_group_cardinality_is_bounded_without_dropping_task_counts(self) -> None:
        self.data["tasks"] = {"tasks": [{"owner": f"owner-{n}"} for n in range(200)]}
        self.write_inputs()
        receipt = jobs.run_job("cohesion")
        owners = receipt["metrics"]["task_owners"]
        self.assertLessEqual(len(owners), jobs.MAX_GROUPS)
        self.assertEqual(sum(owners.values()), 200)
        self.assertGreater(owners["other_groups"], 0)

    def test_deadline_after_child_closes_output_pipes_is_still_bounded(self) -> None:
        outcome = jobs._run(
            [sys.executable, "-I", "-c", "import os,time;os.close(1);os.close(2);time.sleep(5)"], timeout=0.05
        )
        self.assertEqual(outcome.status, "timeout")
        self.assertIsNone(outcome.code)

    def test_cli_status_and_error_output_do_not_expose_bodies(self) -> None:
        stdout = io.StringIO()
        with (
            mock.patch.object(sys, "argv", ["coordination_jobs.py", "--job", "collaboration"]),
            contextlib.redirect_stdout(stdout),
        ):
            self.assertEqual(jobs.main(), 0)
        self.assertEqual(json.loads(stdout.getvalue()), {"job": "collaboration", "status": "ok"})
        with (
            mock.patch.object(sys, "argv", ["coordination_jobs.py", "--job", "cohesion"]),
            mock.patch.object(jobs, "run_job", side_effect=ValueError(PRIVATE_TEXT)),
            contextlib.redirect_stderr(io.StringIO()) as error,
        ):
            self.assertEqual(jobs.main(), 1)
        self.assertNotIn(PRIVATE_TEXT, error.getvalue())


class CoordinationInstaller(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="collective-schedule-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        patcher = mock.patch.object(Path, "home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.destination = self.home / ".config/systemd/user"
        self.calls: list[list[str]] = []

    def command(self, argv: list[str], *, check: bool = True) -> int:
        self.calls.append(argv)
        return 3 if "is-enabled" in argv or "is-active" in argv else 0

    def test_unit_semantics_are_sandboxed_and_keep_existing_gateway(self) -> None:
        proposed = installer.units()
        self.assertEqual(len(proposed), 6)
        self.assertNotIn("collective-heartbeat.service", proposed)
        for job in installer.JOBS:
            text = proposed[f"collective-{job}.service"]
            settings = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
            self.assertEqual(settings["ProtectSystem"], "strict")
            self.assertEqual(settings["ProtectHome"], "read-only")
            self.assertEqual(settings["PrivateNetwork"], "yes")
            self.assertEqual(settings["RestrictAddressFamilies"], "AF_UNIX")
            self.assertEqual(settings["ReadWritePaths"], "%h/.local/state/collective/coordination")
            self.assertIn(f"--job {job}", settings["ExecStart"])
            timer = proposed[f"collective-{job}.timer"]
            timer_settings = dict(line.split("=", 1) for line in timer.splitlines() if "=" in line)
            if job == "quality":
                self.assertEqual(timer_settings["OnCalendar"], "daily")
                self.assertGreater(int(settings["TimeoutStartSec"]), jobs.QUALITY_TIMEOUT)
            else:
                self.assertEqual(timer_settings["OnUnitActiveSec"], "10min" if job == "collaboration" else "30min")

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd consumer unavailable")
    def test_real_systemd_consumer_accepts_all_six_proposals(self) -> None:
        staged = self.home / "staged"
        staged.mkdir()
        paths = []
        for name, content in installer.units().items():
            path = staged / name
            path.write_text(content, encoding="utf-8")
            paths.append(str(path))
        consumer = shutil.which("systemd-analyze")
        if consumer is None:
            self.skipTest("systemd consumer unavailable")
        result = subprocess.run(  # noqa: S603 - fixed read-only consumer over private fixture unit files
            [consumer, "--user", "verify", *paths],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_success_backs_up_only_named_units_and_private_receipt(self) -> None:
        self.destination.mkdir(parents=True)
        original = (installer.MARKER + " prior\n[Unit]\nDescription=prior\n").encode()
        for name in installer.units():
            (self.destination / name).write_bytes(original)
        heartbeat = self.destination / "collective-heartbeat.service"
        heartbeat.write_text("untouched", encoding="utf-8")
        with mock.patch.object(install_monitor, "command", side_effect=self.command):
            receipt = installer.install()
        self.assertEqual(receipt["status"], "installed")
        backup = Path(str(receipt["backup"]))
        for name, content in installer.units().items():
            self.assertEqual((self.destination / name).read_text(), content)
            self.assertEqual((backup / name).read_bytes(), original)
        self.assertEqual(heartbeat.read_text(), "untouched")
        enabled = [argv[-1] for argv in self.calls if "enable" in argv]
        self.assertEqual(set(enabled), {f"collective-{job}.timer" for job in installer.JOBS})
        path = self.home / ".local/state/collective/coordination/installer.json"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(path.read_text()), receipt)

    def test_failed_install_restores_files_and_each_prior_timer_state(self) -> None:
        self.destination.mkdir(parents=True)
        original = (installer.MARKER + " prior\n").encode()
        for name in installer.units():
            (self.destination / name).write_bytes(original)

        def command(argv: list[str], *, check: bool = True) -> int:
            self.calls.append(argv)
            if "is-enabled" in argv:
                return 0 if argv[-1] == "collective-collaboration.timer" else 3
            if "is-active" in argv:
                return 0 if argv[-1] == "collective-cohesion.timer" else 3
            if "enable" in argv and argv[-1] == "collective-quality.timer":
                raise install_monitor.CollectiveError("fixture activation refusal")
            return 0

        with (
            mock.patch.object(install_monitor, "command", side_effect=command),
            self.assertRaisesRegex(install_monitor.CollectiveError, "fixture activation refusal"),
        ):
            installer.install()
        for name in installer.units():
            self.assertEqual((self.destination / name).read_bytes(), original)
        rollback_calls = {(argv[2], argv[-1]) for argv in self.calls if argv[0] == "systemctl"}
        self.assertIn(("stop", "collective-collaboration.timer"), rollback_calls)
        self.assertNotIn(("disable", "collective-collaboration.timer"), rollback_calls)
        self.assertIn(("enable", "collective-collaboration.timer"), rollback_calls)
        self.assertIn(("disable", "collective-cohesion.timer"), rollback_calls)
        self.assertIn(("start", "collective-cohesion.timer"), rollback_calls)
        self.assertIn(("stop", "collective-quality.timer"), rollback_calls)
        self.assertIn(("disable", "collective-quality.timer"), rollback_calls)

    def test_effect_then_error_restores_true_and_false_timer_states(self) -> None:
        prior = {
            "collective-collaboration.timer": {"enabled": False, "active": False},
            "collective-cohesion.timer": {"enabled": True, "active": False},
            "collective-quality.timer": {"enabled": True, "active": True},
        }
        current = {name: dict(state) for name, state in prior.items()}
        failed = False

        def command(argv: list[str], *, check: bool = True) -> int:
            nonlocal failed
            self.calls.append(argv)
            if argv[0] != "systemctl" or argv[2] == "daemon-reload":
                return 0
            verb, timer = argv[2], argv[-1]
            if verb in {"is-enabled", "is-active"}:
                return 0 if current[timer]["enabled" if verb == "is-enabled" else "active"] else 3
            if verb in {"enable", "disable"}:
                current[timer]["enabled"] = verb == "enable"
            if verb in {"start", "stop"} or (verb == "enable" and "--now" in argv):
                current[timer]["active"] = verb != "stop"
            if verb == "enable" and timer == "collective-quality.timer" and not failed:
                # Model a backend that mutates the named timer before reporting failure.
                current[timer] = {"enabled": False, "active": False}
                failed = True
                raise install_monitor.CollectiveError("state changed before command error")
            return 0

        with (
            mock.patch.object(install_monitor, "command", side_effect=command),
            self.assertRaisesRegex(install_monitor.CollectiveError, "state changed before command error"),
        ):
            installer.install()
        self.assertTrue(failed)
        self.assertEqual(current, prior)
        self.assertFalse(any((self.destination / name).exists() for name in installer.units()))

    def test_fresh_failure_removes_new_units_and_records_rollback(self) -> None:
        def command(argv: list[str], *, check: bool = True) -> int:
            if "enable" in argv:
                raise install_monitor.CollectiveError("fixture")
            return self.command(argv, check=check)

        with (
            mock.patch.object(install_monitor, "command", side_effect=command),
            self.assertRaises(install_monitor.CollectiveError),
        ):
            installer.install()
        self.assertFalse(any((self.destination / name).exists() for name in installer.units()))
        receipt = json.loads((self.home / ".local/state/collective/coordination/installer.json").read_text())
        self.assertEqual(receipt["status"], "rolled-back")
        self.assertEqual(receipt["rollback_errors"], [])

    def test_late_receipt_failure_restores_units_and_preserves_initial_error(self) -> None:
        real_write = install_monitor.write_private_json
        writes = 0

        def write(path: Path, value: object) -> None:
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError("fixture receipt failure")
            real_write(path, value)

        with (
            mock.patch.object(install_monitor, "command", side_effect=self.command),
            mock.patch.object(install_monitor, "write_private_json", side_effect=write),
            self.assertRaisesRegex(OSError, "fixture receipt failure"),
        ):
            installer.install()
        self.assertFalse(any((self.destination / name).exists() for name in installer.units()))
        self.assertTrue(any("disable" in argv for argv in self.calls))

    def test_unmanaged_symlink_and_writable_paths_are_refused(self) -> None:
        self.destination.mkdir(parents=True)
        path = self.destination / "collective-collaboration.service"
        path.write_text("unmanaged", encoding="utf-8")
        with mock.patch.object(install_monitor, "command") as command:
            with self.assertRaises(ValueError):
                installer.install()
            command.assert_not_called()
        path.unlink()
        path.symlink_to(self.home / "elsewhere")
        with mock.patch.object(install_monitor, "command"), self.assertRaises(OSError):
            installer.install()
        path.unlink()
        self.destination.chmod(0o777)
        with mock.patch.object(install_monitor, "command"), self.assertRaises(ValueError):
            installer.install()

    def test_rollback_failures_are_recorded_without_hiding_initial_exception(self) -> None:
        failed = False

        def command(argv: list[str], *, check: bool = True) -> int:
            nonlocal failed
            if "enable" in argv:
                failed = True
                raise install_monitor.CollectiveError("initial activation failure")
            if failed:
                raise OSError("cleanup command failure")
            return self.command(argv, check=check)

        with (
            mock.patch.object(install_monitor, "command", side_effect=command),
            self.assertRaisesRegex(install_monitor.CollectiveError, "initial activation failure") as caught,
        ):
            installer.install()
        self.assertIn("Rollback errors", " ".join(caught.exception.__notes__))
        self.assertFalse(any((self.destination / name).exists() for name in installer.units()))
        receipt = json.loads((self.home / ".local/state/collective/coordination/installer.json").read_text())
        self.assertGreater(len(receipt["rollback_errors"]), 0)

    def test_final_and_rollback_receipt_failures_preserve_original_error(self) -> None:
        real_write = install_monitor.write_private_json
        writes = 0

        def write(path: Path, value: object) -> None:
            nonlocal writes
            writes += 1
            if writes >= 2:
                raise OSError("receipt persistence unavailable")
            real_write(path, value)

        with (
            mock.patch.object(install_monitor, "command", side_effect=self.command),
            mock.patch.object(install_monitor, "write_private_json", side_effect=write),
            self.assertRaisesRegex(OSError, "receipt persistence unavailable") as caught,
        ):
            installer.install()
        self.assertIn("record rollback", " ".join(caught.exception.__notes__))
        self.assertFalse(any((self.destination / name).exists() for name in installer.units()))

    def test_default_cli_only_reviews_and_failure_cli_hides_details(self) -> None:
        with (
            mock.patch.object(sys, "argv", ["install_coordination_jobs.py"]),
            mock.patch.object(installer, "install") as install,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(installer.main(), 0)
        install.assert_not_called()
        self.assertEqual(set(json.loads(output.getvalue())), set(installer.units()))
        with (
            mock.patch.object(sys, "argv", ["install_coordination_jobs.py", "--install"]),
            mock.patch.object(installer, "install", side_effect=ValueError(PRIVATE_TEXT)),
            contextlib.redirect_stderr(io.StringIO()) as error,
        ):
            self.assertEqual(installer.main(), 1)
        self.assertEqual(json.loads(error.getvalue()), {"status": "failed", "error": "ValueError"})


if __name__ == "__main__":
    unittest.main()
