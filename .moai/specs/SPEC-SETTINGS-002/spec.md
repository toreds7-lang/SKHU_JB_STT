---
id: SPEC-SETTINGS-002
version: 0.1.0
status: draft
created: 2026-07-11
updated: 2026-07-11
author: manager-spec (MoAI Plan Workflow)
priority: medium
issue_number: 0
---

# SPEC-SETTINGS-002: Settings Tab UX Fixes (Enter-to-Send, Clear History, Tab Reorder)

## HISTORY

| Version | Date       | Author       | Change                                                    |
|---------|------------|--------------|-----------------------------------------------------------|
| 0.1.0   | 2026-07-11 | manager-spec | Initial draft — three follow-up UX fixes for SPEC-SETTINGS-001 |

---

## 1. Overview

### 1.1 Context

SPEC-SETTINGS-001 delivered a full Settings tab (`ui/settings_tab.py`,
`workers/settings_worker.py`, `resources/settings_chat.html`,
`cache_store.SettingsChatCache`, wired into `ui/main_window.py`). The tab lets
users browse, edit, and ask LLM-backed questions about the 9 config/prompt
files. Three small UX gaps have surfaced during use.

### 1.2 Purpose

Close three narrowly-scoped UX/UI gaps in the already-shipped Settings tab:

1. **Enter-to-send** in the Settings Q&A input — currently Enter only inserts a
   newline; the user must click **Ask**. This is inconsistent with every other
   chat surface in the app (RAG chat, notebook chat, wiki).
2. **Clear button** for the Settings Q&A conversation — there is currently no
   way to clear the panel. The Clear action must be **destructive** (permanently
   deletes the persisted on-disk history), matching the NotebookTab precedent.
3. **Move the Settings tab to be the last tab** — it currently sits at index 4
   (between the hidden Graph tab and the Directory tab); the user wants it as the
   very last tab, immediately after the Knowledge-Graph (wiki) tab.

### 1.3 Why (motivation)

- **Consistency**: Enter-to-send is the established input convention across
  `ChatTab`, `NotebookTab`, and `WikiTab`. The Settings Q&A input is the only
  chat input that diverges, which surprises users.
- **Control**: A long-lived, append-only Q&A thread grows without bound and has
  no user-facing reset; a Clear control gives users agency over their history.
- **Discoverability / ergonomics**: Settings is a low-frequency utility tab; the
  user wants primary work tabs (notebook, chat) leftmost and Settings parked at
  the far right next to the other utility tabs.

### 1.4 Target Users

Researchers, faculty, and power users who tune RAG parameters and prompts via
the Settings tab (same audience as SPEC-SETTINGS-001).

---

## 2. Requirements (EARS Format)

### R1 — Enter-to-Send in the Settings Q&A Input

The Settings Q&A input (`qa_input`) currently has no keyboard handling: Enter
inserts a newline and submission is only possible via the **Ask** button.

- **REQ-001 (Event-Driven)**: **When** the user presses Enter without the Shift
  modifier while keyboard focus is in the Settings Q&A input, the Settings tab
  **shall** submit the current input text as a Q&A question (equivalent to
  activating **Ask**) and clear the input field.
- **REQ-002 (Event-Driven)**: **When** the user presses Shift+Enter while keyboard
  focus is in the Settings Q&A input, the Settings tab **shall** insert a
  newline into the input and **shall not** submit a question.
- **REQ-003 (Unwanted Behavior)**: **If** the Settings Q&A input contains only
  empty or whitespace-only text **when** Enter is pressed, **then** the Settings
  tab **shall not** submit a question and **shall** leave the input unchanged.
- **REQ-004 (Ubiquitous)**: The Settings Q&A input's Enter/Shift+Enter behavior
  **shall** match the established convention used by `ChatTab`, `NotebookTab`,
  and `WikiTab` (Enter submits, Shift+Enter inserts a newline).

### R2 — Clear Button for the Settings Q&A Conversation

The Settings Q&A chat panel (`resources/settings_chat.html` rendered inside
`SettingsTab`) is a **single continuous thread** that intermixes questions about
all 9 config/prompt files. The `file` field on each cached entry is
record-keeping only and does not partition the UI (`_load_qa_history()` renders
every cached entry into the same pane regardless of the currently-selected file).

- **REQ-005 (Ubiquitous)**: The Settings Q&A chat panel **shall** provide a Clear
  control positioned alongside the existing Ask / Preview / Edit controls.
- **REQ-006 (Event-Driven)**: **When** the user activates the Clear control, the
  Settings tab **shall** remove all rendered messages from the visible Q&A chat
  display (returning it to its empty placeholder state).
- **REQ-007 (Event-Driven)**: **When** the user activates the Clear control, the
  Settings tab **shall** permanently delete the persisted settings Q&A history
  (the `settings_chat.jsonl` file), not merely reset the visible pane for the
  current session.
