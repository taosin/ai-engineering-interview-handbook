# L04 离线评测实际运行报告

L04 固定八任务合成数据的离线配对评测、逐次成本、nearest-rank p95 与输入拒绝验证；支持 M3-C2 的计算口径子集，不运行真实模型或业务应用。八样本不能估计线上尾延迟，本例的 110% 门槛不是行业标准；不宣布完整 M3/M4 通过，不鉴定日志真实性或学习者能力。

执行时间：2026-10-12T01:04:56.706893+00:00。环境：Python 3.11.5 / Darwin。
本次运行 28 项，28 通过；失败 0、错误 0、跳过 0。
源码执行前后保持一致：True。本报告全部为合成证据，没有真实用户或模型结果。

## 固定实验的实际计算

| 版本 | 实际成功 / 全任务 | 成本（本地单位） | p95（毫秒） | 禁止副作用 |
| --- | --- | --- | --- | --- |
| baseline-v1 | 6/8 = 75.0% | 16 | 300 | 0 |
| candidate-v1 | 6/8 = 75.0% | 20 | 400 | 1 |

成本增加：25%。nearest-rank p95：ceil(0.95 × 8) = 8。
候选通过全部门槛：False；未通过：zero_forbidden_effects, cost_at_most_110_percent, p95_at_most_110_percent。

错误对照实际得到候选 7/7、只计末次 attempt 的成本 16；丢掉超时后 p95 错变成 180 毫秒。
test_00 的通过表示已观察到这个错误对照并验证修正结果，不表示候选或错误算法通过门槛。

## 逐任务结果

| 版本 / 任务 | 终态 | 目标 | 禁止副作用 | 实际成功 | 累计成本 | 耗时 | 失败原因 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| baseline / case-1 | completed | True | 0 | True | 2 | 100 | — |
| baseline / case-2 | completed | True | 0 | True | 2 | 120 | — |
| baseline / case-3 | completed | False | 0 | False | 2 | 130 | goal_not_achieved |
| baseline / case-4 | completed | True | 0 | True | 2 | 150 | — |
| baseline / case-5 | completed | True | 0 | True | 2 | 160 | — |
| baseline / case-6 | completed | True | 0 | True | 2 | 170 | — |
| baseline / case-7 | completed | True | 0 | True | 2 | 200 | — |
| baseline / case-8 | timed_out | False | 0 | False | 2 | 300 | timed_out, goal_not_achieved |
| candidate / case-1 | completed | True | 0 | True | 2 | 100 | — |
| candidate / case-2 | completed | True | 0 | True | 2 | 110 | — |
| candidate / case-3 | completed | True | 0 | True | 2 | 120 | — |
| candidate / case-4 | completed | True | 0 | True | 2 | 130 | — |
| candidate / case-5 | completed | True | 0 | True | 3 | 150 | — |
| candidate / case-6 | completed | True | 0 | True | 3 | 160 | — |
| candidate / case-7 | completed | True | 1 | False | 3 | 180 | forbidden_side_effect |
| candidate / case-8 | timed_out | False | 0 | False | 3 | 400 | timed_out, goal_not_achieved |

## 版本与原始证据

| 文件 | SHA-256 |
| --- | --- |
| evaluation.py | 42216fd59ef9ac06b0a6cb82d5123c483c63348779d452d98fbb26cac468a85f |
| test_evaluation.py | e6c32b0a2edef9e7a45c0064f3dde205fc43806ea0df885f449d27e454c5bc03 |
| run.py | d82facaafad3245e7f1d9e699de58e830be623964419aecbb84e9ac54ae75ecc |

合成输入规范 JSON SHA-256：`345557edc11a9c7c92f63f56b2f47ec312df6ea01234aebeb53148527ceabc13`。
完整输入、每个 attempt、模型评审备注、逐例拒绝原因、门槛和原始 unittest 输出均见 [report.json](report.json)。

## 行为测试

