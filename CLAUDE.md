# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

> **중요**: 사용자는 PyQt6 데스크탑 앱(`python main.py`)을 사용합니다.
> `notebook_rag_agent.py`(Streamlit)는 레거시이며 사용하지 않습니다.
> **코드 수정 시 반드시 PyQt6 쪽 파일을 수정하세요.**

```bash
# Install dependencies (Python >= 3.10 required)
pip install -r requirements_1.txt

# Run the PyQt6 desktop app (기본 실행 방법)
python main.py

# (레거시, 미사용) Streamlit app
# streamlit run notebook_rag_agent.py
```

No build, lint, or test commands are defined for this project.

## Environment Configuration

Copy `.env` (or `env.txt`) to set these variables before running:
- `OPENAI_API_KEY` — Required for embeddings and LLM
- `LLM_MODEL` — Default: `gpt-4o-mini`
- `LLM_BASE_URL` — Leave empty for OpenAI; set for local servers (Ollama, etc.)
- `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` — Override embedding endpoint/model
- `FORCE_WORKERS` — Force Mode 병렬 워커 수 (기본값: 3, 범위: 1-10)

`env_loader.py`가 `env.txt`를 읽어 환경변수에 로드합니다 (`main.py`에서 호출).

## Architecture Overview

이 프로젝트에는 두 가지 UI 구현이 있습니다:

### 1. PyQt6 데스크탑 앱 (현재 사용 중) ← 모든 수정은 여기에

진입점: `main.py` → `ui/main_window.py` (MainWindow)

| 모듈 | 역할 |
|------|------|
| `main.py` | 앱 진입점 (QApplication, 다크 테마, 폰트 설정) |
| `ui/main_window.py` | MainWindow — 탭/패널 조립, 워커 관리, `/f` 감지 |
| `ui/config_panel.py` | 좌측 설정 패널 (LLM/임베딩 URL, 모델, RAG 빌드 버튼) |
| `ui/chat_tab.py` | 채팅 탭 (스트리밍, 답변 중지, Force Mode UI, 예시 질문 칩, 외부 링크) |
| `ui/docs_tab.py` | 문서 탐색 탭 |
| `ui/graph_tab.py` | 그래프 탐색 탭 |
| `ui/notebook_tab.py` | 노트북 뷰어 탭 |
| `ui/dir_tab.py` | 디렉토리 트리 탭 |
| `workers/llm_worker.py` | QThread 워커 (RagBuildWorker, LLMWorker, ForceWorker, AgenticWorker, ExampleQuestionsWorker, SuggestedQueriesWorker, SummaryWorker, NotebookChatWorker) |
| `rag_core.py` | RAG 비즈니스 로직 (UI 무관) — 파싱, 인덱싱, 검색, Force Mode, 요약, 노트북 채팅 함수 |
| `agentic_rag.py` | Agentic Mode 비즈니스 로직 (UI 무관) — 계획/검색 팬아웃/충분성 게이트/합성, 노트북 retriever 어댑터 |
| `env_loader.py` | env.txt 로더 |

### 2. Streamlit 앱 (레거시, 미사용)

`notebook_rag_agent.py` 단일 파일 (~1561줄). **수정하지 마세요.**

### Retrieval Pipeline (LangGraph StateGraph)

The core is a hybrid RAG pipeline with three parallel retrievers, orchestrated by LangGraph:

1. **Vector RAG** — FAISS index with OpenAI embeddings; cached to `.rag_cache/faiss_index/`
2. **BM25** — Keyword ranking via `rank-bm25`; cached to `.rag_cache/bm25.pkl`
3. **Graph RAG** — Custom NetworkX DiGraph over notebook cells with two edge types:
   - `sequential`: adjacent cells in the same notebook (decay 0.5)
   - `shared_var`: code cells sharing assigned variable names (decay 0.8)
   - Multi-hop propagation (2 hops) starting from vector-seeded nodes

After retrieval, `merge_docs` deduplicates results (max 10 docs) and formats the context for the LLM.

`AgentState` fields: `query`, `retrieval_mode`, `vector_docs`, `bm25_docs`, `graph_docs`, `all_docs`, `context`, `answer`, `steps`.

### Indexing Unit

Notebooks in `work/` are parsed cell-by-cell using `nbformat`. Each **cell** is the atomic retrieval unit (a LangChain `Document`). Metadata per document: `cell_idx`, `cell_type`, `notebook`, `notebook_path`, `source` (node ID).

### RAG System Build & Caching

