"""Independent business assertions for the L01 recovery demonstration.

Every test starts with isolated durable stores and ten units of SKU-A. Evidence
is copied into ordinary dictionaries before temporary directories are removed.
"""

from __future__ import annotations

import multiprocessing
import queue
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from recovery import (  # noqa: E402
    Agent,
    AgentStore,
    ContractConflict,
    ParameterConflict,
    ToolClient,
    ToolStore,
    initialize,
)


PARAMS = {"order_id": "order-17", "sku": "SKU-A", "qty": 2}


def _recovery_worker(directory, barrier, results):
    """Spawn-safe worker; the barrier sits before the tool transaction."""
    try:
        root = Path(directory)
        client = ToolClient(
            ToolStore(root / "tool.sqlite3"),
            before_reserve=lambda: barrier.wait(timeout=15),
        )
        operation = Agent(AgentStore(root / "agent.sqlite3"), client).recover("op-1")
        results.put({"ok": True, "operation": operation})
    except BaseException as exc:
        results.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


def _budget_worker(directory, barrier, results):
    try:
        store = AgentStore(Path(directory) / "agent.sqlite3")
        barrier.wait(timeout=15)
        attempt_id = store.claim_call("op-1", "write")
        results.put({"ok": True, "attempt_id": attempt_id})
    except BaseException as exc:
        results.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


