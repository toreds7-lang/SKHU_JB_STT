# Acceptance Criteria — SPEC-SETTINGS-002

Given-When-Then scenarios for the three Settings-tab UX fixes, one per REQ-XXX
in `spec.md`. All scenarios are observable via `pytest` + `pytest-qt`
(widget-level for REQ-001–REQ-009, source-inspection for REQ-010–REQ-012,
matching the existing test conventions in `tests/`).

---

## R1 — Enter-to-Send in the Settings Q&A Input

### AC-REQ-001 — Enter submits the question
- **Given** the Settings tab is open and the user has typed a non-empty question
  (e.g. `"VECTOR_K가 뭐야?"`) into the Q&A input (`qa_input`)
- **When** the user presses Enter without holding Shift
- **Then** the question is submitted exactly as if **Ask** had been clicked (the
  same `_on_ask_clicked` path runs: a user message is appended to the chat
  display and the input field is cleared)
- **And** no literal newline is inserted into the (now-cleared) input.

### AC-REQ-002 — Shift+Enter inserts a newline
- **Given** the Settings tab is open and the user has typed text into `qa_input`
- **When** the user presses Shift+Enter
- **Then** a newline character is inserted at the cursor in `qa_input`
- **And** no question is submitted (no user message appended, input not cleared).

### AC-REQ-003 — Empty Enter is a no-op
- **Given** the `qa_input` is empty or contains only whitespace
- **When** the user presses Enter without Shift
- **Then** no question is submitted and the input remains unchanged (relies on
  the existing empty-guard in `_on_ask_clicked`).

### AC-REQ-004 — Consistency with other chat inputs
- **Given** the app's other chat inputs (`ChatTab`, `NotebookTab`, `WikiTab`)
- **Then** the Settings Q&A input's Enter/Shift+Enter behavior matches them
  (Enter submits, Shift+Enter newlines).

---

## R2 — Clear Button for the Settings Q&A Conversation

### AC-REQ-005 — Clear control exists
- **Given** the Settings tab chat panel is rendered
- **Then** a **Clear** control is present alongside the existing
  Ask / Preview / Edit controls in the chat-panel button column.

### AC-REQ-006 — Clear empties the visible pane
- **Given** the Q&A chat display shows one or more prior exchanges
- **When** the user activates **Clear**
- **Then** the visible chat display is emptied back to its placeholder state
  (the existing `clearChat()` JS runs).

### AC-REQ-007 — Clear permanently deletes on-disk history
- **Given** a persisted `settings_chat.jsonl` exists in the cache dir (e.g. seeded
  via `SettingsChatCache(cache_dir).add(...)`)
- **When** the user activates **Clear**
- **Then** the `settings_chat.jsonl` file no longer exists on disk
  (`SettingsChatCache.clear()` was invoked) — this is a permanent delete, not a
  session-only visual reset.

### AC-REQ-008 — Clear wipes the entire thread regardless of selected file
- **Given** the persisted history contains entries recorded against multiple
  different `file` values, and any one config/prompt file is currently selected
- **When** the user activates **Clear**
- **Then** the entire settings Q&A history is deleted (no per-file partitioning);
  reloading history afterward yields zero entries.

### AC-REQ-009 — Clear is idempotent when no history exists
- **Given** no `settings_chat.jsonl` file exists
- **When** the user activates **Clear**
- **Then** the operation completes without raising an error and the display is
  (still) empty.

---

## R3 — Move the Settings Tab to Be the Last Tab

### AC-REQ-010 — Settings is the last tab
- **Given** `MainWindow._init_ui()` after the change
- **Then** the `addTab(...)` call sequence is
  `notebook → chat → docs → graph → dir → cached → wiki → settings`, with
  `addTab(self.settings_tab, …)` as the final `addTab` call
- **And** `addTab(self.wiki_tab, …)` immediately precedes it
  (`wiki_add < settings_add`, and `settings_add` is the maximum of all `addTab`
  positions).

### AC-REQ-011 — Hidden docs/graph indices preserved
- **Given** the reordered `_init_ui()`
- **Then** `setTabVisible(2, False)` and `setTabVisible(3, False)` remain present
  and continue to hide the Docs(2) and Graph(3) tabs (those tabs did not move).
- **And** the existing test
  `test_docs_and_graph_tab_visibility_indices_preserved` still passes.

### AC-REQ-012 — Tab-switch unsaved-edit guard still works at the new index
- **Given** the Settings tab now sits at the last index with unsaved edits
- **When** the user switches to another tab
- **Then** `MainWindow._on_tab_changed` still routes through
  `settings_tab.confirm_leave()` (resolved via `indexOf(self.settings_tab)`),
  correctly guarding against losing unsaved edits.

---

## Quality Gate / Definition of Done

- [ ] AC-REQ-001 – AC-REQ-004 satisfied (Enter submits, Shift+Enter newlines, empty
      no-op, behavior consistent with other chat inputs).
- [ ] AC-REQ-005 – AC-REQ-009 satisfied (Clear control present; empties pane; deletes
      `settings_chat.jsonl`; wipes whole thread; idempotent).
- [ ] AC-REQ-010 – AC-REQ-012 satisfied (settings last; docs/graph hidden indices
      preserved; tab-switch guard intact).
- [ ] New tests added to `tests/test_settings_tab.py` for REQ-001–REQ-009.
- [ ] `tests/test_main_window_wiring.py`'s `test_settings_tab_added_after_graph_and_before_dir`
      is rewritten (e.g. renamed to `test_settings_tab_added_last`) to assert the new
      order for REQ-010; `test_docs_and_graph_tab_visibility_indices_preserved` still passes.
- [ ] `pytest tests/ -q` passes under `QT_QPA_PLATFORM=offscreen`
      (full suite green, no regressions).
- [ ] `ui.main_window` and `ui.settings_tab` import cleanly headlessly.
- [ ] No changes made to `resources/settings_chat.html` or `cache_store.py`
      (reused as-is; confirmed unchanged).
- [ ] Exclusions honored: no auto-expand height, no Up/Down history, no per-file
      Clear scoping, no Clear confirmation dialog, no new cache method, no GitHub
      issue, no new git branch.
- [ ] Committed directly to `main` (manual git strategy: no auto-branch, no push).
