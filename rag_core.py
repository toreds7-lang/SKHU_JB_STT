"""
RAG Core 비즈니스 로직
- 노트북 파싱, FAISS, BM25, Graph RAG, LangGraph Agent
- UI 의존성 없음 (Streamlit 제거)
"""

import os
import sys
import json
import re
import glob
import hashlib
import pickle
import operator
import shutil
from pathlib import Path
from typing import Any, TypedDict, Annotated, Optional

import nbformat

# ── LangChain / LangGraph ─────────────────────────────────────────────────────
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END

# ── NetworkX (Graph RAG) ──────────────────────────────────────────────────────
import networkx as nx


# ─────────────────────────────────────────────────────────────────────────────
# 환경 설정 로더
# ─────────────────────────────────────────────────────────────────────────────

def _load_env_txt(path: str = "env.txt") -> dict[str, str]:
    """env.txt 파일에서 KEY=VALUE 형태의 설정을 읽어 os.environ에 반영."""
    env_vars = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key, value = key.strip(), value.strip()
                    env_vars[key] = value
                    os.environ.setdefault(key, value)
    return env_vars


_load_env_txt("env.txt")


# ─────────────────────────────────────────────────────────────────────────────
# RAG 파라미터 설정 로더 (config.txt)
# ─────────────────────────────────────────────────────────────────────────────

def _load_config(path: str = "config.txt") -> dict[str, str]:
    """config.txt에서 KEY=VALUE 형태의 RAG 파라미터를 읽어 dict로 반환."""
    cfg: dict[str, str] = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    cfg[key.strip()] = value.strip()
    return cfg


RAG_CONFIG = _load_config()


def _is_trace_debug() -> bool:
    """TRACE_DEBUG 설정이 true인지 확인."""
    return RAG_CONFIG.get("TRACE_DEBUG", "false").lower() == "true"


# ─────────────────────────────────────────────────────────────────────────────
# Settings Metadata Catalog (SPEC-SETTINGS-001 Phase 0)
# ─────────────────────────────────────────────────────────────────────────────
#
# build_config_metadata() parses env.txt / config.txt and discovers the prompt
# files, attaching a documented static catalog (type/category/default/range/
# description/affects_rebuild) to known keys while letting unknown keys pass
# through. It is intentionally NOT called at import time — MainWindow invokes it
# explicitly and hands the result to the Settings tab.

# Overridable path constants (monkeypatched in tests / passed explicitly by
# callers). Kept separate from the _load_env_txt / _load_config default args so
# existing startup behavior is untouched.
_SETTINGS_ENV_PATH = "env.txt"
_SETTINGS_CONFIG_PATH = "config.txt"
_SETTINGS_PROMPTS_DIR = "prompts"

# Documented env.txt parameters (SPEC §4, §2.2 F-SETTINGS-8 category mapping).
_ENV_METADATA_CATALOG: dict[str, dict] = {
    "OPENAI_API_KEY": {
        "type": "str", "required": True, "category": "API", "default": None,
        "description": "OpenAI API 키 (sk-...). 임베딩과 LLM 호출에 필요합니다.",
        "mask_in_ui": True,
    },
    "LLM_MODEL": {
        "type": "str", "required": False, "category": "API", "default": "gpt-4o-mini",
        "description": "LLM 모델 이름 (gpt-4o-mini, gpt-4o 등).",
        "mask_in_ui": False,
    },
    "LLM_BASE_URL": {
        "type": "str", "required": False, "category": "API", "default": "",
        "description": "LLM API 엔드포인트. 비워두면 OpenAI, 로컬 서버(Ollama 등) 사용 시 설정.",
        "mask_in_ui": False,
    },
    "EMBEDDING_MODEL": {
        "type": "str", "required": False, "category": "API", "default": "text-embedding-ada-002",
        "description": "임베딩 모델 이름.",
        "mask_in_ui": False,
    },
    "EMBEDDING_BASE_URL": {
        "type": "str", "required": False, "category": "API", "default": "",
        "description": "임베딩 API 엔드포인트. 비워두면 LLM_BASE_URL/OpenAI를 따릅니다.",
        "mask_in_ui": False,
    },
    "FORCE_WORKERS": {
        "type": "int", "required": False, "category": "STT", "default": 3,
        "min": 1, "max": 10,
        "description": "Force Mode 병렬 워커 수 (1-10).",
        "mask_in_ui": False,
    },
}

# Retriever parameters whose change requires a full RAG index rebuild (SPEC
# §6.1). Only these six trigger the rebuild-confirmation dialog in later phases.
_REBUILD_AFFECTING_KEYS = frozenset({
    "VECTOR_K", "BM25_K", "GRAPH_K", "GRAPH_HOPS", "SEQ_DECAY", "VAR_DECAY",
})

# Documented config.txt parameters (SPEC §4, config.txt table + F-SETTINGS-5 ranges).
_CONFIG_METADATA_CATALOG: dict[str, dict] = {
    "VECTOR_K":        {"type": "int",   "category": "Retrieval", "default": 5,   "min": 1,   "max": 20,  "description": "Vector retriever가 반환하는 top-k 문서 수."},
    "BM25_K":          {"type": "int",   "category": "Retrieval", "default": 5,   "min": 1,   "max": 20,  "description": "BM25 retriever가 반환하는 top-k 문서 수."},
    "GRAPH_K":         {"type": "int",   "category": "Retrieval", "default": 5,   "min": 1,   "max": 20,  "description": "Graph RAG가 반환하는 top-k 문서 수."},
    "GRAPH_HOPS":      {"type": "int",   "category": "Retrieval", "default": 2,   "min": 1,   "max": 5,   "description": "Graph RAG multi-hop 전파 깊이."},
    "SEQ_DECAY":       {"type": "float", "category": "Retrieval", "default": 0.5, "min": 0.0, "max": 1.0, "description": "인접 셀(sequential) 엣지 감쇠 계수."},
    "VAR_DECAY":       {"type": "float", "category": "Retrieval", "default": 0.8, "min": 0.0, "max": 1.0, "description": "변수 공유(shared_var) 엣지 감쇠 계수."},
    "KEYWORD_BOOST":   {"type": "float", "category": "Retrieval", "default": 0.4, "min": 0.0, "max": 1.0, "description": "키워드 보조 점수 부스트 계수."},
    "SEED_COUNT":      {"type": "int",   "category": "Retrieval", "default": 3,   "min": 1,   "max": 10,  "description": "Graph RAG 시작점이 되는 vector seed 문서 수."},
    "VECTOR_WEIGHT":   {"type": "float", "category": "Retrieval", "default": 0.6, "min": 0.0, "max": 1.0, "description": "앙상블에서 Vector 가중치 (BM25_WEIGHT와 합이 1.0)."},
    "BM25_WEIGHT":     {"type": "float", "category": "Retrieval", "default": 0.4, "min": 0.0, "max": 1.0, "description": "앙상블에서 BM25 가중치 (VECTOR_WEIGHT와 합이 1.0)."},
    "MAX_DOCS":        {"type": "int",   "category": "Retrieval", "default": 10,  "min": 1,   "max": 50,  "description": "최종 컨텍스트에 포함할 최대 문서 수."},
    "LLM_TEMPERATURE": {"type": "float", "category": "LLM",       "default": 0.2, "min": 0.0, "max": 2.0, "description": "LLM 응답 temperature (낮을수록 결정적)."},
    "TRACE_DEBUG":     {"type": "bool",  "category": "Debug",     "default": False, "description": "true이면 쿼리별 retriever 결과를 trace_logs/에 저장."},
    "AGENTIC_MAX_ITERS":    {"type": "int", "category": "Agentic", "default": 3,  "min": 1, "max": 10,  "description": "Agentic Mode 검색→평가→보강 최대 반복 횟수."},
    "AGENTIC_FANOUT_K":     {"type": "int", "category": "Agentic", "default": 5,  "min": 1, "max": 20,  "description": "Agentic Mode 검색어당 top-k."},
    "AGENTIC_MAX_SNIPPETS": {"type": "int", "category": "Agentic", "default": 24, "min": 1, "max": 100, "description": "Agentic Mode 누적 근거 상한."},
    "AGENTIC_MAX_QUERIES":  {"type": "int", "category": "Agentic", "default": 8,  "min": 1, "max": 20,  "description": "Agentic Mode 한 패스 검색어 수 상한."},
}