PyQt6 앱에서는 `RagBuildWorker` (QThread)가 `rag_core.build_rag_system()`을 백그라운드에서 호출합니다:
- Parses all `.ipynb` files from the configured notebook directory
- Builds or loads FAISS/BM25 indexes from disk cache
- Builds the NetworkX cell graph
- Returns a dict with all components + stats

File change detection uses MD5 hashing of `.ipynb` files + mtime (`get_dir_hash()`). `MainWindow._check_dir_hash()`가 30초 타이머로 감시하며 변경 감지 시 재구축을 안내합니다.

### Korean Language Support

`kiwipiepy` is used for morphological tokenization in BM25 and Graph RAG keyword boosting. If `kiwipiepy` is unavailable, the code falls back to regex-based tokenization.

### Custom System Prompt

Place a `system_prompt.txt` file in the project root to override the default LLM prompt. The default instructs the model to answer only from the retrieved notebook context and respond in Korean.

### Force Mode (전수 검색)

RAG 파이프라인과 완전히 분리된 **병렬** 검색 모드. 채팅 입력에 `/f 질문` 형태로 사용.

- **트리거**: `/f ` 접두어 (예: `/f 판다스 데이터프레임 병합`). 전각 슬래시(／), fraction slash(⁄) 등 자동 변환.
- **동작**: 모든 `.ipynb` 파일을 5셀 단위 청크로 분할 → N개 병렬 sub-worker가 동시에 LLM 관련성 판단 → 관련 있는 결과만 채팅에 누적 표시
- **병렬 처리**: `ForceWorker` QThread가 `ThreadPoolExecutor(max_workers=N)`으로 청크를 분배. N은 설정 패널의 "병렬 워커 수" SpinBox (1-10)에서 실시간 반영. `env.txt`의 `FORCE_WORKERS`로 초기값 설정 가능.
- **시스템 프롬프트**: `force_prompt.txt` (별도 파일, `system_prompt.txt`와 독립)
- **중지**: 진행 중 "⏹️ 중지" 버튼 클릭으로 모든 sub-worker 즉시 중단 가능
- **PyQt6 구현**:
  - `rag_core.py`: `load_force_prompt()`, `prepare_force_chunks()`, `process_force_chunk()`, `format_force_results()`
  - `workers/llm_worker.py`: `ForceWorker` QThread (내부 `ThreadPoolExecutor` 병렬 처리)
  - `ui/chat_tab.py`: Force Mode UI (QProgressBar + 중지 버튼)
  - `ui/config_panel.py`: `force_workers_spin` QSpinBox (병렬 워커 수, 실시간 반영)
  - `ui/main_window.py`: `_detect_force_mode()` → ForceWorker 생성/관리 (병렬 워커 수 전달)
- FAISS/BM25/Graph 인덱스 불필요 (LLM 설정만 필요)

### Agentic Mode (계획 기반 에이전트 검색)

기존 노트북 RAG 인덱스 위에서 동작하는 **다단계 계획형** 검색 모드. 단일 검색 후 답하는 일반 RAG와 달리,
질문을 분해하고 근거가 충분해질 때까지 반복 검색한다. 복합·비교·"모두 나열"형 질문에 유리.
`D:\2026_Agent\1_Understanding_fast\pure_planning_agentic_rag`의 순수 계획형 루프를 이식했다.

- **루프**: 계획(질문 분해 → 검색어 재작성) → 검색 팬아웃(검색어별 병렬 top-k) → 충분성 게이트(충분?/부족 시 후속 검색어) → (최대 `AGENTIC_MAX_ITERS`회 반복) → 합성(근거 기반 스트리밍 답변)
- **검색 도구**: 기존 `rag_sys["ensemble_retriever"]`(Vector+BM25)를 재사용 (별도 인덱스/PDF 적재 불필요). 따라서 RAG 시스템이 먼저 구축되어 있어야 함.
- **LLM**: 별도 클라이언트 없이 앱의 `self.state.llm`(ChatOpenAI)을 그대로 사용 → 새 의존성 없음.
- **트리거 (2가지)**:
  - 채팅 입력행의 **모드 선택기** 콤보박스에서 `🧭 에이전트` 선택 (지속 적용)
  - `/a 질문` **접두어** (1회성 강제, 선택기보다 우선). 전각 슬래시(／) 등 자동 변환. `/f`(Force)가 `/a`보다 먼저 검사됨.
