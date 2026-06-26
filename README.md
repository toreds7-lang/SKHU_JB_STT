# SKHU Agent V1.0 — Jupyter Notebook RAG Agent

LangGraph 기반 Jupyter Notebook 강의용 하이브리드 RAG AI 에이전트

> **Vector RAG + BM25 + Cell-level Graph RAG** 세 가지 검색 방식을 결합하여
> 강의 노트북에서 정확한 정보를 찾아 AI 튜터가 설명해주는 앱입니다.
> **Streamlit 웹 앱**과 **PyQt6 데스크탑 앱** 두 가지 UI를 지원합니다.

---

## 아키텍처

```
User Query
    │
    ├─► vector_retrieve   (FAISS 의미 검색, k=5)
    ├─► bm25_retrieve     (BM25 키워드 검색, k=5)
    └─► graph_retrieve    (Graph RAG, top_k=5)
              │
         merge_docs  (중복 제거, 최대 10개 컨텍스트 구성)
              │
         LLM (streaming + 대화 히스토리)  →  Answer + 출처 표시

User Query "/f ..."
    │
    └─► Force Mode  (전수 검색, 병렬)
         모든 .ipynb → 5셀 청크 분할 → N개 병렬 워커가 LLM 관련성 판단
              │
         관련 청크만 누적 출력 + 출처 표시
```

모든 검색 노드는 LangGraph `StateGraph`를 통해 순차 실행됩니다.

---

## 검색 방식

| 방식 | 알고리즘 | 특징 |
|------|----------|------|
| **Vector RAG** | FAISS + OpenAI Embeddings | 의미적 유사도 기반, 문맥 이해 |
| **BM25** | TF-IDF 기반 키워드 랭킹 | 정확한 용어 매칭, 짧은 셀에 유리 |
| **Graph RAG** | NetworkX DiGraph + 멀티홉 점수 전파 | 셀 간 관계 추적, 관련 셀 확장 검색 |
| **Hybrid** | EnsembleRetriever (Vector 60% + BM25 40%) | 두 방식의 장점 결합 |
| **Force Mode** | LLM 병렬 판단 (N개 워커) | 모든 노트북 전수 검색, `/f` 접두어로 활성화 |

### Graph RAG 상세

셀 그래프는 두 종류의 엣지로 구성됩니다:

| 엣지 타입 | 조건 | 점수 감쇠 |
|-----------|------|-----------|
| `sequential` | 같은 노트북 내 인접 셀 | 0.5 |
| `shared_var` | 코드 셀 간 변수명 공유 | 0.8 |

검색 흐름:
1. **Vector seed** — 벡터 검색으로 상위 3개 seed 노드 선정 (score=1.0)
2. **Keyword boost** — 쿼리 토큰과 셀 텍스트 매칭 (+0.4 보조 점수)
3. **Multi-hop 전파** — 2 hop 이내 이웃 노드로 점수 전파 (엣지 타입별 감쇠 적용)
4. **상위 top_k 반환** — 점수 기준 정렬 후 반환

---

## 설치

### 1. 가상 환경 생성 및 활성화

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python -m venv .venv
source .venv/bin/activate
```

### 2. 의존성 설치

```bash
# Streamlit 웹 앱
pip install -r requirements_1.txt

# PyQt6 데스크탑 앱
pip install -r requirements_qt.txt
```

### 3. 환경 변수 설정

프로젝트 루트에 `.env` 또는 `env.txt` 파일 생성:

```env
OPENAI_API_KEY=sk-...
LLM_BASE_URL=http://localhost:8000/v1
LLM_MODEL=gpt-4o-mini
EMBEDDING_BASE_URL=
EMBEDDING_MODEL=text-embedding-ada-002
FORCE_WORKERS=3
```

> `LLM_BASE_URL`을 비워두면 OpenAI 공식 API를 사용합니다.
> `EMBEDDING_BASE_URL`을 비워두면 OpenAI 공식 임베딩 API를 사용합니다.

---

## 실행

### Streamlit 웹 앱

```bash
streamlit run notebook_rag_agent.py
```

브라우저에서 `http://localhost:8501` 접속

### PyQt6 데스크탑 앱

```bash
python main.py
```

### PyInstaller 패키징 (배포용 EXE)

```bash
pip install pyinstaller>=6.8.0
pyinstaller build.spec
```

결과물: `dist/SKHU_Agent/SKHU_Agent.exe`
사용자는 `SKHU_Agent.exe` 옆에 `env.txt`와 `work/` 폴더를 배치하여 실행합니다.

---

## UI 구성

두 UI 모두 동일한 5개 탭 구조를 제공합니다:

