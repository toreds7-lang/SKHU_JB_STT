"""Specification tests for ``rag_core.build_config_metadata()``.

SPEC-SETTINGS-001 Phase 0 (Metadata Infrastructure). These tests define the
contract of the config-metadata catalog: known keys get rich static metadata,
unknown keys pass through, missing files degrade to empty sections, and the
seven known prompt files are discovered with an existence flag.
"""

import inspect
import os
import re

import pytest

import rag_core


# ─────────────────────────────────────────────────────────────────────────────
# Return shape
# ─────────────────────────────────────────────────────────────────────────────

def test_returns_env_config_prompts_sections(settings_files):
    meta = rag_core.build_config_metadata()

    assert set(meta.keys()) == {"env", "config", "prompts"}
    assert isinstance(meta["env"], dict)
    assert isinstance(meta["config"], dict)
    assert isinstance(meta["prompts"], dict)


def test_accepts_explicit_path_arguments(settings_files):
    # The function must also accept explicit paths (not only monkeypatched
    # module constants) so callers/tests can target arbitrary files.
    meta = rag_core.build_config_metadata(
        env_path=str(settings_files["env"]),
        config_path=str(settings_files["config"]),
        prompts_dir=str(settings_files["prompts_dir"]),
    )
    assert "VECTOR_K" in meta["config"]
    assert "OPENAI_API_KEY" in meta["env"]


# ─────────────────────────────────────────────────────────────────────────────
# Known-key metadata (config)
# ─────────────────────────────────────────────────────────────────────────────

def test_known_config_key_has_rich_metadata(settings_files):
    vector_k = rag_core.build_config_metadata()["config"]["VECTOR_K"]

    assert vector_k["type"] == "int"
    assert vector_k["default"] == 5
    assert vector_k["min"] == 1
    assert vector_k["max"] == 20
    assert vector_k["category"] == "Retrieval"
    assert vector_k["known"] is True
    # Current value is read from the (temp) config.txt file.
    assert vector_k["value"] == "7"


def test_retriever_key_marked_affects_rebuild(settings_files):
    config = rag_core.build_config_metadata()["config"]
    # GRAPH_HOPS is one of the six retriever params that require a RAG rebuild.
    assert config["GRAPH_HOPS"]["affects_rebuild"] is True