def _non_idempotent_worker(directory, barrier, results):
    """Both workers observe prepared before competing for their first write."""
    class SynchronizedReadStore(AgentStore):
        first_read = True

        def read(self, operation_id):
            operation = super().read(operation_id)
            if self.first_read:
                self.first_read = False
                barrier.wait(timeout=15)
            return operation

    try:
        root = Path(directory)
        store = SynchronizedReadStore(root / "agent.sqlite3")
        client = ToolClient(
            ToolStore(root / "tool.sqlite3"), idempotent=False, drop_response=True
        )
        operation = Agent(store, client).recover("op-1")
        results.put({"ok": True, "operation": operation})
    except BaseException as exc:
        results.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.evidence = {"expected": {}, "observations": {}}
        temporary = tempfile.TemporaryDirectory(prefix="l01-case-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        initialize(self.root)
        self.store = AgentStore(self.root / "agent.sqlite3")
        self.tool = ToolStore(self.root / "tool.sqlite3")
        self.capture("initial")

    def tearDown(self):
        # Also preserve evidence from a failing assertion or worker.
        self.capture("final")

    def capture(self, label):
        self.evidence["observations"][label] = {
            "agent": self.store.snapshot(),
            "tool": self.tool.snapshot(),
        }

    def prepare(self, operation_id="op-1", params=None, max_calls=4):
        return self.store.prepare(
            operation_id, dict(PARAMS if params is None else params), max_calls=max_calls
        )

    def agent(self, **client_options):
        return Agent(self.store, ToolClient(self.tool, **client_options))

    def assert_business(self, available, reservations):
        state = self.tool.snapshot()
        self.assertEqual(state["stock"]["SKU-A"], available)
        self.assertEqual(len(state["reservations"]), reservations)
        self.assertEqual(10 - sum(row["qty"] for row in state["reservations"]), available)
        self.assertEqual(len({row["operation_key"] for row in state["reservations"]}), reservations)

    def crash_and_recover(self, fault, exit_code):
        original = self.prepare()
        process = subprocess.run(
            [
                sys.executable,
                str(HERE / "recovery.py"),
                "--directory", str(self.root),
                "--operation", "op-1",
                "--fault", fault,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.evidence["process"] = {
            "fault": fault,
            "exit_code": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr,
        }
        self.capture("after_process_exit_before_recovery")
        self.assertEqual(process.returncode, exit_code, process.stderr)
        self.assert_business(8, 1)
        self.assertNotEqual(self.store.read("op-1")["state"], "succeeded")
        # New objects read the files; no crashed-process memory is available.
        restarted = Agent(
            AgentStore(self.root / "agent.sqlite3"),
            ToolClient(ToolStore(self.root / "tool.sqlite3")),
        ).recover("op-1")
        self.assertEqual(restarted["key"], original["key"])
        self.assertEqual(restarted["state"], "succeeded")
        self.assert_business(8, 1)

    def concurrent(self, worker):
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(2)
        results = context.Queue()
        processes = [
            context.Process(target=worker, args=(str(self.root), barrier, results))
            for _ in range(2)
        ]
        try:
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=25)
            self.evidence["worker_exit_codes"] = [p.exitcode for p in processes]
            self.assertFalse(any(p.is_alive() for p in processes), "worker hung")
            self.assertTrue(all(p.exitcode == 0 for p in processes))
            replies = []
            for _ in processes:
                try:
                    replies.append(results.get(timeout=3))
                except queue.Empty:
                    self.fail("worker exited without returning evidence")
            self.evidence["worker_results"] = replies
            self.assertTrue(all(reply["ok"] for reply in replies), replies)
            return replies
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                if process.pid is not None:
                    process.join(timeout=3)
            results.close()
            results.join_thread()

    def test_00_broken_retry_reproduces_duplicate_effect(self):
        """Broken control: retrying one logical operation with a new key deducts twice."""
        self.evidence["expected"] = {
            "purpose": "reproduce the known broken retry, not a second legitimate operation",
            "after_lost_response": {"available": 8, "reservations": 1},
            "after_wrong_retry": {"available": 6, "reservations": 2},
            "logical_operations": 1,
        }
        operation = self.prepare()
        self.store.claim_call("op-1", "write")
        with self.assertRaises(TimeoutError):
            ToolClient(self.tool, drop_response=True).reserve(operation["key"], dict(PARAMS))
        self.capture("first_write_committed_response_lost")
        self.assert_business(8, 1)
        # The bug is inventing a new key for the SAME already-prepared operation.
        wrong_retry_key = str(uuid.uuid4())
        self.store.claim_call("op-1", "write")
        ToolClient(self.tool).reserve(wrong_retry_key, dict(PARAMS))
        self.evidence["wrong_attempt_keys"] = [operation["key"], wrong_retry_key]
        self.assertNotEqual(operation["key"], wrong_retry_key)
        self.assertEqual(len(self.store.snapshot()["operations"]), 1)
        self.assertTrue(all(row["order_id"] == "order-17" for row in self.tool.snapshot()["reservations"]))
        self.assert_business(6, 2)

    def test_01_normal_and_completed_restart(self):
        """A completed operation remains one reservation after another recovery."""
        self.evidence["expected"] = {"available": 8, "reservations": 1, "state": "succeeded"}
        original = self.prepare()
        first = self.agent().recover("op-1")
        self.capture("first_success")
        again = Agent(
            AgentStore(self.root / "agent.sqlite3"), ToolClient(self.tool)
        ).recover("op-1")
        self.assertEqual(first["state"], "succeeded")
        self.assertEqual(again["state"], "succeeded")
        self.assertEqual(again["key"], original["key"])
        self.assertEqual(again["calls"], first["calls"])
        self.assert_business(8, 1)

    def test_02_committed_response_lost(self):
        """A lost response is reconciled, without a second business effect."""
        self.evidence["expected"] = {"available": 8, "reservations": 1, "state": "succeeded"}
        self.prepare()
        result = self.agent(drop_response=True).recover("op-1")
        self.assertEqual(result["state"], "succeeded")
        self.assertLessEqual(result["calls"], result["max_calls"])
        self.assert_business(8, 1)

    def test_03_exit_after_tool_commit(self):
        """A real process exits after the tool commits and before its response."""
        self.evidence["expected"] = {"exit_code": 71, "available": 8, "reservations": 1, "state": "succeeded"}
        self.crash_and_recover("after-tool-commit", 71)

    def test_04_exit_before_checkpoint(self):
        """A real process exits after success but before the Agent checkpoint."""
        self.evidence["expected"] = {"exit_code": 72, "available": 8, "reservations": 1, "state": "succeeded"}
        self.crash_and_recover("before-checkpoint", 72)

    def test_05_two_workers_same_operation(self):
        """Two processes reach the same tool operation with an explicit barrier."""
        self.evidence["expected"] = {"available": 8, "reservations": 1, "state": "succeeded", "workers": 2}
        self.prepare(max_calls=8)
        replies = self.concurrent(_recovery_worker)
        self.assertTrue(all(r["operation"]["state"] == "succeeded" for r in replies))
        self.assertEqual(self.store.read("op-1")["state"], "succeeded")
        self.assert_business(8, 1)

    def test_06_late_unknown_cannot_erase_success(self):
        """A stale worker's timeout does not overwrite a confirmed success."""
        self.evidence["expected"] = {"available": 8, "reservations": 1, "state": "succeeded", "late_unknown_ignored": True}
        self.prepare()
        success = self.agent().recover("op-1")
        self.capture("before_stale_write")
        AgentStore(self.root / "agent.sqlite3").note_unknown("op-1", "late timeout")
        current = self.store.read("op-1")
        self.assertEqual(current["state"], "succeeded")
        self.assertEqual(current["result"], success["result"])
        self.assert_business(8, 1)

    def test_07_same_key_different_parameters(self):
        """Changing quantity, order or SKU under an existing key is a conflict."""
        self.evidence["expected"] = {"available": 8, "reservations": 1, "conflicts": 3}
        result = self.tool.reserve("fixed-key", dict(PARAMS))
        self.capture("original_success")
        for change in ({"qty": 3}, {"order_id": "order-18"}, {"sku": "SKU-B"}):
            with self.subTest(change=change):
                with self.assertRaises(ParameterConflict):
                    self.tool.reserve("fixed-key", {**PARAMS, **change})
                self.assert_business(8, 1)
        self.assertEqual(self.tool.lookup("fixed-key", dict(PARAMS)), result)

    def test_08_prepared_key_and_parameters_are_stable(self):
        """A restart reuses the operation key; changing prepared parameters fails."""
        self.evidence["expected"] = {"available": 10, "reservations": 0, "same_key": True, "parameter_conflict": True}
        first = self.prepare()
        reopened = AgentStore(self.root / "agent.sqlite3")
        again = reopened.prepare("op-1", dict(PARAMS))
        self.assertEqual(first["key"], again["key"])
        with self.assertRaises(ParameterConflict):
            reopened.prepare("op-1", {**PARAMS, "qty": 3})
        self.assertEqual(reopened.read("op-1")["params"], PARAMS)
        self.assert_business(10, 0)

    def test_09_different_orders_are_not_deduplicated(self):
        """Two orders produce two distinct reservations, not one SKU-level hit."""
        self.evidence["expected"] = {"available": 6, "reservations": 2, "successful_operations": 2, "replayed_original_available": 8}
        first = self.prepare()
        second = self.prepare("op-2", {**PARAMS, "order_id": "order-18"})
        self.assertNotEqual(first["key"], second["key"])
        for operation_id in ("op-1", "op-2"):
            self.assertEqual(self.agent().recover(operation_id)["state"], "succeeded")
        original_result = self.store.read("op-1")["result"]
        replayed = self.tool.reserve(first["key"], dict(PARAMS))
        self.evidence["replayed_original_result"] = replayed
        self.assertEqual(replayed, original_result)
        self.assertEqual(replayed["available"], 8)
        self.assertEqual(
            {row["order_id"] for row in self.tool.snapshot()["reservations"]},
            {"order-17", "order-18"},
        )
        self.assert_business(6, 2)

    def test_10_one_order_can_have_two_legitimate_operations(self):
        """A new explicit business operation on the same order is not a retry."""
        self.evidence["expected"] = {"available": 6, "reservations": 2, "same_order_distinct_operations": True}
        first = self.prepare("reserve-first")
        second = self.prepare("reserve-additional")
        self.assertNotEqual(first["key"], second["key"])
        for operation_id in ("reserve-first", "reserve-additional"):
            self.assertEqual(self.agent().recover(operation_id)["state"], "succeeded")
        self.capture("two_legitimate_operations")
        for operation_id in ("reserve-first", "reserve-additional"):
            self.agent().recover(operation_id)
        self.assertTrue(all(row["order_id"] == "order-17" for row in self.tool.snapshot()["reservations"]))
        self.assert_business(6, 2)

    def test_11_permanent_error_stops(self):
        """Insufficient stock is a definite rejection, with no business effect."""
        self.evidence["expected"] = {"available": 10, "reservations": 0, "state": "failed", "no_retry_after_failure": True}
        self.prepare(params={**PARAMS, "qty": 11})
        failed = self.agent().recover("op-1")
        self.capture("permanent_failure")
        again = self.agent().recover("op-1")
        self.assertEqual(failed["state"], "failed")
        self.assertTrue(failed["result"].get("reason"))
        self.assertEqual(again["calls"], failed["calls"])
        self.assertEqual(again["state"], "failed")
        self.assert_business(10, 0)

    def test_12_committed_but_budget_exhausted_is_unknown(self):
        """Exhausted reconciliation budget does not turn a committed result into failure."""
        self.evidence["expected"] = {"available": 8, "reservations": 1, "state": "unknown", "calls": 2}
        self.prepare(max_calls=2)
        result = self.agent(drop_response=True, query_offline=True).recover("op-1")
        self.capture("budget_exhausted")
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["calls"], 2)
        self.assertTrue(result["halt_reason"])
        before = self.tool.snapshot()
        restarted = Agent(
            AgentStore(self.root / "agent.sqlite3"),
            ToolClient(self.tool, drop_response=True, query_offline=True),
        ).recover("op-1")
        self.assertEqual(restarted["state"], "unknown")
        self.assertEqual(restarted["calls"], 2)
        self.assertEqual(self.tool.snapshot(), before)
        self.assert_business(8, 1)

    def test_13_uncommitted_timeout_is_still_unknown(self):
        """Without an authoritative result, no side effect does not imply known failure."""
        self.evidence["expected"] = {"available": 10, "reservations": 0, "state": "unknown", "calls": 2}
        self.prepare(max_calls=2)
        result = self.agent(offline=True, query_offline=True).recover("op-1")
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["calls"], 2)
        self.assertTrue(result["halt_reason"])
        self.assert_business(10, 0)

    def test_14_no_contract_does_not_blindly_retry(self):
        """Even two prepared readers get one unsafe write, followed by reconciliation."""
        self.evidence["expected"] = {"available": 8, "reservations": 1, "state": "unknown", "no_second_automatic_call": True}
        self.prepare()
        replies = self.concurrent(_non_idempotent_worker)
        self.assertTrue(all(reply["operation"]["state"] == "unknown" for reply in replies))
        result = self.store.read("op-1")
        self.capture("unknown_without_contract")
        again = self.agent(drop_response=True, idempotent=False).recover("op-1")
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["calls"], 1)
        self.assertTrue(result["halt_reason"])
        self.assertEqual(again["calls"], result["calls"])
        self.assertEqual(again["state"], "unknown")
        self.assert_business(8, 1)

    def test_15_manual_reconciliation_is_audited(self):
        """Explicit reconciliation can learn success without resetting the automatic budget."""
        self.evidence["expected"] = {"available": 8, "reservations": 1, "state": "succeeded", "automatic_calls": 2, "manual_audit_added": True}
        self.prepare(max_calls=2)
        exhausted = self.agent(drop_response=True, query_offline=True).recover("op-1")
        self.assertEqual(exhausted["state"], "unknown")
        before = self.store.snapshot()
        self.capture("before_manual_reconciliation")
        reconciled = self.agent().reconcile("op-1")
        after = self.store.snapshot()
        self.assertEqual(reconciled["state"], "succeeded")
        self.assertEqual(reconciled["calls"], exhausted["calls"])
        self.assertEqual(reconciled["max_calls"], exhausted["max_calls"])
        self.assertGreater(len(after["attempts"]), len(before["attempts"]))
        new_attempts = after["attempts"][len(before["attempts"]):]
        self.assertTrue(all(row["automatic"] == 0 for row in new_attempts))
        self.assertTrue(all(row["kind"] == "manual_query" for row in new_attempts))
        self.assert_business(8, 1)

    def test_16_tool_transaction_rolls_back(self):
        """Failure inside the transaction leaves neither a deduction nor a reservation."""
        self.evidence["expected"] = {"after_fault": {"available": 10, "reservations": 0}, "after_retry": {"available": 8, "reservations": 1}}
        with self.assertRaises(RuntimeError):
            self.tool.reserve("atomic-key", dict(PARAMS), fail_mid_transaction=True)
        self.capture("after_transaction_fault")
        self.assert_business(10, 0)
        self.assertIsNone(self.tool.lookup("atomic-key", dict(PARAMS)))
        result = self.tool.reserve("atomic-key", dict(PARAMS))
        self.assertEqual(result["status"], "succeeded")
        self.assert_business(8, 1)

    def test_17_budget_claim_is_atomic_across_processes(self):
        """Two workers cannot both consume the last persistent remote-call allowance."""
        self.evidence["expected"] = {"available": 10, "reservations": 0, "successful_claims": 1, "calls": 1}
        self.prepare(max_calls=1)
        replies = self.concurrent(_budget_worker)
        self.assertEqual(sum(r["attempt_id"] is not None for r in replies), 1)
        operation = self.store.read("op-1")
        self.assertEqual(operation["calls"], 1)
        self.assertEqual(operation["max_calls"], 1)
        self.assert_business(10, 0)

    def test_18_reprepare_does_not_reset_budget(self):
        """Opening an existing operation cannot refresh its consumed call allowance."""
        self.evidence["expected"] = {"available": 10, "reservations": 0, "calls": 1, "max_calls": 1, "same_key": True}
        original = self.prepare(max_calls=1)
        self.assertIsNotNone(self.store.claim_call("op-1", "write"))
        self.capture("budget_consumed")
        reopened = AgentStore(self.root / "agent.sqlite3")
        with self.assertRaises(ParameterConflict):
            reopened.prepare("op-1", dict(PARAMS), max_calls=4)
        prepared = reopened.prepare("op-1", dict(PARAMS), max_calls=1)
        self.assertEqual(prepared["key"], original["key"])
        self.assertEqual(prepared["calls"], 1)
        self.assertEqual(prepared["max_calls"], 1)
        self.assertIsNone(reopened.claim_call("op-1", "query"))
        self.assert_business(10, 0)


    def test_19_contract_cannot_change_after_unknown_write(self):
        """Changing either persisted retry contract is refused before another call."""
        self.evidence["expected"] = {
            "each_direction": {"available": 8, "reservations": 1, "state": "unknown"},
            "contract_conflicts": 4,
            "no_additional_calls": True,
        }
        for original_mode in (False, True):
            with self.subTest(original_idempotent=original_mode):
                directory = self.root / f"contract-{original_mode}"
                initialize(directory)
                self.store = AgentStore(directory / "agent.sqlite3")
                self.tool = ToolStore(directory / "tool.sqlite3")
                self.capture(f"contract_{original_mode}_initial")
                self.prepare(max_calls=2)
                original = self.agent(
                    idempotent=original_mode, drop_response=True, query_offline=True
                ).recover("op-1")
                self.assertEqual(original["state"], "unknown")
                self.assert_business(8, 1)
                self.capture(f"contract_{original_mode}_before_change")
                before = self.tool.snapshot()
                for method in ("recover", "reconcile"):
                    with self.subTest(method=method):
                        with self.assertRaises(ContractConflict):
                            getattr(self.agent(idempotent=not original_mode), method)("op-1")
                        self.assertEqual(self.store.read("op-1")["calls"], original["calls"])
                        self.assertEqual(self.store.read("op-1")["state"], "unknown")
                        self.assertEqual(self.tool.snapshot(), before)
                self.capture(f"contract_{original_mode}_after_rejection")

    def test_20_tool_storage_lock_leaves_recoverable_unknown(self):
        """A real SQLite write lock fails within its budget, then recovery succeeds."""
        self.evidence["expected"] = {
            "while_locked": {"available": 10, "reservations": 0, "state": "unknown", "halt_reason": "storage_locked; reconcile_required"},
            "after_release": {"available": 8, "reservations": 1, "state": "succeeded"},
        }
        self.prepare()
        lock = sqlite3.connect(str(self.root / "tool.sqlite3"), isolation_level=None)
        try:
            lock.execute("BEGIN IMMEDIATE")
            started = time.monotonic()
            with self.assertRaises(sqlite3.OperationalError):
                self.agent().recover("op-1")
            self.evidence["lock_wait_seconds"] = round(time.monotonic() - started, 4)
            locked = self.store.read("op-1")
            self.capture("after_bounded_storage_error")
            self.assertEqual(locked["state"], "unknown")
            self.assertEqual(locked["halt_reason"], "storage_locked; reconcile_required")
            self.assert_business(10, 0)
        finally:
            lock.rollback()
            lock.close()
        result = self.agent().recover("op-1")
        self.assertEqual(result["state"], "succeeded")
        self.assertLessEqual(result["calls"], result["max_calls"])
        self.assert_business(8, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
