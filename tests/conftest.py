"""Shared pytest fixtures for SPEC-SETTINGS-001 Phase 0 + Phase 1 tests.

The project root is added to sys.path so the top-level modules (``rag_core``,
``workers.*``, ``ui.*``) import cleanly when tests run from any cwd. Qt tests
run under the ``offscreen`` platform so no real display is required.
"""

import os
import sys

import pytest

# ── Make top-level project modules importable ────────────────────────────────
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ── Qt must run headless in CI / test environments ───────────────────────────
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# ``ui.main_window`` transitively imports QtWebEngineWidgets (via ui.chat_tab).
# Qt requires AA_ShareOpenGLContexts to be set (or QtWebEngineWidgets imported)
# before any QApplication is created, otherwise the import raises. Setting it at
# conftest import time — before pytest-qt spins up its QApplication — keeps the
# main_window import safe regardless of test execution order.
from PyQt6.QtCore import QCoreApplication, Qt  # noqa: E402

QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)


@pytest.fixture
def settings_files(tmp_path, monkeypatch):
    """Create temp env.txt / config.txt / prompts dir and point rag_core at them.

    Returns a dict of the created paths so tests can inspect / mutate them.
    ``rag_core`` module-level path constants are monkeypatched so a bare
    ``build_config_metadata()`` call (no args) resolves to these temp files.
    """
    import rag_core

    env_file = tmp_path / "env.txt"
    env_file.write_text(
        "# environment settings\n"
        "\n"
        "OPENAI_API_KEY=sk-test-123\n"
        "LLM_MODEL=gpt-4o\n"
        "CUSTOM_ENV_KEY=hello\n",
        encoding="utf-8",
    )

    config_file = tmp_path / "config.txt"
    config_file.write_text(
        "# rag config\n"
        "VECTOR_K=7\n"
        "GRAPH_HOPS=3\n"
        "MAX_DOCS=12\n"
        "MY_CUSTOM_KEY=123\n",
        encoding="utf-8",
    )

    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    # Only two of the seven known prompt files exist on disk.
    (prompts_dir / "system_prompt.txt").write_text("system prompt body", encoding="utf-8")
    (prompts_dir / "force_prompt.txt").write_text("force prompt body", encoding="utf-8")

    monkeypatch.setattr(rag_core, "_SETTINGS_ENV_PATH", str(env_file))
    monkeypatch.setattr(rag_core, "_SETTINGS_CONFIG_PATH", str(config_file))
    monkeypatch.setattr(rag_core, "_SETTINGS_PROMPTS_DIR", str(prompts_dir))

    return {
        "env": env_file,
        "config": config_file,
        "prompts_dir": prompts_dir,
        "tmp": tmp_path,
    }
