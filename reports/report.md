# Return ACH Test Engine Report

**Overall Status:** ✅ PASSED  
**Target URL:** `http://localhost:8000`  
**Execution Mode:** `mock`  
**Pass Rate:** 100.0%  
**Total Duration:** 1527.46 ms  

## Summary Metrics

| Metric | Value |
|---|---|
| Total Tests | 74 |
| Passed | 74 |
| Failed | 0 |
| Errors | 0 |
| Skipped | 0 |
| Pass Rate | 100.0% |

## Category Breakdown

| Category | Total | Passed | Failed/Errors | Pass Rate |
|---|---|---|---|---|
| `health` | 1 | 1 | 0 | 100.0% |
| `schema` | 39 | 39 | 0 | 100.0% |
| `ach_domain` | 18 | 18 | 0 | 100.0% |
| `error_handling` | 6 | 6 | 0 | 100.0% |
| `security` | 6 | 6 | 0 | 100.0% |
| `connector` | 1 | 1 | 0 | 100.0% |
| `lifecycle` | 3 | 3 | 0 | 100.0% |

## Test Results Detail

| Status | Test ID | Category | HTTP | Duration | Description |
|---|---|---|---|---|---|
| ✅ PASS | `HEALTH_CHECK_ROOT` | health | 200 | 118.3ms | System Health & Availability |
| ✅ PASS | `SCHEMA_POST_API_V1_TRIGGERS_TEMPLATE_METHOD_NOT_ALLOWED` | schema | 405 | 12.7ms | Invalid HTTP Method DELETE on /api/v1/triggers/{template} |
| ✅ PASS | `SCHEMA_POST_API_V1_CASES_CASE_ID_COMMENTS_VALID` | schema | 404 | 76.2ms | Valid Schema Request - POST /api/v1/cases/{case_id}/comments |
| ✅ PASS | `SCHEMA_POST_API_V1_CASES_CASE_ID_COMMENTS_MISSING_BODY` | schema | 422 | 16.7ms | Missing Required Field 'body' |
| ✅ PASS | `SCHEMA_POST_API_V1_CASES_CASE_ID_COMMENTS_INVALID_TYPE_BODY` | schema | 422 | 18.3ms | Invalid Type for Field 'body' |
| ✅ PASS | `SCHEMA_POST_API_V1_CASES_CASE_ID_COMMENTS_BOUNDARY_BODY_EMPTY_STRING` | schema | 422 | 9.1ms | Boundary Violation: body (EMPTY_STRING) |
| ✅ PASS | `SCHEMA_POST_API_V1_CASES_CASE_ID_COMMENTS_BOUNDARY_BODY_EXCEEDS_MAX_LENGTH` | schema | 422 | 6.5ms | Boundary Violation: body (EXCEEDS_MAX_LENGTH) |
| ✅ PASS | `SCHEMA_POST_API_V1_CASES_CASE_ID_COMMENTS_STRICT_EXTRA_FIELD` | schema | 422 | 6.6ms | Strict Extra Field Rejection - POST /api/v1/cases/{case_id}/comments |
| ✅ PASS | `SCHEMA_POST_API_V1_CASES_CASE_ID_COMMENTS_METHOD_NOT_ALLOWED` | schema | 405 | 5.9ms | Invalid HTTP Method DELETE on /api/v1/cases/{case_id}/comments |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_DECISION_VALID` | schema | 404 | 90.9ms | Valid Schema Request - POST /api/v1/tasks/{task_id}/decision |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_DECISION_MISSING_ACTION` | schema | 422 | 46.4ms | Missing Required Field 'action' |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_DECISION_INVALID_TYPE_ACTION` | schema | 422 | 46.4ms | Invalid Type for Field 'action' |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_DECISION_INVALID_TYPE_PROPOSAL_HASH` | schema | 422 | 27.1ms | Invalid Type for Field 'proposal_hash' |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_DECISION_INVALID_TYPE_NOTE` | schema | 422 | 26.7ms | Invalid Type for Field 'note' |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_DECISION_STRICT_EXTRA_FIELD` | schema | 422 | 26.7ms | Strict Extra Field Rejection - POST /api/v1/tasks/{task_id}/decision |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_DECISION_METHOD_NOT_ALLOWED` | schema | 405 | 3.6ms | Invalid HTTP Method DELETE on /api/v1/tasks/{task_id}/decision |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_PREVIEW_VALID` | schema | 404 | 14.6ms | Valid Schema Request - POST /api/v1/tasks/{task_id}/preview |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_PREVIEW_MISSING_MODIFIED_PROPOSAL` | schema | 422 | 4.0ms | Missing Required Field 'modified_proposal' |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_PREVIEW_INVALID_TYPE_MODIFIED_PROPOSAL` | schema | 422 | 3.9ms | Invalid Type for Field 'modified_proposal' |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_PREVIEW_STRICT_EXTRA_FIELD` | schema | 422 | 2.1ms | Strict Extra Field Rejection - POST /api/v1/tasks/{task_id}/preview |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_PREVIEW_METHOD_NOT_ALLOWED` | schema | 405 | 2.1ms | Invalid HTTP Method DELETE on /api/v1/tasks/{task_id}/preview |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_VIEWS_VALID` | schema | 404 | 43.0ms | Valid Schema Request - POST /api/v1/tasks/{task_id}/views |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_VIEWS_MISSING_SESSION_ID` | schema | 422 | 3.2ms | Missing Required Field 'session_id' |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_VIEWS_MISSING_EVENT` | schema | 422 | 26.8ms | Missing Required Field 'event' |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_VIEWS_INVALID_TYPE_SESSION_ID` | schema | 422 | 26.9ms | Invalid Type for Field 'session_id' |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_VIEWS_INVALID_TYPE_EVENT` | schema | 422 | 26.3ms | Invalid Type for Field 'event' |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_VIEWS_BOUNDARY_SESSION_ID_EMPTY_STRING` | schema | 422 | 26.8ms | Boundary Violation: session_id (EMPTY_STRING) |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_VIEWS_BOUNDARY_SESSION_ID_EXCEEDS_MAX_LENGTH` | schema | 422 | 4.8ms | Boundary Violation: session_id (EXCEEDS_MAX_LENGTH) |
| ✅ PASS | `SCHEMA_POST_API_V1_TASKS_TASK_ID_VIEWS_METHOD_NOT_ALLOWED` | schema | 405 | 4.8ms | Invalid HTTP Method DELETE on /api/v1/tasks/{task_id}/views |
| ✅ PASS | `SCHEMA_POST_API_V1_POLICIES_POLICY_HASH_APPROVAL_VALID` | schema | 409 | 11.0ms | Valid Schema Request - POST /api/v1/policies/{policy_hash}/approval |
| ✅ PASS | `SCHEMA_POST_API_V1_POLICIES_POLICY_HASH_APPROVAL_INVALID_TYPE_NOTE` | schema | 422 | 4.7ms | Invalid Type for Field 'note' |
| ✅ PASS | `SCHEMA_POST_API_V1_POLICIES_POLICY_HASH_APPROVAL_BOUNDARY_NOTE_EXCEEDS_MAX_LENGTH` | schema | 422 | 3.9ms | Boundary Violation: note (EXCEEDS_MAX_LENGTH) |
| ✅ PASS | `SCHEMA_POST_API_V1_POLICIES_POLICY_HASH_APPROVAL_STRICT_EXTRA_FIELD` | schema | 422 | 3.4ms | Strict Extra Field Rejection - POST /api/v1/policies/{policy_hash}/approval |
| ✅ PASS | `SCHEMA_POST_API_V1_POLICIES_POLICY_HASH_APPROVAL_METHOD_NOT_ALLOWED` | schema | 405 | 4.0ms | Invalid HTTP Method DELETE on /api/v1/policies/{policy_hash}/approval |
| ✅ PASS | `SCHEMA_PUT_API_V1_CONNECTORS_SYSTEM_VALID` | schema | 200 | 72.5ms | Valid Schema Request - PUT /api/v1/connectors/{system} |
| ✅ PASS | `SCHEMA_PUT_API_V1_CONNECTORS_SYSTEM_MISSING_PROVIDER` | schema | 422 | 3.8ms | Missing Required Field 'provider' |
| ✅ PASS | `SCHEMA_PUT_API_V1_CONNECTORS_SYSTEM_INVALID_TYPE_PROVIDER` | schema | 422 | 4.1ms | Invalid Type for Field 'provider' |
| ✅ PASS | `SCHEMA_PUT_API_V1_CONNECTORS_SYSTEM_BOUNDARY_PROVIDER_EMPTY_STRING` | schema | 422 | 4.3ms | Boundary Violation: provider (EMPTY_STRING) |
| ✅ PASS | `SCHEMA_PUT_API_V1_CONNECTORS_SYSTEM_BOUNDARY_PROVIDER_EXCEEDS_MAX_LENGTH` | schema | 422 | 4.1ms | Boundary Violation: provider (EXCEEDS_MAX_LENGTH) |
| ✅ PASS | `SCHEMA_PUT_API_V1_CONNECTORS_SYSTEM_METHOD_NOT_ALLOWED` | schema | 405 | 4.1ms | Invalid HTTP Method POST on /api/v1/connectors/{system} |
| ✅ PASS | `ACH_REASON_CODE_R01` | ach_domain | 200 | 60.3ms | ACH Return Reason Code R01 (Insufficient Funds (NSF)) |
| ✅ PASS | `ACH_REASON_CODE_R02` | ach_domain | 200 | 56.9ms | ACH Return Reason Code R02 (Account Closed) |
| ✅ PASS | `ACH_REASON_CODE_R03` | ach_domain | 200 | 60.8ms | ACH Return Reason Code R03 (No Account / Unable to Locate Account) |
| ✅ PASS | `ACH_REASON_CODE_R04` | ach_domain | 200 | 52.1ms | ACH Return Reason Code R04 (Invalid Account Number Structure) |
| ✅ PASS | `ACH_REASON_CODE_R07` | ach_domain | 200 | 23.0ms | ACH Return Reason Code R07 (Authorization Revoked by Customer) |
| ✅ PASS | `ACH_REASON_CODE_R08` | ach_domain | 200 | 22.2ms | ACH Return Reason Code R08 (Payment Stopped) |
| ✅ PASS | `ACH_REASON_CODE_R10` | ach_domain | 200 | 22.6ms | ACH Return Reason Code R10 (Customer Advises Unauthorized / Not Authorized) |
| ✅ PASS | `ACH_REASON_CODE_R16` | ach_domain | 200 | 22.8ms | ACH Return Reason Code R16 (Account Frozen / Legal Block) |
| ✅ PASS | `ACH_REASON_CODE_R20` | ach_domain | 200 | 21.2ms | ACH Return Reason Code R20 (Non-Transaction Account) |
| ✅ PASS | `ACH_INVALID_REASON_CODE_R1` | ach_domain | 422 | 11.8ms | Invalid Reason Code Shape: R1 |
| ✅ PASS | `ACH_INVALID_REASON_CODE_R100` | ach_domain | 422 | 11.1ms | Invalid Reason Code Shape: R100 |
| ✅ PASS | `ACH_INVALID_REASON_CODE_INVALID` | ach_domain | 422 | 12.2ms | Invalid Reason Code Shape: INVALID |
| ✅ PASS | `ACH_INVALID_REASON_CODE_99R` | ach_domain | 422 | 10.6ms | Invalid Reason Code Shape: 99R |
| ✅ PASS | `ACH_TRACE_TOO_SHORT` | ach_domain | 422 | 16.0ms | Trace Number Below Minimum Length (4 < 6 chars) |
| ✅ PASS | `ACH_TRACE_INVALID_SYMBOLS` | ach_domain | 422 | 25.8ms | Trace Number With Disallowed Symbols |
| ✅ PASS | `ACH_SETTLEMENT_DATE_TOO_OLD` | ach_domain | 422 | 8.9ms | Implausibly Old Settlement Date (< 2000) |
| ✅ PASS | `ERR_MALFORMED_JSON_POST_API_V1_TRIGGERS_TEMPLATE` | error_handling | 422 | 11.3ms | Malformed JSON Body on POST /api/v1/triggers/{template} |
| ✅ PASS | `ERR_MALFORMED_JSON_POST_API_V1_CASES_CASE_ID_COMMENTS` | error_handling | 422 | 10.9ms | Malformed JSON Body on POST /api/v1/cases/{case_id}/comments |
| ✅ PASS | `SEC_MISSING_USER_ID_API_V1_CASES_CASE_ID_COMMENTS` | security | 403 | 10.0ms | Missing X-User-Id on POST /api/v1/cases/{case_id}/comments |
| ✅ PASS | `SEC_MISSING_USER_ID_API_V1_TASKS_TASK_ID_DECISION` | security | 403 | 13.0ms | Missing X-User-Id on POST /api/v1/tasks/{task_id}/decision |
| ✅ PASS | `SEC_MISSING_USER_ID_API_V1_TASKS_TASK_ID_CLAIM` | security | 403 | 13.4ms | Missing X-User-Id on POST /api/v1/tasks/{task_id}/claim |
| ✅ PASS | `SEC_MISSING_USER_ID_API_V1_TASKS_TASK_ID_PREVIEW` | security | 404 | 9.5ms | Missing X-User-Id on POST /api/v1/tasks/{task_id}/preview |
| ✅ PASS | `SEC_MISSING_USER_ID_API_V1_TASKS_TASK_ID_VIEWS` | security | 403 | 8.7ms | Missing X-User-Id on POST /api/v1/tasks/{task_id}/views |
| ✅ PASS | `SEC_MISSING_USER_ID_API_V1_POLICIES_POLICY_HASH_APPROVAL` | security | 403 | 7.0ms | Missing X-User-Id on POST /api/v1/policies/{policy_hash}/approval |
| ✅ PASS | `ERR_NOT_FOUND_API_V1_CASES_00000000_0000_0000_0000_000000000000` | error_handling | 404 | 18.3ms | 404 Not Found - Case Not Found |
| ✅ PASS | `ERR_NOT_FOUND_API_V1_TASKS_00000000_0000_0000_0000_000000000000` | error_handling | 404 | 12.9ms | 404 Not Found - Task Not Found |
| ✅ PASS | `ERR_NOT_FOUND_API_V1_TRIGGERS_NON_EXISTENT_TEMPLATE_XYZ` | error_handling | 404 | 4.9ms | 404 Not Found - Template Not Found |
| ✅ PASS | `ERR_CONFLICT_STALE_HASH` | error_handling | 404 | 16.2ms | 409 Conflict: Decision with Stale Proposal Hash |
| ✅ PASS | `CONN_LIST_REGISTERED_CONNECTORS` | connector | 200 | 16.9ms | Connector Registry Availability |
| ✅ PASS | `ACH_DEDUPE_INITIAL_TRIGGER` | ach_domain | 200 | 8.1ms | Deduplication: Initial Trigger Submission |
| ✅ PASS | `ACH_LIFECYCLE_STEP1_TRIGGER` | lifecycle | 200 | 9.4ms | Lifecycle Step 1: Trigger Case Creation |
| ✅ PASS | `ACH_DEDUPE_REPLAY_TRIGGER` | ach_domain | 200 | 9.4ms | Deduplication: Duplicate Replay Submission |
| ✅ PASS | `ACH_LIFECYCLE_STEP2_CASE_STATE` | lifecycle | 200 | 49.4ms | Lifecycle Step 2: Verify Created Case State |
| ✅ PASS | `ACH_LIFECYCLE_STEP3_QUERY_TASKS` | lifecycle | 200 | 12.4ms | Lifecycle Step 3: Query Review Tasks for Case |