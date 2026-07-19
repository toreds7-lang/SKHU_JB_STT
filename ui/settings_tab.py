"""SettingsTab - 설정 파일 탐색/편집/Q&A 탭 (SPEC-SETTINGS-001 Phase 1-5).

좌측 목록에서 9개의 설정/프롬프트 파일을 선택하면 우측에 채팅(Q&A) 패널과
파일 뷰어/편집기가 나타난다. 편집·저장·초기화·LLM 프롬프트 수정은 모두
`rag_core`의 순수 로직 함수(lazy import, 무거운 의존성을 탭 모듈 로드 시점에
끌어오지 않기 위함)와 `workers/settings_worker.py`의 QThread 워커를 통해
수행된다. LLM 호출이 필요한 두 흐름(Q&A, LLM 프롬프트 수정)은 이미 만들어진
프롬프트 문자열만 시그널로 올려보내고, 실제 LLM 워커 생성은 MainWindow가
담당한다 (다른 탭들과 동일한 패턴).
"""

import json
import os
import shutil
import sys
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPlainTextEdit, QSplitter, QGroupBox, QCheckBox, QPushButton, QDialog,
    QInputDialog, QMessageBox, QSizePolicy,
)
from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QTextCharFormat

from PyQt6.QtWebEngineWidgets import QWebEngineView

from workers.settings_worker import SettingsFileLoadWorker, SettingsSaveWorker


CATEGORIES = ["API", "Retrieval", "Agentic", "STT", "Debug", "Prompt", "Other"]


class _QAInput(QPlainTextEdit):
    """Q&A 입력창 — Enter로 제출, Shift+Enter로 줄바꿈 (SPEC-SETTINGS-002 R1).

    앱의 다른 채팅 입력(`ChatTab`/`NotebookTab`/`WikiTab`)과 동일한 관례를 따른다.
    자동 높이 확장이나 Up/Down 히스토리 재호출은 의도적으로 포함하지 않는다
    (SPEC-SETTINGS-002 Exclusions 1·2).
    """

    returnPressed = pyqtSignal()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)  # 줄바꿈 삽입
            else:
                self.returnPressed.emit()     # 제출
            return
        super().keyPressEvent(event)


class _ZoomableContentView(QPlainTextEdit):
    """Ctrl+휠로 글꼴 확대/축소가 되는 파일 내용 뷰.

    앱 전역 QSS(dark_theme.qss)가 `QWidget { font-size: 12px; }`를 지정하므로
    zoomIn()/zoomOut()의 QFont 변경은 스타일시트에 덮여 보이지 않는다.
    위젯 자체 스타일시트의 font-size를 갱신하는 방식으로 확대/축소한다.
    """

    _MIN_PX = 7
    _MAX_PX = 32

    def __init__(self, parent=None):
        super().__init__(parent)
        self._font_px = 12
        self._apply_font_style()

    def _apply_font_style(self):
        self.setStyleSheet(
            "QPlainTextEdit { background: #111827; color: #f8f8f2; "
            "border: 1px solid #2a3045; border-radius: 6px; padding: 8px; "
            "font-family: 'JetBrains Mono', Consolas, 'Courier New', monospace; "
            f"font-size: {self._font_px}px; }}"
        )

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                step = 1 if delta > 0 else -1
                new_px = max(self._MIN_PX, min(self._MAX_PX, self._font_px + step))
                if new_px != self._font_px:
                    self._font_px = new_px
                    self._apply_font_style()
            event.accept()
            return
        super().wheelEvent(event)


