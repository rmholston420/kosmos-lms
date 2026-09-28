# Baseline reproduction — 2026-09-28 (main@7e7b1e3)

Clean Python 3.12.13 venv, `pip install -e ".[dev,ui]"`, no Valkey/Postgres/Ollama running. Produced by the Perplexity Computer audit that authored `../TEKTOS_HERMES_IMPLEMENTATION_PLAN.md` (see its Appendix E). Kept short on purpose; regenerate with the commands shown.

## pytest (default testpaths: ports adapters kernel plugins ops)

```
$ pytest -q -p no:cacheprovider
Result: 1788 passed / 2 failed / 21 skipped (1811 collected)

FAILED lines:
FAILED adapters/relational_memory/postgres/test_contract.py::test_is_healthy_without_pool
FAILED plugins/tektos/tests/test_stage_3_12_exit_gate.py::test_tektos_refactors_real_kosmos_file_end_to_end_passes_ruff_bandit_pytest_build_sequence_3_12_dod
```

## pytest tests/ (what CI runs)

```
$ pytest -q -p no:cacheprovider tests/ --ignore=tests/kernel/test_adr141_s133_axioms_routes.py
WARNING  kernel.app:app.py:2057 Vision endpoint not available at http://127.0.0.1:8094/v1: All connection attempts failed

FAILED lines:
FAILED tests/kernel/test_adr141_s1312_voice_routes.py::test_voice_state_envelope
FAILED tests/kernel/test_adr141_s1312_voice_routes.py::test_voice_stt_real_whisper
FAILED tests/kernel/test_adr141_s1312_voice_routes.py::test_voice_tts_real_edge
FAILED tests/kernel/test_adr141_s137_metabolism_routes.py::test_metabolism_full_assessment
FAILED tests/kernel/test_adr141_t7_embedder_surface.py::test_embed_roundtrip_live
FAILED tests/kernel/test_adr141_t7_embedder_surface.py::test_embed_and_embed_meta_agree
FAILED tests/kernel/test_adr141_t8b3_llm_probe.py::test_probe_shape - assert ...
FAILED tests/kernel/test_stage_14_12_tektos_plan_surface.py::test_detail_returns_record
FAILED tests/kernel/test_stage_14_12_tektos_plan_surface.py::test_approve_then_execute_returns_result
FAILED tests/kernel/test_stage_14_12_tektos_plan_surface.py::test_diff_returns_unified_diff
FAILED tests/kernel/test_stage_14_12_tektos_plan_surface.py::test_execute_strips_tektos_plan_prefix
FAILED tests/kernel/test_stage_6_5_1_2_phrouros_and_seed.py::test_phrouros_loop_anomaly_fires
FAILED tests/kernel/test_stage_6_5_4_websocket_event_bus_bridge.py::test_ws_forwards_event_on_subscribed_type
FAILED tests/kernel/test_stage_6_5_4_websocket_event_bus_bridge.py::test_ws_does_not_forward_unsubscribed_type
FAILED tests/kernel/test_stage_6_5_4_websocket_event_bus_bridge.py::test_ws_forwards_multiple_types
FAILED tests/kernel/test_stage_6_5_5_approval_resolve_endpoints.py::test_approve_transitions_to_approved
FAILED tests/kernel/test_stage_6_5_5_approval_resolve_endpoints.py::test_approve_with_modifications_transitions_to_modified
FAILED tests/kernel/test_stage_6_5_5_approval_resolve_endpoints.py::test_reject_transitions_to_rejected
FAILED tests/kernel/test_stage_6_5_5_approval_resolve_endpoints.py::test_reject_without_reason_returns_400_from_kernel
FAILED tests/kernel/test_stage_6_5_5_approval_resolve_endpoints.py::test_reject_with_empty_reason_returns_400
FAILED tests/kernel/test_stage_6_5_5_approval_resolve_endpoints.py::test_approve_with_bad_json_returns_400
FAILED tests/kernel/test_stage_6_5_5_approval_resolve_endpoints.py::test_approve_with_non_object_body_returns_400
FAILED tests/kernel/test_stage_6_5_5_approval_resolve_endpoints.py::test_approve_with_non_string_reason_returns_400
FAILED tests/kernel/test_stage_6_5_5_approval_resolve_endpoints.py::test_double_resolve_returns_409
FAILED tests/kernel/test_stage_8_0_relational_memory_wiring.py::test_postgres_with_dsn_degrades_gracefully_when_pool_unavailable

Result: 850 passed / 25 failed / 3 skipped. 17 failures = Valkey ConnectionRefusedError (127.0.0.1:6379; 34 tracebacks); 8 failures = unmarked live-service tests (Ollama :11434, vision :8094, whisper/edge-tts, Postgres).
```

## bandit 1.9.4

```
$ bandit -q -r ports adapters kernel plugins -x tests,vendor -f json
total 209 {'LOW': 146, 'MEDIUM': 60, 'HIGH': 3}
top test ids: [('B608', 42), ('B110', 40), ('B603', 39), ('B607', 28), ('B404', 20), ('B108', 15), ('B105', 11), ('B112', 5)]
HIGH: [('adapters/sandbox/tektos/vendor/sandbox_exec_donor.py', 160, 'B602'), ('plugins/tektos/tools/sandbox_provider.py', 139, 'B602'), ('plugins/tektos/tools/sandbox_provider.py', 158, 'B602')]
```

## ruff 0.16.9 / mypy 2.3.1 / wheel / audits

- `ruff check .` → 1,114 findings (753 fixable; UP017 255, I001 173, F401 123 …); CI scope (`ports kernel tests scripts`) → 369; `ruff format --check`: 403 files repo-wide / 118 in CI scope.
- `mypy ports kernel` → 86 errors in 28 files.
- `python -m build --wheel` → 52 packages in the wheel; 68 of 120 packages missing (incl. `kernel`).
- `pip-audit` → diskcache 5.6.3 PYSEC-2026-2447. `npm audit` (ui/) → next 16.2.11 critical (fix 16.3.6), postcss high, sharp high. `tsc --noEmit` → 1 error (`ui/tests/03-tektos-plan-workflow.spec.ts(20,61)`).
- GitHub Actions: last 12 runs failed; at 7e7b1e3 lint ✗, typecheck ✗, frontend-lint ✗ (no `lint` script), e2e ✗, python-tests skipped, summary ✓.