- **추론 과정 트레이스**: 답변 위에 접이식 `<details>🧭 추론 과정` 블록으로 계획(하위 질문)·반복별(검색어/근거 수/충분성/부족 항목/후속 검색어)을 표시. 진행 중에는 펼침, 합성 시작 시 접힘. `marked.js`가 raw HTML을 통과시키므로 `chat.html` 수정 불필요.
- **출처**: 합성 후 최종 근거의 노트북·셀을 `📎 출처` 블록으로 답변에 덧붙임 (일반 RAG와 동일 UX).
- **중지**: 스트리밍 중 ⏹ 버튼 → `llm_stop_requested` → `MainWindow._on_llm_stop()`가 AgenticWorker도 중단 (일반 모드와 버튼 공유). 루프/스트림 매 단계 `is_stopped()` 협조적 취소.
- **시스템 프롬프트**: `prompts/agentic_planner_prompt.txt`, `prompts/agentic_sufficiency_prompt.txt`, `prompts/agentic_synthesis_prompt.txt` (없으면 코드 내 한국어 기본값 사용)
- **PyQt6 구현**:
  - `agentic_rag.py`: `NotebookRetrieverAdapter`, `run_agentic_rag()`, `plan()`, `search_fanout()`, `assess_sufficiency()`, `synthesize()`, `chat_json()`, 프롬프트 로더 3종
  - `workers/llm_worker.py`: `AgenticWorker` QThread (signals: `status_signal`, `trace_signal`, `chunk_received`, `finished_signal`, `error_signal`)
  - `ui/chat_tab.py`: `mode_combo`(모드 선택기), `current_mode()`, `start_agentic()`, `on_agentic_trace()`, `_render_agentic_trace()`, `on_agentic_finished()`
  - `ui/main_window.py`: `_detect_agentic_mode()` → AgenticWorker 생성/관리, `_on_agentic_finished()`
- **파라미터** (`config.txt`): `AGENTIC_MAX_ITERS`(3), `AGENTIC_FANOUT_K`(5), `AGENTIC_MAX_SNIPPETS`(24), `AGENTIC_MAX_QUERIES`(8)

### External Link Handling (외부 링크)

채팅 내 링크 클릭 시 QWebEngineView 내부에서 열리지 않고 시스템 기본 브라우저로 열리도록 처리.

- **구현**: `_ExternalLinkPage(QWebEnginePage)` — `acceptNavigationRequest()` 오버라이드
- **동작**: `NavigationTypeLinkClicked` 감지 → `QDesktopServices.openUrl()`로 외부 브라우저 실행, 내부 네비게이션 차단 (`return False`)
- **위치**: `ui/chat_tab.py` — `ChatTab.__init__()`에서 `self.chat_display.setPage(_ExternalLinkPage(...))`로 적용

### Chat Smart Scroll (스마트 스크롤)

`resources/chat.html`에 구현된 채팅 스크롤 제어 로직. AI 스트리밍 응답 중 사용자가 자유롭게 스크롤하여 이전 내용을 읽을 수 있도록 조건부 자동 스크롤 패턴 적용.

- **`isNearBottom(threshold)`**: 사용자가 하단에서 50px 이내에 있는지 판단
- **`scrollToBottom(force)`**: `force=true`이면 무조건 하단 스크롤, 없으면 하단 근처일 때만 스크롤
- **강제 스크롤 (`force=true`)**: `appendUserMessage()`, `startAiMessage()`, `appendFinishedAiMessage()` — 사용자 메시지 전송, AI 응답 시작, 히스토리 복원 시
- **조건부 스크롤 (force 없음)**: `renderStreamingBuffer()`, `finishAiMessage()` — 스트리밍 중/완료 시 사용자가 위로 스크롤했으면 위치 유지

### Streaming Stop (일반 모드 답변 중지)

일반 RAG 쿼리의 AI 스트리밍 응답 도중 사용자가 즉시 중단할 수 있는 기능. ChatGPT 스타일로 전송 버튼이 중지 버튼으로 전환된다.

- **UI**: 스트리밍 시작 시 "전송" 버튼 → 빨간 "⏹" 중지 버튼으로 자동 전환, 완료/중지 시 원래 버튼으로 복원
- **동작**: 중지 클릭 시 `LLMWorker._stopped` 플래그 설정 → 스트리밍 루프(`llm.stream()`) 내 매 토큰마다 체크하여 `break` → 현재까지의 부분 답변을 그대로 표시
- **중지 시점**: 검색(`agent.invoke`) 완료 직후 또는 스트리밍 도중 언제든 가능
- **PyQt6 구현**:
  - `workers/llm_worker.py`: `LLMWorker._stopped` 플래그 + `stop()` 메서드, `stream_messages()` 루프 내 체크
  - `ui/chat_tab.py`: `llm_stop_requested` 시그널, `_on_send()`에서 스트리밍 중이면 중지 emit, `start_streaming()`/`_restore_send_btn()`으로 버튼 전환
  - `ui/main_window.py`: `_on_llm_stop()` → `LLMWorker.stop()` 호출

