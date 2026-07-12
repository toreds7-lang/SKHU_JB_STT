# SPEC-SETTINGS-003 (compact)

- **id**: SPEC-SETTINGS-003 · **status**: draft · **priority**: medium · **issue**: 0
- **title**: 설정 레퍼런스 문서 기반 Q&A 그라운딩
- **scope**: 소스를 읽어 손 저작한 단일 정적 `settings_reference.txt`(루트)를 도입하고, 설정 탭
  Q&A가 이를 추가 근거로 사용하도록 **확장**(대체 아님). SPEC-SETTINGS-001/002 기능 불변.

## 문서화 대상

env 6 (`_ENV_METADATA_CATALOG`) + config 18 (`_CONFIG_METADATA_CATALOG`) + 파일 9
(`SettingsTab.CONFIG_FILES`: env.txt, config.txt, prompts/ 7개). 각 항목: 무엇/소비 함수(실존
심볼)/high-level 흐름.

## Requirements (EARS)

- **R1 정적 레퍼런스 문서** (`settings_reference.txt`, 루트)
  - REQ-001 (ubiquitous): 24 파라미터 + 9 파일을 다루는 단일 정적 체크인 문서 포함.
  - REQ-002/003 (ubiquitous): 파라미터=무엇/소비 모듈·함수(파일+심볼)/흐름; 파일=역할/로더/흐름.
  - REQ-004 (ubiquitous): 인용 심볼은 현재 소스에 실존해야 함(정확성).
  - REQ-005 (unwanted): 단일 통합 문서, 코드 덤프/분할 금지.
- **R2 매칭 키 근거 강화** (`rag_core`, `ui/settings_tab.py`)
  - REQ-006 (event): 키 매칭 시 레퍼런스 해당 섹션을 프롬프트에 추가 근거로 포함.
  - REQ-007 (state): 문서 사용 가능 동안 메타데이터+섹션을 함께 담아 "어디서/어떻게" 설명 가능.
- **R3 비매칭 그라운딩** (`ui/settings_tab.py::_on_ask_clicked`)
  - REQ-008 (event): 키 미매칭 시 레퍼런스 근거 프롬프트를 `qa_requested`→`SettingsQAWorker`로 라우팅.
  - REQ-009 (unwanted): 하드코딩 "문서를 찾을 수 없습니다" 거부 문자열 제거.
  - REQ-010 (event): 그라운딩 답변도 `_append_qa_history`로 기록(`_pending_qa_question` 설정 필수).
- **R4 디그레이데이션/하위호환**
  - REQ-011 (unwanted/if): 문서 부재 시 예외 없이 안전 폴백.
  - REQ-012 (ubiquitous): `find_config_key_in_question`/`validate_kv_text`/`classify_config_changes`/
    `reset_config_defaults`/`mask_sensitive_value` 및 001/002 기능 불변.
  - REQ-013 (ubiquitous): `load_system_prompt`식 동기 로드, 신규 워커/의존성 없음.

## Files to modify

- `settings_reference.txt` (신규) — 24 파라미터 + 9 파일 손 저작(`## PARAM:`/`## FILE:` 규약).
- `rag_core.py` — `_SETTINGS_REFERENCE_PATH`, `load_settings_reference()`, `find_reference_section()`,
  `build_settings_qa_grounded_prompt()`; `build_settings_qa_prompt()`에 선택 인자 `reference_section`(하위호환).
- `ui/settings_tab.py` — 매칭 분기 섹션 근거 주입; 비매칭 분기 그라운딩 경로 교체(+`_pending_qa_question`).
- `tests/test_rag_core_settings.py`, `tests/test_settings_tab.py` — 신규 테스트.
- **변경 없음**: `workers/settings_worker.py`, `resources/settings_chat.html`, `cache_store.py`, `ui/main_window.py`.

## Exclusions

자동 재생성 도구 없음; 파일/파라미터별 분할 없음; `CONFIG_FILES` 미노출(확정); 워커/HTML/JS/캐시
변경 없음; 카탈로그 밖 프롬프트(notebook_run_predict/wiki_concept) 미포함; GitHub 이슈 없음; 새 브랜치 없음
(수동 git → `main` 직접 커밋, 푸시 없음).

## Resolved decisions

레퍼런스 문서는 설정 탭 파일 목록에 노출하지 않음(사용자 확정). 비매칭+문서부재 폴백의 정확한
형태는 구현 시 확정(REQ-011 충족 전제).

## DoD

모든 AC 충족; 신규 R1–R4 테스트; `pytest tests/ -q` 그린(`QT_QPA_PLATFORM=offscreen`, 기존 121개 회귀 없음);
`main` 직접 커밋.