| 탭 | 설명 |
|----|------|
| **채팅** | AI 튜터와 대화, 대화 히스토리 기반 후속 질문, 스트리밍 응답, 출처 표시, 추천 검색어, `/f` Force Mode 전수 검색 |
| **문서 탐색** | 노트북·셀 타입·키워드 필터로 인덱싱된 전체 셀 탐색 |
| **그래프 탐색** | 셀 관계 그래프 통계, 노드 이웃 검색, 엣지 목록 테이블 |
| **노트북 뷰어** | 노트북 전체 셀을 코드/마크다운 스타일로 렌더링 |
| **디렉토리** | 작업 디렉토리 트리, 노트북별 셀 수·파일 크기 표시 |

### 사이드바 / 설정 패널

| 항목 | 설명 | 예시 |
|------|------|------|
| 노트북 디렉토리 | `.ipynb` 파일이 있는 폴더 | `work` |
| LLM Base URL | 로컬 LLM 서버 주소 | `http://localhost:8000/v1` |
| LLM 모델명 | 사용할 모델 이름 | `gpt-4o-mini`, `qwen2.5-7b-instruct` |
| LLM API Key | LLM 인증 키 | `sk-...` 또는 로컬 시 `dummy` |
| Embedding Base URL | 로컬 임베딩 서버 (옵션) | `http://localhost:8001/v1` |
| Embedding 모델명 | 임베딩 모델 | `text-embedding-ada-002` |
| OpenAI API Key | OpenAI 인증 키 | `sk-...` |
| 검색 모드 | 검색 전략 선택 | `all` / `vector` / `bm25` / `graph` |
| Force Mode 병렬 워커 수 | 동시 LLM 호출 스레드 수 (1-10) | `3` |
| 캐시 디렉토리 | 인덱스 저장 경로 | `.rag_cache` |

---

## 파일 변경 감지 및 RAG 재구축

앱은 작업 디렉토리의 MD5 해시를 계산하여 노트북 파일의 추가·삭제·수정을 자동 감지합니다.

| 상태 | 동작 | 캐시 삭제 |
|------|------|-----------|
| RAG 미구축 | RAG 시스템 구축 | 없음 |
| 파일 변경 감지됨 | 자동 재구축 안내 | 메모리 + 디스크 |
| 수동 재구축 | RAG 재구축 | 메모리 + 디스크 |

재구축 시 삭제되는 캐시:
- FAISS 디스크 인덱스 (`.rag_cache/faiss_index/`)
- BM25 피클 파일 (`.rag_cache/bm25.pkl`)

---

## 캐시 구조

```
.rag_cache/
├── faiss_index/        # FAISS 벡터 인덱스 (자동 저장/로드)
│   ├── index.faiss
│   └── index.pkl
└── bm25.pkl            # BM25 인덱스 (자동 저장/로드)
```

수동으로 캐시를 초기화하려면:

```bash
rm -rf .rag_cache
```

---

## 시스템 프롬프트 커스터마이즈

프로젝트 루트에 `system_prompt.txt` 파일을 생성하면 기본 프롬프트를 덮어씁니다.

기본 프롬프트 동작:
- 노트북 컨텍스트 **범위 내**에서만 답변
- 한국어, 친근한 튜터 어투
- 코드 셀 직접 인용 + 줄별 설명
- 내용 없을 시: `"제공된 노트북에서 해당 내용을 찾을 수 없습니다"` 반환

### Force Mode 프롬프트

`force_prompt.txt` 파일로 Force Mode 전용 시스템 프롬프트를 설정합니다.
파일이 없으면 내장 기본값을 사용합니다.

- 청크가 질문과 관련 있으면 `RELEVANT` + 요약 응답
- 관련 없으면 `NOT_RELEVANT` 응답
- 채팅에서 `/f 질문` 또는 `/f질문`으로 Force Mode 활성화

---

## Wiki Q&A (위키 지식베이스 질의응답)

📚 Wiki 탭에 통합된 **경량 질의응답** 기능. RAG 파이프라인(FAISS/BM25/Graph)을
사용하지 않고, 미리 생성된 **위키 마크다운 페이지**를 컨텍스트로 LLM에게 직접 질문합니다.

### 지식베이스 (위키 페이지)

Q&A가 참조하는 내용은 `WikiBuildWorker`가 미리 생성하여 `<캐시디렉토리>/wiki/*.md`에
저장한 마크다운 페이지입니다. 두 종류가 있습니다:

| 페이지 종류 | 생성 함수 | 내용 |
|-------------|-----------|------|
| **노트북 페이지** | `generate_notebook_wiki_page` | `.ipynb` 1개당 1개 (요약 기반, LLM 미사용) |
| **개념 페이지** | `generate_concept_wiki_page` | 추출된 개념 1개당 1개 (개념당 LLM 1회 호출) |

> `index.md`, `log.md`는 Q&A 컨텍스트에서 제외됩니다.

### 동작 흐름