def test_non_retriever_key_does_not_affect_rebuild(settings_files):
    config = rag_core.build_config_metadata()["config"]
    # MAX_DOCS changes context size but does not require an index rebuild.
    assert config["MAX_DOCS"]["affects_rebuild"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Known-key metadata (env)
# ─────────────────────────────────────────────────────────────────────────────

def test_known_env_api_key_metadata(settings_files):
    api_key = rag_core.build_config_metadata()["env"]["OPENAI_API_KEY"]

    assert api_key["category"] == "API"
    assert api_key["mask_in_ui"] is True
    assert api_key["required"] is True
    assert api_key["known"] is True
    assert api_key["value"] == "sk-test-123"


def test_env_value_reflects_file_content(settings_files):
    env = rag_core.build_config_metadata()["env"]
    assert env["LLM_MODEL"]["value"] == "gpt-4o"


# ─────────────────────────────────────────────────────────────────────────────
# Unknown-key pass-through (must NOT error / reject)
# ─────────────────────────────────────────────────────────────────────────────

def test_unknown_config_key_passes_through(settings_files):
    config = rag_core.build_config_metadata()["config"]

    assert "MY_CUSTOM_KEY" in config
    assert config["MY_CUSTOM_KEY"]["known"] is False
    assert config["MY_CUSTOM_KEY"]["value"] == "123"


def test_unknown_env_key_passes_through(settings_files):
    env = rag_core.build_config_metadata()["env"]

    assert "CUSTOM_ENV_KEY" in env
    assert env["CUSTOM_ENV_KEY"]["known"] is False
    assert env["CUSTOM_ENV_KEY"]["value"] == "hello"


# ─────────────────────────────────────────────────────────────────────────────
# Missing files degrade gracefully to empty sections (no raise)
# ─────────────────────────────────────────────────────────────────────────────

def test_missing_env_file_returns_empty_section(tmp_path):
    meta = rag_core.build_config_metadata(
        env_path=str(tmp_path / "does_not_exist_env.txt"),
        config_path=str(tmp_path / "does_not_exist_config.txt"),
        prompts_dir=str(tmp_path / "no_prompts"),
    )
    assert meta["env"] == {}


def test_missing_config_file_returns_empty_section(tmp_path):
    meta = rag_core.build_config_metadata(
        env_path=str(tmp_path / "does_not_exist_env.txt"),
        config_path=str(tmp_path / "does_not_exist_config.txt"),
        prompts_dir=str(tmp_path / "no_prompts"),
    )
    assert meta["config"] == {}


# ─────────────────────────────────────────────────────────────────────────────
# Comments / blank lines are ignored
# ─────────────────────────────────────────────────────────────────────────────

def test_comment_and_blank_lines_ignored(settings_files):
    config = rag_core.build_config_metadata()["config"]
    # The '# rag config' comment line must not become a key.
    assert not any(k.startswith("#") for k in config)
    assert "" not in config


# ─────────────────────────────────────────────────────────────────────────────
# Prompt discovery distinguishes existing vs missing files
# ─────────────────────────────────────────────────────────────────────────────

def test_all_seven_prompt_files_listed(settings_files):
    prompts = rag_core.build_config_metadata()["prompts"]
    expected = {
        "system_prompt.txt",
        "force_prompt.txt",
        "agentic_planner_prompt.txt",
        "agentic_sufficiency_prompt.txt",
        "agentic_synthesis_prompt.txt",
        "notebook_chat_prompt.txt",
        "summary_prompt.txt",
    }
    assert expected == set(prompts.keys())


def test_prompt_discovery_marks_existing_files(settings_files):
    prompts = rag_core.build_config_metadata()["prompts"]
    assert prompts["system_prompt.txt"]["exists"] is True
    assert prompts["force_prompt.txt"]["exists"] is True


def test_prompt_discovery_marks_missing_files(settings_files):
    prompts = rag_core.build_config_metadata()["prompts"]
    # Only system_prompt.txt and force_prompt.txt were created by the fixture.
    assert prompts["summary_prompt.txt"]["exists"] is False
    assert prompts["agentic_planner_prompt.txt"]["exists"] is False


def test_prompt_entries_have_prompt_category(settings_files):
    prompts = rag_core.build_config_metadata()["prompts"]
    assert prompts["system_prompt.txt"]["category"] == "Prompt"
    assert prompts["system_prompt.txt"]["type"] == "file"


# ─────────────────────────────────────────────────────────────────────────────
# Function is not invoked at import time (must be called explicitly)
# ─────────────────────────────────────────────────────────────────────────────

def test_build_config_metadata_is_callable():
    assert callable(rag_core.build_config_metadata)


# ─────────────────────────────────────────────────────────────────────────────
# STT_MODEL metadata (Phase 2-5 gap fix — SPEC §2.2 F-SETTINGS-8 category map)
# ─────────────────────────────────────────────────────────────────────────────

def test_stt_model_is_known_config_key():
    entry = rag_core._CONFIG_METADATA_CATALOG["STT_MODEL"]
    assert entry["category"] == "STT"
    assert entry["default"] == "small"


def test_stt_model_reflected_in_built_metadata(tmp_path):
    config_file = tmp_path / "config.txt"
    config_file.write_text("STT_MODEL=medium\n", encoding="utf-8")
    meta = rag_core.build_config_metadata(
        env_path=str(tmp_path / "missing_env.txt"),
        config_path=str(config_file),
        prompts_dir=str(tmp_path / "prompts"),
    )
    assert meta["config"]["STT_MODEL"]["known"] is True
    assert meta["config"]["STT_MODEL"]["value"] == "medium"
    assert meta["config"]["STT_MODEL"]["category"] == "STT"


# ─────────────────────────────────────────────────────────────────────────────
# load_system_prompt()
# ─────────────────────────────────────────────────────────────────────────────

def test_load_system_prompt_returns_default_when_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    text = rag_core.load_system_prompt()
    assert "AI 튜터" in text


def test_load_system_prompt_reads_override_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "prompts").mkdir()
    (tmp_path / "prompts" / "system_prompt.txt").write_text("커스텀 프롬프트", encoding="utf-8")
    assert rag_core.load_system_prompt() == "커스텀 프롬프트"


# ─────────────────────────────────────────────────────────────────────────────
# find_config_key_in_question()
# ─────────────────────────────────────────────────────────────────────────────

def test_find_config_key_matches_known_key(settings_files):
    meta = rag_core.build_config_metadata()
    assert rag_core.find_config_key_in_question("VECTOR_K가 뭐야?", meta) == "VECTOR_K"


