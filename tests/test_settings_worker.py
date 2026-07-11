"""Specification tests for ``workers.settings_worker`` (Phase 1-5).

- SettingsFileLoadWorker (Phase 1, F-SETTINGS-2/N-SETTINGS-1): async read-only
  file load. Success emits ``content_loaded(content, encoding)``; a missing /
  unreadable file emits ``error_signal(message)``.
- SettingsQAWorker (F-SETTINGS-3): streams an LLM answer given a pre-built
  prompt string.
- SettingsSaveWorker (F-SETTINGS-6): backs up the existing file, then writes
  the new content atomically.
- SettingsPromptRewriteWorker (F-SETTINGS-12): single blocking LLM call that
  returns the rewritten prompt text.
"""

from workers.settings_worker import (
    SettingsFileLoadWorker, SettingsQAWorker, SettingsSaveWorker,
    SettingsPromptRewriteWorker,
)


class _FakeChunk:
    def __init__(self, content):
        self.content = content


class _FakeResponse:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    """Minimal stand-in for ChatOpenAI — only .stream()/.invoke() are used."""

    def __init__(self, chunks=None, response_text="", raise_error=None):
        self._chunks = chunks or []
        self._response_text = response_text
        self._raise_error = raise_error

    def stream(self, messages):
        if self._raise_error:
            raise self._raise_error
        for c in self._chunks:
            yield _FakeChunk(c)

    def invoke(self, messages):
        if self._raise_error:
            raise self._raise_error
        return _FakeResponse(self._response_text)


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


# ─────────────────────────────────────────────────────────────────────────────
# SettingsQAWorker (F-SETTINGS-3)
# ─────────────────────────────────────────────────────────────────────────────

def test_qa_worker_streams_chunks_and_finishes(qapp):
    llm = _FakeLLM(chunks=["안", "녕"])
    worker = SettingsQAWorker(llm, "prompt text")

    chunks: list[str] = []
    finals: list[str] = []
    worker.chunk_received.connect(chunks.append)
    worker.finished_signal.connect(finals.append)

    worker.run()

    assert chunks == ["안", "녕"]
    assert finals == ["안녕"]


def test_qa_worker_error_emits_error_signal(qapp):
    llm = _FakeLLM(raise_error=RuntimeError("boom"))
    worker = SettingsQAWorker(llm, "prompt text")

    errors: list[str] = []
    worker.error_signal.connect(errors.append)

    worker.run()

    assert errors == ["boom"]


def test_qa_worker_stop_halts_streaming(qapp):
    llm = _FakeLLM(chunks=["a", "b", "c"])
    worker = SettingsQAWorker(llm, "prompt text")
    worker.stop()

    chunks: list[str] = []
    worker.chunk_received.connect(chunks.append)
    worker.run()

    assert chunks == []


# ─────────────────────────────────────────────────────────────────────────────
# SettingsSaveWorker (F-SETTINGS-6)
# ─────────────────────────────────────────────────────────────────────────────

def test_save_worker_writes_new_content(qapp, tmp_path):
    target = tmp_path / "config.txt"
    target.write_text("VECTOR_K=5\n", encoding="utf-8")
    cache_dir = tmp_path / ".rag_cache"

    worker = SettingsSaveWorker(str(target), "VECTOR_K=10\n", str(cache_dir))
    finished: list[str] = []
    worker.save_finished.connect(finished.append)

    worker.run()

    assert finished == [str(target)]
    assert target.read_text(encoding="utf-8") == "VECTOR_K=10\n"


def test_save_worker_creates_backup_of_existing_file(qapp, tmp_path):
    target = tmp_path / "config.txt"
    target.write_text("VECTOR_K=5\n", encoding="utf-8")
    cache_dir = tmp_path / ".rag_cache"

    worker = SettingsSaveWorker(str(target), "VECTOR_K=10\n", str(cache_dir))
    worker.run()

    backups = list((cache_dir / "backups").glob("config.txt.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "VECTOR_K=5\n"


def test_save_worker_no_backup_when_file_did_not_exist(qapp, tmp_path):
    target = tmp_path / "prompts" / "system_prompt.txt"
    cache_dir = tmp_path / ".rag_cache"

    worker = SettingsSaveWorker(str(target), "new prompt text", str(cache_dir))
    worker.run()

    assert target.read_text(encoding="utf-8") == "new prompt text"
    backup_dir = cache_dir / "backups"
    assert not backup_dir.exists() or list(backup_dir.iterdir()) == []


def test_save_worker_error_on_unwritable_path(qapp, tmp_path):
    # A directory path can't be written to as a file — should surface via error_signal.
    target = tmp_path / "a_directory"
    target.mkdir()
    cache_dir = tmp_path / ".rag_cache"

    worker = SettingsSaveWorker(str(target), "text", str(cache_dir))
    errors: list[str] = []
    worker.error_signal.connect(errors.append)

    worker.run()

    assert len(errors) == 1


# ─────────────────────────────────────────────────────────────────────────────
# SettingsPromptRewriteWorker (F-SETTINGS-12)
# ─────────────────────────────────────────────────────────────────────────────

def test_rewrite_worker_emits_new_prompt_text(qapp):
    llm = _FakeLLM(response_text="  rewritten prompt  ")
    worker = SettingsPromptRewriteWorker(llm, "rewrite this prompt")

    finals: list[str] = []
    worker.finished_signal.connect(finals.append)

    worker.run()

    assert finals == ["rewritten prompt"]


def test_rewrite_worker_error_emits_error_signal(qapp):
    llm = _FakeLLM(raise_error=RuntimeError("llm down"))
    worker = SettingsPromptRewriteWorker(llm, "rewrite this prompt")

    errors: list[str] = []
    worker.error_signal.connect(errors.append)

    worker.run()

    assert errors == ["llm down"]
