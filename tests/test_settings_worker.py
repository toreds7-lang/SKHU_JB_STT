"""Specification tests for ``workers.settings_worker.SettingsFileLoadWorker``.

SPEC-SETTINGS-001 Phase 1 (F-SETTINGS-2, N-SETTINGS-1): file content is read off
the UI thread. Success emits ``content_loaded(content, encoding)``; a missing /
unreadable file emits ``error_signal(message)``. The worker is read-only.
"""

from workers.settings_worker import SettingsFileLoadWorker


def test_successful_load_emits_content_loaded(qtbot, tmp_path):
    sample = tmp_path / "config.txt"
    sample.write_text("VECTOR_K=5\nBM25_K=5\n", encoding="utf-8")

    worker = SettingsFileLoadWorker(str(sample))
    with qtbot.waitSignal(worker.content_loaded, timeout=3000) as blocker:
        worker.start()
    worker.wait()

    content, encoding = blocker.args
    assert content == "VECTOR_K=5\nBM25_K=5\n"
    assert encoding == "UTF-8"


def test_load_preserves_unicode(qtbot, tmp_path):
    sample = tmp_path / "system_prompt.txt"
    sample.write_text("당신은 친절한 AI 튜터입니다.\n", encoding="utf-8")

    worker = SettingsFileLoadWorker(str(sample))
    with qtbot.waitSignal(worker.content_loaded, timeout=3000) as blocker:
        worker.start()
    worker.wait()

    content, _ = blocker.args
    assert content == "당신은 친절한 AI 튜터입니다.\n"


def test_missing_file_emits_error_signal(qtbot, tmp_path):
    missing = tmp_path / "does_not_exist.txt"

    worker = SettingsFileLoadWorker(str(missing))
    with qtbot.waitSignal(worker.error_signal, timeout=3000) as blocker:
        worker.start()
    worker.wait()

    assert blocker.args[0]  # non-empty error message


def test_success_path_never_emits_error(qtbot, tmp_path):
    sample = tmp_path / "env.txt"
    sample.write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")

    worker = SettingsFileLoadWorker(str(sample))
    errors: list[str] = []
    worker.error_signal.connect(errors.append)

    with qtbot.waitSignal(worker.content_loaded, timeout=3000):
        worker.start()
    worker.wait()
    qtbot.wait(50)  # flush any stray queued signals

    assert errors == []


def test_missing_file_never_emits_content(qtbot, tmp_path):
    worker = SettingsFileLoadWorker(str(tmp_path / "nope.txt"))
    contents: list[str] = []
    worker.content_loaded.connect(lambda c, e: contents.append(c))

    with qtbot.waitSignal(worker.error_signal, timeout=3000):
        worker.start()
    worker.wait()
    qtbot.wait(50)

    assert contents == []


# ── Synchronous run() coverage ───────────────────────────────────────────────
# coverage.py cannot trace code executed inside a QThread, so exercise the run()
# body directly on the main thread (still a valid unit test of the read logic).

def test_run_directly_emits_content(qapp, tmp_path):
    sample = tmp_path / "config.txt"
    sample.write_text("GRAPH_K=5\n", encoding="utf-8")

    worker = SettingsFileLoadWorker(str(sample))
    received: list[tuple[str, str]] = []
    worker.content_loaded.connect(lambda c, e: received.append((c, e)))

    worker.run()

    assert received == [("GRAPH_K=5\n", "UTF-8")]


def test_run_directly_missing_emits_error(qapp, tmp_path):
    worker = SettingsFileLoadWorker(str(tmp_path / "absent.txt"))
    errors: list[str] = []
    worker.error_signal.connect(errors.append)

    worker.run()

    assert len(errors) == 1
    assert "absent.txt" in errors[0]


def test_run_directly_read_failure_emits_error(qapp, tmp_path):
    # A directory path triggers an IsADirectoryError inside open(), which the
    # worker must surface via error_signal rather than propagating.
    a_dir = tmp_path / "a_directory"
    a_dir.mkdir()

    worker = SettingsFileLoadWorker(str(a_dir))
    errors: list[str] = []
    worker.error_signal.connect(errors.append)

    worker.run()

    assert len(errors) == 1
