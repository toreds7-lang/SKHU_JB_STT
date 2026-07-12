---
id: SPEC-SETTINGS-003
version: 0.1.2
status: draft
created: 2026-07-11
updated: 2026-07-11
author: manager-spec (MoAI Plan Workflow)
priority: medium
issue_number: 0
---

# SPEC-SETTINGS-003: 설정 레퍼런스 문서 기반 Q&A 그라운딩

## HISTORY

| Version | Date       | Author       | Change                                                                 |
|---------|------------|--------------|------------------------------------------------------------------------|
| 0.1.0   | 2026-07-11 | manager-spec | 최초 초안 — 정적 설정 레퍼런스 문서(`settings_reference.txt`)와 이를 근거로 하는 Q&A 그라운딩 |
| 0.1.1   | 2026-07-11 | MoAI (plan)  | 사용자 승인 — §8 오픈 이슈(파일 목록 노출 여부) "노출하지 않음"으로 확정, SPEC 확정 |
| 0.1.2   | 2026-07-11 | MoAI (plan)  | plan-auditor 감사(iter 1, FAIL 0.35) 반영: REQ-005/AC-REQ-005에 "high-level" 측정 기준(3-8줄, 코드블록 금지) 추가, AC-REQ-002/003·006/007 REQ당 1개로 분리. frontmatter `labels`/`created_at` 요구와 acceptance.md EARS 재작성 요구는 이 프로젝트의 확립된 8필드 프론트매터 관례(SPEC-SETTINGS-002 선례) 및 `plan.md` 워크플로우의 Given/When/Then acceptance 규격과 상충하여 반영하지 않음(사용자에게 근거와 함께 보고, override) |

---

## 1. Overview

### 1.1 Context

SPEC-SETTINGS-001은 설정 탭(`ui/settings_tab.py`)과 그 위의 LLM 기반 Q&A를 만들었고,
SPEC-SETTINGS-002는 세 가지 UX 개선(Enter 전송, Clear, 탭 순서)을 완료했다(121/121 테스트 통과,
커밋 `9f6929b`). 현재 설정 Q&A의 그라운딩은 다음과 같이 동작한다:

- `ui/settings_tab.py::_on_ask_clicked` (약 911행)가 진입점이다.
- `rag_core.find_config_key_in_question(question, config_metadata)` (약 325행)로 질문에서
  알려진 파라미터 키를 퍼지 매칭한다.
- **키가 매칭되면** `rag_core.build_settings_qa_prompt(question, key, entry, current_value)`
  (약 350행)로 프롬프트를 만들어 `qa_requested` 시그널로 올린다. 이 프롬프트의 근거는
  `_CONFIG_METADATA_CATALOG` / `_ENV_METADATA_CATALOG`의 **한 줄짜리 `description`뿐**이다.
- **키가 매칭되지 않으면** `_on_ask_clicked`가 UI 계층에서 하드코딩된 한국어 거부 메시지
  ("…에 대한 문서를 찾을 수 없습니다…", 약 921-928행)를 직접 출력하고 종료한다. 이때는
  LLM을 전혀 호출하지 않는다.

### 1.2 Problem

1. **근거가 빈약하다.** 매칭된 키조차 한 줄짜리 설명만 근거로 답하므로, "이 파라미터가 실제로
   코드 어디에서 어떻게 쓰이는가"라는 질문에 깊이 있게 답하지 못한다.
2. **횡단(cross-cutting) 질문이 거부된다.** "이 프롬프트 파일들이 서로 어떻게 다른가요",
   "config.txt는 전체적으로 뭘 하나요"처럼 특정 키에 매핑되지 않는 질문은 매칭 실패로 처리되어
   하드코딩된 거부 메시지만 돌아온다. 사용자는 실질적 답을 받지 못한다.

### 1.3 Solution

구현 소스(`rag_core.py`, `agentic_rag.py`, `ui/*.py`, `workers/*.py`, `main.py` 등)를 읽고
손으로 작성한 **하나의 정적 레퍼런스 문서** `settings_reference.txt`(프로젝트 루트)를 도입한다.
이 문서는 6개 env.txt 파라미터, 18개 config.txt 파라미터, 9개 설정/프롬프트 파일 각각에 대해
"무엇인지 / 어느 모듈·함수가 소비하는지 / 시스템에서 값이 어떻게 흐르는지"를 high-level로 기술한다.

설정 Q&A는 이 문서를 **추가 근거**로 삼는다:

