"""Specification tests for ``ui.settings_tab.SettingsTab``.

SPEC-SETTINGS-001 Phase 1 (F-SETTINGS-1, F-SETTINGS-2): a read-only file
browser. The left list shows the nine config files (missing ones grayed out but
still selectable); selecting one loads its raw content into a read-only viewer
with a "{path} · UTF-8" header. Missing files render a placeholder.
"""

import os

import rag_core
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QMessageBox, QDialog

from cache_store import SettingsChatCache
from ui.settings_tab import SettingsTab

EXPECTED_FILES = [
    "env.txt",
    "config.txt",
    "prompts/system_prompt.txt",
    "prompts/force_prompt.txt",
    "prompts/agentic_planner_prompt.txt",
    "prompts/agentic_sufficiency_prompt.txt",
    "prompts/agentic_synthesis_prompt.txt",
    "prompts/notebook_chat_prompt.txt",
    "prompts/summary_prompt.txt",
]


def _row_for(tab, text):
    for i in range(tab.file_list.count()):
        if tab.file_list.item(i).text() == text:
            return i
    raise AssertionError(f"{text!r} not in file list")


def test_lists_nine_expected_files_in_order(qtbot, tmp_path):
    tab = SettingsTab(base_dir=str(tmp_path))
    qtbot.addWidget(tab)

    assert tab.file_list.count() == 9
    actual = [tab.file_list.item(i).text() for i in range(tab.file_list.count())]
    assert actual == EXPECTED_FILES


def test_missing_files_are_grayed_but_selectable(qtbot, tmp_path):
    # Only env.txt exists on disk.
    (tmp_path / "env.txt").write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")

    tab = SettingsTab(base_dir=str(tmp_path))
    qtbot.addWidget(tab)

    env_item = tab.file_list.item(_row_for(tab, "env.txt"))
    missing_item = tab.file_list.item(_row_for(tab, "config.txt"))

    assert env_item.foreground().color().name().lower() == SettingsTab.COLOR_EXISTS.lower()
    assert missing_item.foreground().color().name().lower() == SettingsTab.COLOR_MISSING.lower()

    # Grayed-out files must remain selectable (F-SETTINGS-1).
    assert missing_item.flags() & Qt.ItemFlag.ItemIsSelectable
    assert missing_item.flags() & Qt.ItemFlag.ItemIsEnabled


def test_content_view_is_read_only(qtbot, tmp_path):
    tab = SettingsTab(base_dir=str(tmp_path))
    qtbot.addWidget(tab)
    assert tab.content_view.isReadOnly() is True


def test_selecting_existing_file_loads_content(qtbot, tmp_path):
    (tmp_path / "config.txt").write_text("VECTOR_K=5\nMAX_DOCS=10\n", encoding="utf-8")

    tab = SettingsTab(base_dir=str(tmp_path))
    qtbot.addWidget(tab)

    tab.file_list.setCurrentRow(_row_for(tab, "config.txt"))
    qtbot.waitUntil(lambda: tab.content_view.toPlainText() == "VECTOR_K=5\nMAX_DOCS=10\n",
                    timeout=3000)


def test_selecting_missing_file_shows_placeholder(qtbot, tmp_path):
    tab = SettingsTab(base_dir=str(tmp_path))
    qtbot.addWidget(tab)

    tab.file_list.setCurrentRow(_row_for(tab, "config.txt"))  # does not exist
    qtbot.waitUntil(lambda: tab.content_view.toPlainText() == SettingsTab.PLACEHOLDER_MISSING,
                    timeout=3000)


def test_header_shows_path_and_encoding(qtbot, tmp_path):
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "system_prompt.txt").write_text("hi", encoding="utf-8")

    tab = SettingsTab(base_dir=str(tmp_path))
    qtbot.addWidget(tab)

    tab.file_list.setCurrentRow(_row_for(tab, "prompts/system_prompt.txt"))
    qtbot.waitUntil(lambda: "prompts/system_prompt.txt" in tab.header_label.text(), timeout=3000)
    assert tab.header_label.text() == "prompts/system_prompt.txt · UTF-8"