```
질문 입력 (wiki_qa.html)
    │
    ▼  WikiQAWorker (QThread)
rag_core.wiki_qa()
    │
    ├─ 1. 모든 위키 .md 페이지 메모리 로드
    ├─ 2. 질문을 단어 토큰으로 분해 (\b\w+\b, 소문자화)
    ├─ 3. 페이지별 점수 = 질문 단어가 페이지 본문에 등장한 개수 (BM25-style 키워드 매칭)
    ├─ 4. 점수 상위 5개 페이지 선택 (max_context_pages=5, 점수 0 제외)
    ├─ 5. 각 페이지 앞부분 500자만 잘라 컨텍스트로 결합
    └─ 6. LLM 스트리밍 응답 → wiki_qa.html 패널에 토큰 단위 렌더링
```

검색은 **임베딩이 아닌 단순 키워드 중첩(term presence) 방식**입니다.
시스템 프롬프트는 "주어진 위키 컨텐츠 내에서만 답변하고, 없으면 모른다고 답하며,
마크다운으로 출처를 명시"하도록 지시합니다.

### 설계상 특징 및 주의점

- **Wiki를 먼저 생성해야 함** — 페이지가 없으면 *"위키 페이지를 찾을 수 없습니다. 먼저 Wiki를 생성해 주세요."* 반환
- **키워드 매칭 한정** — 의미·동의어 이해 없음. 질문과 페이지가 **글자가 겹치지 않으면** 그 페이지는 선택되지 않음
- **페이지당 500자 상한** — 답변은 각 페이지의 *앞부분*에 의존하므로 요약·도입부가 가장 중요
- **위키 범위 내 답변** — 노트북 위키에 없는 내용은 답하지 않음

### 잘 동작하는 질문 / 어려운 질문

| 잘 동작 | 어려움 |
|---------|--------|
| 자료의 용어를 그대로 쓴 개념 질문 (예: *"BM25가 무엇인가요?"*) | 내용어가 적은 모호하고 짧은 질문 |
| "X는 어느 노트북에 있나요?" 류 | 위키가 한국어인데 영어(또는 반대)로 묻는 동의어 질문 |
| 명명된 개념의 요약·비교 (예: *"벡터 RAG와 그래프 RAG의 차이는?"*) | 페이지 500자 이후에 묻힌 세부 내용 |
| 특정 주제에 대한 "설명해줘 / 정리해줘" | 어떤 노트북·개념 페이지에도 없는 주제 |

> 노트북 셀 전체에 대한 의미 기반 정밀 검색이 필요하면 **채팅 탭**(일반 RAG, `/a` Agentic,
> `/f` Force)이 더 적합합니다. Wiki Q&A는 생성된 위키 요약에 대한 빠른 조회용입니다.

### 구현 파일

| 파일 | 역할 |
|------|------|
| `rag_core.py` | `wiki_qa()` — 페이지 로드/키워드 스코어링/컨텍스트 구성/LLM 스트리밍 |
| `workers/llm_worker.py` | `WikiQAWorker` QThread(스트리밍), `WikiBuildWorker`(위키 페이지 생성) |
| `ui/wiki_tab.py` | Wiki 탭 UI, `_build_qa_panel()`, `_on_send_qa()`, 스트리밍 콜백 |
| `resources/wiki_qa.html` | Q&A 채팅 인터페이스 (마크다운 렌더링, 스트리밍) |

---

## 대화 히스토리 (Follow-up Aware)

채팅 탭에서 이전 대화 맥락을 기반으로 **자연스러운 후속 질문**이 가능합니다.

### 동작 방식

- LLM 호출 시 최근 **3턴(질문-답변 쌍)**의 대화 히스토리를 함께 전달합니다.
- 학생이 "그러면 join은 뭐가 달라?", "아까 그 코드 설명해줘"와 같은 후속 질문을 하면 LLM이 이전 맥락을 이해하여 답변합니다.
- 현재 질문에 대한 RAG 검색은 기존과 동일하게 수행되며, 히스토리는 LLM의 대화 이해를 돕는 보조 컨텍스트로만 사용됩니다.

### 메시지 구조

```
SystemMessage (시스템 프롬프트)
HumanMessage  (이전 질문 1)          ← 히스토리
AIMessage     (이전 답변 1, 500자 제한) ← 히스토리
HumanMessage  (이전 질문 2)          ← 히스토리
AIMessage     (이전 답변 2, 500자 제한) ← 히스토리
HumanMessage  (RAG 컨텍스트 + 현재 질문)  ← 현재 턴
```

### 특징

