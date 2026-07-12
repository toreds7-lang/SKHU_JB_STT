## Task Decomposition
SPEC: SPEC-SETTINGS-003

| Task ID | Description | Requirement | Dependencies | Planned Files | Status |
|---------|-------------|-------------|--------------|---------------|--------|
| T1 | `_SETTINGS_REFERENCE_PATH` constant + `load_settings_reference()` (sync, safe on missing) | REQ-013, REQ-011, NFR-3 | - | rag_core.py, tests/test_rag_core_settings.py | pending |
| T2 | `find_reference_section(reference_text, key_or_file)` section extractor | REQ-006 | T1 | rag_core.py, tests/test_rag_core_settings.py | pending |
| T3 | `build_settings_qa_prompt(...)` optional `reference_section` arg (backward-compat) + `build_settings_qa_grounded_prompt(question, reference_text)` | REQ-006, REQ-007, REQ-008 | T1, T2 | rag_core.py, tests/test_rag_core_settings.py | pending |
| T4 | Author `## PARAM:` entries for 24 params (6 env + 18 config), grep-verified consumers | REQ-001, REQ-002, REQ-004, REQ-005 | T1-T3 (structure) | settings_reference.txt, tests/test_rag_core_settings.py | pending |
| T5 | Author `## FILE:` entries for 9 CONFIG_FILES, real loader citations | REQ-001, REQ-003, REQ-004, REQ-005, NFR-5 | T4 | settings_reference.txt, tests/test_rag_core_settings.py | pending |
| T6 | settings_tab matched branch: inject reference section into prompt | REQ-006, REQ-007 | T2, T3 | ui/settings_tab.py, tests/test_settings_tab.py | pending |
| T7 | settings_tab unmatched branch: replace hardcoded rejection with grounded `qa_requested` route; invert `test_ask_unknown_key_does_not_emit_qa_requested`; add doc-absent fallback test + `_SETTINGS_REFERENCE_PATH` fixture isolation | REQ-008, REQ-009, REQ-010, REQ-011 | T3 | ui/settings_tab.py, tests/test_settings_tab.py, tests/conftest.py | pending |
| T8 | Full suite green (QT_QPA_PLATFORM=offscreen), TRUST 5 review, exclusion compliance check, commit to main | REQ-012, DoD | T1-T7 | (verification only) | pending |

Planned files (union): `settings_reference.txt` (new), `rag_core.py`, `ui/settings_tab.py`, `tests/test_rag_core_settings.py`, `tests/test_settings_tab.py`, `tests/conftest.py`.
No change: `workers/settings_worker.py`, `resources/settings_chat.html`, `cache_store.py`, `ui/main_window.py`.

Corrections carried from Phase 1 (manager-strategy) into T4/T5: do not cite `app.py` as a FORCE_WORKERS/STT_MODEL consumer (unconfirmed); `env_loader.py` is a generic bulk loader, not a per-key consumer — cite the actual `os.getenv(...)` call sites instead.
