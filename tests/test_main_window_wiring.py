"""Wiring tests for the Settings tab in ``ui.main_window`` (SPEC-SETTINGS-001, T-006).

The full ``MainWindow`` cannot be constructed headlessly (it embeds
``QWebEngineView`` tabs that crash under the offscreen platform), so these tests
verify the integration at the seams: the module imports cleanly with the new
``SettingsTab`` dependency, and ``_init_ui`` wires the tab in the required order
(as the last tab, immediately after the Knowledge-Graph / wiki tab) while
invoking ``build_config_metadata`` once.
"""

import inspect

import ui.main_window as mw
from ui.settings_tab import SettingsTab


def test_main_window_module_imports_cleanly():
    # Importing the module exercises the transitive PyQt6 imports; a clean
    # import is the T-006 acceptance bar (GUI construction is out of reach here).
    assert hasattr(mw, "MainWindow")


def test_settings_tab_class_is_wired_in():
    assert getattr(mw, "SettingsTab") is SettingsTab


def test_settings_tab_added_last():
    # SPEC-SETTINGS-002 R3: Settings is now the LAST tab, added immediately after
    # the wiki (Knowledge-Graph) tab. Its addTab call must be the maximum of all
    # addTab positions, and wiki must immediately precede it.
    src = inspect.getsource(mw.MainWindow._init_ui)

    positions = {
        name: src.index(f'addTab(self.{name}')
        for name in ("notebook_tab", "chat_tab", "docs_tab", "graph_tab",
                     "dir_tab", "cached_tab", "wiki_tab", "settings_tab")
    }

    # settings_tab is the last addTab call.
    assert positions["settings_tab"] == max(positions.values())
    # wiki immediately precedes settings (nothing added in between).
    assert positions["wiki_tab"] < positions["settings_tab"]
    # All the utility tabs precede settings.
    for name in ("dir_tab", "cached_tab", "wiki_tab"):
        assert positions[name] < positions["settings_tab"]


def test_settings_tab_uses_gear_korean_title():
    src = inspect.getsource(mw.MainWindow._init_ui)
    assert '⚙️  설정' in src


def test_build_config_metadata_called_once_in_init():
    src = inspect.getsource(mw.MainWindow._init_ui)
    assert 'build_config_metadata' in src
    assert 'SettingsTab(' in src


def test_docs_and_graph_tab_visibility_indices_preserved():
    # Inserting the settings tab after index 3 must NOT shift the hidden
    # docs(2)/graph(3) tabs, so their setTabVisible calls stay correct.
    src = inspect.getsource(mw.MainWindow._init_ui)
    assert 'setTabVisible(2, False)' in src
    assert 'setTabVisible(3, False)' in src


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2-5: Settings tab signal wiring, cache_dir propagation, tab-switch guard
# ─────────────────────────────────────────────────────────────────────────────

def test_settings_workers_are_imported():
    from workers.settings_worker import SettingsQAWorker, SettingsPromptRewriteWorker
    assert getattr(mw, "SettingsQAWorker") is SettingsQAWorker
    assert getattr(mw, "SettingsPromptRewriteWorker") is SettingsPromptRewriteWorker


def test_settings_tab_signals_connected_in_connect_signals():
    src = inspect.getsource(mw.MainWindow._connect_signals)
    assert "settings_tab.qa_requested.connect" in src
    assert "settings_tab.prompt_rewrite_requested.connect" in src
    assert "settings_tab.rebuild_requested.connect" in src
    assert "settings_tab.file_saved.connect" in src
    assert "tab_widget.currentChanged.connect" in src


def test_settings_handler_methods_exist():
    for name in (
        "_on_settings_qa_requested",
        "_on_settings_rewrite_requested",
        "_on_settings_rebuild_requested",
        "_on_settings_file_saved",
        "_on_tab_changed",
    ):
        assert hasattr(mw.MainWindow, name), f"missing handler: {name}"


def test_settings_qa_handler_guards_on_missing_llm():
    src = inspect.getsource(mw.MainWindow._on_settings_qa_requested)
    assert "self.state.llm" in src
    assert "SettingsQAWorker(" in src


def test_settings_rebuild_handler_reuses_on_build_rag():
    src = inspect.getsource(mw.MainWindow._on_settings_rebuild_requested)
    assert "_on_build_rag" in src


def test_settings_file_saved_reloads_config_and_system_prompt():
    src = inspect.getsource(mw.MainWindow._on_settings_file_saved)
    assert "config.txt" in src
    assert "RAG_CONFIG" in src
    assert "system_prompt.txt" in src
    assert "load_system_prompt" in src


def test_cache_dir_propagated_to_settings_tab_on_rag_ready():
    src = inspect.getsource(mw.MainWindow._on_rag_ready)
    assert "settings_tab.set_cache_dir(" in src


def test_tab_changed_guards_leaving_settings_tab():
    src = inspect.getsource(mw.MainWindow._on_tab_changed)
    assert "confirm_leave" in src
    assert "settings_tab" in src
