## Task Decomposition
SPEC: SPEC-SETTINGS-001 (scope: Phase 0 + Phase 1 only)

| Task ID | Description | Requirement | Dependencies | Planned Files | Status |
|---------|-------------|-------------|---------------|--------|--------|
| T-001 | `build_config_metadata()` — parse env.txt/config.txt, attach known-key metadata (type/category/default/range/description), pass through unknown keys, discover prompts/ files | SPEC §4 | - | rag_core.py | pending |
| T-002 | Unit tests for metadata parsing (known key, unknown key, missing file, prompt discovery) | Testing Strategy | T-001 | tests/conftest.py, tests/test_rag_core_settings.py | pending |
| T-003 | `SettingsFileLoadWorker` (QThread) — async file content load, error signal | F-SETTINGS-2, N-SETTINGS-1 | - | workers/settings_worker.py | pending |
| T-004 | Unit tests for SettingsFileLoadWorker | Testing Strategy | T-003 | tests/test_settings_worker.py | pending |
| T-005 | `SettingsTab(QWidget)` — file list (existing/missing distinction) + read-only content viewer (line numbers, monospace, path+encoding label) | F-SETTINGS-1, F-SETTINGS-2 | T-001, T-003 | ui/settings_tab.py | pending |
| T-006 | Wire SettingsTab into MainWindow tab bar (beside graph_tab) | UI layout note | T-005 | ui/main_window.py | pending |
| T-007 | Manual verification (tab appears, file selection loads content, missing files grayed out) | Manual Testing Checklist | T-006 | - | pending |

Out of scope this run: F-SETTINGS-3 through F-SETTINGS-12 (Q&A chat, editing, diff, backups, rebuild triggers, file monitoring, category filtering, reset-to-defaults, LLM prompt modification) — deferred to a future `/moai run SPEC-SETTINGS-001` invocation.
