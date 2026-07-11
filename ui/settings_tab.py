"""SettingsTab - 설정 파일 탐색 탭 (SPEC-SETTINGS-001 Phase 1).

읽기 전용 설정 파일 브라우저. 좌측 목록에서 9개의 설정/프롬프트 파일을 선택하면
우측 뷰어에 원본 텍스트를 표시한다. 디스크에 존재하지 않는 파일은 흐리게 표시하되
선택은 가능하다 (F-SETTINGS-1). 편집/저장/Q&A 등은 이후 SPEC 단계의 범위다.
"""

import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPlainTextEdit, QSplitter,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from workers.settings_worker import SettingsFileLoadWorker


class SettingsTab(QWidget):
    """읽기 전용 설정 파일 브라우저 위젯."""

    # 좌측 목록에 표시할 9개 파일 (표시 순서 고정, F-SETTINGS-1).
    CONFIG_FILES = [
        "env.txt",
        "config.txt",
        "prompts/system_prompt.txt",
        "prompts/force_prompt.txt",
        "prompts/agentic_planner_prompt.txt",
        "prompts/agentic_sufficiency_prompt.txt",
        "prompts/agentic_synthesis_prompt.txt",
        "prompts/notebook_chat_prompt.txt",
        "prompts/summary_prompt.txt",
    ]

    COLOR_EXISTS = "#e2e8f0"   # 존재하는 파일 (정상 텍스트)
    COLOR_MISSING = "#475569"  # 존재하지 않는 파일 (흐리게)

    PLACEHOLDER_EMPTY = "← 좌측 목록에서 설정 파일을 선택하세요."
    PLACEHOLDER_LOADING = "불러오는 중…"
    PLACEHOLDER_MISSING = "(파일 없음)"

    def __init__(self, base_dir: str = ".", config_metadata: dict | None = None, parent=None):
        super().__init__(parent)
        self._base_dir = base_dir
        self._config_metadata = config_metadata or {}
        self._workers: set[SettingsFileLoadWorker] = set()
        self._build_ui()
        self._populate_file_list()

    # ── UI 구성 ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(8)

        title = QLabel("⚙️  설정 파일")
        title.setStyleSheet("color: #e2e8f0; font-size: 14px; font-weight: 700;")
        layout.addWidget(title)

        hint = QLabel("설정·프롬프트 파일을 선택해 내용을 확인합니다 (읽기 전용).")
        hint.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(hint)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── 좌측: 파일 목록 ─────────────────────────────────────────────────
        self.file_list = QListWidget()
        self.file_list.setStyleSheet(
            "QListWidget { background: #161922; border: 1px solid #2a3045; "
            "border-radius: 6px; color: #e2e8f0; font-size: 12px; "
            "font-family: 'JetBrains Mono', Consolas, monospace; }"
            "QListWidget::item { padding: 6px 8px; border-bottom: 1px solid #1e2330; }"
            "QListWidget::item:selected { background: #1e3a5f; }"
        )
        self.file_list.currentRowChanged.connect(self._on_row_changed)
        splitter.addWidget(self.file_list)

        # ── 우측: 헤더 + 내용 뷰어 ──────────────────────────────────────────
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self.header_label = QLabel("")
        self.header_label.setStyleSheet(
            "color: #94a3b8; font-size: 11px; padding: 2px 4px; "
            "font-family: 'JetBrains Mono', Consolas, monospace;"
        )
        right_layout.addWidget(self.header_label)

        self.content_view = QPlainTextEdit()
        self.content_view.setReadOnly(True)
        self.content_view.setFont(QFont("JetBrains Mono, Consolas, Courier New", 11))
        self.content_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.content_view.setPlaceholderText(self.PLACEHOLDER_EMPTY)
        self.content_view.setStyleSheet(
            "QPlainTextEdit { background: #111827; color: #f8f8f2; "
            "border: 1px solid #2a3045; border-radius: 6px; padding: 8px; }"
        )
        right_layout.addWidget(self.content_view)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 700])
        layout.addWidget(splitter)

    def _populate_file_list(self):
        self.file_list.clear()
        for rel_path in self.CONFIG_FILES:
            item = QListWidgetItem(rel_path)
            exists = os.path.exists(self._abs_path(rel_path))
            item.setForeground(QColor(self.COLOR_EXISTS if exists else self.COLOR_MISSING))
            item.setData(Qt.ItemDataRole.UserRole, rel_path)
            self.file_list.addItem(item)

    # ── 파일 선택 → 비동기 로드 ─────────────────────────────────────────────

    def _on_row_changed(self, row: int):
        if row < 0:
            return
        item = self.file_list.item(row)
        if item is None:
            return
        rel_path = item.data(Qt.ItemDataRole.UserRole)
        self.header_label.setText(f"{rel_path} · UTF-8")
        self.content_view.setPlainText(self.PLACEHOLDER_LOADING)
        self._load_file(rel_path)

    def _load_file(self, rel_path: str):
        worker = SettingsFileLoadWorker(self._abs_path(rel_path))
        worker.content_loaded.connect(
            lambda content, encoding, rp=rel_path: self._on_content_loaded(rp, content, encoding)
        )
        worker.error_signal.connect(lambda _msg, rp=rel_path: self._on_load_error(rp))
        worker.finished.connect(lambda w=worker: self._workers.discard(w))
        self._workers.add(worker)
        worker.start()

    def _on_content_loaded(self, rel_path: str, content: str, encoding: str):
        if not self._is_current(rel_path):
            return
        self.header_label.setText(f"{rel_path} · {encoding}")
        self.content_view.setPlainText(content)

    def _on_load_error(self, rel_path: str):
        if not self._is_current(rel_path):
            return
        self.content_view.setPlainText(self.PLACEHOLDER_MISSING)

    # ── 헬퍼 ────────────────────────────────────────────────────────────────

    def _abs_path(self, rel_path: str) -> str:
        return os.path.normpath(os.path.join(self._base_dir, rel_path))

    def _is_current(self, rel_path: str) -> bool:
        """비동기 로드 완료 시점에 여전히 해당 파일이 선택 중인지 확인."""
        item = self.file_list.currentItem()
        return item is not None and item.data(Qt.ItemDataRole.UserRole) == rel_path
