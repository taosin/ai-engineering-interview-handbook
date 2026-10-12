# L02 流式恢复与取消本地验证报告

L02 本地服务桩的事件重放、页面重建、游标快照、任务隔离与取消竞态验证；使用合成事件和 SQLite 本地副作用，不涉及真实网络、浏览器 EventSource、真实 LLM 或外部工具；未覆盖完整应用既有回归，不宣布 M4 全部通过，不评定学习者能力。

执行时间：2026-10-12T01:06:02.480012+00:00。以下记录来自本次实际测试执行。
环境：Python 3.11.5；SQLite 3.42.0；Darwin。
结果：23 项，23 通过。
执行期间源码保持一致：True。

`test_00` 通过表示实际复现了错误重放导致的重复文字，并验证修复；不代表错误实现符合要求。
取消只阻止本地事务屏障之后尚未启动的工具；已发生的本地副作用保留，不承诺外部工具回滚。
每例完整事件、应用/去重/缺口/快照轨迹和原始输出见 [report.json](report.json)。

## 实现版本

| 文件 | SHA-256 |
| --- | --- |
| streaming.py | 505847d54584f01a4d9e18d32539f4f8ec17422a9d22176e654e6d7a146c2c57 |
| test_streaming.py | fd743e0f1b19ead7dcec59614aae31b5875f6a530f6c83ad0bb9526e4480e976 |
| run.py | 640da209b521c867a75366a74504fea7190e44ff1924924b990e874c73fe632a |

## 用例结果

| 用例 | 状态 | 秒 |
| --- | --- | --- |
| test_00_broken_append_reproduces_duplicate_text | passed | 0.029677 |
| test_01_replay_and_completed_applied_once | passed | 0.019933 |
| test_02_adjacent_equal_text_is_not_deduplicated | passed | 0.030068 |
| test_03_page_and_service_reconstructed_from_disk | passed | 0.016439 |
| test_04_all_page_state_lost_replays_from_zero | passed | 0.031041 |
| test_05_real_process_death_rolls_back_cursor_and_text | passed | 0.12128 |
| test_06_switch_run_ignores_late_old_connection | passed | 0.062627 |
| test_07_close_connection_does_not_cancel_or_rollback | passed | 0.029968 |
| test_08_gap_cannot_skip_missing_event | passed | 0.019632 |
| test_09_out_of_order_terminal_never_completes_early | passed | 0.036492 |
| test_10_expired_cursor_uses_consistent_snapshot | passed | 0.030624 |
| test_11_snapshot_then_new_events_has_no_torn_pair | passed | 0.010449 |
| test_12_late_snapshot_is_scoped_and_cannot_regress | passed | 0.02021 |
| test_13_cancel_wins_before_tool_barrier_ack_delayed | passed | 0.016971 |
| test_14_complete_wins_completion_notice_delayed | passed | 0.021761 |
| test_15_concurrent_terminal_race_has_one_winner | passed | 0.262271 |
| test_16_cancel_does_not_undo_started_effect | passed | 0.017896 |
| test_17_terminal_rejects_later_deltas_and_conflicting_snapshot | passed | 0.02386 |
| test_18_same_identity_different_payload_is_protocol_error | passed | 0.009325 |
| test_19_future_cursor_is_rejected_not_silently_reset | passed | 0.009368 |
| test_20_retention_boundary_is_inclusive_for_cursor | passed | 0.032968 |
| test_21_missing_middle_in_replay_fails_without_skipping | passed | 0.03354 |
| test_22_truncated_tail_is_not_treated_as_complete_recovery | passed | 0.01987 |

## test_00_broken_append_reproduces_duplicate_text

Wrong append-only replay really duplicates text; fixed consumer does not.