def test_find_config_key_is_case_insensitive(settings_files):
    meta = rag_core.build_config_metadata()
    assert rag_core.find_config_key_in_question("what does vector_k do", meta) == "VECTOR_K"


def test_find_config_key_returns_none_for_unknown(settings_files):
    meta = rag_core.build_config_metadata()
    assert rag_core.find_config_key_in_question("오늘 날씨 어때?", meta) is None


def test_find_config_key_prefers_longer_match(settings_files):
    meta = rag_core.build_config_metadata()
    # Both "GRAPH_K" and "GRAPH_HOPS" are known keys; a question naming the
    # longer/more specific key must not resolve to the shorter substring.
    assert rag_core.find_config_key_in_question("GRAPH_HOPS는 뭐야?", meta) == "GRAPH_HOPS"


# ─────────────────────────────────────────────────────────────────────────────
# build_settings_qa_prompt()
# ─────────────────────────────────────────────────────────────────────────────

def test_build_settings_qa_prompt_includes_authoritative_fields(settings_files):
    meta = rag_core.build_config_metadata()
    entry = meta["config"]["VECTOR_K"]
    prompt = rag_core.build_settings_qa_prompt("VECTOR_K가 뭐야?", "VECTOR_K", entry, entry["value"])
    assert "VECTOR_K" in prompt
    assert "1-20" in prompt
    assert "한국어" in prompt or "Korean" in prompt
    assert "Current value: 7" in prompt


# ─────────────────────────────────────────────────────────────────────────────
# mask_sensitive_value()
# ─────────────────────────────────────────────────────────────────────────────

def test_mask_sensitive_value_masks_when_flagged():
    entry = {"mask_in_ui": True}
    assert rag_core.mask_sensitive_value("OPENAI_API_KEY", "sk-abcdef123", entry) == "sk-***"


def test_mask_sensitive_value_passes_through_when_not_flagged():
    entry = {"mask_in_ui": False}
    assert rag_core.mask_sensitive_value("LLM_MODEL", "gpt-4o-mini", entry) == "gpt-4o-mini"


def test_mask_sensitive_value_handles_missing_entry():
    assert rag_core.mask_sensitive_value("ANYTHING", "value", None) == "value"


# ─────────────────────────────────────────────────────────────────────────────
# validate_kv_text()
# ─────────────────────────────────────────────────────────────────────────────

def test_validate_kv_text_accepts_valid_values(settings_files):
    section = rag_core.build_config_metadata()["config"]
    errors = rag_core.validate_kv_text("VECTOR_K=10\nMAX_DOCS=20\n", section)
    assert errors == []


def test_validate_kv_text_rejects_out_of_range_int(settings_files):
    section = rag_core.build_config_metadata()["config"]
    errors = rag_core.validate_kv_text("VECTOR_K=99\n", section)
    assert any("VECTOR_K" in e for e in errors)


def test_validate_kv_text_rejects_non_numeric_int(settings_files):
    section = rag_core.build_config_metadata()["config"]
    errors = rag_core.validate_kv_text("VECTOR_K=abc\n", section)
    assert any("정수" in e for e in errors)


def test_validate_kv_text_rejects_out_of_range_float(settings_files):
    section = rag_core.build_config_metadata()["config"]
    errors = rag_core.validate_kv_text("SEQ_DECAY=5.0\n", section)
    assert any("SEQ_DECAY" in e for e in errors)


def test_validate_kv_text_ignores_unknown_keys(settings_files):
    section = rag_core.build_config_metadata()["config"]
    errors = rag_core.validate_kv_text("MY_CUSTOM_KEY=anything goes\n", section)
    assert errors == []


def test_validate_kv_text_ignores_comments_and_blank_lines(settings_files):
    section = rag_core.build_config_metadata()["config"]
    errors = rag_core.validate_kv_text("# a comment\n\nVECTOR_K=5\n", section)
    assert errors == []


# ─────────────────────────────────────────────────────────────────────────────
# classify_config_changes()
# ─────────────────────────────────────────────────────────────────────────────

def test_classify_config_changes_detects_rebuild_affecting_key(settings_files):
    meta = rag_core.build_config_metadata()
    old_text = "VECTOR_K=5\nMAX_DOCS=10\n"
    new_text = "VECTOR_K=8\nMAX_DOCS=10\n"
    result = rag_core.classify_config_changes(old_text, new_text, meta)
    assert result["requires_rebuild"] is True
    assert "VECTOR_K" in result["affected_keys"]