### Notebook Summary (노트북 요약)

📓 노트북 뷰어 탭에 통합된 LLM 기반 요약 기능.

- **UI**: 좌측 체크박스 노트북 목록 + 우측 셀/요약 전환 뷰 (QSplitter)
- **동작**: 체크한 노트북들의 셀 내용을 LLM에 전송하여 한국어 요약 생성
- **마크다운 렌더링**: 요약 카드에서 `QTextBrowser.setMarkdown()` + `defaultStyleSheet`로 마크다운 렌더링 (헤더, 볼드, 리스트, 코드 블록 등). 채팅 탭의 `marked.js` 방식과 별도로 Qt 네이티브 마크다운 렌더링 사용.
- **시스템 프롬프트**: `summary_prompt.txt` (선택, 없으면 기본 프롬프트 사용)
- **캐시**: 인메모리 — 앱 실행 중 이미 요약된 노트북은 재요청하지 않음
- **중지**: 진행 중 "⏹️ 중지" 버튼으로 즉시 중단 가능
- **PyQt6 구현**:
  - `rag_core.py`: `load_summary_prompt()`, `prepare_notebook_summary_prompt()`
  - `workers/llm_worker.py`: `SummaryWorker` QThread
  - `ui/notebook_tab.py`: 체크박스 목록, 요약 생성 버튼, 프로그레스, 셀/요약 뷰 전환, `QTextBrowser` 마크다운 카드
  - `ui/main_window.py`: `_on_summary_requested()` → SummaryWorker 생성/관리

### Notebook Cell Chat (노트북 셀 채팅)

노트북 뷰어의 "셀 보기"에 통합된 셀 기반 Q&A 채팅 기능. Jupyter 스타일 노트북 렌더링 + 선택 셀 질문.

- **레이아웃**: 셀 보기가 좌우 QSplitter로 분할 — 좌측: Jupyter 스타일 노트북 뷰어, 우측: 채팅 패널
- **노트북 뷰어**: `resources/notebook_viewer.html` — marked.js로 마크다운 렌더링, highlight.js로 코드 구문 강조
- **셀 선택**: 체크박스 기반 다중 셀 선택, Shift+클릭 범위 선택, 전체 선택/해제
- **채팅 동작**: 선택된 셀 + 노트북 요약 + 질문을 LLM에 직접 전송 (RAG 미사용)
- **요약 자동생성**: 요약이 없는 노트북에서 질문 시 SummaryWorker로 자동 생성 후 채팅 시작
- **스트리밍**: `NotebookChatWorker` QThread — 토큰 단위 스트리밍 응답
- **시스템 프롬프트**: `prompts/notebook_chat_prompt.txt` (선택, 없으면 기본 프롬프트)
- **PyQt6 구현**:
  - `rag_core.py`: `load_notebook_chat_prompt()`, `prepare_notebook_chat_prompt()`
  - `workers/llm_worker.py`: `NotebookChatWorker` QThread
  - `ui/notebook_tab.py`: 셀+채팅 QSplitter, `_on_chat_send()`, 스트리밍 콜백
  - `ui/main_window.py`: `_on_notebook_chat()` → NotebookChatWorker 생성/관리
  - `resources/notebook_viewer.html`: Jupyter 스타일 셀 렌더러 (체크박스 선택)
  - `resources/notebook_chat.html`: 채팅 인터페이스 (스트리밍, 마크다운 렌더링)

### RAG Parameter Configuration

`config.txt` (project root, `KEY=VALUE` format) controls RAG pipeline parameters. The file is loaded once at startup via `_load_config()` into the `RAG_CONFIG` dict. If the file is missing, all parameters use built-in defaults.

