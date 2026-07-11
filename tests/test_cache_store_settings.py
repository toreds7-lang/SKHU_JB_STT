"""Specification tests for ``cache_store.SettingsChatCache`` (SPEC-SETTINGS-001 §4.2).

Modeled directly on ``ChatCache``: JSONL, append-only, no file created until
the first ``add()``, and deleted again once emptied.
"""

from cache_store import SettingsChatCache


def test_add_persists_entry(tmp_path):
    cache = SettingsChatCache(str(tmp_path))
    entry_id = cache.add("config.txt", "VECTOR_K이 뭐야?", "Vector retriever top-k입니다.")

    entries = cache.load()
    assert len(entries) == 1
    assert entries[0]["id"] == entry_id
    assert entries[0]["file"] == "config.txt"
    assert entries[0]["question"] == "VECTOR_K이 뭐야?"
    assert entries[0]["answer"] == "Vector retriever top-k입니다."
    assert "ts" in entries[0]


def test_add_appends_multiple_entries_in_order(tmp_path):
    cache = SettingsChatCache(str(tmp_path))
    cache.add("config.txt", "q1", "a1")
    cache.add("env.txt", "q2", "a2")

    entries = cache.load()
    assert [e["question"] for e in entries] == ["q1", "q2"]


def test_no_file_created_until_first_add(tmp_path):
    cache = SettingsChatCache(str(tmp_path))
    assert not cache.path.exists()
    assert cache.load() == []


def test_file_created_on_disk_after_add(tmp_path):
    cache = SettingsChatCache(str(tmp_path))
    cache.add("config.txt", "q", "a")
    assert cache.path.exists()
    assert cache.path.name == "settings_chat.jsonl"


def test_clear_removes_file(tmp_path):
    cache = SettingsChatCache(str(tmp_path))
    cache.add("config.txt", "q", "a")
    assert cache.path.exists()

    cache.clear()
    assert not cache.path.exists()
    assert cache.load() == []


def test_clear_on_nonexistent_cache_is_a_noop(tmp_path):
    cache = SettingsChatCache(str(tmp_path))
    cache.clear()  # must not raise
    assert cache.load() == []


def test_load_ignores_malformed_lines(tmp_path):
    cache = SettingsChatCache(str(tmp_path))
    cache.add("config.txt", "q1", "a1")
    with open(cache.path, "a", encoding="utf-8") as f:
        f.write("not valid json\n")
    cache.add("config.txt", "q2", "a2")

    entries = cache.load()
    assert [e["question"] for e in entries] == ["q1", "q2"]


def test_add_preserves_unicode(tmp_path):
    cache = SettingsChatCache(str(tmp_path))
    cache.add("prompts/system_prompt.txt", "이 프롬프트는 뭐하는거야?", "한국어로 답변합니다.")

    entries = cache.load()
    assert entries[0]["question"] == "이 프롬프트는 뭐하는거야?"
    assert entries[0]["answer"] == "한국어로 답변합니다."