def test_classify_config_changes_non_rebuild_key(settings_files):
    meta = rag_core.build_config_metadata()
    old_text = "MAX_DOCS=10\n"
    new_text = "MAX_DOCS=20\n"
    result = rag_core.classify_config_changes(old_text, new_text, meta)
    assert result["requires_rebuild"] is False
    assert result["affected_keys"] == ["MAX_DOCS"]


def test_classify_config_changes_flags_unknown_keys(settings_files):
    meta = rag_core.build_config_metadata()
    old_text = "MY_KEY=1\n"
    new_text = "MY_KEY=2\n"
    result = rag_core.classify_config_changes(old_text, new_text, meta)
    assert result["unknown_keys"] == ["MY_KEY"]
    assert result["requires_rebuild"] is False


def test_classify_config_changes_no_diff_is_empty(settings_files):
    meta = rag_core.build_config_metadata()
    text = "VECTOR_K=5\n"
    result = rag_core.classify_config_changes(text, text, meta)
    assert result == {"requires_rebuild": False, "affected_keys": [], "unknown_keys": []}


# ─────────────────────────────────────────────────────────────────────────────
# reset_config_defaults()
# ─────────────────────────────────────────────────────────────────────────────

def test_reset_config_defaults_resets_known_keys(settings_files):
    meta = rag_core.build_config_metadata()
    current = "VECTOR_K=99\nMAX_DOCS=50\n"
    result = rag_core.reset_config_defaults(current, meta)
    assert "VECTOR_K=5" in result
    assert "MAX_DOCS=10" in result


def test_reset_config_defaults_preserves_custom_keys(settings_files):
    meta = rag_core.build_config_metadata()
    current = "VECTOR_K=99\nMY_CUSTOM_KEY=keep-me\n"
    result = rag_core.reset_config_defaults(current, meta)
    assert "MY_CUSTOM_KEY=keep-me" in result


def test_reset_config_defaults_preserves_comments(settings_files):
    meta = rag_core.build_config_metadata()
    current = "# a helpful comment\nVECTOR_K=99\n"
    result = rag_core.reset_config_defaults(current, meta)
    assert "# a helpful comment" in result


# ─────────────────────────────────────────────────────────────────────────────
# build_prompt_rewrite_request()
# ─────────────────────────────────────────────────────────────────────────────

def test_build_prompt_rewrite_request_includes_all_parts():
    prompt = rag_core.build_prompt_rewrite_request(
        "Prompt", "RAG 채팅 기본 시스템 프롬프트.", "현재 프롬프트 텍스트", "더 간결하게 만들어줘"
    )
    assert "현재 프롬프트 텍스트" in prompt
    assert "더 간결하게 만들어줘" in prompt
    assert "prompt engineer" in prompt.lower()


# ═════════════════════════════════════════════════════════════════════════════
# SPEC-SETTINGS-003 — Settings reference document grounding
# ═════════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────────
# T1: load_settings_reference()  (REQ-013, REQ-011, NFR-3)
# ─────────────────────────────────────────────────────────────────────────────

def test_load_settings_reference_reads_override_path(tmp_path, monkeypatch):
    ref_file = tmp_path / "settings_reference.txt"
    ref_file.write_text("## PARAM: VECTOR_K\n무엇: top-k 문서 수.\n", encoding="utf-8")
    monkeypatch.setattr(rag_core, "_SETTINGS_REFERENCE_PATH", str(ref_file))

    text = rag_core.load_settings_reference()
    assert "## PARAM: VECTOR_K" in text
    assert "top-k" in text


def test_load_settings_reference_returns_empty_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        rag_core, "_SETTINGS_REFERENCE_PATH", str(tmp_path / "does_not_exist.txt")
    )
    assert rag_core.load_settings_reference() == ""


def test_load_settings_reference_never_raises_on_unreadable(tmp_path, monkeypatch):
    # A directory path is not a readable file — must degrade to "" not raise.
    monkeypatch.setattr(rag_core, "_SETTINGS_REFERENCE_PATH", str(tmp_path))
    assert rag_core.load_settings_reference() == ""


# ─────────────────────────────────────────────────────────────────────────────
# T2: find_reference_section()  (REQ-006)
# ─────────────────────────────────────────────────────────────────────────────

