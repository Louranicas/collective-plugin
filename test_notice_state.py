"""Behavioral contracts for pure notification audit state."""

from __future__ import annotations

import copy
import json
import unittest
from typing import cast
from unittest import mock
from uuid import UUID

import notice_state as notices


def identifier(index: int) -> str:
    return str(UUID(int=index + 1))


def intent(index: int = 0, keys: list[str] | None = None) -> notices.NoticeRecord:
    return notices.reserve(
        [],
        request_id=identifier(index),
        digest="a" * 64,
        keys=keys or [f"mail:p{index}"],
        boot_id="boot",
        endpoint="local-endpoint",
        now=float(index),
    )[0]


class NoticeStateTests(unittest.TestCase):
    def test_missing_journal_and_unknown_generation_are_explicit(self) -> None:
        self.assertEqual(notices.load_records(None), [])
        records = notices.reserve(
            [],
            request_id=identifier(0),
            digest="b" * 64,
            keys=["unavailable"],
            boot_id="",
            endpoint="local",
            now=0,
        )
        self.assertEqual(records[0]["boot_id"], "")
        self.assertEqual(records[0]["status"], "intent")

    def test_crash_load_converts_intent_to_unknown_without_mutating_input(self) -> None:
        source = [intent()]
        loaded = notices.load_records(source)
        self.assertEqual(loaded[0]["status"], "unknown")
        self.assertEqual(notices.held_keys(loaded), {"mail:p0"})
        self.assertEqual(source[0]["status"], "intent")
        loaded[0]["keys"].append("different")
        self.assertEqual(source[0]["keys"], ["mail:p0"])

    def test_unknown_and_in_progress_keys_block_reservation(self) -> None:
        for existing in ([intent()], notices.load_records([intent()])):
            with self.subTest(status=existing[0]["status"]), self.assertRaises(ValueError):
                notices.reserve(
                    existing,
                    request_id=identifier(1),
                    digest="b" * 64,
                    keys=["mail:p0", "new"],
                    boot_id="boot",
                    endpoint="local",
                    now=2,
                )

    def test_resolve_releases_only_named_hold_without_rewriting_unknown(self) -> None:
        source = notices.load_records([intent(keys=["one", "two"])])
        result = notices.resolve_keys(source, {"one", "absent"})
        self.assertEqual(result[0]["status"], "unknown")
        self.assertEqual(result[0]["keys"], ["one", "two"])
        self.assertEqual(result[0]["held_keys"], ["two"])
        self.assertEqual(source[0]["held_keys"], ["one", "two"])
        self.assertEqual(notices.held_keys(result), {"two"})

    def test_reappearing_resolved_condition_can_have_a_new_intent(self) -> None:
        unknown = notices.load_records([intent()])
        resolved = notices.resolve_keys(unknown, {"mail:p0"})
        result = notices.reserve(
            resolved,
            request_id=identifier(2),
            digest="b" * 64,
            keys=["mail:p0"],
            boot_id="boot",
            endpoint="local",
            now=4,
        )
        self.assertEqual([record["status"] for record in result], ["unknown", "intent"])
        self.assertEqual(result[0]["held_keys"], [])
        self.assertEqual(result[1]["held_keys"], ["mail:p0"])

    def test_live_intent_cannot_be_resolved(self) -> None:
        with self.assertRaises(ValueError):
            notices.resolve_keys([intent()], {"mail:p0"})
        self.assertEqual(notices.resolve_keys([intent()], {"other"})[0]["status"], "intent")

    def test_positive_receipt_marks_submitted_and_clears_holds(self) -> None:
        source = [intent()]
        result = notices.finish(source, identifier(0), status="submitted", message_id=42)
        self.assertEqual(result[0]["message_id"], 42)
        self.assertEqual(result[0]["held_keys"], [])
        self.assertEqual(notices.held_keys(result), set())
        self.assertEqual(source[0]["status"], "intent")
        self.assertEqual(notices.load_records(result), result)

    def test_refusal_clears_holds_while_unknown_keeps_them(self) -> None:
        refused = notices.finish([intent()], identifier(0), status="refused")
        unknown = notices.finish([intent()], identifier(0), status="unknown")
        self.assertEqual(refused[0]["held_keys"], [])
        self.assertEqual(unknown[0]["held_keys"], ["mail:p0"])
        self.assertEqual(notices.held_keys(refused), set())

    def test_unknown_can_only_reconcile_to_submitted_with_positive_proof(self) -> None:
        source = notices.load_records([intent()])
        result = notices.finish(source, identifier(0), status="submitted", message_id=1)
        self.assertEqual(result[0]["status"], "submitted")
        for status in ("refused", "unknown"):
            with self.subTest(status=status), self.assertRaises(ValueError):
                notices.finish(source, identifier(0), status=status)

    def test_terminal_outcomes_and_unknown_requests_cannot_transition(self) -> None:
        for status in ("submitted", "refused"):
            finished = notices.finish(
                [intent()],
                identifier(0),
                status=status,
                message_id=1 if status == "submitted" else None,
            )
            with self.subTest(status=status), self.assertRaises(ValueError):
                notices.finish(finished, identifier(0), status="unknown")
        with self.assertRaises(ValueError):
            notices.finish([intent()], identifier(2), status="unknown")
        with self.assertRaises(ValueError):
            notices.finish([intent()], identifier(0), status="intent")

    def test_positive_integer_receipt_is_required(self) -> None:
        for bad in (None, True, False, 0, -1, "1", 1.2):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                notices.finish([intent()], identifier(0), status="submitted", message_id=cast("int | None", bad))
        with self.assertRaises(ValueError):
            notices.finish([intent()], identifier(0), status="unknown", message_id=1)

    def test_duplicate_request_ids_are_rejected_on_load_and_reserve(self) -> None:
        one = intent()
        with self.assertRaises(ValueError):
            notices.load_records([one, copy.deepcopy(one)])
        with self.assertRaises(ValueError):
            notices.reserve(
                [one],
                request_id=identifier(0),
                digest="b" * 64,
                keys=["new"],
                boot_id="boot",
                endpoint="local",
                now=2,
            )

    def test_full_unknown_journal_refuses_new_intent_without_mutation(self) -> None:
        existing = notices.load_records([intent(index) for index in range(notices.MAX_RECORDS)])
        before = copy.deepcopy(existing)
        with self.assertRaises(ValueError):
            notices.reserve(
                existing,
                request_id=identifier(200),
                digest="c" * 64,
                keys=["new"],
                boot_id="boot",
                endpoint="local",
                now=200,
            )
        self.assertEqual(existing, before)

    def test_capacity_prunes_oldest_terminal_outcome_only(self) -> None:
        existing = [intent(index) for index in range(notices.MAX_RECORDS)]
        existing = notices.finish(existing, identifier(20), status="refused")
        existing = notices.finish(existing, identifier(10), status="submitted", message_id=4)
        before = copy.deepcopy(existing)
        result = notices.reserve(
            existing,
            request_id=identifier(200),
            digest="c" * 64,
            keys=["new"],
            boot_id="boot",
            endpoint="local",
            now=200,
        )
        self.assertEqual(len(result), notices.MAX_RECORDS)
        self.assertNotIn(identifier(10), {record["request_id"] for record in result})
        self.assertIn(identifier(20), {record["request_id"] for record in result})
        self.assertEqual(existing, before)

    def test_byte_capacity_refuses_oversized_persisted_state(self) -> None:
        records = [intent(index, keys=[("🧪" * 250) + str(index)]) for index in range(25)]
        with self.assertRaisesRegex(ValueError, "64 KiB"):
            notices.load_records(records)

    def test_reservation_budgets_crash_conversion_before_an_effect(self) -> None:
        record = intent()
        exact_intent_bytes = len(json.dumps([record], ensure_ascii=True, separators=(",", ":")).encode())
        with mock.patch.object(notices, "MAX_BYTES", exact_intent_bytes), self.assertRaises(ValueError):
            notices.reserve(
                [],
                request_id=identifier(0),
                digest="a" * 64,
                keys=["mail:p0"],
                boot_id="boot",
                endpoint="local-endpoint",
                now=0,
            )

    def test_byte_capacity_prunes_terminal_records_before_reservation(self) -> None:
        records = [
            notices.finish([intent(index, keys=["x" * 250 + str(index)])], identifier(index), status="refused")[0]
            for index in range(128)
        ]
        while True:
            try:
                notices.load_records(records)
            except ValueError:
                records.pop()
            else:
                break
        result = notices.reserve(
            records,
            request_id=identifier(200),
            digest="c" * 64,
            keys=["🧪" * 250],
            boot_id="boot",
            endpoint="local",
            now=200,
        )
        self.assertLess(len(result), len(records) + 1)
        self.assertEqual(result[-1]["status"], "intent")

    def test_empty_duplicate_nonstring_and_oversized_keys_are_rejected(self) -> None:
        for bad in (None, (), [], [""], ["x", "x"], ["x" * 257], [1], [str(i) for i in range(17)]):
            row: dict[str, object] = dict(intent())
            row["keys"] = bad
            with self.subTest(value=bad), self.assertRaises(ValueError):
                notices.load_records([row])

    def test_schema_types_and_bounds_are_enforced(self) -> None:
        alterations: list[tuple[str, object]] = [
            ("request_id", "invalid"),
            ("request_id", identifier(10).upper()),
            ("digest", "a" * 63),
            ("digest", "G" * 64),
            ("digest", None),
            ("boot_id", "b" * 129),
            ("boot_id", None),
            ("endpoint", "e" * 513),
            ("endpoint", ""),
            ("endpoint", 3),
            ("created_at", True),
            ("created_at", -1),
            ("created_at", float("nan")),
            ("created_at", float("inf")),
            ("created_at", "1"),
            ("created_at", 10**400),
            ("status", "other"),
            ("status", True),
            ("held_keys", ["not-original"]),
            ("held_keys", []),
        ]
        for key, bad in alterations:
            row: dict[str, object] = dict(intent())
            row[key] = bad
            with self.subTest(key=key, value=bad), self.assertRaises(ValueError):
                notices.load_records([row])
        invalid_values: list[object] = [
            {},
            "bad",
            [1],
            [dict(intent(), extra=True)],
            [dict(intent()) for _ in range(129)],
        ]
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                notices.load_records(value)
        missing = dict(intent())
        missing.pop("digest")
        with self.assertRaises(ValueError):
            notices.load_records([missing])

    def test_terminal_holds_or_receipts_on_unknown_are_rejected(self) -> None:
        for row in (
            dict(intent(), status="submitted", message_id=1),
            dict(intent(), status="refused"),
            dict(intent(), status="unknown", message_id=1),
        ):
            with self.subTest(row=row), self.assertRaises(ValueError):
                notices.load_records([row])
