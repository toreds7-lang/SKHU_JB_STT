# SKHU_Agent.exe 빌드 가이드

## 1. 사전 요구사항

- **Python** >= 3.10
- **OS**: Windows 10 이상

### 의존성 설치

```bash
pip install -r requirements_1.txt
pip install pyinstaller>=6.8.0
```

## 2. ICO 파일 준비

프로젝트 루트에 `SK_Hynix.ico` 파일이 없는 경우, PNG에서 변환합니다:

```bash
python -c "from PIL import Image; Image.open('SK_Hynix.png').save('SK_Hynix.ico')"
```

## 3. 빌드 실행

```bash
cd d:\2026_Agent_STT\SKHU_Agent
pyinstaller build.spec --noconfirm
```

- `--noconfirm`: 기존 `dist/` 폴더를 확인 없이 덮어씀
- 빌드 시간: 약 2~3분 소요

## 4. 결과물 구조

빌드 완료 후 `dist/SKHU_Agent/` 폴더가 생성됩니다:

```
dist/SKHU_Agent/
├── SKHU_Agent.exe              # 실행 파일
├── _internal/                  # 번들된 의존성 및 리소스
│   ├── resources/
│   │   ├── chat.html           # 채팅 HTML 템플릿
│   │   ├── dark_theme.qss      # Qt 다크 테마 스타일시트
│   │   └── js/
│   │       ├── highlight.min.js  # 코드 하이라이팅
│   │       └── marked.min.js     # 마크다운 파싱
│   ├── SK_Hynix.png            # 앱 아이콘
│   ├── system_prompt.txt       # LLM 시스템 프롬프트
│   └── ...                     # Python 런타임, 패키지 등
└── (사용자가 배치할 파일들)
```

## 5. 배포 방법

`dist/SKHU_Agent/` 폴더 전체를 배포합니다.

사용자는 `SKHU_Agent.exe`와 같은 폴더에 다음 파일을 배치해야 합니다:

| 파일/폴더 | 필수 | 설명 |
|-----------|------|------|
| `env.txt` | O | API 키 및 모델 설정 (OPENAI_API_KEY 등) |
| `work/` | O | 강의 노트북 디렉토리 (.ipynb 파일) |
| `system_prompt.txt` | X | 커스텀 LLM 시스템 프롬프트 (기본값 내장) |
| `force_prompt.txt` | X | Force Mode 전용 시스템 프롬프트 (기본값 내장) |

### env.txt 예시

```
OPENAI_API_KEY=sk-proj-...
LLM_MODEL=gpt-4o-mini
LLM_BASE_URL=
EMBEDDING_BASE_URL=
EMBEDDING_MODEL=text-embedding-ada-002
FORCE_WORKERS=3
```

## 6. build.spec 주요 설정

| 설정 | 현재 값 | 설명 |
|------|---------|------|
| 진입점 | `main.py` | PyQt6 데스크탑 앱 |
| `console` | `False` | 배포 시 콘솔 창 숨김 (디버깅 시 `True`로 변경) |
| `icon` | `SK_Hynix.ico` | 실행 파일 아이콘 |
| `upx` | `True` | UPX 압축 활성화 |

### 번들 리소스 (datas)

- `SK_Hynix.png` — 앱 아이콘 이미지
- `system_prompt.txt` — 기본 시스템 프롬프트
- `resources/dark_theme.qss` — Qt 다크 테마
- `resources/chat.html` — 채팅 HTML 템플릿
- `resources/js/` — JavaScript 라이브러리 (marked.js, highlight.js)
- `kiwipiepy` 모델 데이터 — 한국어 형태소 분석 데이터 (자동 수집)

### 제외 모듈 (excludes)

Streamlit 웹 앱 관련 모듈은 빌드에서 제외됩니다:
`streamlit`, `tornado`, `altair`, `bokeh`, `matplotlib`, `tkinter`, `jupyter`, `notebook`, `IPython`

## 7. 트러블슈팅

### `scipy.sparse` Hidden import not found 경고

```
INFO: Analyzing hidden import 'scipy.sparse'
ERROR: Hidden import 'scipy.sparse' not found
```

**문제 없음 — 무시해도 됩니다.**

`scipy.sparse`는 FAISS 등 일부 패키지의 선택적 의존성으로 간접 참조되지만, 이 앱의 실제 실행 경로에서는 사용되지 않습니다. 빌드된 `.exe`를 실행했을 때 정상 동작하면 이 경고는 무해합니다.

**런타임 오류가 발생하는 경우 (드문 경우):** `scipy`를 설치하거나 `build.spec`의 `hiddenimports`에 항목을 추가합니다:

```python
hiddenimports=['scipy.sparse', 'scipy.sparse.csgraph']
```

경고 메시지 자체를 없애려면 `build.spec`의 `hiddenimports`에서 `"scipy.sparse"` 항목을 제거하세요.

### 빌드 폴더 정리

빌드 문제가 발생할 경우, 캐시를 삭제하고 재빌드합니다:

```bash
rmdir /s /q build dist
pyinstaller build.spec --noconfirm
```

### 콘솔 창으로 디버깅

실행 시 오류가 발생하면 `build.spec`에서 `console=True`로 변경 후 재빌드하여 오류 메시지를 확인할 수 있습니다.