def test_cleared_selection_is_a_noop(qtbot, tmp_path):
    (tmp_path / "config.txt").write_text("VECTOR_K=5\n", encoding="utf-8")
    tab = SettingsTab(base_dir=str(tmp_path))
    qtbot.addWidget(tab)

    # currentRowChanged(-1) fires when the list selection is cleared; it must
    # not attempt a load or raise.
    tab._on_row_changed(-1)
    assert tab.content_view.toPlainText() == ""


def test_stale_content_result_is_ignored(qtbot, tmp_path):
    (tmp_path / "config.txt").write_text("VECTOR_K=5\nMAX_DOCS=10\n", encoding="utf-8")
    tab = SettingsTab(base_dir=str(tmp_path))
    qtbot.addWidget(tab)

    tab.file_list.setCurrentRow(_row_for(tab, "config.txt"))
    qtbot.waitUntil(lambda: tab.content_view.toPlainText() == "VECTOR_K=5\nMAX_DOCS=10\n",
                    timeout=3000)

    # A late result for a DIFFERENT (no longer selected) file must be dropped so
    # it cannot clobber the current view.
    tab._on_content_loaded("prompts/summary_prompt.txt", "STALE", "UTF-8")
    assert tab.content_view.toPlainText() == "VECTOR_K=5\nMAX_DOCS=10\n"

    tab._on_load_error("prompts/summary_prompt.txt")
    assert tab.content_view.toPlainText() == "VECTOR_K=5\nMAX_DOCS=10\n"


def test_accepts_config_metadata_without_error(qtbot, tmp_path):
    metadata = rag_core.build_config_metadata(
        env_path=str(tmp_path / "missing_env.txt"),
        config_path=str(tmp_path / "missing_config.txt"),
        prompts_dir=str(tmp_path / "prompts"),
    )
    tab = SettingsTab(base_dir=str(tmp_path), config_metadata=metadata)
    qtbot.addWidget(tab)
    assert tab.file_list.count() == 9


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2-5: edit mode, save/reset flows, category filter, Q&A, unsaved-changes
# ─────────────────────────────────────────────────────────────────────────────

def _make_tab(settings_files, qtbot):
    meta = rag_core.build_config_metadata(
        env_path=str(settings_files["env"]),
        config_path=str(settings_files["config"]),
        prompts_dir=str(settings_files["prompts_dir"]),
    )
    tab = SettingsTab(base_dir=str(settings_files["tmp"]), config_metadata=meta)
    qtbot.addWidget(tab)
    tab.show()  # isVisible() only reflects setVisible() calls once the widget tree is shown
    return tab


def _open_and_wait(tab, qtbot, rel_path, expected_text):
    tab.file_list.setCurrentRow(_row_for(tab, rel_path))
    qtbot.waitUntil(lambda: tab.content_view.toPlainText() == expected_text, timeout=3000)


# ── Edit mode ────────────────────────────────────────────────────────────────

def test_edit_mode_toggle_makes_content_editable(qtbot, settings_files):
    tab = _make_tab(settings_files, qtbot)
    tab.file_list.setCurrentRow(_row_for(tab, "config.txt"))
    qtbot.waitUntil(lambda: "VECTOR_K" in tab.content_view.toPlainText(), timeout=3000)

    tab.edit_btn.click()

    assert tab.content_view.isReadOnly() is False
    assert tab.discard_btn.isVisible() is True
    assert tab.save_btn.isEnabled() is True


def test_has_unsaved_changes_tracks_edits(qtbot, settings_files):
    tab = _make_tab(settings_files, qtbot)
    tab.file_list.setCurrentRow(_row_for(tab, "config.txt"))
    qtbot.waitUntil(lambda: "VECTOR_K" in tab.content_view.toPlainText(), timeout=3000)

    tab.edit_btn.click()
    assert tab.has_unsaved_changes() is False

    tab.content_view.setPlainText(tab.content_view.toPlainText() + "\nEXTRA=1\n")
    assert tab.has_unsaved_changes() is True
    assert "Unstaged Changes" in tab.unsaved_label.text()


