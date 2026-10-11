# L03 本地权限与版本验证报告

L03 合成租户数据上的确定性检索、版本和工具授权验证；覆盖 M4-C2 的本地模拟子集，不是实际身份认证、真实 LLM 抗注入或 MCP OAuth 验收；不覆盖 M4-C1 恢复与 M4-C3 完整应用回归，不宣布 M4 全部通过，不评定学习者能力。

执行时间：2026-10-11T06:47:01.676227+00:00。记录来自本次实际运行，全部使用合成数据。
环境：Python 3.11.5；SQLite 3.42.0；Darwin。
结果：21 项，21 通过；其余状态：{"failed": 0, "error": 0, "skipped": 0, "expected_failure": 0, "unexpected_success": 0}。
执行期间源码保持一致：True。

`test_00` 通过表示复现了错误截断导致的漏召回，并观察到修复结果；不表示错误实现符合业务要求。
所有逐例输入、上下文、引用、授权原因及本地副作用观测见 [report.json](report.json)。
B 合法访问用例含 B 的合成标记；A 请求的上下文、回答及审计单独检查不含该标记。

## 实现版本

| 文件 | SHA-256 |
| --- | --- |
| retrieval.py | 6ebda6005301ec2122eaa09adfa1b2dc47c489ec3749b1518fdde9f3ed03ce03 |
| test_retrieval.py | 50b7b6895033ceaf389e97d72c365f82cc059edeb63fae100dad2ff74d729ec1 |
| run.py | b87688abbabc8e7e0cbf60a2cc6a3cae271f2bdb350bad5a6e21b6f28b344625 |

## 用例结果

| 用例 | 状态 | 秒 |
| --- | --- | --- |
| test_00_broken_top_k_loses_current_evidence | passed | 0.018024 |
| test_01_current_answer_has_supported_location | passed | 0.007581 |
| test_02_legitimate_b_reader_is_not_globally_blocked | passed | 0.007132 |
| test_03_client_tenant_override_does_not_change_identity | passed | 0.01519 |
| test_04_unknown_session_and_constructed_principal_are_not_credentials | passed | 0.012817 |
| test_05_read_permission_is_required_even_for_own_tenant | passed | 0.007608 |
| test_06_injection_reaches_context_but_cannot_authorize_export | passed | 0.016931 |
| test_07_direct_export_bypassing_model_is_denied | passed | 0.009995 |
| test_08_authorized_export_has_a_real_local_effect | passed | 0.011129 |
| test_09_export_permission_does_not_grant_other_tenant_resources | passed | 0.008208 |
| test_10_tool_arguments_cannot_inject_a_session_or_permissions | passed | 0.006458 |
| test_11_missing_current_version_does_not_reuse_old_value | passed | 0.008172 |
| test_12_future_version_does_not_become_current_evidence | passed | 0.012595 |
| test_13_date_boundaries_and_historical_queries | passed | 0.005875 |
| test_14_more_b_candidates_do_not_hide_a_current_document | passed | 0.033509 |
| test_15_conflicting_applicable_evidence_is_not_a_certain_answer | passed | 0.012371 |
| test_16_duplicate_document_id_cannot_silently_replace_evidence | passed | 0.009346 |
| test_17_invalid_dates_and_limits_fail_before_body_reads | passed | 0.007591 |
| test_18_unusable_evidence_does_not_invent_a_fact | passed | 0.012142 |
| test_19_body_tenant_claim_cannot_override_stored_ownership | passed | 0.006255 |
| test_20_unauthorized_body_is_absent_from_context_reply_and_audit | passed | 0.013423 |

## test_00_broken_top_k_loses_current_evidence

Negative control: truncating before filtering falsely loses A-v2.

预期：
```json
{
  "broken_status": "no_current_evidence",
  "fixed_value": 300,
  "initial_ranking": [
    "B-v2",
    "A-v1",
    "A-v2"
  ]
}
```
实际正文读取：["A-v2"]。
实际导出台账：0 条。完整原因与结果见原始记录。

## test_01_current_answer_has_supported_location

A gets 300 with a quote actually present in the cited paragraph.

预期：
```json
{
  "value": 300,
  "citation": {
    "doc_id": "A-v2",
    "paragraph": "p1"
  },
  "no_b_body": true
}
```
实际正文读取：["A-v2"]。
实际导出台账：0 条。完整原因与结果见原始记录。

## test_02_legitimate_b_reader_is_not_globally_blocked

B's real fixture session still receives B's authorized evidence.

预期：
```json
{
  "value": 5000,
  "citation": "B-v2",
  "body_reads": [
    "B-v2"
  ]
}
```
实际正文读取：["B-v2"]。
实际导出台账：0 条。完整原因与结果见原始记录。

## test_03_client_tenant_override_does_not_change_identity

An A session with requested_tenant=B is rejected before body access.

预期：
```json
{
  "reason": "tenant_override_rejected",
  "body_reads": [],
  "export_effects": 0
}
```
实际正文读取：[]。
实际导出台账：0 条。完整原因与结果见原始记录。

## test_04_unknown_session_and_constructed_principal_are_not_credentials

Neither arbitrary session text nor a forged Principal grants access.

预期：
```json
{
  "reason": "unknown_session",
  "body_reads": []
}
```
实际正文读取：[]。
实际导出台账：0 条。完整原因与结果见原始记录。

