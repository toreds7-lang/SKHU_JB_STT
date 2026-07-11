"""Settings file I/O worker — SPEC-SETTINGS-001 Phase 1 (async file load).

Reads a configuration or prompt file off the UI thread so the Settings tab
stays responsive (N-SETTINGS-1). This phase is strictly READ-ONLY: saving,
backup, and validation belong to a later SPEC phase and are intentionally not
implemented here.
"""

import os

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
