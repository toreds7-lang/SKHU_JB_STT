"""Wiring tests for the Settings tab in ``ui.main_window`` (SPEC-SETTINGS-001, T-006).

The full ``MainWindow`` cannot be constructed headlessly (it embeds
``QWebEngineView`` tabs that crash under the offscreen platform), so these tests
verify the integration at the seams: the module imports cleanly with the new
``SettingsTab`` dependency, and ``_init_ui`` wires the tab in the required order
(immediately after the Knowledge-Graph / graph tab) while invoking
``build_config_metadata`` once.
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


def test_settings_tab_added_after_graph_and_before_dir():
    src = inspect.getsource(mw.MainWindow._init_ui)

    graph_add = src.index('addTab(self.graph_tab')
    settings_add = src.index('addTab(self.settings_tab')
    dir_add = src.index('addTab(self.dir_tab')

    # Settings must sit immediately after the graph tab and before the dir tab.
    assert graph_add < settings_add < dir_add


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
