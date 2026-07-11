# Implementation Plan — SPEC-SETTINGS-002

> WHAT/WHY lives in `spec.md`. This plan identifies the exact files to touch and
> the technical approach. No implementation code is written here.

## 1. Technical Approach

All three fixes are additive, low-risk edits that reuse existing code paths. No
new dependencies, no new cache methods, no HTML/JS changes.

### R1 — Enter-to-Send in the Settings Q&A input

**Target file**: `ui/settings_tab.py`

The Q&A input `self.qa_input` is a plain `QPlainTextEdit` built in
`_build_chat_panel()` (currently around line 220) with no keyboard handling.

Two acceptable implementation shapes (pick the smaller that keeps
`_build_chat_panel` readable):

- **Option A (preferred)**: A tiny dedicated `QPlainTextEdit` subclass defined in
  `ui/settings_tab.py` that overrides only `keyPressEvent` with the
  Enter/Shift+Enter branch and exposes a `returnPressed = pyqtSignal()`. This
  mirrors `ui/chat_tab.py`'s `_AutoExpandingEdit.keyPressEvent` (lines 118-125)
  but **without** the auto-expand height logic and **without** the Up/Down
  history branches. Replace the `QPlainTextEdit()` instantiation of `qa_input`
  with this subclass.
- **Option B**: Install an event filter / assign a bound `keyPressEvent` on the
  existing `qa_input` instance achieving the same Enter/Shift+Enter routing.

The Enter/Shift+Enter contract to replicate:
- `Key_Return` / `Key_Enter` **without** `ShiftModifier` → emit `returnPressed`
  (do not call `super().keyPressEvent`).
- `Key_Return` / `Key_Enter` **with** `ShiftModifier` → `super().keyPressEvent`
  (insert newline).
- All other keys → `super().keyPressEvent`.

**Wiring**: connect `self.qa_input.returnPressed.connect(self._on_ask_clicked)`
in `_build_chat_panel()` (mirrors `chat_tab.py:553`
`input_edit.returnPressed.connect(self._on_send)` and `notebook_tab.py:968`).
`_on_ask_clicked` (settings_tab.py:887) already returns early on empty/whitespace
input, so REQ-003 needs no new guard.

### R2 — Clear button for the Settings Q&A conversation

**Target file**: `ui/settings_tab.py` (only)

- **UI**: In `_build_chat_panel()`, add a `Clear` button (`self.clear_btn`) to the
  existing `btn_col` `QVBoxLayout` next to `ask_btn` / `preview_btn` / `edit_btn`
  / `discard_btn` (lines ~229-248). Reuse the same button stylesheet block.
- **Handler**: Add a `_on_clear_qa_clicked()` method that:
  1. Clears the visible display via the existing JS function:
     `self._run_qa_js("clearChat()")` (`_run_qa_js` already exists at
     settings_tab.py:884; `clearChat()` already exists at
     `resources/settings_chat.html:348`).
  2. Permanently deletes the persisted history:
     `SettingsChatCache(self._cache_dir).clear()` (cache_store.py:278 — already
     deletes the whole `settings_chat.jsonl`; wrap in the same defensive
     try/except used by `_append_qa_history`/`_load_qa_history`).
- Connect `self.clear_btn.clicked.connect(self._on_clear_qa_clicked)`.

Follows the destructive NotebookTab precedent (`ui/notebook_tab.py:1646-1653`):
clears in-memory/JS display **and** deletes persisted history, with **no**
confirmation dialog. Because the settings thread is a single continuous log (not
per-file), Clear wipes the entire history regardless of the selected file (REQ-008).

### R3 — Move the Settings tab to be the last tab

**Target file**: `ui/main_window.py`

In `MainWindow._init_ui()`, reorder the `addTab(...)` call sequence (currently
lines 123-130). Move the `self.tab_widget.addTab(self.settings_tab, "⚙️  설정")`
call so it is the **last** `addTab` call, immediately after
`addTab(self.wiki_tab, "🗺️  지식 그래프")`.

Resulting sequence:
```
addTab(self.notebook_tab, "📓  노트북 뷰어")   # 0
addTab(self.chat_tab,     "💬  RAG 채팅")       # 1
addTab(self.docs_tab,     "📄  문서 탐색")       # 2 (hidden)
addTab(self.graph_tab,    "🕸️  그래프 탐색")     # 3 (hidden)
addTab(self.dir_tab,      "📁  디렉토리")         # 4
addTab(self.cached_tab,   "💾  캐시 응답")        # 5
addTab(self.wiki_tab,     "🗺️  지식 그래프")      # 6
addTab(self.settings_tab, "⚙️  설정")           # 7 (new last)
```

Leave `setTabVisible(2, False)` / `setTabVisible(3, False)` (lines 132-133)
unchanged — docs(2) and graph(3) do not move, so the hidden indices stay correct
(REQ-011). The `SettingsTab` construction (line 121) and `config_metadata` build
(lines 119-120) stay where they are; only the `addTab` ordering changes.

