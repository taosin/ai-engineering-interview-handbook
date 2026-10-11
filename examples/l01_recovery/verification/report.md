# L01 恢复验证报告

L01 本地库存恢复示例；不代表 M4 全部验收通过，不包含租户权限验收；未覆盖完整应用既有回归；不评定学习者能力。

执行时间：2026-10-11T04:51:06.238685+00:00。以下记录来自本次运行。
环境：Python 3.11.5（CPython）；SQLite 3.42.0。
结果：21 通过，0 失败，0 错误，0 跳过。

每个用例使用独立临时目录，初始库存为 10。完整业务/Agent 快照、预期与过程证据保存在同目录的 `report.json`；临时数据库执行后清理。

源码 SHA256：

- `examples/l01_recovery/recovery.py`：`9f82d8571cd9da177eabfeb4682d456abe9c96e5f21fd10aac73780503f556fd`
- `examples/l01_recovery/test_recovery.py`：`29a107235340b3236b784ef7e8344cbd662f627bc4eba5d082276befcf72b9bf`
- `examples/l01_recovery/run.py`：`fdd3a5a230bfffeed4874df23806381ca84d9e503853335717eabd497e3bffea`

| 用例 | 状态 | 秒 |
| --- | --- | --- |
| test_00_broken_retry_reproduces_duplicate_effect | passed | 0.0458 |
| test_01_normal_and_completed_restart | passed | 0.0197 |
| test_02_committed_response_lost | passed | 0.0266 |
| test_03_exit_after_tool_commit | passed | 0.1067 |
| test_04_exit_before_checkpoint | passed | 0.1347 |
| test_05_two_workers_same_operation | passed | 0.3209 |
| test_06_late_unknown_cannot_erase_success | passed | 0.0187 |
| test_07_same_key_different_parameters | passed | 0.0301 |
| test_08_prepared_key_and_parameters_are_stable | passed | 0.0114 |
| test_09_different_orders_are_not_deduplicated | passed | 0.0188 |
| test_10_one_order_can_have_two_legitimate_operations | passed | 0.0207 |
| test_11_permanent_error_stops | passed | 0.0132 |
| test_12_committed_but_budget_exhausted_is_unknown | passed | 0.0264 |
| test_13_uncommitted_timeout_is_still_unknown | passed | 0.0392 |
| test_14_no_contract_does_not_blindly_retry | passed | 0.2605 |
| test_15_manual_reconciliation_is_audited | passed | 0.0241 |
| test_16_tool_transaction_rolls_back | passed | 0.0111 |
| test_17_budget_claim_is_atomic_across_processes | passed | 0.2361 |
| test_18_reprepare_does_not_reset_budget | passed | 0.0093 |
| test_19_contract_cannot_change_after_unknown_write | passed | 0.0481 |
| test_20_tool_storage_lock_leaves_recoverable_unknown | passed | 5.3626 |

## test_00_broken_retry_reproduces_duplicate_effect

Broken control: retrying one logical operation with a new key deducts twice.

状态：**passed**。

预期：
```json
{
  "purpose": "reproduce the known broken retry, not a second legitimate operation",
  "after_lost_response": {
    "available": 8,
    "reservations": 1
  },
  "after_wrong_retry": {
    "available": 6,
    "reservations": 2
  },
  "logical_operations": 1
}
```
观测：库存 {"SKU-A": 6}；有效预留记录 2 条。

## test_01_normal_and_completed_restart

A completed operation remains one reservation after another recovery.

状态：**passed**。

预期：
```json
{
  "available": 8,
  "reservations": 1,
  "state": "succeeded"
}
```
观测：库存 {"SKU-A": 8}；有效预留记录 1 条。

## test_02_committed_response_lost

A lost response is reconciled, without a second business effect.

状态：**passed**。

预期：
```json
{
  "available": 8,
  "reservations": 1,
  "state": "succeeded"
}
```
观测：库存 {"SKU-A": 8}；有效预留记录 1 条。

## test_03_exit_after_tool_commit

A real process exits after the tool commits and before its response.

状态：**passed**。

预期：
```json
{
  "exit_code": 71,
  "available": 8,
  "reservations": 1,
  "state": "succeeded"
}
```
观测：库存 {"SKU-A": 8}；有效预留记录 1 条。

## test_04_exit_before_checkpoint

A real process exits after success but before the Agent checkpoint.

状态：**passed**。

预期：
```json
{
  "exit_code": 72,
  "available": 8,
  "reservations": 1,
  "state": "succeeded"
}
```
观测：库存 {"SKU-A": 8}；有效预留记录 1 条。

## test_05_two_workers_same_operation

Two processes reach the same tool operation with an explicit barrier.

状态：**passed**。

预期：
```json
{
  "available": 8,
  "reservations": 1,
  "state": "succeeded",
  "workers": 2
}
```
观测：库存 {"SKU-A": 8}；有效预留记录 1 条。

## test_06_late_unknown_cannot_erase_success

A stale worker's timeout does not overwrite a confirmed success.

状态：**passed**。

预期：
```json
{
  "available": 8,
  "reservations": 1,
  "state": "succeeded",
  "late_unknown_ignored": true
}
```
观测：库存 {"SKU-A": 8}；有效预留记录 1 条。