- **REQ-008 (Ubiquitous)**: The Clear operation **shall** wipe the entire settings
  Q&A history irrespective of which config/prompt file is currently selected
  (the thread is not scoped per-file).
- **REQ-009 (Unwanted Behavior)**: **If** no persisted settings Q&A history exists
  **when** the Clear control is activated, **then** the Settings tab **shall**
  complete the operation without raising an error (idempotent, no-op on disk).

### R3 — Move the Settings Tab to Be the Last Tab

The current tab-creation order in `MainWindow._init_ui()` adds tabs as:
`notebook`(0) → `chat`(1) → `docs`(2, hidden) → `graph`(3, hidden) →
`settings`(4) → `dir`(5) → `cached`(6) → `wiki`(7).

- **REQ-010 (Ubiquitous)**: The Settings tab **shall** be the last tab in the tab
  bar, positioned immediately after the Knowledge-Graph (wiki) tab. The
  resulting order **shall** be: `notebook`(0) → `chat`(1) → `docs`(2, hidden) →
  `graph`(3, hidden) → `dir`(4) → `cached`(5) → `wiki`(6) → `settings`(7).
- **REQ-011 (Ubiquitous)**: The hidden Docs and Graph tabs **shall** remain at
  indices 2 and 3 respectively, so their existing visibility calls
  (`setTabVisible(2, False)` / `setTabVisible(3, False)`) continue to hide the
  correct tabs after the reorder.
- **REQ-012 (State-Driven)**: **While** the Settings tab holds unsaved edits and the
  user switches to another tab, the Settings tab's tab-switch guard
  (`confirm_leave`, reached via `MainWindow._on_tab_changed` using
  `indexOf(self.settings_tab)`) **shall** continue to function correctly at the
  Settings tab's new last-position index.

---

## 3. Non-Functional Constraints

- **NFR-1 (No new dependencies)**: All three fixes reuse existing code paths
  (`_on_ask_clicked`, `SettingsChatCache.clear()`, the `clearChat()` JS function,
  the `addTab` call sequence). No new libraries, cache methods, or JS functions
  are required.
- **NFR-2 (Data safety)**: REQ-007/REQ-008 are intentionally destructive by user
  decision; because they delete user history, the deletion must target only
  `settings_chat.jsonl` and must not touch any other cache artifact (chat cache,
  notebook chat cache, backups, or recovery files).
- **NFR-3 (No regressions)**: The tab reorder must not break any existing
  Settings-tab wiring, signal connections, or the tab-switch unsaved-edit guard.

---

## 4. Exclusions (What NOT to Build)

These are explicitly out of scope for SPEC-SETTINGS-002:

1. **No auto-expanding input height** — Do NOT port `_AutoExpandingEdit`'s
   ChatGPT-style vertical growth (up to 4 lines) to the Settings Q&A input. The
   input keeps its current fixed height (48px).
2. **No Up/Down history recall** — Do NOT port `_AutoExpandingEdit`'s Up/Down
   arrow history navigation (`_history` / `_hist_idx` / `_draft`) to the Settings
   Q&A input. Only the Enter/Shift+Enter branch is in scope.
3. **No per-file scoping of Clear** — Clear wipes the entire settings Q&A thread;
   do NOT add UI or logic to clear only the currently-selected file's entries.
4. **No confirmation dialog for Clear** — Matching the NotebookTab precedent
   (`_on_clear_chat` clears immediately with no prompt), Clear performs its
   destructive delete without a confirmation dialog. (Adding one is a possible
   future enhancement, not part of this SPEC.)
5. **No new `SettingsChatCache` method** — `SettingsChatCache.clear()` already
   deletes the whole `settings_chat.jsonl` file; reuse it as-is.
6. **No changes to `resources/settings_chat.html`** — `clearChat()` already
   exists and does exactly what REQ-006 needs; the HTML/JS is unchanged.
7. **No GitHub issue creation** (`issue_number: 0`).
8. **No new git branch** — Git strategy is manual mode: commit directly to the
   current branch `main`, no push (matches SPEC-SETTINGS-001's precedent).

---

## 5. Assumptions

- The Settings tab from SPEC-SETTINGS-001 Phase 0+1 (plus the Phase 2-5 chat/QA
  wiring present in the current tree) is in place and imports cleanly under
  `QT_QPA_PLATFORM=offscreen`.
- `pytest` + `pytest-qt` infrastructure exists (`tests/` with `conftest.py`;
  40 tests currently passing per SPEC-SETTINGS-001 progress notes).
- `_on_ask_clicked` already guards empty/whitespace input (so REQ-003 is satisfied
  by wiring `returnPressed` to the existing handler rather than adding new guard
  logic).

---

## 6. Related SPECs

- **SPEC-SETTINGS-001** — Builds the Settings tab this SPEC refines. This SPEC
  does not supersede it; SPEC-SETTINGS-001 Phases 2-5 remain independently open.