| Key | Default | Description |
|-----|---------|-------------|
| `VECTOR_K` | 5 | Vector retriever top-k |
| `BM25_K` | 5 | BM25 retriever top-k |
| `GRAPH_K` | 5 | Graph RAG top-k |
| `GRAPH_HOPS` | 2 | Multi-hop propagation depth |
| `SEQ_DECAY` | 0.5 | Sequential edge decay |
| `VAR_DECAY` | 0.8 | Shared variable edge decay |
| `KEYWORD_BOOST` | 0.4 | Keyword score boost multiplier |
| `SEED_COUNT` | 3 | Vector seed documents for Graph RAG |
| `VECTOR_WEIGHT` | 0.6 | Ensemble vector weight |
| `BM25_WEIGHT` | 0.4 | Ensemble BM25 weight |
| `MAX_DOCS` | 10 | Max merged context documents |
| `LLM_TEMPERATURE` | 0.2 | LLM response temperature |
| `TRACE_DEBUG` | false | 쿼리별 retriever 결과를 trace_logs/에 저장 |
| `AGENTIC_MAX_ITERS` | 3 | Agentic Mode 검색→평가→보강 최대 반복 횟수 |
| `AGENTIC_FANOUT_K` | 5 | Agentic Mode 검색어당 top-k |
| `AGENTIC_MAX_SNIPPETS` | 24 | Agentic Mode 누적 근거 상한 |
| `AGENTIC_MAX_QUERIES` | 8 | Agentic Mode 한 패스 검색어 수 상한 |

### Trace Debug Logging (트레이스 디버그)

RAG 검색 파이프라인의 디버깅을 위한 retriever별 결과 로깅 기능. `config.txt`에서 `TRACE_DEBUG=true`로 활성화.

- **활성화**: `config.txt`에서 `TRACE_DEBUG=true` 설정
- **출력 경로**: `trace_logs/` 폴더에 타임스탬프+쿼리명 형태의 `.txt` 파일 생성 (예: `20260324_211218_판다스_데이터프레임.txt`)
- **로그 내용**: 각 쿼리마다 Vector RAG, BM25, Graph RAG, Merged 4단계의 검색 결과를 기록 (노트북명, 셀 번호, 셀 타입, 셀 내용)
- **호출 시점**: `merge_docs` 노드에서 문서 병합 완료 후 자동 호출
- **구현**:
  - `rag_core.py`: `_is_trace_debug()` (설정 확인), `_format_docs_section()` (결과 포맷), `_write_trace_log()` (파일 저장)
  - `merge_docs` 노드 내부에서 `_write_trace_log()` 호출

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | PyQt6 앱 진입점 |
| `ui/main_window.py` | MainWindow (탭/패널 조립, 워커 관리) |
| `ui/config_panel.py` | 좌측 설정 패널 |
| `ui/chat_tab.py` | 채팅 탭 (스트리밍, 답변 중지, 모드 선택기, Force Mode UI, Agentic 트레이스, 외부 링크) |
| `ui/docs_tab.py` | 문서 탐색 탭 |
| `ui/graph_tab.py` | 그래프 탐색 탭 |
| `ui/notebook_tab.py` | 노트북 뷰어 탭 (Jupyter 스타일 렌더링 + 셀 Q&A 채팅) |
| `ui/dir_tab.py` | 디렉토리 트리 탭 |
| `workers/llm_worker.py` | QThread 워커 (RAG빌드, LLM, Force, Agentic, 예시질문, 후속쿼리, 노트북채팅) |
| `rag_core.py` | RAG 비즈니스 로직 (UI 무관) |
| `agentic_rag.py` | Agentic Mode 비즈니스 로직 (계획/검색/게이트/합성, UI 무관) |
| `env_loader.py` | env.txt 환경변수 로더 |
| `notebook_rag_agent.py` | **레거시** Streamlit 앱 (미사용, 수정 금지) |
| `work/` | Lecture notebook directory (`.ipynb` files) |
| `prompts/system_prompt.txt` | Optional custom LLM system prompt |
| `prompts/force_prompt.txt` | Force Mode system prompt (관련성 판단용) |
| `prompts/agentic_planner_prompt.txt` | Agentic Mode 계획/질의 재작성 프롬프트 |
| `prompts/agentic_sufficiency_prompt.txt` | Agentic Mode 충분성 게이트 프롬프트 |
| `prompts/agentic_synthesis_prompt.txt` | Agentic Mode 합성(답변) 프롬프트 |
| `prompts/summary_prompt.txt` | Notebook summary system prompt |
| `prompts/notebook_chat_prompt.txt` | Notebook cell chat system prompt |
| `resources/notebook_viewer.html` | Jupyter 스타일 노트북 셀 렌더러 |
| `resources/notebook_chat.html` | 노트북 셀 Q&A 채팅 인터페이스 |
| `config.txt` | RAG pipeline parameter configuration |
| `trace_logs/` | Trace debug 로그 출력 폴더 (`TRACE_DEBUG=true` 시 생성) |
| `requirements_1.txt` | Python dependencies |
| `.env` / `env.txt` | Environment variables (API keys, model config) |