def test_file_selection_locked_during_edit_mode(qtbot, settings_files):
    tab = _make_tab(settings_files, qtbot)
    tab.file_list.setCurrentRow(_row_for(tab, "config.txt"))
    qtbot.waitUntil(lambda: "VECTOR_K" in tab.content_view.toPlainText(), timeout=3000)
    tab.edit_btn.click()
    locked_row = tab.file_list.currentRow()

    tab.file_list.setCurrentRow(_row_for(tab, "env.txt"))

    assert tab.file_list.currentRow() == locked_row


def test_discard_edits_reverts_content(qtbot, settings_files, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    tab = _make_tab(settings_files, qtbot)
    tab.file_list.setCurrentRow(_row_for(tab, "config.txt"))
    qtbot.waitUntil(lambda: "VECTOR_K" in tab.content_view.toPlainText(), timeout=3000)
    original = tab.content_view.toPlainText()
    tab.edit_btn.click()
    tab.content_view.setPlainText("GARBAGE\n")

    tab.discard_btn.click()

    assert tab.content_view.toPlainText() == original
    assert tab._edit_mode is False


# ── Save flow ────────────────────────────────────────────────────────────────

def test_save_prompt_file_writes_to_disk(qtbot, settings_files, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    tab = _make_tab(settings_files, qtbot)
    tab.set_cache_dir(str(settings_files["tmp"] / ".rag_cache"))
    _open_and_wait(tab, qtbot, "prompts/system_prompt.txt", "system prompt body")

    tab.edit_btn.click()
    tab.content_view.setPlainText("updated system prompt")

    saved = []
    tab.file_saved.connect(saved.append)

    ok = tab._do_save()
    qtbot.waitUntil(lambda: saved == ["prompts/system_prompt.txt"], timeout=3000)

    assert ok is True
    assert (settings_files["prompts_dir"] / "system_prompt.txt").read_text(encoding="utf-8") \
        == "updated system prompt"
    assert tab.content_view.isReadOnly() is True


def test_save_config_with_invalid_value_shows_error_and_stays_editable(qtbot, settings_files, monkeypatch):
    errors_shown = []
    monkeypatch.setattr(
        QMessageBox, "critical",
        staticmethod(lambda *a, **k: (errors_shown.append(a[-1]), QMessageBox.StandardButton.Ok)[-1]),
    )
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))

    tab = _make_tab(settings_files, qtbot)
    tab.file_list.setCurrentRow(_row_for(tab, "config.txt"))
    qtbot.waitUntil(lambda: "VECTOR_K" in tab.content_view.toPlainText(), timeout=3000)

    tab.edit_btn.click()
    tab.content_view.setPlainText("VECTOR_K=999\n")

    ok = tab._do_save()

    assert ok is False
    assert errors_shown
    assert "VECTOR_K" in errors_shown[0]
    assert tab.content_view.isReadOnly() is False


