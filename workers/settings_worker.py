"""Settings file I/O + Q&A workers — SPEC-SETTINGS-001 Phase 1-5.

- SettingsFileLoadWorker: async read-only file load (Phase 1, N-SETTINGS-1).
- SettingsQAWorker: streaming LLM Q&A about a config parameter (F-SETTINGS-3).
- SettingsSaveWorker: backup + atomic write (F-SETTINGS-6). Validation and the
  rebuild-confirmation dialog happen in the caller (SettingsTab, on the UI
  thread) *before* this worker starts — it only performs the file I/O.
- SettingsPromptRewriteWorker: single blocking LLM call to rewrite a prompt
  file per a user's free-text request (F-SETTINGS-12).
"""

import os
import shutil
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal


class SettingsFileLoadWorker(QThread):
    """Load a single config/prompt file's raw text on a background thread.

    Emits ``content_loaded(content, encoding)`` on success, or
    ``error_signal(message)`` when the file is missing or cannot be read.
    """
    content_loaded = pyqtSignal(str, str)   # (content, encoding)
    error_signal   = pyqtSignal(str)        # human-readable error message

    ENCODING = "UTF-8"

    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path

    def run(self):
        try:
            if not os.path.exists(self.file_path):
                self.error_signal.emit(f"파일을 찾을 수 없습니다: {self.file_path}")
                return
            with open(self.file_path, encoding="utf-8") as f:
                content = f.read()
            self.content_loaded.emit(content, self.ENCODING)
        except Exception as e:  # noqa: BLE001 — surface any read failure to the UI
            self.error_signal.emit(str(e))


class SettingsQAWorker(QThread):
    """설정 파라미터에 대한 LLM Q&A 스트리밍 (F-SETTINGS-3).

    호출자가 이미 rag_core.find_config_key_in_question() /
    build_settings_qa_prompt()로 프롬프트를 구성해 전달한다 — 이 워커는 순수
    스트리밍 실행만 담당한다.
    """
    chunk_received  = pyqtSignal(str)
    finished_signal = pyqtSignal(str)   # full answer
    error_signal    = pyqtSignal(str)

    def __init__(self, llm, prompt: str):
        super().__init__()
        self.llm      = llm
        self.prompt   = prompt
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        try:
            from langchain_core.messages import HumanMessage
            buf = ""
            for chunk in self.llm.stream([HumanMessage(content=self.prompt)]):
                if self._stopped:
                    break
                buf += chunk.content
                self.chunk_received.emit(chunk.content)
            self.finished_signal.emit(buf)
        except Exception as e:
            self.error_signal.emit(str(e))


class SettingsSaveWorker(QThread):
    """설정/프롬프트 파일 저장 (백업 + 원자적 쓰기) — F-SETTINGS-6.

    검증(validate_kv_text)과 재구축 확인 다이얼로그는 호출자가 UI 스레드에서
    이 워커를 시작하기 *전에* 수행한다. 이 워커는 순수 파일 I/O만 담당한다.
    """
    save_finished = pyqtSignal(str)   # file_path
    error_signal  = pyqtSignal(str)

    def __init__(self, file_path: str, new_text: str, cache_dir: str):
        super().__init__()
        self.file_path = file_path
        self.new_text  = new_text
        self.cache_dir = cache_dir

    def run(self):
        try:
            src = Path(self.file_path)
            backup_dir = Path(self.cache_dir) / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)

            if src.exists():
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = backup_dir / f"{src.name}.{ts}.bak"
                shutil.copy2(src, backup_path)

            src.parent.mkdir(parents=True, exist_ok=True)
            tmp = src.with_suffix(src.suffix + ".tmp")
            tmp.write_text(self.new_text, encoding="utf-8")
            os.replace(tmp, src)

            self.save_finished.emit(str(src))
        except Exception as e:
            self.error_signal.emit(str(e))


class SettingsPromptRewriteWorker(QThread):
    """LLM을 이용한 프롬프트 파일 재작성 (F-SETTINGS-12).

    스트리밍이 아닌 단일 blocking 호출 — SPEC 요구사항이 "설명 없이 새 프롬프트
    텍스트만 반환"이므로 토큰 단위 표시가 필요 없다.
    """
    finished_signal = pyqtSignal(str)   # new prompt text
    error_signal    = pyqtSignal(str)

    def __init__(self, llm, prompt: str):
        super().__init__()
        self.llm    = llm
        self.prompt = prompt

    def run(self):
        try:
            from langchain_core.messages import HumanMessage
            response = self.llm.invoke([HumanMessage(content=self.prompt)])
            self.finished_signal.emit(response.content.strip())
        except Exception as e:
            self.error_signal.emit(str(e))