class SettingsTab(QWidget):
    """설정 파일 브라우저 + Q&A 채팅 + 편집/저장/초기화 위젯."""

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

    # MainWindow가 연결하는 시그널 — LLM이 필요한 두 흐름은 완성된 프롬프트
    # 문자열만 올려보낸다 (llm 객체는 MainWindow.state에만 있음).
    qa_requested              = pyqtSignal(str)   # 완성된 Q&A 프롬프트
    prompt_rewrite_requested  = pyqtSignal(str)   # 완성된 프롬프트 재작성 요청
    rebuild_requested         = pyqtSignal()      # "재구축 지금" 선택 시
    file_saved                = pyqtSignal(str)   # 저장/초기화 완료된 rel_path

    def __init__(self, base_dir: str = ".", config_metadata: dict | None = None, parent=None):
        super().__init__(parent)
        self._base_dir = base_dir
        self._config_metadata = config_metadata or {}
        self._workers: set[SettingsFileLoadWorker] = set()
        self._save_workers: set[SettingsSaveWorker] = set()

        self._cache_dir = os.path.join(base_dir, ".rag_cache")
        self._current_rel_path: str | None = None
        self._edit_mode = False
        self._original_text = ""
        self._locked_row = -1
        self._active_categories: set[str] | None = None  # None == "All"
        self._known_mtimes: dict[str, float] = {}
        self._banner_rel_path: str | None = None
        self._pending_recovery: dict[str, str] = {}
        self._pending_qa_question: str = ""
        self._pending_rewrite_original: str = ""

        self._build_ui()
        self._populate_file_list()
        self._snapshot_mtimes()
        self._offer_recovery_if_present()

        self._recovery_timer = QTimer(self)
        self._recovery_timer.setInterval(30_000)
        self._recovery_timer.timeout.connect(self._save_recovery)

        self._monitor_timer = QTimer(self)
        self._monitor_timer.setInterval(2_000)
        self._monitor_timer.timeout.connect(self._check_external_changes)
        self._monitor_timer.start()

    # ── UI 구성 ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(8)

        title = QLabel("⚙️  설정 파일")
        title.setStyleSheet("color: #e2e8f0; font-size: 14px; font-weight: 700;")
        layout.addWidget(title)

        hint = QLabel("설정·프롬프트 파일을 선택해 질문하거나 편집합니다.")
        hint.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(hint)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_file_panel())
        splitter.addWidget(self._build_chat_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([260, 640, 420])
        layout.addWidget(splitter, 1)

    def _build_left_panel(self) -> QWidget:
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        # ── 카테고리 필터 ────────────────────────────────────────────────────
        cat_box = QGroupBox("카테고리")
        cat_box.setStyleSheet(
            "QGroupBox { color: #94a3b8; font-size: 11px; border: 1px solid #2a3045; "
            "border-radius: 6px; margin-top: 6px; padding-top: 6px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; }"
        )
        cat_layout = QVBoxLayout(cat_box)
        cat_layout.setSpacing(2)
        cat_layout.setContentsMargins(8, 4, 8, 6)

        self.category_checks: dict[str, QCheckBox] = {}

        self.all_check = QCheckBox("All")
        self.all_check.setChecked(True)
        self.all_check.setStyleSheet("color: #e2e8f0; font-size: 11px;")
        self.all_check.toggled.connect(self._on_all_category_toggled)
        cat_layout.addWidget(self.all_check)

        for cat in CATEGORIES:
            cb = QCheckBox(cat)
            cb.setStyleSheet("color: #94a3b8; font-size: 11px;")
            cb.toggled.connect(self._on_category_toggled)
            cat_layout.addWidget(cb)
            self.category_checks[cat] = cb

        left_layout.addWidget(cat_box)

        # ── 파일 목록 ────────────────────────────────────────────────────────
        self.file_list = QListWidget()
        self.file_list.setStyleSheet(
            "QListWidget { background: #161922; border: 1px solid #2a3045; "
            "border-radius: 6px; color: #e2e8f0; font-size: 12px; "
            "font-family: 'JetBrains Mono', Consolas, monospace; }"
            "QListWidget::item { padding: 6px 8px; border-bottom: 1px solid #1e2330; }"
            "QListWidget::item:selected { background: #1e3a5f; }"
        )
        self.file_list.currentRowChanged.connect(self._on_row_changed)
        left_layout.addWidget(self.file_list, 1)

        # ── 액션 버튼 ────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self.reload_btn = QPushButton("🔄 새로고침")
        self.save_btn = QPushButton("💾 저장")
        self.reset_btn = QPushButton("↺ 기본값")
        for b in (self.reload_btn, self.save_btn, self.reset_btn):
            b.setStyleSheet(
                "QPushButton { background: #1e2330; color: #94a3b8; border: 1px solid #2d3748; "
                "border-radius: 4px; padding: 4px 6px; font-size: 10px; }"
                "QPushButton:hover { background: #2d3748; color: #e2e8f0; }"
                "QPushButton:disabled { color: #475569; }"
            )
            btn_row.addWidget(b)
        self.save_btn.setEnabled(False)
        self.reload_btn.clicked.connect(self._on_reload_files_clicked)
        self.save_btn.clicked.connect(self._do_save)
        self.reset_btn.clicked.connect(self._do_reset)
        left_layout.addLayout(btn_row)

        self.unsaved_label = QLabel("")
        self.unsaved_label.setStyleSheet("color: #fbbf24; font-size: 10px;")
        left_layout.addWidget(self.unsaved_label)

        left.setMinimumWidth(200)
        return left

    def _build_chat_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        if getattr(sys, "frozen", False):
            _base = Path(sys._MEIPASS)
        else:
            _base = Path(__file__).parent.parent

        self.qa_display = QWebEngineView()
        html_path = _base / "resources" / "settings_chat.html"
        self.qa_display.setUrl(QUrl.fromLocalFile(str(html_path.resolve())))
        v.addWidget(self.qa_display, 1)

        self.ask_btn = QPushButton("Ask")
        self.preview_btn = QPushButton("Preview")
        self.edit_btn = QPushButton("Edit")
        self.discard_btn = QPushButton("Discard")
        self.clear_btn = QPushButton("Clear")
        self.discard_btn.setVisible(False)
        for b in (self.ask_btn, self.preview_btn, self.edit_btn, self.discard_btn, self.clear_btn):
            b.setStyleSheet(
                "QPushButton { background: #1e2330; color: #94a3b8; border: 1px solid #2d3748; "
                "border-radius: 4px; padding: 4px 10px; font-size: 11px; }"
                "QPushButton:hover { background: #2d3748; color: #e2e8f0; }"
                "QPushButton:disabled { color: #475569; }"
            )
        self.preview_btn.setEnabled(False)
        self.ask_btn.clicked.connect(self._on_ask_clicked)
        self.preview_btn.clicked.connect(self._on_preview_clicked)
        self.edit_btn.clicked.connect(self._enter_edit_mode)
        self.discard_btn.clicked.connect(self._discard_edits)
        self.clear_btn.clicked.connect(self._on_clear_qa_clicked)

        toolbar_row = QHBoxLayout()
        for b in (self.preview_btn, self.edit_btn, self.discard_btn, self.clear_btn):
            toolbar_row.addWidget(b)
        toolbar_row.addStretch(1)
        v.addLayout(toolbar_row)

        input_row = QHBoxLayout()
        self.qa_input = _QAInput()
        self.qa_input.setPlaceholderText("설정 파라미터에 대해 질문하세요… (예: VECTOR_K가 뭐야?)")
        self.qa_input.setFixedHeight(48)
        self.qa_input.setStyleSheet(
            "QPlainTextEdit { background: #161922; color: #e2e8f0; "
            "border: 1px solid #2a3045; border-radius: 6px; padding: 6px; font-size: 12px; }"
        )
        self.qa_input.returnPressed.connect(self._on_ask_clicked)
        input_row.addWidget(self.qa_input, 1)
        self.ask_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        input_row.addWidget(self.ask_btn)

        v.addLayout(input_row)
        panel.setMinimumWidth(300)
        return panel

    def _build_file_panel(self) -> QWidget:
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        header_row = QHBoxLayout()
        self.header_label = QLabel("")
        self.header_label.setStyleSheet(
            "color: #94a3b8; font-size: 11px; padding: 2px 4px; "
            "font-family: 'JetBrains Mono', Consolas, monospace;"
        )
        header_row.addWidget(self.header_label, 1)

        self.modify_llm_btn = QPushButton("🪄 LLM로 수정")
        self.modify_llm_btn.setStyleSheet(
            "QPushButton { background: #1e2330; color: #94a3b8; border: 1px solid #2d3748; "
            "border-radius: 4px; padding: 3px 8px; font-size: 10px; }"
            "QPushButton:hover { background: #2d3748; color: #e2e8f0; }"
        )
        self.modify_llm_btn.setVisible(False)
        self.modify_llm_btn.clicked.connect(self._on_modify_via_llm_clicked)
        header_row.addWidget(self.modify_llm_btn)
        right_layout.addLayout(header_row)

        self.warning_banner = QWidget()
        wb_layout = QHBoxLayout(self.warning_banner)
        wb_layout.setContentsMargins(6, 4, 6, 4)
        self.warning_label = QLabel("")
        self.warning_label.setStyleSheet("color: #fbbf24; font-size: 11px;")
        wb_layout.addWidget(self.warning_label, 1)
        self.reload_banner_btn = QPushButton("Reload")
        self.reload_banner_btn.setStyleSheet(
            "QPushButton { background: #2d2a10; color: #fde68a; border: 1px solid #854d0e; "
            "border-radius: 4px; padding: 2px 8px; font-size: 10px; }"
        )
        self.reload_banner_btn.clicked.connect(self._on_reload_banner_clicked)
        wb_layout.addWidget(self.reload_banner_btn)
        self.warning_banner.setStyleSheet("background: #2d2a10; border-radius: 6px;")
        self.warning_banner.setVisible(False)
        right_layout.addWidget(self.warning_banner)

        self.content_view = _ZoomableContentView()
        self.content_view.setReadOnly(True)
        self.content_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.content_view.setPlaceholderText(self.PLACEHOLDER_EMPTY)
        right_layout.addWidget(self.content_view, 1)

        right.setMinimumWidth(360)
        return right

    def _populate_file_list(self):
        self.file_list.clear()
        for rel_path in self.CONFIG_FILES:
            if not self._matches_active_category(rel_path):
                continue
            item = QListWidgetItem(rel_path)
            exists = os.path.exists(self._abs_path(rel_path))
            item.setForeground(QColor(self.COLOR_EXISTS if exists else self.COLOR_MISSING))
            item.setData(Qt.ItemDataRole.UserRole, rel_path)
            self.file_list.addItem(item)

    # ── 카테고리 필터 ─────────────────────────────────────────────────────────

    def _file_categories(self, rel_path: str) -> set[str]:
        if rel_path.startswith("prompts/"):
            return {"Prompt"}
        section_key = "env" if rel_path == "env.txt" else "config"
        section = self._config_metadata.get(section_key, {})
        return {e.get("category", "Other") for e in section.values()}

    def _matches_active_category(self, rel_path: str) -> bool:
        if self._active_categories is None:
            return True
        return bool(self._file_categories(rel_path) & self._active_categories)

    def _on_all_category_toggled(self, checked: bool):
        if checked:
            for cb in self.category_checks.values():
                cb.blockSignals(True)
                cb.setChecked(False)
                cb.blockSignals(False)
            self._active_categories = None
            self._populate_file_list()

    def _on_category_toggled(self):
        active = {cat for cat, cb in self.category_checks.items() if cb.isChecked()}
        if active:
            self.all_check.blockSignals(True)
            self.all_check.setChecked(False)
            self.all_check.blockSignals(False)
            self._active_categories = active
        else:
            self.all_check.blockSignals(True)
            self.all_check.setChecked(True)
            self.all_check.blockSignals(False)
            self._active_categories = None
        self._populate_file_list()

    # ── 파일 선택 → 비동기 로드 ─────────────────────────────────────────────

    def _on_row_changed(self, row: int):
        if self._edit_mode:
            # 편집 중에는 선택 잠금 (F-SETTINGS-4 step 4).
            self.file_list.blockSignals(True)
            self.file_list.setCurrentRow(self._locked_row)
            self.file_list.blockSignals(False)
            return
        if row < 0:
            return
        item = self.file_list.item(row)
        if item is None:
            return
        rel_path = item.data(Qt.ItemDataRole.UserRole)
        self._current_rel_path = rel_path
        self.header_label.setText(f"{rel_path} · UTF-8")
        self.content_view.setPlainText(self.PLACEHOLDER_LOADING)
        self.modify_llm_btn.setVisible(rel_path.startswith("prompts/"))
        self.warning_banner.setVisible(False)
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
        if rel_path in self._pending_recovery:
            recovered = self._pending_recovery.pop(rel_path)
            self.content_view.setPlainText(recovered)
            self._original_text = content
            self._enter_edit_mode(skip_snapshot=True)
        else:
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

    def set_cache_dir(self, cache_dir: str):
        self._cache_dir = cache_dir
        self._offer_recovery_if_present()
        self._load_qa_history()

    # ── 편집 모드 ─────────────────────────────────────────────────────────────

    def _enter_edit_mode(self, skip_snapshot: bool = False):
        if not self._current_rel_path:
            return
        if not skip_snapshot:
            self._original_text = self.content_view.toPlainText()
        self.content_view.setReadOnly(False)
        self._edit_mode = True
        self._locked_row = self.file_list.currentRow()
        self.edit_btn.setEnabled(False)
        self.discard_btn.setVisible(True)
        self.save_btn.setEnabled(True)
        self.content_view.textChanged.connect(self._on_text_changed)
        self._recovery_timer.start()
        self._update_unsaved_label()

    def _exit_edit_mode(self):
        self.content_view.setReadOnly(True)
        self._edit_mode = False
        self.edit_btn.setEnabled(True)
        self.discard_btn.setVisible(False)
        self.save_btn.setEnabled(False)
        self.unsaved_label.setText("")
        self.preview_btn.setEnabled(False)
        self._recovery_timer.stop()
        try:
            self.content_view.textChanged.disconnect(self._on_text_changed)
        except TypeError:
            pass

    def _on_text_changed(self):
        self._update_unsaved_label()

    def _update_unsaved_label(self):
        current = self.content_view.toPlainText()
        changed = current != self._original_text
        self.preview_btn.setEnabled(changed)
        if changed:
            n = self._count_changed_lines(self._original_text, current)
            self.unsaved_label.setText(f"Unstaged Changes: {n} lines")
        else:
            self.unsaved_label.setText("")

    @staticmethod
    def _count_changed_lines(a: str, b: str) -> int:
        a_lines, b_lines = a.splitlines(), b.splitlines()
        matcher = SequenceMatcher(None, a_lines, b_lines)
        count = 0
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag != "equal":
                count += max(i2 - i1, j2 - j1)
        return count

    def has_unsaved_changes(self) -> bool:
        return self._edit_mode and self.content_view.toPlainText() != self._original_text

    def _discard_edits(self):
        if self.has_unsaved_changes():
            reply = QMessageBox.question(
                self, "편집 취소", f"'{self._current_rel_path}'의 저장하지 않은 변경사항을 취소할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.content_view.setPlainText(self._original_text)
        self._exit_edit_mode()
        self._delete_recovery_file(self._current_rel_path)

    def confirm_leave(self) -> bool:
        """탭 전환 전 MainWindow가 호출. 저장하지 않은 변경이 없으면 즉시 True."""
        if not self.has_unsaved_changes():
            return True
        choice = self._ask_leave_choice()
        if choice == "save":
            return self._do_save()
        if choice == "discard":
            self.content_view.setPlainText(self._original_text)
            self._exit_edit_mode()
            self._delete_recovery_file(self._current_rel_path)
            return True
        return False

    def _ask_leave_choice(self) -> str:
        """'save' / 'discard' / 'cancel' — 별도 메서드로 분리해 테스트에서 monkeypatch 가능."""
        box = QMessageBox(self)
        box.setWindowTitle("저장하지 않은 변경사항")
        box.setText(f"'{self._current_rel_path}'에 저장하지 않은 변경사항이 있습니다.")
        save_btn = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard_btn = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save_btn:
            return "save"
        if clicked is discard_btn:
            return "discard"
        return "cancel"

    # ── 자동 저장 복구 ────────────────────────────────────────────────────────

    def _recovery_dir(self) -> Path:
        return Path(self._cache_dir) / "settings_recovery"

    def _recovery_file(self, rel_path: str) -> Path:
        return self._recovery_dir() / (rel_path.replace("/", "__") + ".recovery")

    def _save_recovery(self):
        if not self._edit_mode or not self._current_rel_path:
            return
        try:
            self._recovery_dir().mkdir(parents=True, exist_ok=True)
            self._recovery_file(self._current_rel_path).write_text(
                self.content_view.toPlainText(), encoding="utf-8"
            )
        except OSError:
            pass

    def _delete_recovery_file(self, rel_path: str | None):
        if not rel_path:
            return
        try:
            self._recovery_file(rel_path).unlink(missing_ok=True)
        except OSError:
            pass

    def _offer_recovery_if_present(self):
        rec_dir = self._recovery_dir()
        if not rec_dir.exists():
            return
        for f in sorted(rec_dir.glob("*.recovery")):
            rel_path = f.stem.replace("__", "/")
            reply = QMessageBox.question(
                self, "복구 가능한 편집 발견",
                f"'{rel_path}'에 저장되지 않은 편집 내용이 있습니다. 복구할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    self._pending_recovery[rel_path] = f.read_text(encoding="utf-8")
                except OSError:
                    pass
            else:
                try:
                    f.unlink()
                except OSError:
                    pass

    # ── 저장 / 검증 / 재구축 확인 ─────────────────────────────────────────────

    def _do_save(self) -> bool:
        if not self._current_rel_path or not self._edit_mode:
            return False

        new_text = self.content_view.toPlainText()
        is_config = self._current_rel_path == "config.txt"
        is_env = self._current_rel_path == "env.txt"

        if is_config or is_env:
            from rag_core import validate_kv_text
            section = self._config_metadata.get("config" if is_config else "env", {})
            errors = validate_kv_text(new_text, section)
            if errors:
                QMessageBox.critical(self, "검증 오류", "\n".join(errors))
                return False

        reply = QMessageBox.question(
            self, "저장 확인", f"'{self._current_rel_path}'에 변경사항을 저장할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return False

        trigger_rebuild = False
        if is_config:
            from rag_core import classify_config_changes
            classification = classify_config_changes(self._original_text, new_text, self._config_metadata)
            if classification["requires_rebuild"]:
                choice = self._ask_rebuild_choice()
                if choice == "cancel":
                    return False
                trigger_rebuild = choice == "now"

        self._run_save_worker(new_text, trigger_rebuild)
        return True

    def _ask_rebuild_choice(self) -> str:
        box = QMessageBox(self)
        box.setWindowTitle("재구축 필요")
        box.setText("검색 설정(retriever)이 변경되었습니다. 지금 RAG 인덱스를 재구축할까요?")
        now_btn = box.addButton("Rebuild Now", QMessageBox.ButtonRole.AcceptRole)
        later_btn = box.addButton("Rebuild Later", QMessageBox.ButtonRole.ActionRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is now_btn:
            return "now"
        if clicked is later_btn:
            return "later"
        return "cancel"

    def _run_save_worker(self, new_text: str, trigger_rebuild: bool):
        rel_path = self._current_rel_path
        abs_path = self._abs_path(rel_path)
        worker = SettingsSaveWorker(abs_path, new_text, self._cache_dir)
        worker.save_finished.connect(
            lambda _p, rp=rel_path, rb=trigger_rebuild: self._on_save_finished(rp, rb)
        )
        worker.error_signal.connect(self._on_save_error)
        worker.finished.connect(lambda w=worker: self._save_workers.discard(w))
        self._save_workers.add(worker)
        worker.start()

    def _on_save_finished(self, rel_path: str, trigger_rebuild: bool):
        self._delete_recovery_file(rel_path)
        self._exit_edit_mode()
        self._original_text = self.content_view.toPlainText()
        self._populate_file_list()
        self._snapshot_mtimes()
        self.unsaved_label.setText(f"✓ {rel_path} 저장 완료")
        self.file_saved.emit(rel_path)
        if trigger_rebuild:
            self.rebuild_requested.emit()

    def _on_save_error(self, msg: str):
        QMessageBox.critical(self, "저장 오류", msg)

    # ── 초기화 (Reset to Defaults) ────────────────────────────────────────────

    def _do_reset(self):
        if not self._current_rel_path:
            return
        if self._current_rel_path == "env.txt":
            QMessageBox.information(self, "알림", "env.txt는 초기화할 수 없습니다 (API 키 보호).")
            return

        reply = QMessageBox.question(
            self, "기본값으로 초기화", f"'{self._current_rel_path}'를 기본값으로 초기화할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        if self._current_rel_path == "config.txt":
            from rag_core import reset_config_defaults
            abs_path = self._abs_path(self._current_rel_path)
            try:
                disk_text = Path(abs_path).read_text(encoding="utf-8")
            except OSError:
                disk_text = ""
            reset_text = reset_config_defaults(disk_text, self._config_metadata)
            self._original_text = disk_text
            self.content_view.setPlainText(reset_text)
            self._enter_edit_mode(skip_snapshot=True)
        elif self._current_rel_path.startswith("prompts/"):
            self._reset_prompt_file(self._current_rel_path)

    def _reset_prompt_file(self, rel_path: str):
        abs_path = Path(self._abs_path(rel_path))
        if abs_path.exists():
            backup_dir = Path(self._cache_dir) / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(abs_path, backup_dir / f"{abs_path.name}.{ts}.bak")
            abs_path.unlink()
        self._populate_file_list()
        self._snapshot_mtimes()
        if self._current_rel_path == rel_path:
            self._load_file(rel_path)
        self.unsaved_label.setText(f"✓ {rel_path} 기본값으로 초기화됨")
        self.file_saved.emit(rel_path)

    # ── 외부 변경 감지 ────────────────────────────────────────────────────────

    def _snapshot_mtimes(self):
        for rel_path in self.CONFIG_FILES:
            try:
                self._known_mtimes[rel_path] = os.path.getmtime(self._abs_path(rel_path))
            except OSError:
                self._known_mtimes.pop(rel_path, None)

    def _check_external_changes(self):
        for rel_path in self.CONFIG_FILES:
            try:
                mtime = os.path.getmtime(self._abs_path(rel_path))
            except OSError:
                continue
            prev = self._known_mtimes.get(rel_path)
            self._known_mtimes[rel_path] = mtime
            if prev is not None and mtime != prev and rel_path == self._current_rel_path:
                self._show_warning_banner(rel_path)

    def _show_warning_banner(self, rel_path: str):
        self._banner_rel_path = rel_path
        self.warning_label.setText(f"⚠️ '{rel_path}' 파일이 외부에서 변경되었습니다.")
        self.warning_banner.setVisible(True)

    def _on_reload_banner_clicked(self):
        rel_path = self._banner_rel_path
        self.warning_banner.setVisible(False)
        if not rel_path:
            return
        self._exit_edit_mode()
        self._load_file(rel_path)

    def _on_reload_files_clicked(self):
        if self.has_unsaved_changes():
            reply = QMessageBox.question(
                self, "새로고침", "저장하지 않은 변경사항을 버리고 새로고침할까요?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._exit_edit_mode()
        self._populate_file_list()
        if self._current_rel_path:
            self._load_file(self._current_rel_path)
        self._snapshot_mtimes()

    # ── 미리보기 / Diff ───────────────────────────────────────────────────────

    def _on_preview_clicked(self):
        if not self.has_unsaved_changes():
            return
        self._open_diff_dialog(self._original_text, self.content_view.toPlainText(), mode="edit")

    def _mask_text(self, rel_path: str, text: str) -> str:
        if rel_path not in ("env.txt", "config.txt"):
            return text
        section_key = "env" if rel_path == "env.txt" else "config"
        section = self._config_metadata.get(section_key, {})
        try:
            from rag_core import mask_sensitive_value
        except ImportError:
            return text

        out_lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if "=" in stripped and not stripped.startswith("#"):
                key, _, value = stripped.partition("=")
                key = key.strip()
                entry = section.get(key)
                if entry and entry.get("mask_in_ui"):
                    out_lines.append(f"{key}={mask_sensitive_value(key, value.strip(), entry)}")
                    continue
            out_lines.append(line)
        return "\n".join(out_lines)

    def _open_diff_dialog(self, original: str, edited: str, mode: str):
        rel_path = self._current_rel_path or ""
        masked_original = self._mask_text(rel_path, original)
        masked_edited = self._mask_text(rel_path, edited)

        dlg = QDialog(self)
        dlg.setWindowTitle(f"미리보기 — {rel_path}")
        dlg.resize(900, 500)
        v = QVBoxLayout(dlg)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left_view = QPlainTextEdit(masked_original)
        right_view = QPlainTextEdit(masked_edited)
        for view in (left_view, right_view):
            view.setReadOnly(True)
            view.setFont(QFont("JetBrains Mono, Consolas, Courier New", 10))
            view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        splitter.addWidget(left_view)
        splitter.addWidget(right_view)
        v.addWidget(splitter, 1)

        self._highlight_diff(left_view, right_view, masked_original, masked_edited)

        btn_row = QHBoxLayout()
        if mode == "edit":
            save_btn = QPushButton("Save")
            discard_btn = QPushButton("Discard")
            continue_btn = QPushButton("Continue Editing")
            save_btn.clicked.connect(lambda: (dlg.accept(), self._do_save()))
            discard_btn.clicked.connect(lambda: (dlg.accept(), self._discard_edits()))
            continue_btn.clicked.connect(dlg.reject)
            btn_row.addWidget(save_btn)
            btn_row.addWidget(discard_btn)
            btn_row.addWidget(continue_btn)
        else:  # "rewrite" — F-SETTINGS-12 Accept/Reject
            accept_btn = QPushButton("Accept")
            reject_btn = QPushButton("Reject")

            def _accept():
                dlg.accept()
                self.content_view.setPlainText(edited)
                self._enter_edit_mode(skip_snapshot=True)
                self._original_text = original
                self._do_save()

            accept_btn.clicked.connect(_accept)
            reject_btn.clicked.connect(dlg.reject)
            btn_row.addWidget(accept_btn)
            btn_row.addWidget(reject_btn)
        v.addLayout(btn_row)

        dlg.exec()

    @staticmethod
    def _highlight_diff(left_view: QPlainTextEdit, right_view: QPlainTextEdit,
                        original: str, edited: str):
        a_lines, b_lines = original.splitlines(), edited.splitlines()
        matcher = SequenceMatcher(None, a_lines, b_lines)

        fmt_remove = QTextCharFormat()
        fmt_remove.setBackground(QColor("#4a1e1e"))
        fmt_add = QTextCharFormat()
        fmt_add.setBackground(QColor("#1e4a2a"))

        def _apply(view: QPlainTextEdit, start: int, end: int, fmt: QTextCharFormat):
            doc = view.document()
            for i in range(start, end):
                block = doc.findBlockByNumber(i)
                if not block.isValid():
                    continue
                cursor = view.textCursor()
                cursor.setPosition(block.position())
                cursor.select(cursor.SelectionType.LineUnderCursor)
                cursor.mergeCharFormat(fmt)

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag in ("replace", "delete"):
                _apply(left_view, i1, i2, fmt_remove)
            if tag in ("replace", "insert"):
                _apply(right_view, j1, j2, fmt_add)

    # ── LLM 프롬프트 수정 (F-SETTINGS-12) ─────────────────────────────────────

    def _on_modify_via_llm_clicked(self):
        if not self._current_rel_path or not self._current_rel_path.startswith("prompts/"):
            return
        text, ok = QInputDialog.getMultiLineText(
            self, "LLM로 프롬프트 수정", "어떻게 수정할까요?", ""
        )
        if not ok or not text.strip():
            return

        current_text = self.content_view.toPlainText()
        prompt_key = self._current_rel_path.split("/", 1)[1]
        entry = self._config_metadata.get("prompts", {}).get(prompt_key, {})

        from rag_core import build_prompt_rewrite_request
        prompt = build_prompt_rewrite_request(
            entry.get("category", "Prompt"), entry.get("description", ""),
            current_text, text.strip(),
        )
        self._pending_rewrite_original = current_text
        self.modify_llm_btn.setEnabled(False)
        self.prompt_rewrite_requested.emit(prompt)

    def on_rewrite_finished(self, new_text: str):
        self.modify_llm_btn.setEnabled(True)
        self._open_diff_dialog(self._pending_rewrite_original, new_text, mode="rewrite")

    def on_rewrite_error(self, msg: str):
        self.modify_llm_btn.setEnabled(True)
        QMessageBox.critical(self, "오류", msg)

    # ── Q&A 채팅 (F-SETTINGS-3) ────────────────────────────────────────────

    def _run_qa_js(self, script: str):
        self.qa_display.page().runJavaScript(script)

    def _on_ask_clicked(self):
        question = self.qa_input.toPlainText().strip()
        if not question:
            return
        self.qa_input.clear()
        self._run_qa_js(f"appendUserMessage({json.dumps(question)})")
        self._run_qa_js("startAiMessage()")

        from rag_core import (
            find_config_key_in_question,
            build_settings_qa_prompt,
            build_settings_qa_grounded_prompt,
            build_settings_qa_enumeration_prompt,
            detect_settings_enumeration_scope,
            load_settings_reference,
            find_reference_section,
        )

        # 레퍼런스 문서는 매칭/비매칭 양쪽에서 근거로 쓰인다 (SPEC-SETTINGS-003).
        # 없거나 못 읽으면 빈 문자열 — 예외 없이 폴백 (REQ-011).
        reference_text = load_settings_reference()

        # 전체/파일 단위 열거 질문("모든 파라미터 설명해줘" 등)은 키 매칭보다 먼저
        # 검사한다 — 질문에 특정 키 이름이 섞여도 단일 키 경로로 새지 않도록.
        scope = detect_settings_enumeration_scope(question)
        if scope is not None and reference_text:
            prompt = build_settings_qa_enumeration_prompt(
                question, self._config_metadata, reference_text, scope
            )
            self._pending_qa_question = question
            self.qa_requested.emit(prompt)
            return

        key = find_config_key_in_question(question, self._config_metadata)

        if key is None:
            # 비매칭: 하드코딩 거부 대신 레퍼런스 문서 기반 그라운딩 LLM 경로로 라우팅.
            if reference_text:
                prompt = build_settings_qa_grounded_prompt(question, reference_text)
                self._pending_qa_question = question
                self.qa_requested.emit(prompt)
            else:
                # 레퍼런스 문서 부재 시 안전 폴백 (LLM 미호출, 비크래시).
                answer = (
                    "현재 참고할 수 있는 설정 레퍼런스 문서가 없어 이 질문에 답변하기 "
                    "어렵습니다. 관련 설정 파일을 직접 확인해 주세요."
                )
                self._run_qa_js(f"streamingBuffer = {json.dumps(answer)}; finishAiMessage();")
                self._append_qa_history(question, answer)
            return

        entry = self._config_metadata.get("config", {}).get(key) \
            or self._config_metadata.get("env", {}).get(key)
        current_value = entry.get("value") if entry else None
        reference_section = find_reference_section(reference_text, key) if reference_text else ""
        prompt = build_settings_qa_prompt(
            question, key, entry or {}, current_value,
            reference_section=reference_section or None,
        )
        self._pending_qa_question = question
        self.qa_requested.emit(prompt)

    def on_qa_chunk(self, chunk: str):
        self._run_qa_js(f"streamingBuffer += {json.dumps(chunk)}; renderStreamingBuffer();")

    def on_qa_finished(self, answer: str):
        self._run_qa_js("finishAiMessage();")
        self._append_qa_history(self._pending_qa_question, answer)

    def on_qa_error(self, msg: str):
        self._run_qa_js("removeStatus();")
        QMessageBox.critical(self, "오류", msg)

    def _on_clear_qa_clicked(self):
        """Q&A 대화 초기화 (SPEC-SETTINGS-002 R2) — 표시 비우기 + 영구 삭제.

        NotebookTab 선례를 따라 확인 대화상자 없이 즉시 초기화한다. 파일 단위가
        아닌 전체 스레드(`settings_chat.jsonl`)를 영구 삭제한다.
        """
        self._run_qa_js("clearChat()")
        try:
            from cache_store import SettingsChatCache
            SettingsChatCache(self._cache_dir).clear()
        except Exception:
            pass

    def _append_qa_history(self, question: str, answer: str):
        if not question:
            return
        try:
            from cache_store import SettingsChatCache
            SettingsChatCache(self._cache_dir).add(self._current_rel_path or "", question, answer)
        except Exception:
            pass

    def _load_qa_history(self):
        try:
            from cache_store import SettingsChatCache
            entries = SettingsChatCache(self._cache_dir).load()
        except Exception:
            entries = []
        for e in entries:
            self._run_qa_js(f"appendUserMessage({json.dumps(e.get('question', ''))})")
            self._run_qa_js(f"appendFinishedAiMessage({json.dumps(e.get('answer', ''))})")
