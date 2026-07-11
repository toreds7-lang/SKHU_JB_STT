"""Specification tests for ``rag_core.build_config_metadata()``.

SPEC-SETTINGS-001 Phase 0 (Metadata Infrastructure). These tests define the
contract of the config-metadata catalog: known keys get rich static metadata,
unknown keys pass through, missing files degrade to empty sections, and the
seven known prompt files are discovered with an existence flag.
"""

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
