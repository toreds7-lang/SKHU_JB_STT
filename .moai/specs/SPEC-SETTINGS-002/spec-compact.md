# SPEC-SETTINGS-002 (compact)

- **id**: SPEC-SETTINGS-002 · **status**: draft · **priority**: medium · **issue**: 0
- **title**: Settings Tab UX Fixes — Enter-to-Send, Clear History, Tab Reorder
- **scope**: Three narrow follow-up UX fixes to the SPEC-SETTINGS-001 Settings tab. No new deps, no HTML/JS or cache changes.

## Requirements (EARS)

- **R1 Enter-to-send** (`ui/settings_tab.py` `qa_input`)
  - REQ-001 (event): Enter (no Shift) → submit as Q&A (like Ask) + clear input.
  - REQ-002 (event): Shift+Enter → insert newline, do not submit.
  - REQ-003 (unwanted): empty/whitespace + Enter → no submit, input unchanged.
  - REQ-004 (ubiquitous): matches ChatTab/NotebookTab/WikiTab Enter/Shift+Enter convention.
- **R2 Clear button** (Settings Q&A chat panel; single continuous thread)
  - REQ-005 (ubiquitous): Clear control beside Ask/Preview/Edit.
  - REQ-006 (event): Clear → empty visible pane (`clearChat()` JS, already exists).
  - REQ-007 (event): Clear → permanently delete `settings_chat.jsonl`
    (`SettingsChatCache.clear()`, already exists) — destructive, NotebookTab precedent.
  - REQ-008 (ubiquitous): wipes entire thread regardless of selected file.
  - REQ-009 (unwanted): no history file → idempotent no-op, no error.
- **R3 Settings tab last** (`ui/main_window.py` `_init_ui` addTab order)
  - REQ-010: order → notebook,chat,docs(hidden),graph(hidden),dir,cached,wiki,**settings(last)**.
  - REQ-011: docs(2)/graph(3) stay hidden — `setTabVisible(2/3,False)` unchanged.
  - REQ-012 (state): tab-switch unsaved-edit guard still works (`indexOf(settings_tab)`).

## Files to modify

- `ui/settings_tab.py` — Enter-to-send key handler + `returnPressed`→`_on_ask_clicked`; add Clear button + `_on_clear_qa_clicked` (JS `clearChat()` + `SettingsChatCache.clear()`).
- `ui/main_window.py` — move `addTab(self.settings_tab, …)` to be last (after wiki).
- `tests/test_settings_tab.py` — new tests for Enter/Shift+Enter/empty + Clear (empties pane, deletes jsonl, idempotent).
- `tests/test_main_window_wiring.py` — rewrite `test_settings_tab_added_after_graph_and_before_dir` for new order; keep `test_docs_and_graph_tab_visibility_indices_preserved`.
- **No change**: `resources/settings_chat.html` (`clearChat()` exists), `cache_store.py` (`SettingsChatCache.clear()` exists).

## Exclusions

No auto-expand height; no Up/Down history recall; no per-file Clear scoping; no Clear confirmation dialog (matches NotebookTab); no new cache method; no HTML/JS change; no GitHub issue; no new git branch (manual git → commit to `main`, no push).

## DoD

All ACs met; new R1/R2 tests + updated R3 wiring test; `pytest tests/ -q` green under `QT_QPA_PLATFORM=offscreen`; committed directly to `main`.