def test_save_config_with_rebuild_key_cancel_aborts(qtbot, settings_files, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    tab = _make_tab(settings_files, qtbot)
    tab.file_list.setCurrentRow(_row_for(tab, "config.txt"))
    qtbot.waitUntil(lambda: "VECTOR_K" in tab.content_view.toPlainText(), timeout=3000)

    tab.edit_btn.click()
    tab.content_view.setPlainText("VECTOR_K=5\nGRAPH_HOPS=4\nMAX_DOCS=12\nMY_CUSTOM_KEY=123\n")
    monkeypatch.setattr(tab, "_ask_rebuild_choice", lambda: "cancel")

    ok = tab._do_save()

    assert ok is False
    assert tab.content_view.isReadOnly() is False


def test_save_config_with_rebuild_now_emits_rebuild_requested(qtbot, settings_files, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    tab = _make_tab(settings_files, qtbot)
    tab.set_cache_dir(str(settings_files["tmp"] / ".rag_cache"))
    tab.file_list.setCurrentRow(_row_for(tab, "config.txt"))
    qtbot.waitUntil(lambda: "VECTOR_K" in tab.content_view.toPlainText(), timeout=3000)

    tab.edit_btn.click()
    tab.content_view.setPlainText("VECTOR_K=5\nGRAPH_HOPS=4\nMAX_DOCS=12\nMY_CUSTOM_KEY=123\n")
    monkeypatch.setattr(tab, "_ask_rebuild_choice", lambda: "now")

    rebuilds = []
    tab.rebuild_requested.connect(lambda: rebuilds.append(True))
    saved = []
    tab.file_saved.connect(saved.append)

    ok = tab._do_save()
    qtbot.waitUntil(lambda: saved == ["config.txt"], timeout=3000)

    assert ok is True
    assert rebuilds == [True]


# ── Reset to defaults ─────────────────────────────────────────────────────────

def test_reset_env_txt_shows_info_and_is_noop(qtbot, settings_files, monkeypatch):
    infos = []
    monkeypatch.setattr(
        QMessageBox, "information",
        staticmethod(lambda *a, **k: (infos.append(True), QMessageBox.StandardButton.Ok)[-1]),
    )
    tab = _make_tab(settings_files, qtbot)
    tab.file_list.setCurrentRow(_row_for(tab, "env.txt"))
    qtbot.waitUntil(lambda: "OPENAI_API_KEY" in tab.content_view.toPlainText(), timeout=3000)

    tab._do_reset()

    assert infos == [True]
    assert "sk-test-123" in settings_files["env"].read_text(encoding="utf-8")


def test_reset_config_defaults_enters_edit_mode_with_reset_text(qtbot, settings_files, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    tab = _make_tab(settings_files, qtbot)
    tab.file_list.setCurrentRow(_row_for(tab, "config.txt"))
    qtbot.waitUntil(lambda: "VECTOR_K" in tab.content_view.toPlainText(), timeout=3000)

    tab._do_reset()

    assert tab._edit_mode is True
    text = tab.content_view.toPlainText()
    assert "VECTOR_K=5" in text          # reset to catalog default
    assert "MY_CUSTOM_KEY=123" in text  # custom key preserved


def test_reset_prompt_file_deletes_with_backup(qtbot, settings_files, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    tab = _make_tab(settings_files, qtbot)
    tab.set_cache_dir(str(settings_files["tmp"] / ".rag_cache"))
    _open_and_wait(tab, qtbot, "prompts/force_prompt.txt", "force prompt body")

    saved = []
    tab.file_saved.connect(saved.append)

    tab._do_reset()

    assert saved == ["prompts/force_prompt.txt"]
    assert not (settings_files["prompts_dir"] / "force_prompt.txt").exists()
    backups = list((settings_files["tmp"] / ".rag_cache" / "backups").glob("force_prompt.txt.*.bak"))
    assert len(backups) == 1


# ── Category filter ───────────────────────────────────────────────────────────

def test_category_filter_shows_only_matching_files(qtbot, settings_files):
    tab = _make_tab(settings_files, qtbot)
    assert tab.file_list.count() == 9

    tab.category_checks["API"].setChecked(True)

    names = [tab.file_list.item(i).text() for i in range(tab.file_list.count())]
    assert "env.txt" in names
    assert "prompts/system_prompt.txt" not in names
    assert tab.all_check.isChecked() is False


def test_category_filter_all_restores_full_list(qtbot, settings_files):
    tab = _make_tab(settings_files, qtbot)
    tab.category_checks["API"].setChecked(True)
    assert tab.file_list.count() < 9

    tab.all_check.setChecked(True)
    assert tab.file_list.count() == 9


# ── Unsaved-changes guard (confirm_leave) ────────────────────────────────────

def test_confirm_leave_true_when_no_unsaved_changes(qtbot, settings_files):
    tab = _make_tab(settings_files, qtbot)
    assert tab.confirm_leave() is True


def test_confirm_leave_discard_choice(qtbot, settings_files, monkeypatch):
    tab = _make_tab(settings_files, qtbot)
    tab.file_list.setCurrentRow(_row_for(tab, "config.txt"))
    qtbot.waitUntil(lambda: "VECTOR_K" in tab.content_view.toPlainText(), timeout=3000)
    tab.edit_btn.click()
    tab.content_view.setPlainText("CHANGED=1\n")

    monkeypatch.setattr(tab, "_ask_leave_choice", lambda: "discard")

    assert tab.confirm_leave() is True
    assert tab._edit_mode is False


def test_confirm_leave_cancel_choice_keeps_editing(qtbot, settings_files, monkeypatch):
    tab = _make_tab(settings_files, qtbot)
    tab.file_list.setCurrentRow(_row_for(tab, "config.txt"))
    qtbot.waitUntil(lambda: "VECTOR_K" in tab.content_view.toPlainText(), timeout=3000)
    tab.edit_btn.click()
    tab.content_view.setPlainText("CHANGED=1\n")

    monkeypatch.setattr(tab, "_ask_leave_choice", lambda: "cancel")

    assert tab.confirm_leave() is False
    assert tab._edit_mode is True


# ── External change detection ─────────────────────────────────────────────────

def test_external_change_shows_warning_banner(qtbot, settings_files):
    tab = _make_tab(settings_files, qtbot)
    tab.file_list.setCurrentRow(_row_for(tab, "config.txt"))
    qtbot.waitUntil(lambda: "VECTOR_K" in tab.content_view.toPlainText(), timeout=3000)
    assert tab.warning_banner.isVisible() is False

    current_mtime = os.path.getmtime(settings_files["config"])
    os.utime(settings_files["config"], (current_mtime + 5, current_mtime + 5))

    tab._check_external_changes()

    assert tab.warning_banner.isVisible() is True


# ── LLM-assisted prompt modification button visibility ───────────────────────

def test_modify_llm_button_visible_only_for_prompt_files(qtbot, settings_files):
    tab = _make_tab(settings_files, qtbot)
    tab.file_list.setCurrentRow(_row_for(tab, "config.txt"))
    qtbot.waitUntil(lambda: "VECTOR_K" in tab.content_view.toPlainText(), timeout=3000)
    assert tab.modify_llm_btn.isVisible() is False

    _open_and_wait(tab, qtbot, "prompts/system_prompt.txt", "system prompt body")
    assert tab.modify_llm_btn.isVisible() is True


def test_on_rewrite_finished_opens_diff_dialog_without_raising(qtbot, settings_files, monkeypatch):
    monkeypatch.setattr(QDialog, "exec", lambda self: 0)
    tab = _make_tab(settings_files, qtbot)
    _open_and_wait(tab, qtbot, "prompts/system_prompt.txt", "system prompt body")

    tab._pending_rewrite_original = "system prompt body"
    tab.on_rewrite_finished("new rewritten prompt")

    assert tab.modify_llm_btn.isEnabled() is True


# ── Q&A chat ───────────────────────────────────────────────────────────────────

def test_ask_known_key_emits_qa_requested(qtbot, settings_files):
    tab = _make_tab(settings_files, qtbot)
    requested = []
    tab.qa_requested.connect(requested.append)

    tab.qa_input.setPlainText("VECTOR_K가 뭐야?")
    tab.ask_btn.click()

    assert len(requested) == 1
    assert "VECTOR_K" in requested[0]


def test_ask_unknown_key_does_not_emit_qa_requested(qtbot, settings_files):
    tab = _make_tab(settings_files, qtbot)
    requested = []
    tab.qa_requested.connect(requested.append)

    tab.qa_input.setPlainText("오늘 날씨 어때?")
    tab.ask_btn.click()

    assert requested == []


def test_qa_callbacks_do_not_raise(qtbot, settings_files, monkeypatch):
    monkeypatch.setattr(QMessageBox, "critical",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    tab = _make_tab(settings_files, qtbot)
    tab.on_qa_chunk("hello")
    tab.on_qa_finished("full answer")
    tab.on_qa_error("boom")


# ── R1: Enter-to-send in the Q&A input (SPEC-SETTINGS-002 REQ-001..004) ──────

def test_enter_submits_question(qtbot, settings_files, monkeypatch):
    # JS calls go to a dead QWebEngine page under offscreen; stub them out so the
    # observable side effects are purely the Python-side ones.
    tab = _make_tab(settings_files, qtbot)
    monkeypatch.setattr(tab, "_run_qa_js", lambda *a, **k: None)
    requested = []
    tab.qa_requested.connect(requested.append)

    tab.qa_input.setPlainText("VECTOR_K가 뭐야?")
    QTest.keyClick(tab.qa_input, Qt.Key.Key_Return)

    # Same path as clicking Ask: qa_requested fires and the input is cleared,
    # with no stray newline left behind.
    assert len(requested) == 1
    assert "VECTOR_K" in requested[0]
    assert tab.qa_input.toPlainText() == ""


def test_shift_enter_inserts_newline_and_does_not_submit(qtbot, settings_files, monkeypatch):
    tab = _make_tab(settings_files, qtbot)
    monkeypatch.setattr(tab, "_run_qa_js", lambda *a, **k: None)
    requested = []
    tab.qa_requested.connect(requested.append)

    tab.qa_input.setPlainText("VECTOR_K가 뭐야?")
    # Move cursor to end so the newline is appended, not prepended.
    cursor = tab.qa_input.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    tab.qa_input.setTextCursor(cursor)

    QTest.keyClick(tab.qa_input, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)

    assert "\n" in tab.qa_input.toPlainText()
    assert requested == []


def test_empty_enter_is_a_noop(qtbot, settings_files, monkeypatch):
    tab = _make_tab(settings_files, qtbot)
    monkeypatch.setattr(tab, "_run_qa_js", lambda *a, **k: None)
    requested = []
    tab.qa_requested.connect(requested.append)

    tab.qa_input.setPlainText("   ")  # whitespace only
    QTest.keyClick(tab.qa_input, Qt.Key.Key_Return)

    assert requested == []
    assert tab.qa_input.toPlainText() == "   "


# ── R2: Clear button for the Q&A conversation (SPEC-SETTINGS-002 REQ-005..009) ─

def test_clear_button_exists_in_chat_panel(qtbot, settings_files):
    tab = _make_tab(settings_files, qtbot)
    assert hasattr(tab, "clear_btn")
    assert tab.clear_btn.text().strip() != ""


def test_clear_deletes_history_file_and_clears_display(qtbot, settings_files, monkeypatch):
    tab = _make_tab(settings_files, qtbot)
    js_calls = []
    monkeypatch.setattr(tab, "_run_qa_js", lambda script: js_calls.append(script))

    cache = SettingsChatCache(tab._cache_dir)
    cache.add("config.txt", "VECTOR_K가 뭐야?", "벡터 검색 top-k입니다.")
    assert cache.path.exists()

    tab.clear_btn.click()

    assert not cache.path.exists()
    assert any("clearChat()" in c for c in js_calls)


def test_clear_wipes_entire_thread_regardless_of_selected_file(qtbot, settings_files, monkeypatch):
    tab = _make_tab(settings_files, qtbot)
    monkeypatch.setattr(tab, "_run_qa_js", lambda *a, **k: None)

    cache = SettingsChatCache(tab._cache_dir)
    cache.add("config.txt", "q1", "a1")
    cache.add("env.txt", "q2", "a2")
    cache.add("prompts/system_prompt.txt", "q3", "a3")
    tab._current_rel_path = "env.txt"

    tab._on_clear_qa_clicked()

    assert SettingsChatCache(tab._cache_dir).load() == []


def test_clear_is_idempotent_when_no_history(qtbot, settings_files, monkeypatch):
    tab = _make_tab(settings_files, qtbot)
    monkeypatch.setattr(tab, "_run_qa_js", lambda *a, **k: None)

    cache = SettingsChatCache(tab._cache_dir)
    assert not cache.path.exists()

    # Must not raise even though there is nothing to delete.
    tab._on_clear_qa_clicked()

    assert not cache.path.exists()


# ── Auto-save recovery ────────────────────────────────────────────────────────

def test_offer_recovery_restores_pending_edit_on_load(qtbot, settings_files, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))

    rec_dir = settings_files["tmp"] / ".rag_cache" / "settings_recovery"
    rec_dir.mkdir(parents=True)
    (rec_dir / "config.txt.recovery").write_text("RECOVERED=1\n", encoding="utf-8")

    tab = _make_tab(settings_files, qtbot)

    tab.file_list.setCurrentRow(_row_for(tab, "config.txt"))
    qtbot.waitUntil(lambda: tab.content_view.toPlainText() == "RECOVERED=1\n", timeout=3000)
    assert tab._edit_mode is True
