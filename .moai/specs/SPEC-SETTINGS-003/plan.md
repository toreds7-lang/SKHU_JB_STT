# Implementation Plan — SPEC-SETTINGS-003

> WHAT/WHY는 `spec.md`에 있다. 이 문서는 건드릴 파일과 기술적 접근만 식별한다.
> 여기서 구현 코드를 작성하지 않는다. 모든 행/함수 인용은 현재 소스를 읽어 확인한 값이다.

## 1. Technical Approach

핵심은 **하나의 정적 근거 문서 + 두 개의 그라운딩 경로(매칭/비매칭)**다. 워커·HTML·JS·캐시는
건드리지 않는다. `SettingsQAWorker`는 단일 프롬프트 문자열(`HumanMessage`)만 받으므로
(`workers/settings_worker.py:47-71`), 모든 그라운딩은 `rag_core`가 만드는 프롬프트 문자열
안에서 처리한다.

### R1 — 정적 레퍼런스 문서 (`settings_reference.txt`)

**경로 결정**: 프로젝트 루트 `settings_reference.txt`.

- **근거**: `docs/` 디렉터리가 없음(확인함). `config.txt`, `env.txt`, `prompts/*.txt`가 모두
  루트에 있고, `load_system_prompt()`는 루트 상대 경로로 파일을 읽는다. 새 `docs/` 관례를
  도입할 이유가 없어 루트 배치가 가장 단순하고 일관적이다.

**문서 구조(저작은 /moai run 단계, 소스를 읽는 에이전트가 수행)**. 파서가 섹션을 안정적으로
추출할 수 있도록 각 항목은 일관된 헤더 규약을 따른다. 권장 규약(구현 시 확정):

```
## PARAM: VECTOR_K
- 무엇: Vector retriever가 반환하는 top-k 문서 수.
- 소비 위치: rag_core.build_rag_system() / merge_docs() — RAG_CONFIG["VECTOR_K"]로 읽힘.
- 흐름(high-level): 앙상블 리트리버의 vector 검색 top-k에 전달되어 merge_docs()의 후보 수를 좌우.
- 기본/범위: 5 (1–20).

## FILE: prompts/system_prompt.txt
- 역할: RAG 채팅 기본 시스템 프롬프트.
- 로더: rag_core.load_system_prompt() — 없으면 내장 _DEFAULT_SYSTEM_PROMPT 사용.
- 흐름(high-level): make_agent()가 에이전트 생성 시 시스템 메시지로 주입.
```

- 파라미터 항목은 `## PARAM: <KEY>`, 파일 항목은 `## FILE: <path>` 헤더로 시작한다(섹션 추출용).
- 각 항목의 소비 위치는 **실제 존재하는 심볼**을 인용해야 한다(REQ-004). 확인된 소비처 예시:
  - config 파라미터: `rag_core.py`의 `RAG_CONFIG.get(...)` 사용부(`build_rag_system` 816행,
    `merge_docs`의 `MAX_DOCS` 1018행 등), agentic 파라미터는 `agentic_rag.py`(4곳).
  - env 파라미터: `env_loader.py`, `ui/config_panel.py`, `workers/stt_worker.py`,
    `workers/stt_subprocess.py`, `app.py`(STT_MODEL/FORCE_WORKERS 소비 확인함).
  - 프롬프트 파일: `rag_core.load_system_prompt()`(286행), `load_force_prompt()`(1327행),
    `load_summary_prompt()`(1449행), `load_notebook_chat_prompt()`(1527행), agentic 프롬프트
    로더 3종은 `agentic_rag.py`.
- **정확성 저작 절차**: 저작 에이전트는 각 항목을 쓰기 전에 해당 파라미터/파일명을 코드베이스에서
  grep해 실제 소비 함수를 확인한 뒤 인용한다.

### R2 — 매칭된 키 프롬프트에 레퍼런스 섹션 추가

**대상 파일**: `rag_core.py`, `ui/settings_tab.py`

`rag_core.py`에 추가:

- `_SETTINGS_REFERENCE_PATH = "settings_reference.txt"` — 오버라이드 가능한 모듈 상수
  (`_SETTINGS_ENV_PATH` 99행 등과 동일 패턴; NFR-3 테스트 주입용).
- `load_settings_reference() -> str` — `load_system_prompt()`(286행)와 동일한 동기 읽기.
  파일이 없으면 빈 문자열 반환(예외 없음).
- `find_reference_section(reference_text: str, key_or_file: str) -> str` — 주어진 키/파일명의
  `## PARAM:`/`## FILE:` 섹션을 추출. 없으면 빈 문자열.

`build_settings_qa_prompt(...)`(350행) 확장 방침 — **하위 호환 유지**:

- 선택 인자 `reference_section: str | None = None`를 **끝에 추가**한다(기본값 None → 기존 호출과
  출력이 동일하므로 `tests/test_rag_core_settings.py`의 기존 단언이 깨지지 않음).
- `reference_section`이 주어지면 권위 메타데이터 블록 뒤에 "추가 레퍼런스(코드 사용처)" 블록으로
  덧붙인다.