## test_07_same_key_different_parameters

Changing quantity, order or SKU under an existing key is a conflict.

状态：**passed**。

预期：
```json
{
  "available": 8,
  "reservations": 1,
  "conflicts": 3
}
```
观测：库存 {"SKU-A": 8}；有效预留记录 1 条。

## test_08_prepared_key_and_parameters_are_stable

A restart reuses the operation key; changing prepared parameters fails.

状态：**passed**。

预期：
```json
{
  "available": 10,
  "reservations": 0,
  "same_key": true,
  "parameter_conflict": true
}
```
观测：库存 {"SKU-A": 10}；有效预留记录 0 条。

## test_09_different_orders_are_not_deduplicated

Two orders produce two distinct reservations, not one SKU-level hit.

状态：**passed**。

预期：
```json
{
  "available": 6,
  "reservations": 2,
  "successful_operations": 2,
  "replayed_original_available": 8
}
```
观测：库存 {"SKU-A": 6}；有效预留记录 2 条。

## test_10_one_order_can_have_two_legitimate_operations

A new explicit business operation on the same order is not a retry.

状态：**passed**。

预期：
```json
{
  "available": 6,
  "reservations": 2,
  "same_order_distinct_operations": true
}
```
观测：库存 {"SKU-A": 6}；有效预留记录 2 条。

## test_11_permanent_error_stops

Insufficient stock is a definite rejection, with no business effect.

状态：**passed**。

预期：
```json
{
  "available": 10,
  "reservations": 0,
  "state": "failed",
  "no_retry_after_failure": true
}
```
观测：库存 {"SKU-A": 10}；有效预留记录 0 条。

## test_12_committed_but_budget_exhausted_is_unknown

Exhausted reconciliation budget does not turn a committed result into failure.

状态：**passed**。

预期：
```json
{
  "available": 8,
  "reservations": 1,
  "state": "unknown",
  "calls": 2
}
```
观测：库存 {"SKU-A": 8}；有效预留记录 1 条。

## test_13_uncommitted_timeout_is_still_unknown

Without an authoritative result, no side effect does not imply known failure.

状态：**passed**。

预期：
```json
{
  "available": 10,
  "reservations": 0,
  "state": "unknown",
  "calls": 2
}
```
观测：库存 {"SKU-A": 10}；有效预留记录 0 条。

## test_14_no_contract_does_not_blindly_retry

Even two prepared readers get one unsafe write, followed by reconciliation.

状态：**passed**。

预期：
```json
{
  "available": 8,
  "reservations": 1,
  "state": "unknown",
  "no_second_automatic_call": true
}
```
观测：库存 {"SKU-A": 8}；有效预留记录 1 条。

## test_15_manual_reconciliation_is_audited

Explicit reconciliation can learn success without resetting the automatic budget.

状态：**passed**。

预期：
```json
{
  "available": 8,
  "reservations": 1,
  "state": "succeeded",
  "automatic_calls": 2,
  "manual_audit_added": true
}
```
观测：库存 {"SKU-A": 8}；有效预留记录 1 条。

## test_16_tool_transaction_rolls_back

Failure inside the transaction leaves neither a deduction nor a reservation.

状态：**passed**。

预期：
```json
{
  "after_fault": {
    "available": 10,
    "reservations": 0
  },
  "after_retry": {
    "available": 8,
    "reservations": 1
  }
}
```
观测：库存 {"SKU-A": 8}；有效预留记录 1 条。

## test_17_budget_claim_is_atomic_across_processes

Two workers cannot both consume the last persistent remote-call allowance.

状态：**passed**。

预期：
```json
{
  "available": 10,
  "reservations": 0,
  "successful_claims": 1,
  "calls": 1
}
```
观测：库存 {"SKU-A": 10}；有效预留记录 0 条。

## test_18_reprepare_does_not_reset_budget

Opening an existing operation cannot refresh its consumed call allowance.

状态：**passed**。

预期：
```json
{
  "available": 10,
  "reservations": 0,
  "calls": 1,
  "max_calls": 1,
  "same_key": true
}
```
观测：库存 {"SKU-A": 10}；有效预留记录 0 条。

## test_19_contract_cannot_change_after_unknown_write

Changing either persisted retry contract is refused before another call.

状态：**passed**。

预期：
```json
{
  "each_direction": {
    "available": 8,
    "reservations": 1,
    "state": "unknown"
  },
  "contract_conflicts": 4,
  "no_additional_calls": true
}
```
观测：库存 {"SKU-A": 8}；有效预留记录 1 条。

## test_20_tool_storage_lock_leaves_recoverable_unknown

A real SQLite write lock fails within its budget, then recovery succeeds.

状态：**passed**。

预期：
```json
{
  "while_locked": {
    "available": 10,
    "reservations": 0,
    "state": "unknown",
    "halt_reason": "storage_locked; reconcile_required"
  },
  "after_release": {
    "available": 8,
    "reservations": 1,
    "state": "succeeded"
  }
}
```
观测：库存 {"SKU-A": 8}；有效预留记录 1 条。