# Documented prompt files under prompts/ (SPEC F-SETTINGS-1). These seven are a
# fixed catalog — build_config_metadata() reports each with an 'exists' flag so
# the UI can distinguish files present on disk from those using built-in defaults.
_PROMPT_METADATA_CATALOG: dict[str, str] = {
    "system_prompt.txt":              "RAG 채팅 기본 시스템 프롬프트.",
    "force_prompt.txt":               "Force Mode 관련성 판단 프롬프트.",
    "agentic_planner_prompt.txt":     "Agentic Mode 계획/질의 재작성 프롬프트.",
    "agentic_sufficiency_prompt.txt": "Agentic Mode 충분성 게이트 프롬프트.",
    "agentic_synthesis_prompt.txt":   "Agentic Mode 합성(답변) 프롬프트.",
    "notebook_chat_prompt.txt":       "노트북 셀 채팅 프롬프트.",
    "summary_prompt.txt":             "노트북 요약 프롬프트.",
}


def _parse_kv_file(path: str) -> dict[str, str]:
    """Parse a KEY=VALUE settings file, preserving insertion order.

    Returns an empty dict when the file is missing (never raises). Blank lines
    and '#' comment lines are ignored — same convention as _load_config().
    """
    result: dict[str, str] = {}
    if not path or not os.path.exists(path):
        return result
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                result[key.strip()] = value.strip()
    return result


def _build_kv_section(parsed: dict[str, str], catalog: dict[str, dict],
                      rebuild_keys: "frozenset[str]" = frozenset()) -> dict[str, dict]:
    """Merge parsed KEY=VALUE pairs with a static metadata catalog.

    Known keys receive a copy of their catalog metadata (the catalog is never
    mutated); unknown keys pass through with minimal inferred metadata. Every
    entry carries its current 'value' (as read from disk) and a 'known' flag.
    """
    section: dict[str, dict] = {}
    for key, value in parsed.items():
        if key in catalog:
            entry = dict(catalog[key])
            entry["known"] = True
            entry.setdefault("affects_rebuild", key in rebuild_keys)
        else:
            entry = {
                "type": "str",
                "category": "Other",
                "default": None,
                "description": "",
                "known": False,
                "affects_rebuild": False,
            }
        entry["value"] = value
        section[key] = entry
    return section


def build_config_metadata(env_path: str | None = None,
                          config_path: str | None = None,
                          prompts_dir: str | None = None) -> dict[str, dict]:
    """Build the settings-metadata catalog for the Settings tab (SPEC §4).

    Parses env.txt and config.txt, attaches documented metadata to known keys,
    passes unknown keys through unchanged, and discovers the seven prompt files
    (each flagged as existing or missing). Missing env.txt / config.txt yield an
    empty section rather than raising. This function is NOT invoked at import
    time — MainWindow calls it explicitly and passes the result to SettingsTab.

    Returns: {'env': {...}, 'config': {...}, 'prompts': {...}}
    """
    env_path = env_path if env_path is not None else _SETTINGS_ENV_PATH
    config_path = config_path if config_path is not None else _SETTINGS_CONFIG_PATH
    prompts_dir = prompts_dir if prompts_dir is not None else _SETTINGS_PROMPTS_DIR

    env_section = _build_kv_section(_parse_kv_file(env_path), _ENV_METADATA_CATALOG)
    config_section = _build_kv_section(
        _parse_kv_file(config_path), _CONFIG_METADATA_CATALOG, _REBUILD_AFFECTING_KEYS
    )

    prompts_section: dict[str, dict] = {}
    for filename, description in _PROMPT_METADATA_CATALOG.items():
        prompts_section[filename] = {
            "type": "file",
            "category": "Prompt",
            "description": description,
            "affects_rebuild": False,
            "known": True,
            "exists": os.path.exists(os.path.join(prompts_dir, filename)),
        }

    return {"env": env_section, "config": config_section, "prompts": prompts_section}


# ── 한국어 형태소 분석 ────────────────────────────────────────────────────────
def _path_is_ascii(p: str) -> bool:
    try:
        p.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _try_short_path(p: str) -> str:
    """Windows 8.3 단축경로 시도. 8dot3name 비활성화 등으로 실패하면 원본 반환."""
    if sys.platform != "win32":
        return p
    try:
        import ctypes
        from ctypes import wintypes
        GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
        GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        GetShortPathNameW.restype = wintypes.DWORD
        buf = ctypes.create_unicode_buffer(32768)
        if GetShortPathNameW(p, buf, 32768) and buf.value and _path_is_ascii(buf.value):
            return buf.value
    except Exception:
        pass
    return p


def _kiwi_model_path() -> str | None:
    """kiwi 모델 디렉토리를 ASCII 경로로 반환.

    Why: kiwipiepy 의 네이티브 C++ 로더가 비-ASCII 경로의 .mdl 파일을 열지 못해
    'Cannot open extract.mdl for WordDetector' 가 발생한다 (한글 사용자명/폴더명).
    1) 원본 경로가 ASCII 면 그대로 사용.
    2) 아니면 Windows 8.3 단축경로(ASCII) 시도.
    3) 그래도 안되면 모델 파일들을 보장된 ASCII 위치(C:\\Users\\Public\\...)로 복사 후 그 경로 반환.
    """
    try:
        if getattr(sys, "frozen", False):
            base = os.path.join(sys._MEIPASS, "kiwipiepy_model")
        else:
            try:
                import kiwipiepy_model as _kpm
                base = _kpm.get_model_path() if hasattr(_kpm, "get_model_path") \
                    else os.path.dirname(_kpm.__file__)
            except ImportError:
                import kiwipiepy as _kp
                base = os.path.dirname(_kp.__file__)
        if not os.path.isdir(base):
            return None
        if _path_is_ascii(base):
            return base
        short = _try_short_path(base)
        if _path_is_ascii(short) and os.path.isdir(short):
            return short
        # Fallback: ASCII 보장 위치로 모델 복사
        public = os.environ.get("PUBLIC") or r"C:\Users\Public"
        target = os.path.join(public, "SKHU_Agent", "kiwipiepy_model")
        if not _path_is_ascii(target):
            target = r"C:\SKHU_Agent\kiwipiepy_model"
        marker = os.path.join(target, ".copied_ok")
        if not os.path.isfile(marker):
            import shutil
            os.makedirs(target, exist_ok=True)
            for name in os.listdir(base):
                src = os.path.join(base, name)
                dst = os.path.join(target, name)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                elif os.path.isdir(src):
                    shutil.copytree(src, dst, dirs_exist_ok=True)
            with open(marker, "w") as fh:
                fh.write("ok")
        return target
    except Exception:
        return None


try:
    from kiwipiepy import Kiwi
    _kiwi_mp = _kiwi_model_path()
    _kiwi = Kiwi(model_path=_kiwi_mp) if _kiwi_mp else Kiwi()

    def korean_tokenize(text: str) -> list[str]:
        """kiwipiepy 기반 한국어 형태소 분석 토크나이저."""
        tokens = []
        for token in _kiwi.tokenize(text):
            form = token.form.strip()
            if len(form) >= 2 or (len(form) == 1 and form.isalnum()):
                tokens.append(form.lower())
        return tokens

except ImportError:
    _kiwi = None

    def korean_tokenize(text: str) -> list[str]:
        """Fallback: 공백+정규식 기반 토크나이징."""
        return [t.lower() for t in re.split(r"\W+", text) if t]


# ─────────────────────────────────────────────────────────────────────────────
# 1. 노트북 파싱
# ─────────────────────────────────────────────────────────────────────────────

def parse_notebook(path: str) -> list[dict]:
    """노트북을 셀 단위로 파싱합니다."""
    with open(path, "r", encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=4)

    cells = []
    for idx, cell in enumerate(nb.cells):
        source = cell.source.strip()
        if not source:
            continue
        cell_dict = {
            "cell_idx": idx,
            "cell_type": cell.cell_type,
            "source": source,
            "notebook": Path(path).stem,
            "notebook_path": path,
        }
        if cell.cell_type == "markdown" and hasattr(cell, "attachments") and cell.attachments:
            cell_dict["attachments"] = dict(cell.attachments)
        cells.append(cell_dict)
    return cells


