# Acceptance Criteria — SPEC-SETTINGS-003

`spec.md`의 REQ-XXX별 Given-When-Then 시나리오. 문서 완전성/정확성과 프롬프트 구성은
`pytest`/`pytest-qt`로 관찰 가능하다(문서 존재·완전성은 파일 검사, 프롬프트 구성은 문자열 단언,
비매칭 라우팅은 `qa_requested` 시그널 스파이). LLM 응답 자체의 품질은 비결정적이므로 검증 대상은
**프롬프트에 올바른 근거가 포함되는지**와 **경로가 올바르게 라우팅되는지**다.

---

## R1 — 정적 설정 레퍼런스 문서

### AC-REQ-001 — 문서가 존재하고 단일 파일이다
- **Given** 저장소 체크아웃 상태에서
- **When** 프로젝트 루트를 확인하면
- **Then** `settings_reference.txt` 파일이 하나 존재한다 (파라미터/파일별로 쪼개진 다중 문서가 아님).

### AC-REQ-002 — 파라미터 항목 완전성 및 구조
- **Given** `settings_reference.txt`의 내용과 `rag_core`의 카탈로그
  (`_ENV_METADATA_CATALOG` 6키, `_CONFIG_METADATA_CATALOG` 18키)
- **When** 각 파라미터 키를 문서에서 찾으면
- **Then** 24개 파라미터 키 전부가 `## PARAM:` 항목으로 문서에 등장하며, 각 항목은 "무엇 / 소비
  위치(모듈·함수) / high-level 흐름"을 담는다.

### AC-REQ-003 — 파일 항목 완전성 및 구조
- **Given** `settings_reference.txt`의 내용과 `SettingsTab.CONFIG_FILES`(9파일)
- **When** 각 파일명을 문서에서 찾으면
- **Then** 9개 파일명 전부가 `## FILE:` 항목으로 문서에 등장하며, 각 항목은 "역할 / 로더·소비 함수 /
  high-level 흐름"을 담는다.

### AC-REQ-004 — 인용 정확성(스팟체크)
- **Given** 문서가 인용한 소비 함수 표본
  (예: `build_rag_system`, `load_system_prompt`, `load_force_prompt`, `load_summary_prompt`)
- **When** 해당 심볼을 현재 소스에서 조회하면
- **Then** 모두 실제로 존재한다 (존재하지 않는 함수·파일을 인용하지 않는다).

