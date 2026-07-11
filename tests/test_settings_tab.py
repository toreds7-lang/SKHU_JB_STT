"""Specification tests for ``ui.settings_tab.SettingsTab``.

SPEC-SETTINGS-001 Phase 1 (F-SETTINGS-1, F-SETTINGS-2): a read-only file
browser. The left list shows the nine config files (missing ones grayed out but
still selectable); selecting one loads its raw content into a read-only viewer
with a "{path} · UTF-8" header. Missing files render a placeholder.
"""

from PyQt6.QtCore import Qt

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
    import rag_core
    metadata = rag_core.build_config_metadata(
        env_path=str(tmp_path / "missing_env.txt"),
        config_path=str(tmp_path / "missing_config.txt"),
        prompts_dir=str(tmp_path / "prompts"),
    )
    tab = SettingsTab(base_dir=str(tmp_path), config_metadata=metadata)
    qtbot.addWidget(tab)
    assert tab.file_list.count() == 9