## test_05_read_permission_is_required_even_for_own_tenant

Knowing the tenant does not grant knowledge:read.

预期：
```json
{
  "reason": "missing_permission",
  "body_reads": []
}
```
实际正文读取：[]。
实际导出台账：0 条。完整原因与结果见原始记录。

## test_06_injection_reaches_context_but_cannot_authorize_export

Authorized malicious text reaches the stub; a scripted call is denied.

预期：
```json
{
  "injection_in_context": true,
  "export_effects": 0,
  "reason": "missing_permission"
}
```
实际正文读取：["A-v2"]。
实际导出台账：0 条。完整原因与结果见原始记录。

## test_07_direct_export_bypassing_model_is_denied

Direct invocation rejects a read-only user before any export effect.

预期：
```json
{
  "reason": "missing_permission",
  "export_effects": 0,
  "body_reads": []
}
```
实际正文读取：[]。
实际导出台账：0 条。完整原因与结果见原始记录。

## test_08_authorized_export_has_a_real_local_effect

Positive control: export permission plus ownership records one export.

预期：
```json
{
  "export_effects": 1,
  "tenant": "A",
  "doc_id": "A-v2"
}
```
实际正文读取：["A-v2"]。
实际导出台账：1 条。完整原因与结果见原始记录。

## test_09_export_permission_does_not_grant_other_tenant_resources

An A exporter cannot export B by supplying its document id.

预期：
```json
{
  "reason": "resource_not_owned_or_missing",
  "export_effects": 0,
  "body_reads": []
}
```
实际正文读取：[]。
实际导出台账：0 条。完整原因与结果见原始记录。

## test_10_tool_arguments_cannot_inject_a_session_or_permissions

Tool arguments never replace the separately bound server session.

预期：
```json
{
  "invalid_request": true,
  "export_effects": 0,
  "body_reads": []
}
```
实际正文读取：[]。
实际导出台账：0 条。完整原因与结果见原始记录。

## test_11_missing_current_version_does_not_reuse_old_value

Deleting A-v2 yields unknown, not the historical 500.

预期：
```json
{
  "status": "no_current_evidence",
  "value": null,
  "citations": []
}
```
实际正文读取：[]。
实际导出台账：0 条。完整原因与结果见原始记录。

## test_12_future_version_does_not_become_current_evidence

Moving A-v2 into the future leaves the queried date without evidence.

预期：
```json
{
  "status": "no_current_evidence",
  "value": null
}
```
实际正文读取：[]。
实际导出台账：0 条。完整原因与结果见原始记录。

## test_13_date_boundaries_and_historical_queries

Inclusive date boundaries select v1 on Sep 30 and v2 on Oct 1.

预期：
```json
{
  "values": {
    "2026-09-30": 500,
    "2026-10-01": 300,
    "2026-10-11": 300
  }
}
```
实际正文读取：["A-v1", "A-v2", "A-v2"]。
实际导出台账：0 条。完整原因与结果见原始记录。

## test_14_more_b_candidates_do_not_hide_a_current_document

Twenty high-ranked B distractors cannot consume A's top-k capacity.

预期：
```json
{
  "value": 300,
  "selected_ids": [
    "A-v2"
  ],
  "body_reads": [
    "A-v2"
  ]
}
```
实际正文读取：["A-v2"]。
实际导出台账：0 条。完整原因与结果见原始记录。

## test_15_conflicting_applicable_evidence_is_not_a_certain_answer

Two applicable conflicting rules produce uncertainty and both citations.

预期：
```json
{
  "status": "conflicting_evidence",
  "value": null,
  "citations": 2
}
```
实际正文读取：["A-v2", "A-conflict"]。
实际导出台账：0 条。完整原因与结果见原始记录。

## test_16_duplicate_document_id_cannot_silently_replace_evidence

A duplicate primary key fails rather than silently changing a citation.

预期：
```json
{
  "duplicate_rejected": true,
  "current_value": 300
}
```
实际正文读取：["A-v2"]。
实际导出台账：0 条。完整原因与结果见原始记录。

## test_17_invalid_dates_and_limits_fail_before_body_reads

Invalid dates and top-k values cannot silently change query semantics.

预期：
```json
{
  "invalid_requests_rejected": 7,
  "body_reads": []
}
```
实际正文读取：[]。
实际导出台账：0 条。完整原因与结果见原始记录。

## test_18_unusable_evidence_does_not_invent_a_fact

The deterministic stub admits it cannot parse an unsupported document.

预期：
```json
{
  "status": "unusable_evidence",
  "value": null,
  "citations": []
}
```
实际正文读取：["A-v2"]。
实际导出台账：0 条。完整原因与结果见原始记录。

## test_19_body_tenant_claim_cannot_override_stored_ownership

B content claiming tenant A remains excluded from A's model input.

预期：
```json
{
  "value": 300,
  "no_b_body": true
}
```
实际正文读取：["A-v2"]。
实际导出台账：0 条。完整原因与结果见原始记录。

## test_20_unauthorized_body_is_absent_from_context_reply_and_audit

No B plaintext appears in the A request's context, reply or audit.

预期：
```json
{
  "no_unauthorized_plaintext": true,
  "export_effects": 0
}
```
实际正文读取：["A-v2"]。
实际导出台账：0 条。完整原因与结果见原始记录。