预期：
```json
{
  "broken": "北京北京晴",
  "fixed": "北京晴"
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-A",
    "seq": 6,
    "text": "北京晴",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：1 条。

## test_01_replay_and_completed_applied_once

After cursor 3, delivery of 2,3,4,5,6 and repeated 6 is idempotent.

预期：
```json
{
  "text": "北京晴",
  "seq": 6,
  "completion_applications": 1,
  "duplicates": [
    2,
    3,
    6
  ]
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-A",
    "seq": 6,
    "text": "北京晴",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：1 条。

## test_02_adjacent_equal_text_is_not_deduplicated

Different sequence identities containing 哈 must both remain visible.

预期：
```json
{
  "text": "哈哈",
  "seq": 4
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-A",
    "seq": 4,
    "text": "哈哈",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：0 条。

## test_03_page_and_service_reconstructed_from_disk

New objects have no connection memory but read matching durable cursor/text.

预期：
```json
{
  "replayed_seq": [
    4,
    5,
    6
  ],
  "text": "北京晴",
  "completion_applications": 1
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-A",
    "seq": 6,
    "text": "北京晴",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：1 条。

## test_04_all_page_state_lost_replays_from_zero

An empty replacement client must not reuse a cursor detached from text.

预期：
```json
{
  "start_cursor": 0,
  "text": "北京晴"
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-A",
    "seq": 6,
    "text": "北京晴",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：1 条。

## test_05_real_process_death_rolls_back_cursor_and_text

os._exit(73) between SQL updates and commit leaves neither half persisted.

预期：
```json
{
  "child_exit": 73,
  "after_crash": {
    "seq": 2,
    "text": "北"
  },
  "recovered_text": "北京晴"
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-A",
    "seq": 6,
    "text": "北京晴",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：1 条。

## test_06_switch_run_ignores_late_old_connection

Late A deltas/terminal cannot modify B display or B's persisted content.

预期：
```json
{
  "active": "run-B",
  "text": "沪雨",
  "seq": 4,
  "old_A_text": "北京"
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-A",
    "seq": 3,
    "text": "北京",
    "state": "running",
    "completion_applications": 0,
    "cancel_requested": 0
  },
  {
    "run_id": "run-B",
    "seq": 4,
    "text": "沪雨",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：1 条。

## test_07_close_connection_does_not_cancel_or_rollback

Closing the local stream changes no server task or durable tool effect.

预期：
```json
{
  "server_state_after_close": "running",
  "effects": 1,
  "final_state": "completed"
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-A",
    "seq": 4,
    "text": "晴",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：1 条。

## test_08_gap_cannot_skip_missing_event

Receiving seq 5 at cursor 3 freezes state until contiguous replay fills 4.

预期：
```json
{
  "gap_cursor": 3,
  "recovered_text": "北京晴"
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-A",
    "seq": 6,
    "text": "北京晴",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：1 条。

## test_09_out_of_order_terminal_never_completes_early

Out-of-order terminal/deltas are rejected, not rendered speculatively.

预期：
```json
{
  "outcomes": [
    "gap",
    "applied",
    "gap",
    "applied",
    "gap",
    "applied"
  ],
  "before_recovery_state": "running"
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-A",
    "seq": 6,
    "text": "北京晴",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：1 条。

## test_10_expired_cursor_uses_consistent_snapshot

Expired cursor replaces content with snapshot instead of appending a suffix.

预期：
```json
{
  "response": "snapshot",
  "reason": "cursor_expired",
  "text": "北京晴",
  "completion_applications": 1
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-A",
    "seq": 6,
    "text": "北京晴",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：1 条。

## test_11_snapshot_then_new_events_has_no_torn_pair

Captured snapshot remains at seq 3 / 北京 while later writes continue.

预期：
```json
{
  "captured": {
    "seq": 3,
    "text": "北京",
    "state": "running"
  },
  "final": {
    "seq": 5,
    "text": "北京晴"
  }
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-A",
    "seq": 5,
    "text": "北京晴",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：0 条。

## test_12_late_snapshot_is_scoped_and_cannot_regress

Old snapshots cannot overwrite another run or roll its own cursor back.

预期：
```json
{
  "active_B_text": "乙",
  "wrong_run": "inactive",
  "old_cursor": "stale"
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-B",
    "seq": 3,
    "text": "乙",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  },
  {
    "run_id": "run-A",
    "seq": 6,
    "text": "北京晴",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：1 条。

## test_13_cancel_wins_before_tool_barrier_ack_delayed

Cancelled is committed before barrier release; delayed ack cannot run tool.

预期：
```json
{
  "state": "cancelled",
  "effects": 0,
  "tool_started": false,
  "completion_applications": 0
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-B",
    "seq": 2,
    "text": "",
    "state": "cancelled",
    "completion_applications": 0,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：0 条。

## test_14_complete_wins_completion_notice_delayed

Cancel response arriving before completion notice still reports completed.

预期：
```json
{
  "state": "completed",
  "effects": 0,
  "cancel_accepted": false,
  "completion_applications": 1
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-B",
    "seq": 2,
    "text": "",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：0 条。

## test_15_concurrent_terminal_race_has_one_winner

Two independent connections race behind a barrier; exactly one terminal commits.

预期：
```json
{
  "trials": 12,
  "accepted_per_run": 1,
  "terminal_events_per_run": 1
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "race-0",
    "seq": 2,
    "text": "",
    "state": "cancelled",
    "completion_applications": 0,
    "cancel_requested": 0
  },
  {
    "run_id": "race-1",
    "seq": 2,
    "text": "",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  },
  {
    "run_id": "race-2",
    "seq": 2,
    "text": "",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  },
  {
    "run_id": "race-3",
    "seq": 2,
    "text": "",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  },
  {
    "run_id": "race-4",
    "seq": 2,
    "text": "",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  },
  {
    "run_id": "race-5",
    "seq": 2,
    "text": "",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  },
  {
    "run_id": "race-6",
    "seq": 2,
    "text": "",
    "state": "cancelled",
    "completion_applications": 0,
    "cancel_requested": 0
  },
  {
    "run_id": "race-7",
    "seq": 2,
    "text": "",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  },
  {
    "run_id": "race-8",
    "seq": 2,
    "text": "",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  },
  {
    "run_id": "race-9",
    "seq": 2,
    "text": "",
    "state": "cancelled",
    "completion_applications": 0,
    "cancel_requested": 0
  },
  {
    "run_id": "race-10",
    "seq": 2,
    "text": "",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  },
  {
    "run_id": "race-11",
    "seq": 2,
    "text": "",
    "state": "cancelled",
    "completion_applications": 0,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：0 条。

## test_16_cancel_does_not_undo_started_effect

Cancellation after local effect starts preserves the effect ledger.

预期：
```json
{
  "state": "cancelled",
  "effects": 1
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-B",
    "seq": 3,
    "text": "",
    "state": "cancelled",
    "completion_applications": 0,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：1 条。

## test_17_terminal_rejects_later_deltas_and_conflicting_snapshot

Neither producer continuation nor a conflicting snapshot overwrites terminal.

预期：
```json
{
  "text": "北京晴",
  "state": "completed",
  "rejected_mutations": 3
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-A",
    "seq": 6,
    "text": "北京晴",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：1 条。

## test_18_same_identity_different_payload_is_protocol_error

A retained event identity may not silently acquire different content.

预期：
```json
{
  "text": "北",
  "seq": 2,
  "conflicting_content": "rejected"
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-A",
    "seq": 2,
    "text": "北",
    "state": "running",
    "completion_applications": 0,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：1 条。

## test_19_future_cursor_is_rejected_not_silently_reset

A cursor ahead of durable server state is an error, not a valid empty replay.

预期：
```json
{
  "server_seq": 6,
  "future_cursor": 7,
  "result": "ProtocolError"
}
```
实际客户端任务状态：
```json
[]
```
实际本地工具副作用：1 条。

## test_20_retention_boundary_is_inclusive_for_cursor

Cursor equal to minimum_cursor can replay the remaining contiguous suffix.

预期：
```json
{
  "kind": "events",
  "sequences": [
    4,
    5,
    6
  ]
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-A",
    "seq": 6,
    "text": "北京晴",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：1 条。

## test_21_missing_middle_in_replay_fails_without_skipping

A damaged delivery omitting seq 4 is detected; the next replay repairs it.

预期：
```json
{
  "cursor_after_damage": 3,
  "text_after_damage": "北京",
  "repaired": "北京晴"
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-A",
    "seq": 6,
    "text": "北京晴",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：1 条。

## test_22_truncated_tail_is_not_treated_as_complete_recovery

A missing final event is detected by through_seq, despite no internal gap.

预期：
```json
{
  "cursor_after_damage": 5,
  "state_after_damage": "running",
  "final_seq": 6
}
```
实际客户端任务状态：
```json
[
  {
    "run_id": "run-A",
    "seq": 6,
    "text": "北京晴",
    "state": "completed",
    "completion_applications": 1,
    "cancel_requested": 0
  }
]
```
实际本地工具副作用：1 条。

## 本次 unittest 原始输出（个人路径脱敏）

~~~text
test_00_broken_append_reproduces_duplicate_text (test_streaming.StreamingTests.test_00_broken_append_reproduces_duplicate_text)
Wrong append-only replay really duplicates text; fixed consumer does not. ... ok
test_01_replay_and_completed_applied_once (test_streaming.StreamingTests.test_01_replay_and_completed_applied_once)
After cursor 3, delivery of 2,3,4,5,6 and repeated 6 is idempotent. ... ok
test_02_adjacent_equal_text_is_not_deduplicated (test_streaming.StreamingTests.test_02_adjacent_equal_text_is_not_deduplicated)
Different sequence identities containing 哈 must both remain visible. ... ok
test_03_page_and_service_reconstructed_from_disk (test_streaming.StreamingTests.test_03_page_and_service_reconstructed_from_disk)
New objects have no connection memory but read matching durable cursor/text. ... ok
test_04_all_page_state_lost_replays_from_zero (test_streaming.StreamingTests.test_04_all_page_state_lost_replays_from_zero)
An empty replacement client must not reuse a cursor detached from text. ... ok
test_05_real_process_death_rolls_back_cursor_and_text (test_streaming.StreamingTests.test_05_real_process_death_rolls_back_cursor_and_text)
os._exit(73) between SQL updates and commit leaves neither half persisted. ... ok
test_06_switch_run_ignores_late_old_connection (test_streaming.StreamingTests.test_06_switch_run_ignores_late_old_connection)
Late A deltas/terminal cannot modify B display or B's persisted content. ... ok
test_07_close_connection_does_not_cancel_or_rollback (test_streaming.StreamingTests.test_07_close_connection_does_not_cancel_or_rollback)
Closing the local stream changes no server task or durable tool effect. ... ok
test_08_gap_cannot_skip_missing_event (test_streaming.StreamingTests.test_08_gap_cannot_skip_missing_event)
Receiving seq 5 at cursor 3 freezes state until contiguous replay fills 4. ... ok
test_09_out_of_order_terminal_never_completes_early (test_streaming.StreamingTests.test_09_out_of_order_terminal_never_completes_early)
Out-of-order terminal/deltas are rejected, not rendered speculatively. ... ok
test_10_expired_cursor_uses_consistent_snapshot (test_streaming.StreamingTests.test_10_expired_cursor_uses_consistent_snapshot)
Expired cursor replaces content with snapshot instead of appending a suffix. ... ok
test_11_snapshot_then_new_events_has_no_torn_pair (test_streaming.StreamingTests.test_11_snapshot_then_new_events_has_no_torn_pair)
Captured snapshot remains at seq 3 / 北京 while later writes continue. ... ok
test_12_late_snapshot_is_scoped_and_cannot_regress (test_streaming.StreamingTests.test_12_late_snapshot_is_scoped_and_cannot_regress)
Old snapshots cannot overwrite another run or roll its own cursor back. ... ok
test_13_cancel_wins_before_tool_barrier_ack_delayed (test_streaming.StreamingTests.test_13_cancel_wins_before_tool_barrier_ack_delayed)
Cancelled is committed before barrier release; delayed ack cannot run tool. ... ok
test_14_complete_wins_completion_notice_delayed (test_streaming.StreamingTests.test_14_complete_wins_completion_notice_delayed)
Cancel response arriving before completion notice still reports completed. ... ok
test_15_concurrent_terminal_race_has_one_winner (test_streaming.StreamingTests.test_15_concurrent_terminal_race_has_one_winner)
Two independent connections race behind a barrier; exactly one terminal commits. ... ok
test_16_cancel_does_not_undo_started_effect (test_streaming.StreamingTests.test_16_cancel_does_not_undo_started_effect)
Cancellation after local effect starts preserves the effect ledger. ... ok
test_17_terminal_rejects_later_deltas_and_conflicting_snapshot (test_streaming.StreamingTests.test_17_terminal_rejects_later_deltas_and_conflicting_snapshot)
Neither producer continuation nor a conflicting snapshot overwrites terminal. ... ok
test_18_same_identity_different_payload_is_protocol_error (test_streaming.StreamingTests.test_18_same_identity_different_payload_is_protocol_error)
A retained event identity may not silently acquire different content. ... ok
test_19_future_cursor_is_rejected_not_silently_reset (test_streaming.StreamingTests.test_19_future_cursor_is_rejected_not_silently_reset)
A cursor ahead of durable server state is an error, not a valid empty replay. ... ok
test_20_retention_boundary_is_inclusive_for_cursor (test_streaming.StreamingTests.test_20_retention_boundary_is_inclusive_for_cursor)
Cursor equal to minimum_cursor can replay the remaining contiguous suffix. ... ok
test_21_missing_middle_in_replay_fails_without_skipping (test_streaming.StreamingTests.test_21_missing_middle_in_replay_fails_without_skipping)
A damaged delivery omitting seq 4 is detected; the next replay repairs it. ... ok
test_22_truncated_tail_is_not_treated_as_complete_recovery (test_streaming.StreamingTests.test_22_truncated_tail_is_not_treated_as_complete_recovery)
A missing final event is detected by through_seq, despite no internal gap. ... ok

----------------------------------------------------------------------
Ran 23 tests in 0.910s

OK
~~~
