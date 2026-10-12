"""Behavior checks with actual SQLite state, event traces and process faults."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from streaming import ClientStore, ProtocolError, ServiceStore, Session, sample_a


HERE = Path(__file__).resolve().parent


class StreamingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="l02-")
        self.root = Path(self.temporary.name)
        self.service = ServiceStore(self.root / "service.sqlite3")
        self.store = ClientStore(self.root / "client.sqlite3")
        self.client = Session(self.store)
        self.evidence = {"expected": {}, "observations": {}}

    def tearDown(self):
        # Copy raw synthetic observations before TemporaryDirectory is removed,
        # including state after a failed assertion.
        self.evidence["observations"]["final"] = {
            "service": self.service.snapshot(), "client": self.store.snapshot(),
            "active_run": self.client.active_run, "connected": self.client.connected,
        }
        self.temporary.cleanup()

    def record(self, key, value):
        self.evidence["observations"][key] = value

    def expect(self, **values):
        self.evidence["expected"].update(values)

    def feed(self, events, client=None):
        target = client or self.client
        return [target.receive(event) for event in events]

    def assert_a(self):
        self.assertEqual(self.client.display["text"], "北京晴")
        self.assertEqual(self.client.display["seq"], 6)
        self.assertEqual(self.client.display["state"], "completed")
        self.assertEqual(self.client.display["completion_applications"], 1)

    def test_00_broken_append_reproduces_duplicate_text(self):
        """Wrong append-only replay really duplicates text; fixed consumer does not."""
        events = sample_a(self.service)
        observed = "".join(e["payload"]["text"] for e in events[:3] if e["type"] == "delta")
        before = observed
        for event in events[1:]:
            if event["type"] == "delta":
                observed += event["payload"]["text"]
        self.record("broken_consumer", {"before_disconnect": before, "delivered": events[1:], "after": observed})
        self.expect(broken="北京北京晴", fixed="北京晴")
        self.assertEqual(observed, "北京北京晴")
        self.client.select("run-A")
        self.feed(events[:3]); self.feed(events[1:])
        self.assert_a()

    def test_01_replay_and_completed_applied_once(self):
        """After cursor 3, delivery of 2,3,4,5,6 and repeated 6 is idempotent."""
        events = sample_a(self.service)
        self.client.select("run-A")
        self.feed(events[:3])
        self.client.close()
        self.record("disconnected", self.client.display)
        self.expect(text="北京晴", seq=6, completion_applications=1, duplicates=[2, 3, 6])
        outcomes = self.feed(events[1:] + [events[-1]])
        self.record("delivery_outcomes", outcomes)
        self.assertEqual(outcomes, ["duplicate", "duplicate", "applied", "applied", "applied", "duplicate"])
        self.assert_a()

    def test_02_adjacent_equal_text_is_not_deduplicated(self):
        """Different sequence identities containing 哈 must both remain visible."""
        self.service.create("run-A", "重复文字")
        self.service.delta("run-A", "哈"); self.service.delta("run-A", "哈")
        self.service.finish("run-A", "completed")
        self.client.select("run-A"); self.client.recover(self.service)
        self.expect(text="哈哈", seq=4)
        self.assertEqual(self.client.display["text"], "哈哈")
        self.assertEqual(self.client.display["seq"], 4)

    def test_03_page_and_service_reconstructed_from_disk(self):
        """New objects have no connection memory but read matching durable cursor/text."""
        events = sample_a(self.service)
        self.client.select("run-A"); self.feed(events[:3])
        self.record("before_reload", self.client.display)
        self.service = ServiceStore(self.root / "service.sqlite3")
        self.store = ClientStore(self.root / "client.sqlite3")
        self.client = Session(self.store)
        self.assertIsNone(self.client.active_run)
        self.client.select("run-A")
        self.assertEqual((self.client.display["seq"], self.client.display["text"]), (3, "北京"))
        response = self.client.recover(self.service)
        self.expect(replayed_seq=[4, 5, 6], text="北京晴", completion_applications=1)
        self.assertEqual([e["seq"] for e in response["events"]], [4, 5, 6])
        self.assert_a()

    def test_04_all_page_state_lost_replays_from_zero(self):
        """An empty replacement client must not reuse a cursor detached from text."""
        events = sample_a(self.service)
        self.client.select("run-A"); self.feed(events[:3])
        self.record("lost_client_state", self.store.snapshot())
        self.store = ClientStore(self.root / "new-page.sqlite3")
        self.client = Session(self.store); self.client.select("run-A")
        self.assertEqual((self.client.display["seq"], self.client.display["text"]), (0, ""))
        self.client.recover(self.service)
        self.expect(start_cursor=0, text="北京晴")
        self.assert_a()

    def test_05_real_process_death_rolls_back_cursor_and_text(self):
        """os._exit(73) between SQL updates and commit leaves neither half persisted."""
        events = sample_a(self.service)
        self.client.select("run-A"); self.feed(events[:2])
        command = [sys.executable, "-c", (
            "import json,sys; from streaming import ClientStore; "
            "ClientStore(sys.argv[1]).apply(json.loads(sys.argv[2]),crash_before_commit=True)"),
            str(self.store.path), json.dumps(events[2], ensure_ascii=False)]
        process = subprocess.run(command, cwd=HERE, capture_output=True, text=True, timeout=15)
        self.record("child_process", {"returncode": process.returncode, "stdout": process.stdout, "stderr": process.stderr})
        self.record("after_crash", self.client.display)
        self.expect(child_exit=73, after_crash={"seq": 2, "text": "北"}, recovered_text="北京晴")
        self.assertEqual(process.returncode, 73)
        self.assertEqual((self.client.display["seq"], self.client.display["text"]), (2, "北"))
        self.assertNotIn(3, [e["seq"] for e in self.store.snapshot()["applied"]])
        self.client.recover(self.service)
        self.assert_a()

    def test_06_switch_run_ignores_late_old_connection(self):
        """Late A deltas/terminal cannot modify B display or B's persisted content."""
        events = sample_a(self.service)
        self.client.select("run-A"); self.feed(events[:3])
        self.service.create("run-B", "上海降雨")
        self.service.delta("run-B", "沪"); self.service.delta("run-B", "雨")
        self.service.finish("run-B", "completed")
        self.client.select("run-B"); self.client.recover(self.service)
        before = self.client.display
        self.record("late_delivery", self.feed(events[3:]))
        self.expect(active="run-B", text="沪雨", seq=4, old_A_text="北京")
        self.assertEqual(self.client.display, before)
        self.assertEqual(self.store.read("run-A")["text"], "北京")
        self.assertEqual(self.store.read("run-B")["text"], "沪雨")
        self.assertEqual(self.store.read("run-B")["seq"], 4)

    def test_07_close_connection_does_not_cancel_or_rollback(self):
        """Closing the local stream changes no server task or durable tool effect."""
        self.service.create("run-A", "天气")
        self.client.select("run-A"); self.client.recover(self.service)
        effect = self.service.start_tool("run-A")
        self.client.close()
        before = self.service.snapshot()
        self.record("after_close", before)
        self.expect(server_state_after_close="running", effects=1, final_state="completed")
        self.assertEqual(before["runs"][0]["state"], "running")
        self.assertTrue(effect["started"])
        self.assertEqual(len(before["tool_effects"]), 1)
        self.service.delta("run-A", "晴"); self.service.finish("run-A", "completed")
        self.client.recover(self.service)
        self.assertEqual(self.client.display["text"], "晴")
        self.assertEqual(len(self.service.snapshot()["tool_effects"]), 1)

    def test_08_gap_cannot_skip_missing_event(self):
        """Receiving seq 5 at cursor 3 freezes state until contiguous replay fills 4."""
        events = sample_a(self.service)
        self.client.select("run-A"); self.feed(events[:3])
        before = self.client.display
        self.assertEqual(self.client.receive(events[4]), "gap")
        self.assertEqual(self.client.display, before)
        self.record("gap_state", self.client.display)
        self.expect(gap_cursor=3, recovered_text="北京晴")
        self.client.recover(self.service)
        self.assert_a()

    def test_09_out_of_order_terminal_never_completes_early(self):
        """Out-of-order terminal/deltas are rejected, not rendered speculatively."""
        events = sample_a(self.service)
        self.client.select("run-A")
        outcomes = self.feed([events[5], events[0], events[4], events[1], events[3], events[2]])
        self.record("outcomes", outcomes)
        self.expect(outcomes=["gap", "applied", "gap", "applied", "gap", "applied"], before_recovery_state="running")
        self.assertEqual(outcomes, self.evidence["expected"]["outcomes"])
        self.assertEqual(self.client.display["state"], "running")
        self.assertEqual(self.client.display["text"], "北京")
        self.client.recover(self.service)
        self.assert_a()

    def test_10_expired_cursor_uses_consistent_snapshot(self):
        """Expired cursor replaces content with snapshot instead of appending a suffix."""
        events = sample_a(self.service)
        self.client.select("run-A"); self.feed(events[:3])
        self.service.prune("run-A", 4)
        response = self.client.recover(self.service)
        self.record("expired_response", response)
        self.expect(response="snapshot", reason="cursor_expired", text="北京晴", completion_applications=1)
        self.assertEqual(response["kind"], "snapshot")
        self.assertEqual(response["reason"], "cursor_expired")
        self.client.receive_snapshot(response["snapshot"])
        self.feed([events[2], events[-1]])
        self.assert_a()

    def test_11_snapshot_then_new_events_has_no_torn_pair(self):
        """Captured snapshot remains at seq 3 / 北京 while later writes continue."""
        self.service.create("run-A", "天气")
        self.service.delta("run-A", "北"); self.service.delta("run-A", "京")
        self.service.prune("run-A", 3)
        captured = self.service.replay("run-A", 0)["snapshot"]
        self.service.delta("run-A", "晴"); self.service.finish("run-A", "completed")
        self.client.select("run-A"); self.client.receive_snapshot(captured)
        self.record("captured_snapshot", captured)
        self.expect(captured={"seq": 3, "text": "北京", "state": "running"}, final={"seq": 5, "text": "北京晴"})
        self.assertEqual((self.client.display["seq"], self.client.display["text"]), (3, "北京"))
        self.client.recover(self.service)
        self.assertEqual((self.client.display["seq"], self.client.display["text"]), (5, "北京晴"))
        self.assertEqual(self.client.display["completion_applications"], 1)

    def test_12_late_snapshot_is_scoped_and_cannot_regress(self):
        """Old snapshots cannot overwrite another run or roll its own cursor back."""
        sample_a(self.service); self.service.prune("run-A", 3)
        snapshot = self.service.replay("run-A", 0)["snapshot"]
        self.service.create("run-B", "不同输入")
        self.service.delta("run-B", "乙"); self.service.finish("run-B", "completed")
        self.client.select("run-B"); self.client.recover(self.service)
        self.expect(active_B_text="乙", wrong_run="inactive", old_cursor="stale")
        before = self.client.display
        self.assertEqual(self.client.receive_snapshot(snapshot), "inactive")
        self.assertEqual(self.client.display, before)
        self.client.select("run-A"); self.client.receive_snapshot(snapshot)
        old = {**snapshot, "seq": 2, "text": "北", "state": "running"}
        self.assertEqual(self.client.receive_snapshot(old), "stale")
        self.assert_a()

    def blocked_tool(self):
        entered, release = threading.Event(), threading.Event()
        def barrier():
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test barrier timed out")
        pool = ThreadPoolExecutor(max_workers=1)
        self.addCleanup(pool.shutdown, wait=True)
        self.addCleanup(release.set)
        future = pool.submit(self.service.start_tool, "run-B", "weather", barrier)
        self.assertTrue(entered.wait(5))
        return release, future

    def test_13_cancel_wins_before_tool_barrier_ack_delayed(self):
        """Cancelled is committed before barrier release; delayed ack cannot run tool."""
        self.service.create("run-B", "等待工具")
        self.client.select("run-B"); self.client.recover(self.service)
        release, future = self.blocked_tool()
        cancel_ack = self.client.request_cancel(self.service)
        self.record("before_ack", {"client": self.client.display, "service": self.service.snapshot()})
        self.assertEqual(self.client.display["state"], "running")
        self.assertEqual(self.client.display["cancel_requested"], 1)
        release.set(); outcome = future.result(timeout=5)
        completion_ack = self.service.finish("run-B", "completed")
        self.client.receive_ack(completion_ack)  # requested completed, reports cancelled
        self.client.receive_ack(cancel_ack)
        self.record("tool_outcome", outcome)
        self.record("notification_order", [completion_ack, cancel_ack])
        self.expect(state="cancelled", effects=0, tool_started=False, completion_applications=0)
        self.assertFalse(outcome["started"])
        self.assertEqual(len(self.service.snapshot()["tool_effects"]), 0)
        self.assertEqual(self.client.display["state"], "cancelled")
        self.assertEqual(self.client.display["cancel_requested"], 0)
        self.assertEqual(self.client.display["completion_applications"], 0)

    def test_14_complete_wins_completion_notice_delayed(self):
        """Cancel response arriving before completion notice still reports completed."""
        self.service.create("run-B", "等待工具")
        self.client.select("run-B"); self.client.recover(self.service)
        release, future = self.blocked_tool()
        completed_ack = self.service.finish("run-B", "completed")
        cancel_ack = self.client.request_cancel(self.service)
        release.set(); outcome = future.result(timeout=5)
        self.client.receive_ack(cancel_ack)
        self.client.receive_ack(completed_ack)
        self.record("notification_order", [cancel_ack, completed_ack])
        self.expect(state="completed", effects=0, cancel_accepted=False, completion_applications=1)
        self.assertFalse(cancel_ack["accepted"])
        self.assertFalse(outcome["started"])
        self.assertEqual(self.client.display["state"], "completed")
        self.assertEqual(self.client.display["completion_applications"], 1)
        self.assertEqual(len(self.service.snapshot()["tool_effects"]), 0)

    def test_15_concurrent_terminal_race_has_one_winner(self):
        """Two independent connections race behind a barrier; exactly one terminal commits."""
        trials = []
        self.expect(trials=12, accepted_per_run=1, terminal_events_per_run=1)
        for index in range(12):
            run_id = "race-" + str(index)
            self.service.create(run_id, "竞态")
            barrier = threading.Barrier(2)
            def finish(state):
                barrier.wait(timeout=5)
                return ServiceStore(self.service.path).finish(run_id, state)
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(finish, state) for state in ("completed", "cancelled")]
                acks = [future.result(timeout=10) for future in futures]
            self.client.select(run_id); self.client.recover(self.service)
            self.client.receive_ack(acks[1]); self.client.receive_ack(acks[0])
            terminal = [event for event in self.service.replay(run_id, 0)["events"] if event["type"] in {"completed", "cancelled"}]
            trials.append({"run_id": run_id, "acks": acks, "terminal_events": terminal, "client": self.client.display})
            self.record("trials", trials)
            self.assertEqual(sum(ack["accepted"] for ack in acks), 1)
            self.assertEqual(len(terminal), 1)
            self.assertEqual(acks[0]["state"], acks[1]["state"])
            self.assertEqual(self.client.display["state"], acks[0]["state"])

    def test_16_cancel_does_not_undo_started_effect(self):
        """Cancellation after local effect starts preserves the effect ledger."""
        self.service.create("run-B", "已开始工具")
        self.service.start_tool("run-B")
        self.client.select("run-B"); self.client.recover(self.service)
        ack = self.client.request_cancel(self.service)
        self.client.receive_ack(ack)
        self.expect(state="cancelled", effects=1)
        self.assertEqual(len(self.service.snapshot()["tool_effects"]), 1)
        self.assertEqual(self.client.display["state"], "cancelled")

    def test_17_terminal_rejects_later_deltas_and_conflicting_snapshot(self):
        """Neither producer continuation nor a conflicting snapshot overwrites terminal."""
        sample_a(self.service)
        self.client.select("run-A"); self.client.recover(self.service)
        before = self.client.display
        with self.assertRaises(ProtocolError):
            self.service.delta("run-A", "错")
        with self.assertRaises(ProtocolError):
            self.client.receive({"run_id": "run-A", "seq": 7, "type": "delta", "payload": {"text": "错"}})
        with self.assertRaises(ProtocolError):
            self.client.receive_snapshot({"run_id": "run-A", "seq": 7, "text": "北京晴", "state": "cancelled"})
        self.expect(text="北京晴", state="completed", rejected_mutations=3)
        self.assertEqual(self.client.display, before)

    def test_18_same_identity_different_payload_is_protocol_error(self):
        """A retained event identity may not silently acquire different content."""
        events = sample_a(self.service)
        self.client.select("run-A"); self.feed(events[:2])
        with self.assertRaises(ProtocolError):
            self.client.receive({**events[1], "payload": {"text": "南"}})
        self.expect(text="北", seq=2, conflicting_content="rejected")
        self.assertEqual((self.client.display["seq"], self.client.display["text"]), (2, "北"))

    def test_19_future_cursor_is_rejected_not_silently_reset(self):
        """A cursor ahead of durable server state is an error, not a valid empty replay."""
        sample_a(self.service)
        self.expect(server_seq=6, future_cursor=7, result="ProtocolError")
        with self.assertRaises(ProtocolError):
            self.service.replay("run-A", 7)
        self.assertEqual(self.service.snapshot()["runs"][0]["seq"], 6)

    def test_20_retention_boundary_is_inclusive_for_cursor(self):
        """Cursor equal to minimum_cursor can replay the remaining contiguous suffix."""
        events = sample_a(self.service)
        self.client.select("run-A"); self.feed(events[:3])
        self.service.prune("run-A", 3)
        response = self.client.recover(self.service)
        self.expect(kind="events", sequences=[4, 5, 6])
        self.assertEqual(response["kind"], "events")
        self.assertEqual([event["seq"] for event in response["events"]], [4, 5, 6])
        self.assert_a()

    def test_21_missing_middle_in_replay_fails_without_skipping(self):
        """A damaged delivery omitting seq 4 is detected; the next replay repairs it."""
        events = sample_a(self.service)
        self.client.select("run-A"); self.feed(events[:3])
        original = self.service.replay
        def damaged(run_id, cursor):
            response = original(run_id, cursor)
            return {**response, "events": [e for e in response["events"] if e["seq"] != 4]}
        self.service.replay = damaged
        with self.assertRaises(ProtocolError):
            self.client.recover(self.service)
        self.record("after_damaged_replay", self.client.display)
        self.expect(cursor_after_damage=3, text_after_damage="北京", repaired="北京晴")
        self.assertEqual((self.client.display["seq"], self.client.display["text"]), (3, "北京"))
        self.service.replay = original
        self.client.recover(self.service)
        self.assert_a()

    def test_22_truncated_tail_is_not_treated_as_complete_recovery(self):
        """A missing final event is detected by through_seq, despite no internal gap."""
        events = sample_a(self.service)
        self.client.select("run-A"); self.feed(events[:3])
        original = self.service.replay
        def damaged(run_id, cursor):
            response = original(run_id, cursor)
            return {**response, "events": response["events"][:-1]}
        self.service.replay = damaged
        with self.assertRaises(ProtocolError):
            self.client.recover(self.service)
        self.record("after_truncated_replay", self.client.display)
        self.expect(cursor_after_damage=5, state_after_damage="running", final_seq=6)
        self.assertEqual((self.client.display["seq"], self.client.display["state"]), (5, "running"))
        self.service.replay = original
        self.client.recover(self.service)
        self.assert_a()


if __name__ == "__main__":
    unittest.main(verbosity=2)