| 用例 | 结果 | 秒 |
| --- | --- | --- |
| test_00_wrong_report_and_correct_result | passed | 0.001185 |
| test_01_model_pass_cannot_override_duplicate_effect | passed | 0.000303 |
| test_02_timeout_includes_all_attempt_cost_and_latency | passed | 0.000293 |
| test_03_missing_final_rejected | passed | 0.000128 |
| test_04_duplicate_final_rejected_even_at_eight_rows | passed | 0.000511 |
| test_05_extra_final_rejected | passed | 0.000481 |
| test_06_unknown_final_case_rejected | passed | 0.000499 |
| test_07_mixed_final_version_rejected | passed | 0.000503 |
| test_08_mixed_attempt_version_rejected | passed | 0.000407 |
| test_09_run_version_rejected | passed | 0.000353 |
| test_10_manifest_change_rejected | passed | 7.9e-05 |
| test_11_missing_attempt_rejected | passed | 0.000363 |
| test_12_duplicate_attempt_rejected_at_expected_count | passed | 0.000473 |
| test_13_retry_sequence_gap_rejected | passed | 0.000468 |
| test_14_false_attempt_count_rejected | passed | 0.003657 |
| test_15_abnormal_numeric_values_rejected | passed | 0.000933 |
| test_16_final_latency_cannot_drop_first_attempt | passed | 0.000185 |
| test_17_timeout_cannot_claim_goal_achieved | passed | 0.000152 |
| test_18_final_cannot_override_attempt_goal | passed | 7.1e-05 |
| test_19_prior_attempt_effect_cannot_be_dropped | passed | 0.000184 |
| test_20_claimed_success_cannot_override_evidence | passed | 0.000591 |
| test_21_types_and_unknown_fields_rejected | passed | 0.000966 |
| test_22_json_duplicate_keys_and_nonfinite_literals_rejected | passed | 0.000694 |
| test_23_nearest_rank_explicit_sample_and_invalid_inputs | passed | 0.000216 |
| test_24_row_order_does_not_change_pairing_and_input_is_unchanged | passed | 0.001959 |
| test_25_gate_boundary_and_real_passing_control | passed | 0.001583 |
| test_26_zero_baseline_has_explicit_undefined_relative_growth | passed | 0.000809 |
| test_27_json_round_trip_and_fixture_isolation | passed | 0.001722 |

## 本次原始测试输出