`ui/settings_tab.py::_on_ask_clicked`(911행) 매칭 분기(930-935행):

- `load_settings_reference()` + `find_reference_section(ref, key)`로 섹션을 구해
  `build_settings_qa_prompt(question, key, entry, current_value, reference_section=section)`로 전달.

### R3 — 매칭 실패를 그라운딩 LLM 경로로 교체

**대상 파일**: `rag_core.py`, `ui/settings_tab.py`

`rag_core.py`에 추가:

- `build_settings_qa_grounded_prompt(question: str, reference_text: str) -> str` — 레퍼런스
  문서(전체 또는 관련 내용)를 근거로 하고, "문서에 근거해서만 한국어로 답하고 없으면 모른다고 하라"는
  가드를 포함하는 프롬프트를 만든다.

`ui/settings_tab.py::_on_ask_clicked` 비매칭 분기(현재 921-928행, 하드코딩 거부) 교체:

- 현재: `answer = "…문서를 찾을 수 없습니다…"` → `finishAiMessage()` (LLM 미호출).
- 변경 후:
  1. `ref = load_settings_reference()`.
  2. `ref`가 비어 있지 않으면 `prompt = build_settings_qa_grounded_prompt(question, ref)`,
     `self._pending_qa_question = question`, `self.qa_requested.emit(prompt)`로 스트리밍 경로
     진입(매칭 경로와 동일하게 `on_qa_finished`가 `_append_qa_history` 수행 → REQ-010 충족).
  3. `ref`가 비어 있으면(문서 없음, REQ-011 폴백): 카탈로그 요약 기반 그라운딩 프롬프트로 폴백하거나,
     그것도 어려우면 기존 안내 문자열로 회귀(비크래시). 구현 시 폴백 형태 확정.

**중요(비매칭 경로의 `_pending_qa_question`)**: 기존 비매칭 분기는 `_pending_qa_question`을
설정하지 않고 즉시 히스토리를 append한다. 스트리밍 경로로 바꾸면 emit 전에 반드시
`self._pending_qa_question = question`을 설정해야 `on_qa_finished`(940-942행)가 올바른 질문으로
히스토리를 남긴다.

## 2. Files to Modify

| File | Change | Requirement |
|------|--------|-------------|
| `settings_reference.txt` (신규, 루트) | env 6 + config 18 + 파일 9 항목을 `## PARAM:` / `## FILE:` 헤더 규약으로 손 저작 (소비 함수·흐름 포함) | R1 |
| `rag_core.py` | `_SETTINGS_REFERENCE_PATH` 상수, `load_settings_reference()`, `find_reference_section()`, `build_settings_qa_grounded_prompt()` 추가; `build_settings_qa_prompt()`에 선택 인자 `reference_section` 추가(하위 호환) | R1,R2,R3 |
| `ui/settings_tab.py` | `_on_ask_clicked` 매칭 분기에 레퍼런스 섹션 근거 주입; 비매칭 분기의 하드코딩 거부를 그라운딩 `qa_requested` 경로로 교체(+ `_pending_qa_question` 설정) | R2,R3 |
| `tests/test_rag_core_settings.py` | 새 로더/섹션추출/그라운딩 프롬프트 빌더 테스트 + `build_settings_qa_prompt` 하위 호환(인자 없이 호출 시 기존 출력 유지) | R1–R4 |
| `tests/test_settings_tab.py` | 비매칭 질문이 하드코딩 거부 대신 `qa_requested`를 emit함(+`_pending_qa_question` 설정); 매칭 질문 프롬프트에 레퍼런스 섹션 포함; 문서 없을 때 비크래시 폴백 | R2,R3,R4 |

**변경 없음**: `workers/settings_worker.py`, `resources/settings_chat.html`, `cache_store.py`,
`ui/main_window.py`(기존 `qa_requested` → `_on_settings_qa_requested` 배선 재사용).

## 3. Test Strategy (TDD, 프로젝트 품질 모드)

- **R1(문서 존재/완전성/정확성)** (`tests/test_rag_core_settings.py`):
  - `settings_reference.txt`가 존재하고, 24개 파라미터 키와 9개 파일명이 모두 문서에 등장한다
    (완전성 — 카탈로그 키 리스트 대비 검사).
  - 정확성 스팟체크: 문서가 인용한 소비 함수 표본(예: `build_rag_system`, `load_system_prompt`,
    `load_force_prompt`)이 실제 소스에 존재하는 심볼인지 확인(grep/AST 표본 검증).
- **R2(매칭 섹션 근거)** (`tests/test_rag_core_settings.py`):
  - `find_reference_section(ref, "VECTOR_K")`가 해당 섹션 텍스트를 반환.
  - `build_settings_qa_prompt(..., reference_section=section)` 출력에 섹션 텍스트가 포함됨.
  - `build_settings_qa_prompt(...)`를 `reference_section` 없이 호출하면 **기존과 동일한 출력**
    (하위 호환 회귀 방지).