- **세션 내 한정**: 대화 히스토리는 앱 실행 중에만 유지되며, 앱 종료 시 초기화됩니다.
- **대화 초기화**: 🗑️ 버튼 클릭 시 히스토리도 함께 초기화됩니다.
- **Force Mode 제외**: `/f` Force Mode 대화는 히스토리에 포함되지 않습니다.
- **토큰 절약**: 이전 답변은 최대 500자로 잘라서 전달하여 토큰 사용량을 최소화합니다.

### 구현 파일

| 파일 | 역할 |
|------|------|
| `ui/chat_tab.py` | `get_history_for_llm()` — 최근 N턴 히스토리 추출, Force Mode 필터링, 답변 길이 제한 |
| `ui/main_window.py` | 히스토리를 추출하여 `LLMWorker`에 전달 |
| `workers/llm_worker.py` | `_build_history_messages()` — 히스토리를 LangChain 메시지로 변환하여 LLM에 주입 |

---

## 프로젝트 구조

```
SKHU_Agent/
├── notebook_rag_agent.py          # Streamlit 웹 앱 (단일 파일)
├── main.py                        # PyQt6 데스크탑 앱 진입점
├── rag_core.py                    # RAG 비즈니스 로직 (UI 비의존)
├── ui/                            # PyQt6 UI 모듈
│   ├── main_window.py             #   메인 윈도우 (QSplitter + QTabWidget)
│   ├── config_panel.py            #   설정 패널
│   ├── chat_tab.py                #   채팅 탭
│   ├── docs_tab.py                #   문서 탐색 탭
│   ├── graph_tab.py               #   그래프 탐색 탭
│   ├── notebook_tab.py            #   노트북 뷰어 탭
│   └── dir_tab.py                 #   디렉토리 탭
├── workers/                       # 백그라운드 워커
│   └── llm_worker.py              #   RAG 빌드 / LLM 추론 QThread
├── resources/                     # 리소스 파일
│   └── dark_theme.qss             #   다크 테마 스타일시트
├── build.spec                     # PyInstaller 빌드 스펙
├── system_prompt.txt              # 커스텀 시스템 프롬프트 (옵션)
├── force_prompt.txt               # Force Mode 전용 시스템 프롬프트 (옵션)
├── SK_Hynix.png                   # 로고 이미지
├── SK_Hynix.ico                   # 로고 아이콘 (EXE용)
├── .env / env.txt                 # 환경 변수
├── requirements_1.txt             # Streamlit 앱 의존성
├── requirements_qt.txt            # PyQt6 앱 의존성
├── work/                          # 강의 노트북 디렉토리
│   └── *.ipynb
└── .rag_cache/                    # 자동 생성 캐시 디렉토리
    ├── faiss_index/
    └── bm25.pkl
```

---

## 배포

### Docker (Streamlit 웹 앱)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements_1.txt .
RUN pip install -r requirements_1.txt
COPY notebook_rag_agent.py .
COPY SK_Hynix.png .
COPY work/ work/
EXPOSE 8501
CMD ["streamlit", "run", "notebook_rag_agent.py", \
     "--server.port=8501", "--server.address=0.0.0.0"]
```

```bash
docker build -t skhu-agent .
docker run -p 8501:8501 \
  -e OPENAI_API_KEY=sk-... \
  -e LLM_BASE_URL=http://host.docker.internal:8000/v1 \
  skhu-agent
```

### PyInstaller (데스크탑 EXE)

```bash
# ICO 파일 생성 (최초 1회)
python -c "from PIL import Image; Image.open('SK_Hynix.png').save('SK_Hynix.ico')"

# 빌드
pip install pyinstaller>=6.8.0
pyinstaller build.spec

# 배포: dist/SKHU_Agent/ 폴더 전체 배포
# 사용자는 SKHU_Agent.exe 옆에 env.txt와 work/ 폴더 배치
```

### 포트 / 외부 접속 옵션 (Streamlit)

```bash
# 포트 변경
streamlit run notebook_rag_agent.py --server.port 8080

# 외부 접속 허용
streamlit run notebook_rag_agent.py --server.address 0.0.0.0
```

---

## 주요 의존성

### 공통

| 패키지 | 용도 |
|--------|------|
| `langchain` / `langgraph` | RAG 파이프라인 오케스트레이션 |
| `langchain-openai` | OpenAI LLM / Embedding 연동 |
| `faiss-cpu` | 벡터 인덱스 |
| `rank-bm25` | BM25 키워드 검색 |
| `kiwipiepy` | 한국어 형태소 분석 |
| `networkx` | Graph RAG 셀 그래프 |
| `nbformat` | Jupyter 노트북 파싱 |
| `openai` / `tiktoken` | OpenAI API / 토큰 카운트 |

### Streamlit 전용

| 패키지 | 용도 |
|--------|------|
| `streamlit` | 웹 UI |

### PyQt6 전용

| 패키지 | 용도 |
|--------|------|
| `PyQt6` | 데스크탑 UI |