- **매칭된 키**: 기존 메타데이터 한 줄 근거에 더해 레퍼런스 문서의 해당 섹션을 프롬프트에 포함한다.
- **매칭 실패**: 하드코딩 거부 메시지 대신, 레퍼런스 문서(전체 또는 관련 섹션)를 근거로 한 LLM
  프롬프트를 만들어 기존 `qa_requested` → `SettingsQAWorker` 스트리밍 경로로 실제 답변을 생성한다.

이 SPEC은 **기존 Q&A 흐름을 대체하지 않고 확장**한다. 편집/저장/검증/초기화/diff, Enter 전송,
Clear, 탭 순서 등 SPEC-SETTINGS-001/002 기능은 그대로 유지된다.

### 1.4 Target Users

RAG 파라미터·프롬프트를 설정 탭에서 조율하는 연구자·교수·파워 유저 (SPEC-SETTINGS-001과 동일 대상).

---

## 2. Scope

### 2.1 문서화 대상 (레퍼런스 문서 스코프)

레퍼런스 문서가 반드시 다뤄야 하는 항목은 설정 탭의 카탈로그가 정의한 범위와 일치한다:

- **env.txt 파라미터 6개** (`rag_core._ENV_METADATA_CATALOG`): `OPENAI_API_KEY`, `LLM_MODEL`,
  `LLM_BASE_URL`, `EMBEDDING_MODEL`, `EMBEDDING_BASE_URL`, `FORCE_WORKERS`.
- **config.txt 파라미터 18개** (`rag_core._CONFIG_METADATA_CATALOG`): `VECTOR_K`, `BM25_K`,
  `GRAPH_K`, `GRAPH_HOPS`, `SEQ_DECAY`, `VAR_DECAY`, `KEYWORD_BOOST`, `SEED_COUNT`,
  `VECTOR_WEIGHT`, `BM25_WEIGHT`, `MAX_DOCS`, `LLM_TEMPERATURE`, `TRACE_DEBUG`,
  `AGENTIC_MAX_ITERS`, `AGENTIC_FANOUT_K`, `AGENTIC_MAX_SNIPPETS`, `AGENTIC_MAX_QUERIES`,
  `STT_MODEL`.
- **파일 9개** (`SettingsTab.CONFIG_FILES`): `env.txt`, `config.txt`, 그리고 `prompts/` 아래
  7개 프롬프트 파일 (`system_prompt.txt`, `force_prompt.txt`, `agentic_planner_prompt.txt`,
  `agentic_sufficiency_prompt.txt`, `agentic_synthesis_prompt.txt`, `notebook_chat_prompt.txt`,
  `summary_prompt.txt`).

문서화 범위는 **디스크의 config.txt에 현재 존재하는 키가 아니라 위 카탈로그**를 기준으로 한다
(config.txt에 일부 키가 없어도 18개 전부 문서화한다).

### 2.2 코드 변경 대상

- `rag_core.py` — 레퍼런스 문서 로더 + 섹션 추출 + 그라운딩 프롬프트 빌더 (추가 함수).
- `ui/settings_tab.py` — `_on_ask_clicked`의 하드코딩 거부 분기를 그라운딩 LLM 경로로 교체,
  매칭 경로에 레퍼런스 섹션 근거 추가.

---

## 3. Requirements (EARS Format)

### R1 — 정적 설정 레퍼런스 문서

- **REQ-001 (Ubiquitous)**: 시스템은 프로젝트 루트에 체크인된 단일 정적 텍스트 문서
  `settings_reference.txt`를 **포함해야 한다(shall)**. 이 문서는 §2.1의 24개 파라미터(env 6 +
  config 18)와 9개 파일 전부를 다룬다.
- **REQ-002 (Ubiquitous)**: 문서의 각 **파라미터** 항목은 (a) 그 파라미터가 무엇인지,
  (b) 그 값을 소비하는 모듈·함수·클래스와 소스 위치(파일명 + 함수/클래스 이름), (c) 값이
  시스템에서 high-level로 어떻게 흐르는지를 **기술해야 한다(shall)**.
- **REQ-003 (Ubiquitous)**: 문서의 각 **파일** 항목은 그 파일의 역할, 그 파일을 읽는 로더/소비
  함수, 그리고 내용이 high-level로 어떻게 사용되는지를 **기술해야 한다(shall)**.
- **REQ-004 (Ubiquitous)**: 문서가 인용하는 모든 소비 모듈·함수·클래스 이름은 현재 소스에
  실제로 존재하는 심볼과 **대응해야 한다(shall)** (정확성 제약 — 존재하지 않는 함수/파일을
  지어내지 않는다).