```text
test_00_wrong_report_and_correct_result (test_evaluation.EvaluationTests.test_00_wrong_report_and_correct_result)
Reproduce 7/7 and dropped retry cost, then recover paired 6/8 and three failed gates. ... ok
test_01_model_pass_cannot_override_duplicate_effect (test_evaluation.EvaluationTests.test_01_model_pass_cannot_override_duplicate_effect)
The candidate case-7 model pass remains visible but cannot erase its deterministic failure. ... ok
test_02_timeout_includes_all_attempt_cost_and_latency (test_evaluation.EvaluationTests.test_02_timeout_includes_all_attempt_cost_and_latency)
A timed-out task still contributes to the denominator, both costs and endpoint latency. ... ok
test_03_missing_final_rejected (test_evaluation.EvaluationTests.test_03_missing_final_rejected)
A missing final row cannot silently shrink the denominator. ... ok
test_04_duplicate_final_rejected_even_at_eight_rows (test_evaluation.EvaluationTests.test_04_duplicate_final_rejected_even_at_eight_rows)
Replacing a task with a duplicate preserves row count but is still rejected. ... ok
test_05_extra_final_rejected (test_evaluation.EvaluationTests.test_05_extra_final_rejected)
An extra duplicate final row is not a ninth task. ... ok
test_06_unknown_final_case_rejected (test_evaluation.EvaluationTests.test_06_unknown_final_case_rejected)
An unrelated task cannot replace a missing paired task. ... ok
test_07_mixed_final_version_rejected (test_evaluation.EvaluationTests.test_07_mixed_final_version_rejected)
A final from a different implementation version is rejected. ... ok
test_08_mixed_attempt_version_rejected (test_evaluation.EvaluationTests.test_08_mixed_attempt_version_rejected)
Every retry must belong to the same implementation version. ... ok
test_09_run_version_rejected (test_evaluation.EvaluationTests.test_09_run_version_rejected)
The run version cannot be changed without the exercise contract. ... ok
test_10_manifest_change_rejected (test_evaluation.EvaluationTests.test_10_manifest_change_rejected)
Dropping a failed task from the manifest cannot redefine this experiment. ... ok
test_11_missing_attempt_rejected (test_evaluation.EvaluationTests.test_11_missing_attempt_rejected)
Dropping an earlier retry is rejected even if all final rows remain. ... ok
test_12_duplicate_attempt_rejected_at_expected_count (test_evaluation.EvaluationTests.test_12_duplicate_attempt_rejected_at_expected_count)
An attempt duplicate cannot fill the slot of another attempt. ... ok
test_13_retry_sequence_gap_rejected (test_evaluation.EvaluationTests.test_13_retry_sequence_gap_rejected)
An ordinal gap is rejected rather than treating the latest event as the entire run. ... ok
test_14_false_attempt_count_rejected (test_evaluation.EvaluationTests.test_14_false_attempt_count_rejected)
A final row cannot pretend a two-attempt allocation had only one call. ... ok
test_15_abnormal_numeric_values_rejected (test_evaluation.EvaluationTests.test_15_abnormal_numeric_values_rejected)
Negative, boolean, string, nonfinite and unbounded measures cannot produce a score. ... ok
test_16_final_latency_cannot_drop_first_attempt (test_evaluation.EvaluationTests.test_16_final_latency_cannot_drop_first_attempt)
An endpoint duration less than the summed attempts is rejected. ... ok
test_17_timeout_cannot_claim_goal_achieved (test_evaluation.EvaluationTests.test_17_timeout_cannot_claim_goal_achieved)
A timed-out attempt cannot silently claim a verified goal. ... ok
test_18_final_cannot_override_attempt_goal (test_evaluation.EvaluationTests.test_18_final_cannot_override_attempt_goal)
The final goal must agree with the terminal attempt evidence. ... ok
test_19_prior_attempt_effect_cannot_be_dropped (test_evaluation.EvaluationTests.test_19_prior_attempt_effect_cannot_be_dropped)
A side effect from an earlier attempt must survive into the final ledger. ... ok
test_20_claimed_success_cannot_override_evidence (test_evaluation.EvaluationTests.test_20_claimed_success_cannot_override_evidence)
Unlike a non-authoritative judge note, a contradictory success claim invalidates input. ... ok
test_21_types_and_unknown_fields_rejected (test_evaluation.EvaluationTests.test_21_types_and_unknown_fields_rejected)
Goals, counts, schemas and fields are typed rather than coerced. ... ok
test_22_json_duplicate_keys_and_nonfinite_literals_rejected (test_evaluation.EvaluationTests.test_22_json_duplicate_keys_and_nonfinite_literals_rejected)
JSON parsing rejects overwritten keys, NaN/Infinity, excessive size and malformed input. ... ok
test_23_nearest_rank_explicit_sample_and_invalid_inputs (test_evaluation.EvaluationTests.test_23_nearest_rank_explicit_sample_and_invalid_inputs)
The p95 rank includes the eighth timeout, rather than interpolating or dropping it. ... ok
test_24_row_order_does_not_change_pairing_and_input_is_unchanged (test_evaluation.EvaluationTests.test_24_row_order_does_not_change_pairing_and_input_is_unchanged)
Task and attempt order do not alter results; the calculator does not mutate evidence. ... ok
test_25_gate_boundary_and_real_passing_control (test_evaluation.EvaluationTests.test_25_gate_boundary_and_real_passing_control)
Exactly 110 percent is accepted when deterministic failures are absent; any excess fails. ... ok
test_26_zero_baseline_has_explicit_undefined_relative_growth (test_evaluation.EvaluationTests.test_26_zero_baseline_has_explicit_undefined_relative_growth)
A zero baseline does not divide by zero or manufacture a relative percentage. ... ok
test_27_json_round_trip_and_fixture_isolation (test_evaluation.EvaluationTests.test_27_json_round_trip_and_fixture_isolation)
Independent copies and JSON input retain the same full paired calculation. ... ok

----------------------------------------------------------------------
Ran 28 tests in 0.020s

OK
```