### AC-REQ-005 — 통합 문서 & 코드 덤프 아님
- **Given** `settings_reference.txt`
- **Then** 별도 파일로 분할되지 않은 단일 문서이며, 각 `## PARAM:`/`## FILE:` 항목의 산문은
  3-8줄 이내이고, 코드 블록(``` 펜스 또는 4칸 들여쓰기 코드)을 포함하지 않으며, 소스 위치는
  파일명+함수/클래스명으로만 인용한다(코드 라인 전체 복사 없음).

---

## R2 — 매칭된 키 Q&A 그라운딩 강화

### AC-REQ-006 — 매칭 프롬프트에 레퍼런스 섹션 포함
- **Given** 레퍼런스 문서가 존재하고 사용자가 알려진 키를 포함한 질문(예: `"VECTOR_K가 뭐야?"`)을
  입력한 상태
- **When** 질문을 전송하면(`_on_ask_clicked`가 `find_config_key_in_question`으로 `VECTOR_K` 매칭)
- **Then** `qa_requested`로 올라가는 프롬프트에는 기존 권위 메타데이터(한 줄 description)에 더해
  `find_reference_section(ref, "VECTOR_K")`가 반환한 레퍼런스 섹션 텍스트가 포함된다.

### AC-REQ-007 — 기존 메타데이터 전용 경로의 하위 호환
- **Given** `build_settings_qa_prompt(...)`의 기존 호출부
- **When** `reference_section` 인자 없이 호출하면
- **Then** 출력은 이 SPEC 이전과 동일하다(기존 `tests/test_rag_core_settings.py` 단언이 깨지지 않음).

---

## R3 — 매칭 실패 질문의 그라운딩 답변

### AC-REQ-008 — 비매칭 질문이 그라운딩 LLM 경로로 라우팅
- **Given** 레퍼런스 문서가 존재하고 사용자가 어떤 키와도 매칭되지 않는 횡단 질문
  (예: `"이 프롬프트 파일들이 서로 어떻게 다른가요?"`)을 입력한 상태
- **When** 질문을 전송하면
- **Then** `_on_ask_clicked`는 하드코딩 거부 메시지를 출력하지 않고, 대신
  `build_settings_qa_grounded_prompt(question, reference_text)`로 만든 프롬프트를 `qa_requested`로
  emit한다(레퍼런스 내용이 프롬프트에 포함됨).
- **And** emit 이전에 `_pending_qa_question`이 해당 질문으로 설정된다.

### AC-REQ-009 — 하드코딩 거부 문자열 제거
- **Given** 매칭 실패 질문
- **When** 전송하면
- **Then** "…문서를 찾을 수 없습니다…" 하드코딩 거부 문자열이 UI에 나타나지 않는다
  (`_on_ask_clicked` 소스에서 해당 즉시-거부 분기가 제거/대체됨).

### AC-REQ-010 — 그라운딩 답변도 히스토리에 기록
- **Given** 비매칭 질문이 그라운딩 스트리밍 경로로 답변 완료된 상태
- **When** `on_qa_finished(answer)`가 호출되면
- **Then** `_append_qa_history(_pending_qa_question, answer)`가 매칭 키 답변과 동일하게 실행되어
  교환이 `settings_chat.jsonl`에 기록된다.

---

## R4 — 그레이스풀 디그레이데이션 & 하위 호환

### AC-REQ-011 — 문서가 없을 때도 비크래시
- **Given** `_SETTINGS_REFERENCE_PATH`가 존재하지 않는 경로를 가리키도록 설정된 상태
- **When** 사용자가 비매칭 질문을 전송하면
- **Then** `load_settings_reference()`는 빈 문자열을 반환하고, Q&A는 예외를 던지지 않고 안전 폴백
  (카탈로그 요약 기반 그라운딩 프롬프트 또는 비크래시 안내)으로 처리된다.

### AC-REQ-012 — 기존 함수·기능 회귀 없음
- **Given** 변경 후 전체 테스트 스위트
- **When** `pytest tests/ -q`를 `QT_QPA_PLATFORM=offscreen`에서 실행하면
- **Then** 기존 121개 테스트가 모두 통과하고, `find_config_key_in_question`,
  `validate_kv_text`, `classify_config_changes`, `reset_config_defaults`,
  `mask_sensitive_value`의 동작과 편집/저장/검증/초기화/diff, Enter 전송, Clear, 탭 순서가 변하지
  않는다.

### AC-REQ-013 — 동기 로드, 신규 의존성/워커 없음
- **Given** 레퍼런스 문서 로딩 구현
- **Then** `load_settings_reference()`는 `load_system_prompt`와 동일한 동기 `Path.read_text`
  패턴을 쓰며, 새 QThread 워커나 런타임 의존성을 추가하지 않는다.

---

## Quality Gate / Definition of Done

- [ ] AC-REQ-001–005 충족: `settings_reference.txt` 단일 파일 존재, 24 파라미터 + 9 파일 완전성,
      인용 정확성 스팟체크 통과, 코드 덤프/분할 아님.
- [ ] AC-REQ-006–007 충족: 매칭 프롬프트에 레퍼런스 섹션 포함, `build_settings_qa_prompt` 하위 호환.
- [ ] AC-REQ-008–010 충족: 비매칭 질문이 그라운딩 `qa_requested` 경로로 라우팅, 하드코딩 거부 제거,
      `_pending_qa_question` 설정, 히스토리 기록.
- [ ] AC-REQ-011–013 충족: 문서 부재 시 비크래시 폴백, 기존 121 테스트 그린, 동기 로드/무신규의존성.
- [ ] 새 테스트 추가: `tests/test_rag_core_settings.py`(로더/섹션/그라운딩 프롬프트/완전성/정확성),
      `tests/test_settings_tab.py`(비매칭 라우팅/매칭 섹션 근거/폴백).
- [ ] `pytest tests/ -q`가 `QT_QPA_PLATFORM=offscreen`에서 전부 통과(회귀 없음).
- [ ] `rag_core`, `ui.settings_tab`가 헤드리스에서 깨끗이 임포트.
- [ ] 배제 준수: 자동 재생성 도구 없음, 파일/파라미터별 분할 없음, `CONFIG_FILES` 미노출(확정),
      워커/HTML/JS/캐시 변경 없음, 카탈로그 밖 프롬프트(notebook_run_predict/wiki_concept) 미포함,
      GitHub 이슈 없음, 새 브랜치 없음.
- [ ] `main`에 직접 커밋(수동 git 전략: 자동 브랜치·푸시 없음).