- **REQ-005 (Unwanted Behavior)**: 문서는 파라미터/파일별로 쪼개진 여러 파일이 아니라 **하나의
  통합 문서여야 하며**, 구현 코드 전문 복붙이나 줄 단위 스키마 덤프를 **포함해서는 안 된다(shall
  not)**. "high-level"의 측정 가능한 기준: 각 항목은 산문(prose) 3-8줄 이내이며, 코드 블록
  (` ``` ` 펜스 또는 4칸 들여쓰기 코드)을 포함하지 않고, 소스 위치는 파일명+함수/클래스명으로만
  인용한다(코드 라인 전체 복사 금지).

### R2 — 매칭된 키의 Q&A 그라운딩 강화

- **REQ-006 (Event-Driven)**: 사용자의 설정 Q&A 질문이 알려진 config/env 키와 매칭될 **때(when)**,
  시스템은 기존 CONFIG_METADATA 한 줄 근거에 더해 레퍼런스 문서의 **해당 파라미터 섹션**을 LLM
  프롬프트의 추가 근거로 **포함해야 한다(shall)**.
- **REQ-007 (State-Driven)**: 레퍼런스 문서를 사용할 수 있는 **동안(while)**, 매칭 키 Q&A
  프롬프트는 권위 있는 메타데이터(기존)와 레퍼런스 문서 섹션(신규)을 함께 담아 LLM이 그 파라미터가
  "어디서·어떻게" 쓰이는지 설명할 수 있게 **해야 한다(shall)**.

### R3 — 매칭 실패 질문의 그라운딩 답변

- **REQ-008 (Event-Driven)**: 사용자의 설정 Q&A 질문이 어떤 알려진 config/env 키와도 매칭되지
  않을 **때(when)**, 시스템은 레퍼런스 문서(전체 또는 가장 관련 있는 내용)를 근거로 한 LLM
  프롬프트를 만들어 기존 `qa_requested` → `SettingsQAWorker` 스트리밍 경로로 **라우팅해야
  한다(shall)** — 하드코딩된 거부 메시지를 내보내지 않는다.
- **REQ-009 (Unwanted Behavior)**: `_on_ask_clicked`는 매칭 실패 질문에 대해 하드코딩된
  "…문서를 찾을 수 없습니다…" 거부 문자열을 더 이상 **출력해서는 안 된다(shall not)**.
- **REQ-010 (Event-Driven)**: 매칭 실패 질문이 그라운딩 경로로 답변될 **때(when)**, 시스템은
  그 교환을 매칭 키 답변과 동일하게 설정 Q&A 히스토리(`_append_qa_history`)에 **기록해야
  한다(shall)**.

### R4 — 그레이스풀 디그레이데이션 & 하위 호환

- **REQ-011 (Unwanted Behavior)**: 레퍼런스 문서가 없거나 읽을 수 없는 경우 **(if)**,
  설정 Q&A는 여전히 동작해야 하며 — 매칭 키 질문은 기존 메타데이터 전용 프롬프트로,
  매칭 실패 질문은 오류 없이 안전한 폴백(카탈로그 요약 기반 프롬프트 또는 비크래시 안내)으로
  처리 — 예외를 던지지 **않아야 한다(shall not)**.
- **REQ-012 (Ubiquitous)**: 이 변경은 `find_config_key_in_question`, `validate_kv_text`,
  `classify_config_changes`, `reset_config_defaults`, `mask_sensitive_value`의 동작과
  SPEC-SETTINGS-001/002 기능(파일 편집/저장/검증/초기화/diff, Enter 전송, Clear, 탭 순서)을
  변경하지 **않아야 한다(shall)**.
- **REQ-013 (Ubiquitous)**: 레퍼런스 문서는 `load_system_prompt`와 동일하게 **동기적으로**
  로드되어야 하며(shall), 새로운 QThread 워커나 런타임 의존성을 도입하지 않는다.

---

## 4. Non-Functional Constraints

- **NFR-1 (신규 의존성 없음)**: 사용자가 선택한 정적 저작 방식에 따라 새 라이브러리·런타임 도구를
  추가하지 않는다. 레퍼런스 문서는 빌드/런타임에 생성되지 않는 체크인 텍스트 파일이다.
- **NFR-2 (동기 로드)**: 문서는 작아서(수 KB) 워커 스레드 없이 동기 읽기로 충분하다
  (`rag_core.load_system_prompt`의 `Path(...).read_text` 패턴과 동일).
- **NFR-3 (테스트 용이성)**: 레퍼런스 문서 경로는 오버라이드 가능한 모듈 상수
  (예: `_SETTINGS_REFERENCE_PATH`)로 두어, `tests/conftest.py`의 `settings_files` 픽스처가
  기존 `_SETTINGS_*_PATH` 상수를 몽키패치하는 것과 동일한 방식으로 테스트에서 임시 파일을
  주입할 수 있게 한다.
- **NFR-4 (프롬프트 크기)**: 매칭 실패 경로가 전체 문서를 프롬프트에 담을 경우 토큰 사용량이
  커질 수 있다. 문서는 high-level 요약에 한정해 단일 Q&A 호출(gpt-4o-mini 기준) 컨텍스트에
  안전히 들어가는 크기를 유지한다.
- **NFR-5 (API 키 보호)**: `settings_reference.txt`는 `OPENAI_API_KEY`가 **무엇인지**만 설명하고
  실제 키 값을 담지 않는다 (N-SETTINGS-2 API 키 보호 원칙 계승).

---

## 5. Exclusions (What NOT to Build)

SPEC-SETTINGS-003에서 명시적으로 범위 밖인 항목:

1. **자동 재생성 도구 없음** — 사용자의 명시적 선택에 따라, 소스를 런타임에 스캔해 문서를
   자동 생성/갱신하는 도구나 자동화는 만들지 않는다. 문서는 손으로 작성하고 이후 수동 갱신한다.
2. **파일/파라미터별 분할 없음** — 하나의 통합 `settings_reference.txt`만 만든다. 파라미터마다,
   파일마다 별도 문서를 두지 않는다.
3. **파일 브라우저에 노출하지 않음(기본값)** — `settings_reference.txt`는 `SettingsTab.CONFIG_FILES`의
   9개 파일 목록에 추가하지 않으며, 설정 탭의 파일 목록/에디터에서 사용자가 편집할 수 없다.
   이 문서는 사용자 설정이 아니라 Q&A 그라운딩용 내부 근거 문서다. (§8 오픈 이슈 참조 — 사용자가
   원하면 열람 전용으로 노출하는 것은 향후 확장으로 재검토 가능.)
4. **워커 변경 없음** — `SettingsQAWorker`/`SettingsPromptRewriteWorker`는 단일 프롬프트 문자열만
   받으므로 그대로 재사용한다. 모든 그라운딩은 프롬프트 문자열 안에서 이뤄진다.
5. **HTML/JS 변경 없음** — `resources/settings_chat.html`은 그대로 둔다.
6. **9개 파일 밖 프롬프트 미포함** — `prompts/`에 존재하지만 설정 탭 카탈로그에 없는
   `notebook_run_predict_prompt.txt`, `wiki_concept_prompt.txt`는 문서화 범위 밖이다.
7. **GitHub 이슈 생성 없음** (`issue_number: 0`).
8. **새 git 브랜치 없음** — 수동 git 전략: 현재 브랜치 `main`에 직접 커밋, 푸시 없음
   (SPEC-SETTINGS-001/002 선례와 동일).

---

## 6. Assumptions

- SPEC-SETTINGS-001/002가 완료되어 설정 탭 Q&A 경로(`_on_ask_clicked`, `qa_requested` →
  `MainWindow._on_settings_qa_requested` → `SettingsQAWorker`)가 현 트리에 존재하고
  `QT_QPA_PLATFORM=offscreen`에서 깨끗이 임포트된다.
- `pytest` + `pytest-qt` 인프라가 존재한다(`tests/` + `conftest.py`; 현재 121개 테스트 함수).
- `rag_core.load_system_prompt()`가 `Path(...).read_text(encoding="utf-8")`로 프롬프트 txt를
  동기 로드하는 패턴이 확인되었으며, 레퍼런스 문서 로더도 이를 그대로 따른다.
- `settings_reference.txt`의 산문(prose)은 이 SPEC의 구현 단계(/moai run)에서 소스를 읽는
  에이전트가 저작한다. 본 SPEC은 문서의 **필수 구조/섹션**만 규정하고 문장 자체는 규정하지 않는다.

---

## 7. Related SPECs

- **SPEC-SETTINGS-001** — 설정 탭과 F-SETTINGS-3(CONFIG_METADATA→LLM 하이브리드 Q&A 설계)을
  만든 원본. 본 SPEC은 그 Q&A 그라운딩 경로를 확장한다(대체 아님).
- **SPEC-SETTINGS-002** — 설정 탭 UX 개선 3종(Enter 전송, Clear, 탭 순서). 완료됨. 본 SPEC은
  그 기능을 변경하지 않는다.

---

## 8. Resolved Decisions

- **레퍼런스 문서를 설정 탭 파일 목록에 열람 전용으로 노출할까?** 사용자 확인 결과 **노출하지
  않음**으로 확정 (§5 배제 3). `settings_reference.txt`는 사용자 설정 파일이 아니라 Q&A 그라운딩용
  내부 근거 문서로만 취급하며, `CONFIG_FILES`에 추가하지 않는다. (열람 전용 노출은 향후 별도
  SPEC으로 재검토 가능.)