**Resilience note**: `_on_tab_changed` (main_window.py:725-735) resolves the
settings index dynamically via `self.tab_widget.indexOf(self.settings_tab)`
(line 728), so the unsaved-edit tab-switch guard (REQ-012) requires no change.

## 2. Files to Modify

| File | Change | Requirement |
|------|--------|-------------|
| `ui/settings_tab.py` | Add minimal Enter-to-send `QPlainTextEdit` subclass (or key handler) + wire `returnPressed` → `_on_ask_clicked` | R1 |
| `ui/settings_tab.py` | Add `Clear` button to chat-panel `btn_col` + `_on_clear_qa_clicked()` (JS `clearChat()` + `SettingsChatCache.clear()`) | R2 |
| `ui/main_window.py` | Reorder `addTab` calls so `settings_tab` is added last (after `wiki_tab`) | R3 |
| `tests/test_settings_tab.py` | New tests: Enter submits, Shift+Enter inserts newline, empty-Enter no-op; Clear empties pane AND deletes `settings_chat.jsonl` (incl. idempotent no-op) | R1, R2 |
| `tests/test_main_window_wiring.py` | Rewrite `test_settings_tab_added_after_graph_and_before_dir` for the new order; confirm `test_docs_and_graph_tab_visibility_indices_preserved` still passes | R3 |

**No changes required** to `resources/settings_chat.html` (its `clearChat()` at
line 348 already resets the pane) or `cache_store.py` (`SettingsChatCache.clear()`
at line 278 already deletes the whole JSONL). Confirm-only, do not edit.

## 3. Test Strategy (TDD, per project quality mode)

- **R1 tests** (`tests/test_settings_tab.py`, using `qtbot`):
  - Typing text then sending an Enter key event (`QTest.keyClick` with
    `Qt.Key.Key_Return`, no modifier) submits — assert via the `qa_requested`
    signal firing (or `_on_ask_clicked` side effects: input cleared) using a
    monkeypatched/`qtbot.waitSignal` hook. Prefer asserting the input is cleared
    and a user message is appended, matching how `_on_ask_clicked` behaves.
  - Shift+Enter inserts a newline and does NOT submit — assert `qa_input`
    `toPlainText()` gains a `\n` and no submission side effect occurs.
  - Empty/whitespace + Enter is a no-op (no submission).
- **R2 tests** (`tests/test_settings_tab.py`):
  - After seeding `SettingsChatCache(tmp).add(...)` so `settings_chat.jsonl`
    exists, activating Clear deletes the file on disk (`path.exists()` is False)
    and issues the `clearChat()` JS (assert via a spy on `_run_qa_js`).
  - Clear with no existing history file completes without error (idempotent).
- **R3 tests** (`tests/test_main_window_wiring.py`, source-inspection style,
  matching the existing headless approach):
  - Rewrite `test_settings_tab_added_after_graph_and_before_dir` →
    e.g. `test_settings_tab_added_last` asserting
    `wiki_add < settings_add` and that `addTab(self.settings_tab` is the last
    `addTab(...)` occurrence in `_init_ui` source (and that `dir_add`,
    `cached_add`, `wiki_add` all precede `settings_add`).
  - Keep `test_docs_and_graph_tab_visibility_indices_preserved` — it must still
    pass since `setTabVisible(2/3)` are unchanged.

## 4. Milestones (priority order, no time estimates)

1. **M1 — R3 tab reorder** (lowest risk, unblocks nothing): reorder `addTab`,
   update `test_main_window_wiring.py`.
2. **M2 — R1 Enter-to-send**: add key handler/subclass + wiring + tests.
3. **M3 — R2 Clear button**: add button + handler + tests.
4. **M4 — Full suite green**: run `pytest tests/ -q` under
   `QT_QPA_PLATFORM=offscreen`; TRUST 5 review; commit directly to `main`
   (manual git strategy, no branch, no push).

## 5. Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Reorder shifts a hardcoded tab index elsewhere | Low | Verified: only `setTabVisible(2/3)` use literal indices and those tabs don't move; `_on_tab_changed` uses `indexOf(self.settings_tab)` (dynamic). |
| Enter-to-send accidentally ports unwanted history/auto-grow behavior | Low | Explicit exclusions; implement only the Enter/Shift+Enter branch. |
| Clear deletes more than intended | Low | Scope deletion strictly to `SettingsChatCache.clear()` (single `settings_chat.jsonl`); no other cache touched. |
| Headless test can't construct full `MainWindow` (QWebEngineView) | Low | Follow existing `test_main_window_wiring.py` source-inspection pattern for R3; use `qtbot` widget-level tests for R1/R2 as in `test_settings_tab.py`. |