def load_notebooks(directory: str, progress_callback=None) -> list[dict]:
    """디렉토리 내 모든 .ipynb 파일을 파싱합니다."""
    notebooks = glob.glob(os.path.join(directory, "**", "*.ipynb"), recursive=True)
    all_cells = []
    for nb_path in notebooks:
        if progress_callback:
            progress_callback(f"파싱 중: {Path(nb_path).name}")
        try:
            cells = parse_notebook(nb_path)
            all_cells.extend(cells)
        except Exception as e:
            print(f"파싱 실패: {nb_path} – {e}")
    return all_cells


# ─────────────────────────────────────────────────────────────────────────────
# 2. 셀 → LangChain Document 변환
# ─────────────────────────────────────────────────────────────────────────────

def cells_to_documents(cells: list[dict]) -> list[Document]:
    docs = []
    for c in cells:
        content = f"[{c['cell_type'].upper()} CELL]\n{c['source']}"
        docs.append(Document(
            page_content=content,
            metadata={
                "cell_idx":      c["cell_idx"],
                "cell_type":     c["cell_type"],
                "notebook":      c["notebook"],
                "notebook_path": c["notebook_path"],
                "source":        f"{c['notebook']}#cell{c['cell_idx']}",
            }
        ))
    return docs


# ─────────────────────────────────────────────────────────────────────────────
# 3. Cell-level Graph 구성
# ─────────────────────────────────────────────────────────────────────────────

def build_cell_graph(cells: list[dict]) -> nx.DiGraph:
    """
    노드: 각 셀
    엣지:
      - sequential : 같은 노트북 내 순서
      - shared_var : 코드 셀 간 변수명 공유
    """
    G = nx.DiGraph()

    for c in cells:
        node_id = f"{c['notebook']}#cell{c['cell_idx']}"
        G.add_node(node_id, source_text=c["source"], **c)

    # Sequential edges
    nb_groups: dict[str, list[dict]] = {}
    for c in cells:
        nb_groups.setdefault(c["notebook"], []).append(c)

    for nb, nb_cells in nb_groups.items():
        nb_cells_sorted = sorted(nb_cells, key=lambda x: x["cell_idx"])
        for i in range(len(nb_cells_sorted) - 1):
            src = f"{nb}#cell{nb_cells_sorted[i]['cell_idx']}"
            tgt = f"{nb}#cell{nb_cells_sorted[i+1]['cell_idx']}"
            G.add_edge(src, tgt, rel="sequential")

    # Shared variable edges (코드 셀만)
    code_cells = [c for c in cells if c["cell_type"] == "code"]
    assign_re = re.compile(r"^([a-zA-Z_]\w*)\s*=", re.MULTILINE)

    cell_vars: dict[str, set[str]] = {}
    for c in code_cells:
        node_id = f"{c['notebook']}#cell{c['cell_idx']}"
        cell_vars[node_id] = set(assign_re.findall(c["source"]))

    node_ids = list(cell_vars.keys())
    for i, n1 in enumerate(node_ids):
        for j, n2 in enumerate(node_ids):
            if i >= j:
                continue
            shared = cell_vars[n1] & cell_vars[n2]
            if shared:
                G.add_edge(n1, n2, rel="shared_var",
                           vars=",".join(list(shared)[:5]))

    return G


def graph_search(G: nx.DiGraph, docs: list[Document],
                 query: str, vector_retriever,
                 top_k: int = 5, hops: int = 2,
                 seq_decay: float = 0.5, var_decay: float = 0.8) -> list[Document]:
    """
    Graph RAG (Vector seed + 키워드 보조 + multi-hop 전파):
    1. Vector retriever로 의미론적 seed 노드 선정
    2. 셀 내용 키워드 보조 점수 부여
    3. 엣지 가중치 기반 multi-hop 점수 전파
    """
    doc_map = {d.metadata["source"]: d for d in docs}

    # Step 1: Vector seed 선정
    try:
        seed_docs = vector_retriever.invoke(query)
        scores: dict[str, float] = {
            d.metadata["source"]: 1.0
            for d in seed_docs[:3]
            if d.metadata["source"] in G
        }
    except Exception:
        scores = {}

    # Step 1b: 키워드 보조 점수
    stopwords = {"", "the", "a", "is", "in", "of", "for", "and", "or", "to",
                 "이", "가", "를", "을", "은", "는", "의", "에", "도", "로",
                 "으로", "에서", "과", "와", "하다", "있다", "되다"}
    tokens = set(korean_tokenize(query)) - stopwords

    if tokens:
        for node_id, data in G.nodes(data=True):
            cell_text = data.get("source_text", "").lower()
            kw_score = sum(1 for t in tokens if t in cell_text)
            if kw_score > 0:
                boost = min(kw_score / len(tokens), 1.0) * 0.4
                scores[node_id] = max(scores.get(node_id, 0), boost)

    if not scores:
        return []

    # Step 2: 가중치 기반 multi-hop 점수 전파
    for _ in range(hops):
        new_scores = dict(scores)
        for node, score in scores.items():
            if node not in G:
                continue
            for neighbor in G.successors(node):
                rel = G.get_edge_data(node, neighbor, default={}).get("rel", "")
                weight = var_decay if rel == "shared_var" else seq_decay
                new_scores[neighbor] = max(new_scores.get(neighbor, 0.0), score * weight)
            for neighbor in G.predecessors(node):
                rel = G.get_edge_data(neighbor, node, default={}).get("rel", "")
                weight = var_decay if rel == "shared_var" else seq_decay
                new_scores[neighbor] = max(new_scores.get(neighbor, 0.0), score * weight)
        scores = new_scores

    # Step 3: 점수 기준 상위 top_k 반환
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    return [doc_map[nid] for nid, _ in ranked[:top_k] if nid in doc_map]


# ─────────────────────────────────────────────────────────────────────────────
# 4. RAG 시스템 초기화
# ─────────────────────────────────────────────────────────────────────────────