_SAMPLE_REFERENCE = (
    "# 헤더 서문 (섹션 아님)\n"
    "\n"
    "## PARAM: VECTOR_K\n"
    "무엇: Vector retriever top-k 문서 수.\n"
    "소비 위치: rag_core.build_rag_system().\n"
    "\n"
    "## PARAM: MAX_DOCS\n"
    "무엇: 최종 컨텍스트 최대 문서 수.\n"
    "소비 위치: rag_core.make_agent() 내부 merge_docs.\n"
    "\n"
    "## FILE: prompts/system_prompt.txt\n"
    "역할: RAG 채팅 기본 시스템 프롬프트.\n"
    "로더: rag_core.load_system_prompt().\n"
)


def test_find_reference_section_extracts_param_block():
    section = rag_core.find_reference_section(_SAMPLE_REFERENCE, "VECTOR_K")
    assert "## PARAM: VECTOR_K" in section
    assert "Vector retriever top-k" in section
    # Must stop at the next header — MAX_DOCS content must not bleed in.
    assert "MAX_DOCS" not in section


def test_find_reference_section_extracts_file_block():
    section = rag_core.find_reference_section(_SAMPLE_REFERENCE, "prompts/system_prompt.txt")
    assert "## FILE: prompts/system_prompt.txt" in section
    assert "load_system_prompt" in section


def test_find_reference_section_last_block_reaches_end():
    section = rag_core.find_reference_section(_SAMPLE_REFERENCE, "MAX_DOCS")
    assert "최종 컨텍스트 최대 문서 수" in section
    assert "merge_docs" in section


def test_find_reference_section_returns_empty_for_unknown():
    assert rag_core.find_reference_section(_SAMPLE_REFERENCE, "NONEXISTENT_KEY") == ""


def test_find_reference_section_returns_empty_for_empty_reference():
    assert rag_core.find_reference_section("", "VECTOR_K") == ""


def test_find_reference_section_is_case_sensitive_exact():
    # Exact-token match — a substring key like "VECTOR" must not match VECTOR_K.
    assert rag_core.find_reference_section(_SAMPLE_REFERENCE, "VECTOR") == ""


# ─────────────────────────────────────────────────────────────────────────────
# T3: build_settings_qa_prompt(reference_section=...) + grounded prompt
# (REQ-006, REQ-007, REQ-008)
# ─────────────────────────────────────────────────────────────────────────────

def test_build_settings_qa_prompt_backward_compatible_without_ref(settings_files):
    # Byte-identical output when the new arg is omitted (regression pin).
    meta = rag_core.build_config_metadata()
    entry = meta["config"]["VECTOR_K"]
    without = rag_core.build_settings_qa_prompt("VECTOR_K가 뭐야?", "VECTOR_K", entry, entry["value"])
    with_none = rag_core.build_settings_qa_prompt(
        "VECTOR_K가 뭐야?", "VECTOR_K", entry, entry["value"], reference_section=None
    )
    assert without == with_none


def test_build_settings_qa_prompt_appends_reference_section(settings_files):
    meta = rag_core.build_config_metadata()
    entry = meta["config"]["VECTOR_K"]
    section = "## PARAM: VECTOR_K\n무엇: 고유한 레퍼런스 마커 XYZZY.\n"
    prompt = rag_core.build_settings_qa_prompt(
        "VECTOR_K가 뭐야?", "VECTOR_K", entry, entry["value"], reference_section=section
    )
    # Authoritative metadata still present…
    assert "VECTOR_K" in prompt
    assert "Current value: 7" in prompt
    # …and the reference section text is appended.
    assert "XYZZY" in prompt


def test_build_settings_qa_prompt_empty_ref_stays_backward_compatible(settings_files):
    meta = rag_core.build_config_metadata()
    entry = meta["config"]["VECTOR_K"]
    without = rag_core.build_settings_qa_prompt("VECTOR_K가 뭐야?", "VECTOR_K", entry, entry["value"])
    with_empty = rag_core.build_settings_qa_prompt(
        "VECTOR_K가 뭐야?", "VECTOR_K", entry, entry["value"], reference_section=""
    )
    assert without == with_empty


def test_build_settings_qa_grounded_prompt_embeds_reference():
    ref = "## PARAM: VECTOR_K\n무엇: 고유마커 QUUX.\n## FILE: config.txt\n역할: RAG 하이퍼파라미터.\n"
    prompt = rag_core.build_settings_qa_grounded_prompt("이 파일들 차이가 뭐야?", ref)
    assert "이 파일들 차이가 뭐야?" in prompt
    assert "QUUX" in prompt