- **R3(비매칭 그라운딩)** (`tests/test_settings_tab.py`, `qtbot`):
  - 어떤 키와도 매칭 안 되는 질문(예: `"이 프롬프트 파일들이 서로 어떻게 다른가요?"`) 입력 후
    전송 시, 하드코딩 거부 문자열이 나오지 않고 `qa_requested`가 emit되며
    `_pending_qa_question`이 설정된다(`qtbot.waitSignal` 또는 시그널 스파이).
  - `build_settings_qa_grounded_prompt(q, ref)` 출력에 레퍼런스 내용이 포함됨.
- **R4(디그레이데이션/하위호환)**:
  - `_SETTINGS_REFERENCE_PATH`를 존재하지 않는 경로로 몽키패치했을 때 `load_settings_reference()`가
    빈 문자열을 반환하고, 비매칭 질문 전송이 예외 없이 안전 폴백으로 처리됨.
  - 기존 121개 테스트가 그대로 통과(회귀 없음).

## 4. Milestones (우선순위 순, 시간 추정 없음)

1. **M1 — rag_core 그라운딩 인프라**: `_SETTINGS_REFERENCE_PATH`, `load_settings_reference()`,
   `find_reference_section()`, `build_settings_qa_grounded_prompt()`, `build_settings_qa_prompt`
   선택 인자. 단위 테스트 추가.
2. **M2 — 레퍼런스 문서 저작**: 소스를 읽어 `settings_reference.txt`의 24 파라미터 + 9 파일 항목
   저작(정확성 grep 확인 포함). 완전성/정확성 테스트 추가.
3. **M3 — settings_tab 배선**: 매칭 분기 섹션 근거 주입 + 비매칭 분기 그라운딩 경로 교체
   (`_pending_qa_question` 설정 포함). 위젯 테스트 추가.
4. **M4 — 전체 그린**: `pytest tests/ -q`를 `QT_QPA_PLATFORM=offscreen`에서 실행, TRUST 5 리뷰,
   `main`에 직접 커밋(수동 git, 브랜치·푸시 없음).

## 5. Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|-----------|
| `build_settings_qa_prompt` 시그니처 변경으로 기존 테스트 파손 | Medium | 인자를 **선택(기본 None)**으로 추가하고 None일 때 기존 출력 유지; 하위 호환 회귀 테스트로 고정 |
| 비매칭 경로가 `_pending_qa_question` 미설정으로 히스토리 오염 | Medium | emit 직전 항상 `_pending_qa_question = question` 설정(테스트로 검증) |
| 전체 문서를 프롬프트에 담아 토큰 과다 | Low-Med | 문서를 high-level 요약으로 제한(NFR-4); 필요 시 관련 섹션만 선택하는 최적화는 후속 |
| 레퍼런스 문서가 소스와 시간이 지나며 어긋남 | Medium | 정적·수동 갱신이 사용자 선택(§5 배제 1); 정확성 스팟체크 테스트로 최소 방어, 갱신은 수동 |
| 문서 삭제 시 Q&A 크래시 | Low | `load_settings_reference()`가 빈 문자열 반환 + 비크래시 폴백(REQ-011) |

## 6. MX Tag Plan (Lightweight Scan)

신규 공개 API 표면만 스캔 대상이다 (기존 코드 상호작용은 하위 호환 유지로 최소화됨, 고fan_in
함수 변경 없음).

- `rag_core.load_settings_reference()` — `@MX:NOTE` 후보. 호출자는 `_on_ask_clicked` 매칭/비매칭
  분기 2곳뿐(fan_in < 3) — `@MX:ANCHOR` 불필요.
- `rag_core.find_reference_section()` — `@MX:NOTE` 후보 (섹션 파싱 규약이 `settings_reference.txt`의
  `## PARAM:`/`## FILE:` 헤더와 암묵적으로 결합되어 있음 — 규약이 바뀌면 함께 깨지는 위험을 주석으로 남김).
- `rag_core.build_settings_qa_grounded_prompt()` — `@MX:NOTE` 후보 (프롬프트 가드레일 근거 설명).
- `rag_core.build_settings_qa_prompt()`의 신규 선택 인자 `reference_section` — 기존 호출자
  (`ui/settings_tab.py`)와 테스트 양쪽에서 쓰이므로 시그니처 변경 지점에 `@MX:NOTE`로 하위 호환
  의도를 남긴다.
- 위험 패턴(goroutine 유사 동시성, complexity>=15) 없음 — `@MX:WARN` 불필요.
- 미테스트 공개 함수 없음(전부 R1–R4 테스트 계획에 포함) — `@MX:TODO` 불필요.

## 7. Resolved Decisions / Remaining Implementation Choices

- **레퍼런스 문서를 설정 탭 파일 목록에 열람 전용으로 노출?** 사용자 확인 결과 **비노출로 확정**
  (spec.md §5 배제 3, §8). `CONFIG_FILES` 확장은 하지 않는다. (향후 열람 전용 노출이 필요해지면
  별도 후속 SPEC으로 재검토.)
- **비매칭 + 문서 없음 폴백의 정확한 형태**(카탈로그 요약 그라운딩 vs 기존 안내 문자열)는 구현
  단계에서 확정. 어느 쪽이든 REQ-011의 "예외 없이 동작" 제약은 충족.