def build_rag_system(nb_dir: str, embedding_base_url: str,
                     openai_api_key: str, cache_path: str,
                     embedding_model: str = "text-embedding-ada-002",
                     progress_callback=None):
    """
    RAG 시스템을 구축하여 반환합니다.
    progress_callback: Optional[Callable[[str], None]] — 진행 상태 문자열 콜백
    """
    if progress_callback:
        progress_callback("노트북 파싱 중…")

    cells = load_notebooks(nb_dir, progress_callback)
    if not cells:
        return None

    if progress_callback:
        progress_callback("문서 변환 중…")
    docs = cells_to_documents(cells)

    # Embeddings
    embedding_kwargs = {"api_key": openai_api_key, "model": embedding_model}
    if embedding_base_url:
        embedding_kwargs["base_url"] = embedding_base_url
    embeddings = OpenAIEmbeddings(**embedding_kwargs)

    # Vector Store (FAISS)
    faiss_path = os.path.join(cache_path, "faiss_index")
    if progress_callback:
        progress_callback("FAISS 인덱스 구축 중…")
    os.makedirs(cache_path, exist_ok=True)
    _faiss_valid = (
        os.path.exists(os.path.join(faiss_path, "index.faiss")) and
        os.path.exists(os.path.join(faiss_path, "index.pkl"))
    )
    if _faiss_valid:
        try:
            vector_store = FAISS.load_local(faiss_path, embeddings,
                                            allow_dangerous_deserialization=True)
        except Exception:
            # 손상된 인덱스 → 삭제 후 재빌드
            shutil.rmtree(faiss_path, ignore_errors=True)
            vector_store = FAISS.from_documents(docs, embeddings)
            vector_store.save_local(faiss_path)
    else:
        # 불완전한 디렉토리가 남아 있을 수 있으므로 정리 후 재빌드
        if os.path.exists(faiss_path):
            shutil.rmtree(faiss_path, ignore_errors=True)
        vector_store = FAISS.from_documents(docs, embeddings)
        vector_store.save_local(faiss_path)

    vector_retriever = vector_store.as_retriever(search_kwargs={"k": 5})

    # BM25
    bm25_path = os.path.join(cache_path, "bm25.pkl")
    if progress_callback:
        progress_callback("BM25 인덱스 구축 중…")
    if os.path.exists(bm25_path):
        with open(bm25_path, "rb") as f:
            bm25_retriever = pickle.load(f)
    else:
        bm25_retriever = BM25Retriever.from_documents(
            docs, preprocess_func=korean_tokenize
        )
        bm25_retriever.k = 5
        with open(bm25_path, "wb") as f:
            pickle.dump(bm25_retriever, f)

    # Ensemble (Vector + BM25)
    ensemble_retriever = EnsembleRetriever(
        retrievers=[vector_retriever, bm25_retriever],
        weights=[0.6, 0.4],
    )

    # Cell Graph
    if progress_callback:
        progress_callback("셀 그래프 구축 중…")
    graph = build_cell_graph(cells)

    if progress_callback:
        progress_callback("완료!")

    return {
        "docs":               docs,
        "cells":              cells,
        "vector_retriever":   vector_retriever,
        "bm25_retriever":     bm25_retriever,
        "ensemble_retriever": ensemble_retriever,
        "graph":              graph,
        "nb_count":           len(set(c["notebook"] for c in cells)),
        "cell_count":         len(cells),
        "code_count":         sum(1 for c in cells if c["cell_type"] == "code"),
        "md_count":           sum(1 for c in cells if c["cell_type"] == "markdown"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Trace Debug 로깅
# ─────────────────────────────────────────────────────────────────────────────

def _format_docs_section(title: str, docs: list) -> str:
    """retriever 결과를 텍스트 섹션으로 포맷."""
    lines = [f"[{title}] ({len(docs)} docs)"]
    lines.append("-" * 40)
    for i, d in enumerate(docs):
        nb    = d.metadata.get("notebook", "?")
        cidx  = d.metadata.get("cell_idx", "?")
        ctype = d.metadata.get("cell_type", "?")
        lines.append(f"[{i+1}] notebook: {nb}, cell #{cidx} ({ctype})")
        lines.append(d.page_content)
        lines.append("---")
    if not docs:
        lines.append("(없음)")
    lines.append("")
    return "\n".join(lines)


def _write_trace_log(query: str, vector_docs: list, bm25_docs: list,
                     graph_docs: list, merged_docs: list) -> None:
    """TRACE_DEBUG가 true일 때 retriever별 검색 결과를 파일로 저장."""
    if not _is_trace_debug():
        return

    from datetime import datetime

    trace_dir = Path("trace_logs")
    trace_dir.mkdir(exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 파일명용 쿼리 축약 (특수문자 제거, 30자 제한)
    safe_q = re.sub(r'[\\/:*?"<>|\s]+', '_', query)[:30].strip('_')
    filename = trace_dir / f"{ts}_{safe_q}.txt"

    dt_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sections = [
        f"Query: {query}",
        f"Time: {dt_str}",
        "=" * 40,
        "",
        _format_docs_section("Vector RAG", vector_docs),
        _format_docs_section("BM25", bm25_docs),
        _format_docs_section("Graph RAG", graph_docs),
        _format_docs_section("Merged", merged_docs),
    ]
    filename.write_text("\n".join(sections), encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# 5. LangGraph Agent
# ─────────────────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    query:          str
    retrieval_mode: str
    vector_docs:    list[Document]
    bm25_docs:      list[Document]
    graph_docs:     list[Document]
    all_docs:       list[Document]
    context:        str
    answer:         str
    steps:          Annotated[list[str], operator.add]


def make_agent(llm_base_url: str, llm_api_key: str, llm_model: str,
               rag_sys: dict):
    """LangGraph 에이전트를 생성합니다."""

    llm = ChatOpenAI(
        base_url=llm_base_url if llm_base_url else None,
        api_key=llm_api_key or "dummy",
        model=llm_model,
        temperature=0.2,
        streaming=True,
    )

    def vector_retrieve(state: AgentState) -> AgentState:
        docs = rag_sys["vector_retriever"].invoke(state["query"])
        return {**state, "vector_docs": docs,
                "steps": ["✅ Vector RAG 검색 완료"]}

    def bm25_retrieve(state: AgentState) -> AgentState:
        docs = rag_sys["bm25_retriever"].invoke(state["query"])
        return {**state, "bm25_docs": docs,
                "steps": ["✅ BM25 키워드 검색 완료"]}

    def graph_retrieve(state: AgentState) -> AgentState:
        docs = graph_search(rag_sys["graph"], rag_sys["docs"],
                            state["query"],
                            vector_retriever=rag_sys["vector_retriever"],
                            top_k=5)
        return {**state, "graph_docs": docs,
                "steps": ["✅ Graph RAG 검색 완료"]}

    def merge_docs(state: AgentState) -> AgentState:
        seen, merged = set(), []
        for d in (state.get("vector_docs", []) +
                  state.get("bm25_docs",   []) +
                  state.get("graph_docs",  [])):
            key = d.metadata.get("source", d.page_content[:60])
            if key not in seen:
                seen.add(key)
                merged.append(d)

        _max_docs = int(RAG_CONFIG.get("MAX_DOCS", "10"))
        parts = []
        for i, d in enumerate(merged[:_max_docs]):
            nb    = d.metadata.get("notebook", "?")
            cidx  = d.metadata.get("cell_idx", "?")
            ctype = d.metadata.get("cell_type", "?")
            parts.append(
                f"[문서 {i+1}] 노트북: {nb}, 셀 #{cidx} ({ctype})\n"
                f"{d.page_content}\n"
            )
        context = "\n---\n".join(parts)

        _write_trace_log(
            query=state["query"],
            vector_docs=state.get("vector_docs", []),
            bm25_docs=state.get("bm25_docs", []),
            graph_docs=state.get("graph_docs", []),
            merged_docs=merged[:_max_docs],
        )

        return {**state, "all_docs": merged, "context": context,
                "steps": ["✅ 문서 병합 완료"]}

    _prompt_file = Path("prompts/system_prompt.txt")
    if _prompt_file.exists():
        SYSTEM_PROMPT = _prompt_file.read_text(encoding="utf-8").strip()
    else:
        SYSTEM_PROMPT = """당신은 Jupyter Notebook 강의 자료를 분석하는 친절한 AI 튜터입니다.
반드시 주어진 컨텍스트(노트북 셀 내용)만을 근거로 답변하세요.

답변 방식:
- 처음 접하는 학습자도 이해할 수 있도록 최대한 쉽고 친근한 말투로 설명합니다.
- 개념은 간단한 비유나 예시를 들어 직관적으로 이해할 수 있게 합니다.
- 단계별로 나눠서 논리적인 흐름이 보이도록 자세히 설명합니다.
- 중요한 용어나 핵심 개념은 별도로 강조해서 설명합니다.

규칙:
1. 컨텍스트에 있는 내용만 사용합니다. 컨텍스트 외부 지식은 절대 사용하지 마세요.
2. 코드 셀이 있으면 해당 코드를 직접 인용하고, 각 줄이 무엇을 하는지 단계별로 상세히 설명합니다.
3. 마크다운 셀이 있으면 개념 설명에 적극 활용합니다.
4. 답변은 한국어로 작성합니다.
5. 코드 예시는 ```python 블록으로 감쌉니다.
6. 컨텍스트에 없는 내용은 절대 추측하지 말고 "제공된 노트북에서 해당 내용을 찾을 수 없습니다"라고 답변하세요."""

    LLM_ONLY_PROMPT = """당신은 AI 튜터입니다. 이번 질문은 강의 노트북에서 관련 문서를 찾지 못했습니다.
일반 AI 지식을 바탕으로 최선을 다해 답변하되, 반드시 첫 줄에 다음 문구를 포함하세요:
"⚠️ 노트북에서 관련 내용을 찾지 못해 일반 지식으로 답변합니다."
답변은 한국어로 작성하세요."""

    workflow = StateGraph(AgentState)
    workflow.add_node("vector_retrieve", vector_retrieve)
    workflow.add_node("bm25_retrieve",   bm25_retrieve)
    workflow.add_node("graph_retrieve",  graph_retrieve)
    workflow.add_node("merge_docs",      merge_docs)

    workflow.set_entry_point("vector_retrieve")
    workflow.add_edge("vector_retrieve", "bm25_retrieve")
    workflow.add_edge("bm25_retrieve",   "graph_retrieve")
    workflow.add_edge("graph_retrieve",  "merge_docs")
    workflow.add_edge("merge_docs",      END)

    return workflow.compile(), llm, SYSTEM_PROMPT, LLM_ONLY_PROMPT


# ─────────────────────────────────────────────────────────────────────────────
# 6. 유틸 함수
# ─────────────────────────────────────────────────────────────────────────────

def build_directory_tree(root: str, cell_count_map: dict[str, int] | None = None) -> dict:
    """디렉토리 트리를 재귀적으로 구성합니다."""
    root_path = Path(root)
    if not root_path.exists():
        return {}

    def _build(path: Path) -> dict:
        node = {"name": path.name, "type": "dir", "path": str(path), "children": []}
        try:
            items = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
            for item in items:
                if item.name.startswith(".") or item.name == "__pycache__":
                    continue
                if item.is_dir():
                    node["children"].append(_build(item))
                elif item.suffix.lower() == ".ipynb":
                    cc = (cell_count_map or {}).get(str(item), None)
                    node["children"].append({
                        "name": item.name,
                        "type": "notebook",
                        "path": str(item),
                        "cell_count": cc,
                        "size": item.stat().st_size,
                    })
                else:
                    node["children"].append({
                        "name": item.name,
                        "type": "file",
                        "path": str(item),
                        "ext":  item.suffix.lower(),
                        "size": item.stat().st_size,
                    })
        except PermissionError:
            pass
        return node

    return _build(root_path)


def get_file_md5(filepath: str) -> str:
    """개별 파일의 MD5 해시를 반환합니다."""
    h = hashlib.md5()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
    except Exception:
        pass
    return h.hexdigest()


def get_dir_hash(nb_dir: str) -> str:
    """노트북 디렉토리의 .ipynb 파일 목록과 수정 시각으로 해시를 생성합니다."""
    h = hashlib.md5()
    try:
        files = sorted(Path(nb_dir).rglob("*.ipynb"))
        for f in files:
            h.update(f.name.encode())
            h.update(str(f.stat().st_mtime).encode())
    except Exception:
        pass
    return h.hexdigest()


def get_wiki_metadata_path(cache_dir: str) -> Path:
    """Wiki 메타데이터 파일 경로를 반환합니다."""
    return Path(cache_dir) / "wiki_metadata.json"


def get_wiki_graph_cache_path(cache_dir: str) -> Path:
    """Wiki 그래프 캐시 파일 경로를 반환합니다."""
    return Path(cache_dir) / "wiki_graph.json"


def save_wiki_metadata(cache_dir: str, nb_dir: str, dir_hash: str) -> None:
    """Wiki 메타데이터를 저장합니다."""
    from datetime import datetime
    metadata = {
        "nb_dir": nb_dir,
        "dir_hash": dir_hash,
        "timestamp": datetime.now().isoformat(),
    }
    meta_path = get_wiki_metadata_path(cache_dir)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


def load_wiki_metadata(cache_dir: str) -> dict[str, str] | None:
    """Wiki 메타데이터를 로드합니다. 없으면 None."""
    meta_path = get_wiki_metadata_path(cache_dir)
    if meta_path.exists():
        try:
            with open(meta_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def save_wiki_graph_cache(cache_dir: str, graph_data: dict) -> None:
    """Wiki 그래프 데이터를 캐시합니다."""
    cache_path = get_wiki_graph_cache_path(cache_dir)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(graph_data, f, ensure_ascii=False, indent=2)


def load_wiki_graph_cache(cache_dir: str) -> dict[str, Any] | None:
    """Wiki 그래프 캐시를 로드합니다. 없으면 None."""
    cache_path = get_wiki_graph_cache_path(cache_dir)
    if cache_path.exists():
        try:
            with open(cache_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def should_rebuild_wiki(cache_dir: str, nb_dir: str) -> bool:
    """Wiki 재구축이 필요한지 확인합니다.
    노트북 디렉터리 해시가 변경되었으면 True."""
    metadata = load_wiki_metadata(cache_dir)
    if not metadata:
        return True  # 메타데이터 없으면 재구축 필요

    current_hash = get_dir_hash(nb_dir)
    cached_hash = metadata.get("dir_hash", "")
    return current_hash != cached_hash


def format_cell_preview(doc: Document, max_len: int = 300) -> str:
    text = doc.page_content
    return text[:max_len] + ("…" if len(text) > max_len else "")


# ─────────────────────────────────────────────────────────────────────────────
# 7. 후속 질문 생성
# ─────────────────────────────────────────────────────────────────────────────

def generate_example_questions(llm, docs: list, n: int = 4) -> list[str]:
    """전체 문서에서 핵심 키워드를 추출한 뒤 예시 질문 n개를 생성합니다."""
    total = len(docs)
    if total <= 12:
        sample = docs
    else:
        indices = [int(i * total / 12) for i in range(12)]
        sample = [docs[i] for i in indices]

    full_context = "\n\n".join(
        f"[셀 {i+1}] {d.page_content[:400]}" for i, d in enumerate(sample)
    )

    prompt = f"""You are an educational AI helping learners study Jupyter notebooks.

Below is a sample of notebook cells. Your task:
1. Identify the 5 most important KEYWORDS or CONCEPTS in this notebook.
2. Based on those keywords, generate exactly {n} short questions a learner would naturally ask.

Notebook content:
{full_context}

Rules:
- Questions must be grounded in the actual content and keywords of the notebook
- Each question must be concise (under 15 words)
- Write questions in Korean
- Do NOT generate generic questions — each must reflect a specific concept from the notebook
- Return ONLY a valid JSON object in this exact format:
{{
  "keywords": ["키워드1", "키워드2", "키워드3", "키워드4", "키워드5"],
  "questions": ["질문1?", "질문2?", "질문3?", "질문4?"]
}}

JSON:"""

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        text = response.content.strip()
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            parsed = json.loads(text[start:end+1])
            questions = parsed.get("questions", [])
            return [q for q in questions if isinstance(q, str)][:n]
    except Exception:
        pass
    return []


def generate_suggested_queries(llm, query: str, answer: str, n: int = 3) -> list[str]:
    """현재 Q&A를 바탕으로 후속 쿼리 n개를 생성합니다."""
    prompt = f"""You are an educational AI. A learner asked a question and received an answer.
Generate {n} follow-up search queries the learner would naturally want to search next.

Question: {query}
Answer: {answer[:600]}

Rules:
- Queries must be short and searchable (under 12 words)
- Each query should target a different concept from the answer
- Match the language of the original question (Korean if Korean)
- Return ONLY valid JSON:
{{
  "queries": ["쿼리1", "쿼리2", "쿼리3"]
}}

JSON:"""
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        text = response.content.strip()
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            parsed = json.loads(text[start:end+1])
            queries = parsed.get("queries", [])
            return [q for q in queries if isinstance(q, str)][:n]
    except Exception:
        pass
    return []


def generate_followup_questions(llm, query: str, answer: str) -> list[str]:
    """답변에서 핵심 개념을 파악하고 후속 질문 2~3개를 생성합니다."""
    prompt = f"""You are an educational AI helping a learner study Jupyter notebooks.

A learner asked a question and received an answer. Your task:
1. Identify the most important CONCEPTS or TERMS in the answer that deserve deeper exploration.
2. Generate 2-3 follow-up questions that target those key concepts.

Question: {query}
Answer: {answer[:800]}

Rules:
- Prioritize questions about concepts that are central, non-obvious, or commonly misunderstood
- Do NOT ask questions already answered above
- Each question must be concise (under 15 words)
- Match the language of the original question (Korean if Korean)
- Return ONLY a valid JSON object in this exact format:
{{
  "key_concepts": ["개념1", "개념2", "개념3"],
  "questions": ["질문1?", "질문2?", "질문3?"]
}}

JSON:"""
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        text = response.content.strip()
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            parsed = json.loads(text[start:end+1])
            questions = parsed.get("questions", [])
            return [q for q in questions if isinstance(q, str)][:3]
    except Exception:
        pass
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Force Mode (전수 검색)
# ─────────────────────────────────────────────────────────────────────────────

def load_force_prompt() -> str:
    """force_prompt.txt에서 Force Mode 시스템 프롬프트를 로드합니다."""
    _fp = Path("prompts/force_prompt.txt")
    if _fp.exists():
        return _fp.read_text(encoding="utf-8").strip()
    return (
        "당신은 Jupyter Notebook 강의 자료의 관련성을 판단하는 AI입니다.\n\n"
        "사용자의 질문과 노트북 셀 내용(청크)이 주어집니다.\n\n"
        "작업:\n"
        "1. 이 청크가 사용자의 질문과 관련이 있는지 판단하세요.\n"
        "2. 관련이 있다면 \"RELEVANT\"로 시작하고, 해당 내용을 바탕으로 답변/요약을 작성하세요.\n"
        "3. 관련이 없다면 \"NOT_RELEVANT\"라고만 답변하세요.\n\n"
        "규칙:\n"
        "- 질문의 핵심 주제와 직접적으로 관련된 경우만 RELEVANT입니다.\n"
        "- RELEVANT인 경우, 해당 청크의 내용만을 근거로 설명하세요.\n"
        "- 코드 셀이 있으면 코드를 인용하고 설명하세요.\n"
        "- 답변은 한국어로 작성합니다.\n"
        "- 간결하되 핵심 내용을 빠짐없이 포함하세요."
    )


def prepare_force_chunks(nb_dir: str, chunk_size: int = 5) -> list[dict]:
    """노트북 디렉토리의 모든 파일을 chunk_size셀씩 묶어 청크 리스트로 반환."""
    notebooks = sorted(
        glob.glob(os.path.join(nb_dir, "**", "*.ipynb"), recursive=True)
    )
    chunks = []
    for nb_path in notebooks:
        try:
            cells = parse_notebook(nb_path)
        except Exception:
            continue
        nb_name = Path(nb_path).stem

        for i in range(0, len(cells), chunk_size):
            group = cells[i:i + chunk_size]
            cell_indices = [c["cell_idx"] for c in group]
            if len(cell_indices) > 1:
                cell_range = f"#{min(cell_indices)}-#{max(cell_indices)}"
            else:
                cell_range = f"#{cell_indices[0]}"

            text_parts = []
            for c in group:
                text_parts.append(
                    f"[{c['cell_type'].upper()} CELL #{c['cell_idx']}]\n{c['source']}"
                )
            chunk_text = "\n\n---\n\n".join(text_parts)

            if len(chunk_text.strip()) < 50:
                continue

            chunks.append({
                "notebook": nb_name,
                "notebook_path": nb_path,
                "cell_range": cell_range,
                "text": chunk_text,
            })
    return chunks


def process_force_chunk(llm, force_prompt: str, query: str, chunk: dict):
    """단일 청크에 대해 LLM 관련성 판단. 관련 있으면 dict, 없으면 None."""
    user_msg = (
        f"질문: {query}\n\n"
        f"노트북: {chunk['notebook']}\n"
        f"셀 범위: {chunk['cell_range']}\n\n"
        f"청크 내용:\n{chunk['text'][:4000]}"
    )

    response = llm.invoke([
        SystemMessage(content=force_prompt),
        HumanMessage(content=user_msg),
    ])

    answer = response.content.strip()

    if answer.upper().startswith("NOT_RELEVANT"):
        return None

    if answer.upper().startswith("RELEVANT"):
        answer = answer[len("RELEVANT"):].lstrip(":").lstrip()

    return {
        "notebook": chunk["notebook"],
        "cell_range": chunk["cell_range"],
        "summary": answer,
    }


def format_force_results(results: list[dict], progress: tuple,
                         stopped: bool = False) -> str:
    """Force Mode 결과를 마크다운 문자열로 포맷."""
    processed, total = progress
    parts = ["🔍 **Force Mode 검색 결과**\n"]

    for r in results:
        parts.append(
            f"\n---\n📓 **{r['notebook']}** (셀 {r['cell_range']})\n\n"
            f"{r['summary']}"
        )

    if not results:
        parts.append("\n\n관련 문서를 찾지 못했습니다.")

    if stopped:
        parts.append(
            f"\n\n---\n⏹️ 검색 중단됨: {processed}/{total}개 청크 검색 완료, "
            f"{len(results)}개 관련 문서 발견"
        )
    else:
        parts.append(
            f"\n\n---\n✅ 검색 완료: {total}개 청크 중 "
            f"{len(results)}개 관련 문서 발견"
        )

    return "\n".join(parts)


# ── 노트북 요약 (Summary) ───────────────────────────────────────────────────


def load_summary_prompt() -> str:
    """summary_prompt.txt에서 요약 시스템 프롬프트를 로드합니다."""
    _fp = Path("prompts/summary_prompt.txt")
    if _fp.exists():
        return _fp.read_text(encoding="utf-8").strip()
    return (
        "당신은 Jupyter Notebook 강의 자료를 분석하는 AI 요약 전문가입니다.\n\n"
        "주어진 노트북의 전체 셀 내용을 바탕으로 핵심 요약을 작성합니다.\n\n"
        "요약 방식:\n"
        "- 노트북의 주제와 학습 목표를 먼저 파악합니다\n"
        "- 다루는 핵심 개념과 기술을 목록으로 정리합니다\n"
        "- 주요 코드 예제가 있으면 간략히 언급합니다\n"
        "- 3~5개의 핵심 포인트로 구조화합니다\n\n"
        "규칙:\n"
        "1. 주어진 셀 내용만을 근거로 요약합니다\n"
        "2. 답변은 한국어로 작성합니다\n"
        "3. 마크다운 형식을 사용합니다\n"
        "4. 200~400자 내외로 간결하게 작성합니다"
    )


def get_summary_prompt_hash() -> str:
    """현재 요약 프롬프트의 MD5 해시를 반환합니다. 캐시 무효화 판단에 사용됩니다."""
    return hashlib.md5(load_summary_prompt().encode()).hexdigest()


def prepare_notebook_summary_prompt(
    notebook_name: str, cells: list[dict], max_chars: int = 6000
) -> str:
    """노트북의 셀들을 요약용 프롬프트 문자열로 조합합니다."""
    md_cells = [c for c in cells if c["cell_type"] == "markdown"]
    code_cells = [c for c in cells if c["cell_type"] == "code"]

    parts: list[str] = []
    budget = max_chars

    # 마크다운 셀 우선 포함
    for c in md_cells:
        src = c["source"]
        if len(src) > 500:
            src = src[:500] + "...(생략)"
        entry = f"[MARKDOWN #{c['cell_idx']}]\n{src}\n"
        if budget - len(entry) < 0:
            break
        parts.append(entry)
        budget -= len(entry)

    # 코드 셀: 앞쪽 + 뒤쪽 우선
    if code_cells and budget > 200:
        half = max(len(code_cells) // 2, 1)
        priority = code_cells[:half] + code_cells[-half:]
        seen = set()
        for c in priority:
            if c["cell_idx"] in seen:
                continue
            seen.add(c["cell_idx"])
            src = c["source"]
            if len(src) > 500:
                src = src[:500] + "...(생략)"
            entry = f"[CODE #{c['cell_idx']}]\n{src}\n"
            if budget - len(entry) < 0:
                break
            parts.append(entry)
            budget -= len(entry)

    cell_text = "\n".join(parts)
    return (
        f"노트북: {notebook_name}\n"
        f"총 셀 수: {len(cells)}개 (코드: {len(code_cells)}, "
        f"마크다운: {len(md_cells)})\n\n"
        f"--- 셀 내용 ---\n{cell_text}\n\n"
        f"위 노트북의 내용을 분석하여 핵심 요약을 작성해 주세요."
    )


# ── 노트북 채팅 (Notebook Chat) ──────────────────────────────────────────────


def load_notebook_chat_prompt() -> str:
    """notebook_chat_prompt.txt에서 노트북 채팅 시스템 프롬프트를 로드합니다."""
    _fp = Path("prompts/notebook_chat_prompt.txt")
    if _fp.exists():
        return _fp.read_text(encoding="utf-8").strip()
    return (
        "당신은 Jupyter Notebook 코드 분석 전문가이자 프로그래밍 튜터입니다.\n\n"
        "사용자가 선택한 노트북 셀의 내용과 노트북 요약을 바탕으로 질문에 답변합니다.\n\n"
        "답변 방식:\n"
        "- 선택된 셀의 코드/마크다운 내용을 정확하게 분석합니다\n"
        "- 코드 설명 시 단계별로 명확하게 설명합니다\n"
        "- 필요 시 개선된 코드 예시를 제공합니다\n"
        "- 노트북 요약 컨텍스트를 활용하여 전체 맥락에서 답변합니다\n"
        "- 변수·함수의 연관 관계를 설명할 때는 반드시 화살표(→) 또는 Mermaid flowchart(```mermaid ... ```)로 시각화합니다\n"
        "  (관계가 단순하면 화살표, 복잡하거나 분기·병합이 있으면 Mermaid flowchart 사용)\n\n"
        "규칙:\n"
        "1. 주어진 셀 내용과 요약만을 근거로 답변합니다\n"
        "2. 답변은 한국어로 작성합니다\n"
        "3. 마크다운 형식을 사용합니다"
    )


def prepare_notebook_chat_prompt(
    notebook_name: str,
    selected_cells: list[dict],
    question: str,
    *,
    context_mode: str = "summary",
    summary: str = "",
    all_cells: list[dict] | None = None,
) -> str:
    """노트북 채팅용 사용자 프롬프트를 생성합니다.

    context_mode: "summary" → 요약 + 선택된 셀
                  "full"    → 노트북 전체 셀(선택된 셀에 [★ 선택됨] 마커)
    """
    parts = [f"노트북: {notebook_name}"]

    use_full = context_mode == "full" and all_cells

    if use_full:
        selected_idx = {c.get("cell_idx") for c in selected_cells}
        parts.append("\n--- 노트북 전체 내용 ---")
        for c in sorted(all_cells, key=lambda x: x.get("cell_idx", 0)):
            tag = "CODE" if c.get("cell_type") == "code" else "MARKDOWN"
            idx = c.get("cell_idx", "?")
            src = c.get("source", "")
            marker = "[★ 선택됨] " if idx in selected_idx else ""
            parts.append(f"{marker}[{tag} #{idx}]\n{src}")

        if selected_cells:
            sel_list = ", ".join(f"#{c.get('cell_idx', '?')}" for c in selected_cells)
            parts.append(f"\n--- 사용자가 질문하는 셀 ---\n선택된 셀 번호: {sel_list}")
    else:
        if summary:
            parts.append(f"\n--- 노트북 요약 ---\n{summary}")

        if selected_cells:
            parts.append("\n--- 선택된 셀 ---")
            for c in selected_cells:
                tag = "CODE" if c.get("cell_type") == "code" else "MARKDOWN"
                src = c.get("source", "")
                parts.append(f"[{tag} #{c.get('cell_idx', '?')}]\n{src}")

    parts.append(f"\n--- 질문 ---\n{question}")

    return "\n".join(parts)


# ── 노트북 실행 결과 예측 (Run Predict) ──────────────────────────────────────


def load_run_predict_prompt() -> str:
    """notebook_run_predict_prompt.txt에서 실행 결과 예측 지시문을 로드합니다."""
    _fp = Path("prompts/notebook_run_predict_prompt.txt")
    if _fp.exists():
        return _fp.read_text(encoding="utf-8").strip()
    return (
        "이 노트북을 처음부터 끝까지 실제 Python/Jupyter 커널에서 실행한다고 가정하고, "
        "각 코드 셀의 실행 결과를 예측해 주세요. 실제로 코드를 실행하는 것이 아니라 "
        "**예측**이라는 점을 답변 맨 앞에 한 줄로 명시하세요.\n\n"
        "규칙:\n"
        "- 코드 셀을 순서대로 모의 실행하면서 변수·함수·임포트 상태를 다음 셀까지 이어갑니다.\n"
        "- 각 코드 셀마다 `### 셀 #N 실행 결과` 제목 아래, 예상되는 표준출력(print 등)과 "
        "마지막 줄이 표현식이면 Jupyter처럼 자동 출력되는 값을 코드블록으로 보여주세요.\n"
        "- 에러가 발생할 것으로 예상되면 Traceback 형태로 표시하고, 그로 인해 이후 셀이 "
        "영향을 받는 부분까지 예측합니다.\n"
        "- 마크다운 셀은 건너뛰고 코드 셀만 대상으로 합니다."
    )


def get_run_predict_prompt_hash() -> str:
    """현재 실행 예측 프롬프트의 MD5 해시를 반환합니다. 캐시 무효화 판단에 사용됩니다."""
    return hashlib.md5(load_run_predict_prompt().encode()).hexdigest()


# ── Wiki 생성 (Knowledge Graph) ─────────────────────────────────────────────

def slug(name: str) -> str:
    """이름을 위키 파일명용 소문자 하이픈 슬러그로 변환.
    예: 'LangGraph Memory' → 'langgraph-memory'"""
    import re as _re
    s = name.lower().strip()
    s = _re.sub(r'[^a-z0-9가-힣\-_]', '-', s)
    s = _re.sub(r'-+', '-', s).strip('-')
    return s or "unknown"


def extract_wiki_links(md_content: str) -> list[str]:
    """마크다운 텍스트에서 [[slug]] 형태의 위키 링크를 모두 추출하여
    slug 문자열 리스트로 반환합니다."""
    return re.findall(r'\[\[([^\]]+)\]\]', md_content)


def load_wiki_concept_prompt() -> str:
    """prompts/wiki_concept_prompt.txt를 읽어 개념 추출 시스템 프롬프트를 반환합니다.
    파일이 없으면 내장 기본값을 반환합니다."""
    concept_prompt_path = Path("prompts/wiki_concept_prompt.txt")
    if concept_prompt_path.exists():
        return concept_prompt_path.read_text(encoding="utf-8").strip()

    return (
        "당신은 Jupyter Notebook 강의 자료에서 핵심 개념을 추출하는 전문가입니다.\n"
        "주어진 노트북 요약에서 학습자가 이해해야 할 핵심 개념, 기술, 라이브러리, 알고리즘을 추출합니다.\n"
        "규칙:\n"
        "1. 개념은 5~8개 추출합니다\n"
        "2. 구체적이고 검색 가능한 명칭을 사용합니다 (예: MemorySaver, FAISS, StateGraph)\n"
        "3. 너무 일반적인 개념은 제외합니다 (예: Python, 함수, 변수)\n"
        "4. 반드시 아래 JSON 형식으로만 응답합니다: {\"concepts\": [\"개념1\", \"개념2\", ...]}\n"
        "\nJSON:"
    )


def append_wiki_log(wiki_dir: Path, action: str, detail: str) -> None:
    """wiki_dir/log.md에 타임스탐프 감사 로그 항목을 추가합니다."""
    from datetime import datetime
    log_path = wiki_dir / "log.md"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"- **{timestamp}** | {action} | {detail}\n"

    if log_path.exists():
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)
    else:
        header = "# Wiki Log\n\nAppend-only record of all wiki operations.\n\n"
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(header + entry)


def generate_notebook_wiki_page(
    nb_name: str,
    summary: str,
    wiki_dir: Path,
    *,
    overwrite: bool = False,
) -> Path:
    """노트북 요약(summaries.json에서 읽은 텍스트)으로 노트북 위키 페이지를 생성합니다.
    wiki_dir/<slug>.md 에 저장하고 Path를 반환합니다.
    overwrite=False이면 파일이 이미 존재할 때 스킵합니다."""
    from datetime import datetime

    wiki_dir.mkdir(parents=True, exist_ok=True)
    page_slug = slug(nb_name)
    page_path = wiki_dir / f"{page_slug}.md"

    if page_path.exists() and not overwrite:
        return page_path

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    content = f"""---
type: notebook
slug: {page_slug}
label: {nb_name}
---

# {nb_name}

**Summary**: {summary.split(chr(10))[0][:150]}…

**Sources**: [[{page_slug}]]

**Last updated**: {timestamp}

---

{summary}

## Related pages

(자동 생성됨)
"""

    page_path.write_text(content, encoding="utf-8")
    return page_path


def extract_concepts_from_notebook(
    llm,
    nb_name: str,
    summary: str,
    concept_prompt: str,
) -> list[str]:
    """단일 노트북 요약에서 핵심 개념 목록을 추출합니다.
    반환값: 개념 이름 문자열 리스트 (예: ['MemorySaver', 'thread_id', ...])"""
    import json as _json

    user_msg = f"노트북 '{nb_name}'의 요약:\n\n{summary}"

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        response = llm.invoke([
            SystemMessage(content=concept_prompt),
            HumanMessage(content=user_msg),
        ])

        text = response.content.strip()
        # JSON 객체 추출 (```json ... ``` 형식도 처리)
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        parsed = _json.loads(text)
        concepts = parsed.get("concepts", [])
        return [c.strip() for c in concepts if isinstance(c, str)]
    except Exception:
        return []


def generate_concept_wiki_page(
    llm,
    concept_name: str,
    related_notebooks: list[str],
    summaries: dict[str, str],
    wiki_dir: Path,
    existing_slugs: set[str],
    *,
    overwrite: bool = False,
) -> Path | None:
    """LLM을 호출하여 단일 개념 위키 페이지를 생성합니다.
    related_notebooks의 요약을 컨텍스트로 주고, [[wiki-links]]를 포함한
    마크다운을 wiki_dir/<slug>.md 에 저장합니다.
    LLM 실패 시 None을 반환합니다."""
    import re as _re
    from datetime import datetime

    page_slug = slug(concept_name)
    page_path = wiki_dir / f"{page_slug}.md"

    if page_path.exists() and not overwrite:
        return page_path

    # 관련 노트북 요약 컨텍스트 구성
    context_parts = [f"개념: {concept_name}\n\n관련 노트북:\n"]
    for nb_name in related_notebooks[:5]:  # 최대 5개
        summary = summaries.get(nb_name, {}).get("summary", "")
        if isinstance(summary, str):
            context_parts.append(f"- {nb_name}: {summary[:200]}…\n")

    context = "".join(context_parts)

    prompt = (
        f"아래 정보를 바탕으로 '{concept_name}' 개념에 대한 위키 페이지를 작성해 주세요.\n\n"
        f"{context}\n\n"
        f"위키 페이지 형식:\n"
        f"# {{제목}}\n"
        f"**Summary**: 한 줄 요약\n"
        f"**Sources**: 관련 노트북을 [[슬러그]] 형식으로\n"
        f"본문: 마크다운 형식\n\n"
        f"## 작성 규칙:\n"
        f"1. [[...]] 형식의 위키링크만 사용하세요\n"
        f"2. 유효한 위키링크는 이것들입니다: {', '.join(list(existing_slugs)[:10])}…\n"
        f"3. 존재하지 않는 개념으로는 링크를 만들지 마세요\n"
        f"4. 마크다운 형식을 준수하세요\n"
        f"5. 개념의 흐름이나 구조를 시각화하기 위해 mermaid flowchart를 반드시 포함하세요. 반드시 아래 규칙을 준수하세요:\n"
        f"   - flowchart TD (top-down) 형식 사용\n"
        f"   - 노드 ID는 영문 알파벳만 사용 (A, B, C, D 등)\n"
        f"   - 노드 레이블은 반드시 따옴표로 감싸세요 (예: A[\\\"label\\\"])\n"
        f"   - 노드 레이블에 특수문자나 한글은 사용하지 마세요\n"
        f"   - 화살표는 --> 또는 -->|조건| 형식 사용\n"
        f"   - 마크다운 코드블록 ```mermaid 안에 flowchart를 작성하세요\n"
        f"6. Related pages 섹션은 제일 마지막에 추가하세요 (## Related pages: [[다른-개념]] 형식)"
    )

    try:
        from langchain_core.messages import HumanMessage
        response = llm.invoke([HumanMessage(content=prompt)])
        content = response.content.strip()

        # 유효하지 않은 위키링크 제거
        def filter_links(match):
            link_text = match.group(1)
            return f"[[{link_text}]]" if link_text in existing_slugs else link_text

        content = _re.sub(r'\[\[([^\]]+)\]\]', filter_links, content)

        # 프론트매터 추가
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_content = f"""---
type: concept
slug: {page_slug}
label: {concept_name}
---

{content}

**Last updated**: {timestamp}
"""

        page_path.write_text(full_content, encoding="utf-8")
        return page_path
    except Exception as e:
        print(f"Error generating concept page for {concept_name}: {e}")
        return None


def build_wiki_graph(wiki_dir: Path) -> dict:
    """wiki_dir/*.md 파일들을 스캔하여 그래프 JSON을 빌드합니다.
    노드: 각 페이지 (type=notebook|concept), 엣지: [[wiki-links]] 기반.
    반환값:
    {
      'nodes': [{'id': str, 'label': str, 'type': str,
                 'summary': str, 'content': str}],
      'edges': [{'source': str, 'target': str}]
    }"""
    import re as _re

    nodes = []
    edges = []
    node_ids = set()

    # 모든 .md 파일 읽기 (index.md, log.md 제외)
    for md_file in sorted(wiki_dir.glob("*.md")):
        if md_file.name in ("index.md", "log.md"):
            continue

        try:
            content = md_file.read_text(encoding="utf-8")

            # 프론트매터 파싱
            match = _re.match(r'^---\n(.*?)\n---', content, _re.DOTALL)
            metadata = {}
            if match:
                fm_text = match.group(1)
                for line in fm_text.split('\n'):
                    if ':' in line:
                        k, v = line.split(':', 1)
                        metadata[k.strip()] = v.strip()

            node_id = metadata.get("slug", slug(md_file.stem))
            node_label = metadata.get("label", md_file.stem)
            node_type = metadata.get("type", "concept")

            # 요약 추출 (첫 200자)
            summary_match = _re.search(r'\*\*Summary\*\*:\s*(.+?)(?:\n|$)', content)
            summary = summary_match.group(1)[:150] if summary_match else ""

            nodes.append({
                "id": node_id,
                "label": node_label,
                "type": node_type,
                "summary": summary,
                "content": content,
            })
            node_ids.add(node_id)
        except Exception as e:
            print(f"Error processing {md_file.name}: {e}")

    # 엣지 수집
    for md_file in sorted(wiki_dir.glob("*.md")):
        if md_file.name in ("index.md", "log.md"):
            continue

        try:
            content = md_file.read_text(encoding="utf-8")
            source_id = slug(md_file.stem)

            # [[링크]] 추출
            links = extract_wiki_links(content)
            for target_id in links:
                if target_id in node_ids:
                    edges.append({"source": source_id, "target": target_id})
        except Exception:
            pass

    return {"nodes": nodes, "edges": edges}


def save_wiki_index(wiki_dir: Path, nodes: list[dict]) -> None:
    """노드 리스트로부터 wiki_dir/index.md 를 생성합니다."""
    wiki_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Wiki Index",
        "",
        "Table of contents for all wiki pages.",
        "",
        "| Name | Type | Slug |",
        "|------|------|------|",
    ]

    for node in sorted(nodes, key=lambda x: (x.get("type", ""), x.get("label", ""))):
        label = node.get("label", "")
        node_type = node.get("type", "")
        node_id = node.get("id", "")
        lines.append(f"| [[{node_id}]] | {node_type} | {node_id} |")

    index_path = wiki_dir / "index.md"
    index_path.write_text("\n".join(lines), encoding="utf-8")


def wiki_qa(
    llm,
    question: str,
    wiki_dir: Path,
    max_context_pages: int = 5,
    stream_callback: callable = None,
) -> str:
    """위키 컨텐츠를 컨텍스트로 사용해 LLM이 질문에 답변합니다.
    BM25-style 키워드 매칭으로 관련 페이지를 선택합니다."""
    from langchain_core.messages import HumanMessage, SystemMessage

    # 모든 위키 페이지 로드
    pages = {}
    for md_file in wiki_dir.glob("*.md"):
        if md_file.name in ("index.md", "log.md"):
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
            pages[md_file.stem] = content
        except Exception:
            pass

    if not pages:
        return "위키 페이지를 찾을 수 없습니다. 먼저 Wiki를 생성해 주세요."

    # 간단한 키워드 매칭으로 관련 페이지 선택
    import re as _re
    question_words = set(_re.findall(r'\b\w+\b', question.lower()))

    scored_pages = []
    for page_name, page_content in pages.items():
        content_lower = page_content.lower()
        score = sum(1 for word in question_words if word in content_lower)
        if score > 0:
            scored_pages.append((score, page_name, page_content))

    scored_pages.sort(reverse=True)
    context_pages = scored_pages[:max_context_pages]

    context = "## 위키 정보\n\n"
    for _, page_name, page_content in context_pages:
        # 최대 500자까지
        context += f"### {page_name}\n{page_content[:500]}\n\n"

    system_prompt = (
        "당신은 한국어 강의 자료 위키의 지식베이스를 기반으로 질문에 답변하는 AI입니다.\n"
        "주어진 위키 컨텐츠 내에서만 답변하고, 없으면 모른다고 답하세요.\n"
        "마크다운 형식을 사용하고, 출처를 명시하세요."
    )

    user_prompt = f"{context}\n## 질문\n{question}"

    try:
        if stream_callback:
            # 스트리밍 모드
            for chunk in llm.stream([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]):
                if hasattr(chunk, "content") and chunk.content:
                    stream_callback(chunk.content)
            return ""  # 스트리밍 완료, 합산은 호출자가 처리
        else:
            # 일반 모드
            response = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ])
            return response.content.strip()
    except Exception as e:
        return f"오류: {str(e)}"