def test_build_settings_qa_grounded_prompt_has_no_hallucination_guard():
    ref = "## PARAM: VECTOR_K\n무엇: top-k.\n"
    prompt = rag_core.build_settings_qa_grounded_prompt("질문", ref)
    # Must instruct Korean-only, document-grounded answers and an "I don't know"
    # escape hatch when the answer is not in the document.
    assert "한국어" in prompt or "Korean" in prompt
    lowered = prompt.lower()
    assert "문서" in prompt
    assert ("모른" in prompt or "찾을 수 없" in prompt or "don't" in lowered or "do not" in lowered)


# ─────────────────────────────────────────────────────────────────────────────
# T4 + T5: settings_reference.txt authored document
# (REQ-001..REQ-005, NFR-5)
# ─────────────────────────────────────────────────────────────────────────────

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REFERENCE_FILE = os.path.join(_REPO_ROOT, "settings_reference.txt")


def _read_reference_doc() -> str:
    with open(_REFERENCE_FILE, encoding="utf-8") as f:
        return f.read()


def _iter_section_bodies(text: str):
    """Yield (header_token, [non-empty body lines]) for each ## PARAM:/## FILE: block."""
    lines = text.splitlines()
    current_token = None
    body: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") and (":" in stripped):
            if current_token is not None:
                yield current_token, body
            header = stripped[3:].strip()
            _, _, token = header.partition(":")
            current_token = token.strip()
            body = []
        elif current_token is not None and stripped:
            body.append(stripped)
    if current_token is not None:
        yield current_token, body


def test_reference_doc_exists_as_single_file():
    # AC-REQ-001: exactly one reference file at the project root.
    assert os.path.isfile(_REFERENCE_FILE)
    # No split-per-item companion files.
    assert not os.path.isdir(os.path.join(_REPO_ROOT, "settings_reference"))


def test_reference_doc_covers_all_24_params():
    # AC-REQ-002: 6 env + 18 config keys all appear as ## PARAM: headers.
    text = _read_reference_doc()
    keys = list(rag_core._ENV_METADATA_CATALOG) + list(rag_core._CONFIG_METADATA_CATALOG)
    assert len(keys) == 24
    for key in keys:
        section = rag_core.find_reference_section(text, key)
        assert section, f"missing ## PARAM: {key}"
        assert section.startswith(f"## PARAM: {key}")


def test_reference_doc_covers_all_9_files():
    # AC-REQ-003: the 9 SettingsTab.CONFIG_FILES all appear as ## FILE: headers.
    from ui.settings_tab import SettingsTab

    text = _read_reference_doc()
    assert len(SettingsTab.CONFIG_FILES) == 9
    for rel_path in SettingsTab.CONFIG_FILES:
        section = rag_core.find_reference_section(text, rel_path)
        assert section, f"missing ## FILE: {rel_path}"
        assert section.startswith(f"## FILE: {rel_path}")


def test_reference_doc_cited_symbols_exist_in_source():
    # AC-REQ-004: spot-checked consumer symbols must be real functions.
    import agentic_rag

    text = _read_reference_doc()
    for symbol in ("build_rag_system", "load_system_prompt",
                   "load_force_prompt", "load_summary_prompt"):
        assert symbol in text, f"expected {symbol} to be cited"
        assert callable(getattr(rag_core, symbol))
    for symbol in ("load_agentic_planner_prompt", "load_agentic_synthesis_prompt"):
        assert callable(getattr(agentic_rag, symbol))


def test_reference_doc_has_no_code_fences_or_indented_code():
    # AC-REQ-005: no ``` fences and no 4-space-indented code blocks.
    text = _read_reference_doc()
    assert "```" not in text
    for line in text.splitlines():
        # A line that is indented by >=4 spaces and non-empty would be a code block.
        if line and not line.strip() == "":
            assert not re.match(r"^ {4,}\S", line), f"indented code line: {line!r}"


def test_reference_doc_entries_are_prose_3_to_8_lines():
    # AC-REQ-005: each entry's prose body is between 3 and 8 lines.
    text = _read_reference_doc()
    bodies = list(_iter_section_bodies(text))
    assert bodies, "no sections parsed"
    for token, body in bodies:
        assert 3 <= len(body) <= 8, f"{token}: {len(body)} body lines (want 3-8)"


def test_reference_doc_openai_key_never_contains_real_key():
    # NFR-5: OPENAI_API_KEY entry explains what it is, never embeds a key value.
    text = _read_reference_doc()
    section = rag_core.find_reference_section(text, "OPENAI_API_KEY")
    assert section
    # No sk- prefixed secret-looking token in the whole document.
    assert not re.search(r"sk-[A-Za-z0-9]{16,}", text)
