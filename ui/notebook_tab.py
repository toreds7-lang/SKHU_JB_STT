"""
NotebookTab - 노트북 뷰어 + 셀 채팅 + 요약 탭
좌측: 체크박스 노트북 목록 + 요약 생성 버튼
우측: 셀+채팅 보기 / 요약 보기 전환
  - 셀+채팅: 좌측 QWebEngineView(notebook_viewer.html) + 우측 채팅 패널
"""

import json
import os
import sys
import uuid
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QFrame, QSizePolicy,
    QPushButton, QProgressBar, QSplitter, QSplitterHandle, QStackedWidget, QCheckBox,
    QPlainTextEdit, QApplication, QTreeWidget, QTreeWidgetItem,
)
from PyQt6.QtCore import Qt, QUrl, pyqtSignal, QFileSystemWatcher
from PyQt6.QtGui import QFont, QColor, QKeySequence, QShortcut, QDesktopServices
from ui.stt_button import STTButton
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage

from cache_store import NotebookChatCache


# ── 스타일 상수 ──────────────────────────────────────────────────────────────

_BTN_STYLE = (
    "QPushButton { background: #4f8ef7; color: #fff; border: none; "
    "border-radius: 6px; padding: 6px 14px; font-size: 12px; font-weight: 600; }"
    "QPushButton:hover { background: #3b7be0; }"
    "QPushButton:disabled { background: #334155; color: #64748b; }"
)
_STOP_BTN_STYLE = (
    "QPushButton { background: #dc2626; color: #fff; border: none; "
    "border-radius: 6px; padding: 6px 14px; font-size: 12px; font-weight: 600; }"
    "QPushButton:hover { background: #b91c1c; }"
)
_SEND_BTN_STYLE = (
    "QPushButton { background: #4f8ef7; color: #fff; border: none; "
    "border-radius: 6px; padding: 6px 16px; font-size: 12px; font-weight: 600; }"
    "QPushButton:hover { background: #3b7be0; }"
    "QPushButton:disabled { background: #334155; color: #64748b; }"
)
_CHAT_STOP_BTN_STYLE = (
    "QPushButton { background: #dc2626; color: #fff; border: none; "
    "border-radius: 6px; padding: 6px 16px; font-size: 12px; font-weight: 600; }"
    "QPushButton:hover { background: #b91c1c; }"
)
_TOGGLE_ACTIVE = (
    "QPushButton { background: #1e2330; color: #e2e8f0; border: 1px solid #4f8ef7; "
    "border-radius: 4px; padding: 4px 12px; font-size: 11px; font-weight: 600; }"
)
_TOGGLE_INACTIVE = (
    "QPushButton { background: transparent; color: #64748b; border: 1px solid #2a3045; "
    "border-radius: 4px; padding: 4px 12px; font-size: 11px; }"
    "QPushButton:hover { color: #94a3b8; border-color: #475569; }"
)
_OUTLINE_TREE_STYLE = (
    "QTreeWidget { background: #0d0f14; border: none; color: #d4d4d4; "
    "font-size: 12px; outline: 0; }"
    "QTreeWidget::item { padding: 3px 4px; border-radius: 3px; }"
    "QTreeWidget::item:selected { background: #1e3a5f; color: #93c5fd; }"
    "QTreeWidget::item:hover:!selected { background: #161922; }"
    "QTreeWidget::branch { background: #0d0f14; }"
)


# ── 접이식 스플리터 ───────────────────────────────────────────────────────────

class _CollapseHandle(QSplitterHandle):
    """스플리터 핸들 중앙에 ◀/▶ 버튼을 넣어 한 번 클릭으로 패널을 접고 펼친다."""

    _BTN_STYLE = (
        "QPushButton { background: #374151; color: #9ca3af; border: none; "
        "border-radius: 3px; font-size: 9px; padding: 0; }"
        "QPushButton:hover { background: #4b5563; color: #e2e8f0; }"
    )

    def __init__(self, orientation, parent, collapse_index: int = 1,
                 secondary_collapse_index: int | None = None):
        super().__init__(orientation, parent)
        self._collapse_index = collapse_index
        self._secondary_collapse_index = secondary_collapse_index
        self._saved_sizes: list[int] | None = None
        self._saved_sizes2: list[int] | None = None

        has_secondary = secondary_collapse_index is not None
        btn_h = 18 if has_secondary else 40

        arrow = "▶" if collapse_index == 1 else "◀"
        self._btn = QPushButton(arrow, self)
        self._btn.setFixedSize(16, btn_h)
        self._btn.setStyleSheet(self._BTN_STYLE)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setToolTip("셀 Q&A 패널 접기/펼치기" if collapse_index == 1 else "패널 접기/펼치기")
        self._btn.clicked.connect(self._toggle)
        self.splitter().splitterMoved.connect(self._sync_arrow)

        if has_secondary:
            arrow2 = "▶" if secondary_collapse_index == 1 else "◀"
            self._btn2 = QPushButton(arrow2, self)
            self._btn2.setFixedSize(16, btn_h)
            self._btn2.setStyleSheet(self._BTN_STYLE)
            self._btn2.setCursor(Qt.CursorShape.PointingHandCursor)
            self._btn2.setToolTip("노트북 뷰어 접기/펼치기" if secondary_collapse_index == 0 else "패널 접기/펼치기")
            self._btn2.clicked.connect(self._toggle2)
        else:
            self._btn2 = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cx = (self.width() - 16) // 2
        if self._btn2 is not None:
            cy = self.height() // 2
            self._btn2.move(cx, cy - 19)
            self._btn.move(cx, cy + 1)
        else:
            self._btn.move(cx, (self.height() - 40) // 2)

    def _sync_arrow(self):
        sizes = self.splitter().sizes()

        collapsed = sizes[self._collapse_index] == 0
        self._btn.setText("◀" if collapsed else "▶") if self._collapse_index == 1 \
            else self._btn.setText("▶" if collapsed else "◀")

        if self._btn2 is not None:
            collapsed2 = sizes[self._secondary_collapse_index] == 0
            self._btn2.setText("◀" if collapsed2 else "▶") if self._secondary_collapse_index == 1 \
                else self._btn2.setText("▶" if collapsed2 else "◀")

    def _toggle_index(self, collapse_idx: int, saved_attr: str):
        splitter = self.splitter()
        sizes = splitter.sizes()
        total = sum(sizes)
        saved = getattr(self, saved_attr)
        if sizes[collapse_idx] == 0:
            restored = saved or [total * 58 // 100, total * 42 // 100]
            splitter.setSizes(restored)
            setattr(self, saved_attr, None)
        else:
            setattr(self, saved_attr, list(sizes))
            splitter.setSizes([0, total] if collapse_idx == 0 else [total, 0])
        self._sync_arrow()

    def _toggle(self):
        self._toggle_index(self._collapse_index, '_saved_sizes')

    def _toggle2(self):
        self._toggle_index(self._secondary_collapse_index, '_saved_sizes2')


class _CollapsibleSplitter(QSplitter):
    """버튼으로 한 패널을 접을 수 있는 QSplitter."""

    def __init__(self, orientation, collapse_index: int = 1,
                 secondary_collapse_index: int | None = None, parent=None):
        super().__init__(orientation, parent)
        self._collapse_index = collapse_index
        self._secondary_collapse_index = secondary_collapse_index
        self.setHandleWidth(16)

    def createHandle(self):
        return _CollapseHandle(self.orientation(), self, self._collapse_index,
                               self._secondary_collapse_index)

    def toggle(self):
        h = self.handle(1)
        if isinstance(h, _CollapseHandle):
            h._toggle()


# ── QWebEnginePage: 외부 링크 + 클립보드 ──────────────────────────────────────

class _LinkPage(QWebEnginePage):
    """외부 링크 → 시스템 브라우저, __COPY__ → 클립보드"""

    def acceptNavigationRequest(self, url, nav_type, is_main):
        if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main)

    def javaScriptConsoleMessage(self, level, message, line, source):
        if message.startswith("__COPY__:"):
            QApplication.clipboard().setText(message[len("__COPY__:"):])


class _ViewerLinkPage(_LinkPage):
    """노트북 뷰어 전용 — 셀 선택 변경 알림(__SEL_CHANGED__)을 NotebookTab으로 전달."""

    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self._tab = tab

    def javaScriptConsoleMessage(self, level, message, line, source):
        if message == "__SEL_CHANGED__":
            self._tab._on_viewer_selection_changed()
            return
        if message.startswith("__WORD_GRAPH__:"):
            self._tab._on_word_graph_requested(message[len("__WORD_GRAPH__:"):])
            return
        if message.startswith("__DEFINE__:"):
            self._tab._on_define_requested(message[len("__DEFINE__:"):])
            return
        if message.startswith("__EXPLAIN__:"):
            try:
                text = json.loads(message[len("__EXPLAIN__:"):])
            except Exception:
                text = message[len("__EXPLAIN__:"):]
            self._tab._on_explain_requested(text)
            return
        if message.startswith("__PASTE_INPUT__:"):
            try:
                text = json.loads(message[len("__PASTE_INPUT__:"):])
            except Exception:
                text = message[len("__PASTE_INPUT__:"):]
            self._tab._on_paste_to_input(text)
            return
        super().javaScriptConsoleMessage(level, message, line, source)


class _ChatLinkPage(_LinkPage):
    """채팅 웹뷰 전용 — __SAVE_NB__/__UNSAVE_NB__ 콘솔 메시지를 NotebookTab으로 전달."""

    def __init__(self, tab, parent=None):
        super().__init__(parent)
        self._tab = tab

    def javaScriptConsoleMessage(self, level, message, line, source):
        if message.startswith("__SAVE_NB__:"):
            self._tab._handle_save_request(message[len("__SAVE_NB__:"):])
            return
        if message.startswith("__UNSAVE_NB__:"):
            self._tab._handle_unsave_request(message[len("__UNSAVE_NB__:"):])
            return
        if message.startswith("__WORD_GRAPH__:"):
            self._tab._on_word_graph_requested(message[len("__WORD_GRAPH__:"):])
            return
        if message.startswith("__DEFINE__:"):
            self._tab._on_define_requested(message[len("__DEFINE__:"):])
            return
        if message.startswith("__EXPLAIN__:"):
            try:
                text = json.loads(message[len("__EXPLAIN__:"):])
            except Exception:
                text = message[len("__EXPLAIN__:"):]
            self._tab._on_explain_requested(text)
            return
        if message.startswith("__PASTE_INPUT__:"):
            try:
                text = json.loads(message[len("__PASTE_INPUT__:"):])
            except Exception:
                text = message[len("__PASTE_INPUT__:"):]
            self._tab._on_paste_to_input(text)
            return
        super().javaScriptConsoleMessage(level, message, line, source)


# ── 자동 확장 텍스트 입력 (ChatTab과 동일 패턴) ──────────────────────────────

class _AutoExpandingEdit(QPlainTextEdit):
    """Enter 전송, Shift+Enter 줄바꿈. 최대 4줄까지 자동 확장."""
    returnPressed = pyqtSignal()

    _MIN_HEIGHT = 36
    _MAX_HEIGHT = 144

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("선택한 셀에 대해 질문하세요…")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self._MIN_HEIGHT)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.document().contentsChanged.connect(self._adjust_height)
        self._history: list[str] = []
        self._hist_idx: int = -1
        self._draft: str = ""
        self._history_file: Path | None = None

    def showEvent(self, event):
        super().showEvent(event)
        line_h = self.fontMetrics().lineSpacing()
        if line_h >= 8:
            margins = self.contentsMargins()
            v_pad = margins.top() + margins.bottom() + 4
            self._MIN_HEIGHT = line_h + v_pad
            self._MAX_HEIGHT = line_h * 4 + v_pad
            self.setFixedHeight(self._MIN_HEIGHT)

    def _adjust_height(self):
        doc = self.document()
        total_lines = 0
        block = doc.begin()
        while block.isValid():
            layout = block.layout()
            count = layout.lineCount() if layout else 0
            total_lines += count if count > 0 else 1
            block = block.next()
        total_lines = max(1, total_lines)

        line_h = self.fontMetrics().lineSpacing()
        margins = self.contentsMargins()
        new_h = line_h * total_lines + margins.top() + margins.bottom() + 4
        new_h = max(self._MIN_HEIGHT, min(new_h, self._MAX_HEIGHT))
        self.setFixedHeight(new_h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._adjust_height()

    def set_history_file(self, path: Path) -> None:
        self._history_file = path
        try:
            if path.exists():
                self._history = json.loads(path.read_text(encoding="utf-8"))
                self._hist_idx = -1
                self._draft = ""
        except Exception:
            self._history = []

    def add_to_history(self, text: str) -> None:
        text = text.strip()
        if not text or text.startswith('[자동 설명 요청]'):
            return
        if self._history and self._history[-1] == text:
            return
        self._history.append(text)
        if len(self._history) > 100:
            self._history = self._history[-100:]
        self._hist_idx = -1
        self._draft = ""
        if self._history_file:
            try:
                self._history_file.parent.mkdir(parents=True, exist_ok=True)
                self._history_file.write_text(
                    json.dumps(self._history, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
            except Exception:
                pass

    def _is_on_first_line(self) -> bool:
        return self.textCursor().blockNumber() == 0

    def _is_on_last_line(self) -> bool:
        return self.textCursor().blockNumber() == self.document().lastBlock().blockNumber()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.returnPressed.emit()
            return

        if key == Qt.Key.Key_Up:
            if not self._history:
                super().keyPressEvent(event)
                return
            if self._hist_idx == -1:
                self._draft = self.toPlainText()
                self._hist_idx = len(self._history) - 1
            elif self._hist_idx > 0:
                self._hist_idx -= 1
            self.setPlainText(self._history[self._hist_idx])
            c = self.textCursor(); c.movePosition(c.MoveOperation.End); self.setTextCursor(c)
            return

        if key == Qt.Key.Key_Down:
            if self._hist_idx == -1:
                super().keyPressEvent(event)
                return
            if self._hist_idx < len(self._history) - 1:
                self._hist_idx += 1
                self.setPlainText(self._history[self._hist_idx])
            else:
                self._hist_idx = -1
                self.setPlainText(self._draft)
                self._draft = ""
            c = self.textCursor(); c.movePosition(c.MoveOperation.End); self.setTextCursor(c)
            return

        super().keyPressEvent(event)


# ── 색상 상수 ────────────────────────────────────────────────────────────────

_SUMMARIZED_COLOR = QColor("#60a5fa")
_STALE_COLOR      = QColor("#f59e0b")
_DEFAULT_COLOR    = QColor("#e2e8f0")


# ── 자동 설명 (auto-explain) 상수 ─────────────────────────────────────────────

_AUTO_EXPLAIN_SENTINEL = "__AUTO_EXPLAIN__"
_AUTO_EXPLAIN_DISPLAY  = "[자동 설명 요청]"
_AUTO_EXPLAIN_QUESTION = (
    "선택된 셀들을 학습자가 이해할 수 있도록 한국어로 단계별로 자세히 설명해 주세요. "
    "코드라면 동작 원리·핵심 개념·사용 예시를, 마크다운이라면 의도와 맥락을 설명해 주세요."
)


# ── NotebookTab ──────────────────────────────────────────────────────────────

class NotebookTab(QWidget):
    summary_requested        = pyqtSignal(dict)   # {name: [cells]}
    stop_requested           = pyqtSignal()
    notebook_chat_requested  = pyqtSignal(str, list, str, str, list)
    # (question, selected_cells, notebook_name, summary, conversation_history)
    notebook_chat_stop       = pyqtSignal()
    cache_updated            = pyqtSignal()       # 캐시 저장/삭제 시 emit (CachedResponsesTab refresh용)

    def __init__(self):
        super().__init__()
        self._cells: list[dict] = []
        self._summaries: dict[str, str] = {}
        self._summary_prompt_hashes: dict[str, str] = {}  # name → 해당 요약 생성에 쓰인 프롬프트 md5
        self._stale_summaries: set[str] = set()
        self._cache_dir: str = ".rag_cache"
        self._current_nb: str = ""
        self._summary_font_size = 13
        self._viewer_font_size = 13
        self._chat_font_size = 13
        self._summary_page_ready = False
        self._summary_view_dirty = False
        self._viewer_page_ready = False
        self._chat_page_ready = False
        self._selection_mode = False
        self._is_streaming = False
        self._chat_history: list[dict] = []     # [{role, content}]
        self._pending_chat_question: str = ""   # 요약 자동생성 후 대기 중인 질문
        self._pending_chat_cells: list[dict] = []
        self._last_chat_question: str = ""      # 히스토리에 저장할 직전 질문
        self._pending_nb_name: str = ""         # 진행 중인 채팅의 노트북 이름 (캐시 저장용)
        self._pending_cell_indices: list = []   # 진행 중인 채팅의 선택 셀 (캐시 저장용)
        self._recent_messages: dict = {}        # message_id → {nb, question, answer, cell_indices}
        self._context_mode: str = "summary"     # "summary" | "full"
        self._history_cache: NotebookChatCache | None = None  # set_cache_dir에서 초기화
        self._pending_restore_nb: str = ""                     # 페이지 로드 전 복원 대기 노트북
        self._stt_language = "ko"
        self._recorder   = None
        self._stt_worker = None
        self._build_ui()
        self._setup_prompt_watcher()

    # ── UI 빌드 ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(8)

        # ── 메인 스플리터 (좌: 목록 | 우: 콘텐츠) ────────────────────────────
        self._list_splitter = _CollapsibleSplitter(Qt.Orientation.Horizontal, collapse_index=0)
        self._list_splitter.setStyleSheet(
            "QSplitter::handle { background: #2a3045; }"
        )

        # ── 좌측 패널: 체크박스 목록 + 요약 버튼 ────────────────────────────
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(6)

        select_all_row = QHBoxLayout()
        select_all_row.setContentsMargins(0, 0, 0, 0)
        select_all_row.setSpacing(6)
        self.select_all_cb = QCheckBox("전체선택")
        self.select_all_cb.setStyleSheet(
            "QCheckBox { color: #94a3b8; font-size: 11px; }"
            "QCheckBox::indicator { width: 14px; height: 14px; }"
        )
        self.select_all_cb.stateChanged.connect(self._on_select_all)
        self.selected_count_label = QLabel("0개 선택")
        self.selected_count_label.setStyleSheet("color: #64748b; font-size: 10px;")
        select_all_row.addWidget(self.select_all_cb)
        select_all_row.addWidget(self.selected_count_label)
        select_all_row.addStretch()
        left_layout.addLayout(select_all_row)

        legend = QLabel("🔵 요약 완료  🟡 이전 프롬프트")
        legend.setStyleSheet("color: #64748b; font-size: 10px;")
        left_layout.addWidget(legend)

        self.nb_list = QListWidget()
        self.nb_list.setStyleSheet(
            "QListWidget { background: #0d0f14; border: 1px solid #2a3045; "
            "border-radius: 6px; color: #e2e8f0; font-size: 11px; }"
            "QListWidget::item { padding: 4px 6px; }"
            "QListWidget::item:selected { background: #1e2330; color: #93c5fd; }"
            "QListWidget::item:hover { background: #161922; }"
        )
        self.nb_list.itemClicked.connect(self._on_item_clicked)
        self.nb_list.itemChanged.connect(self._on_item_check_changed)
        left_layout.addWidget(self.nb_list)

        self.generate_btn = QPushButton("📝 요약 생성")
        self.generate_btn.setStyleSheet(_BTN_STYLE)
        self.generate_btn.clicked.connect(self._on_generate_click)
        left_layout.addWidget(self.generate_btn)

        self.edit_prompt_btn = QPushButton("✏️ 프롬프트 편집")
        self.edit_prompt_btn.setStyleSheet(_BTN_STYLE)
        self.edit_prompt_btn.setToolTip("prompts/summary_prompt.txt를 텍스트 에디터로 엽니다")
        self.edit_prompt_btn.clicked.connect(self._on_edit_prompt)
        left_layout.addWidget(self.edit_prompt_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet(
            "QProgressBar { background: #1e2330; border: 1px solid #2a3045; "
            "border-radius: 4px; text-align: center; color: #e2e8f0; "
            "font-size: 10px; height: 18px; }"
            "QProgressBar::chunk { background: #4f8ef7; border-radius: 3px; }"
        )
        self.progress_bar.hide()
        left_layout.addWidget(self.progress_bar)

        self.stop_btn = QPushButton("⏹️ 중지")
        self.stop_btn.setStyleSheet(_STOP_BTN_STYLE)
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        self.stop_btn.hide()
        left_layout.addWidget(self.stop_btn)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #64748b; font-size: 10px;")
        self.status_label.setWordWrap(True)
        left_layout.addWidget(self.status_label)

        self._list_splitter.addWidget(left_panel)

        # ── 우측 패널: 셀+채팅 / 요약 보기 ──────────────────────────────────
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(6)

        # 뷰 전환 버튼
        toggle_row = QHBoxLayout()
        self.outline_view_btn = QPushButton("아웃라인")
        self.outline_view_btn.setStyleSheet(_TOGGLE_ACTIVE)
        self.outline_view_btn.clicked.connect(lambda: self._switch_view(0))

        self.summary_view_btn = QPushButton("요약 보기")
        self.summary_view_btn.setStyleSheet(_TOGGLE_INACTIVE)
        self.summary_view_btn.clicked.connect(lambda: self._switch_view(1))

        self.cell_view_btn = QPushButton("셀 보기")
        self.cell_view_btn.setStyleSheet(_TOGGLE_INACTIVE)
        self.cell_view_btn.clicked.connect(lambda: self._switch_view(2))

        toggle_row.addWidget(self.outline_view_btn)
        toggle_row.addWidget(self.summary_view_btn)
        toggle_row.addWidget(self.cell_view_btn)
        toggle_row.addStretch()

        self.selection_mode_btn = QPushButton("☑ 선택 모드")
        self.selection_mode_btn.setStyleSheet(_TOGGLE_INACTIVE)
        self.selection_mode_btn.setCheckable(True)
        self.selection_mode_btn.clicked.connect(self._on_selection_mode_toggled)
        toggle_row.addWidget(self.selection_mode_btn)

        self.chat_toggle_btn = QPushButton("💬 Q&A")
        self.chat_toggle_btn.setStyleSheet(_TOGGLE_INACTIVE)
        self.chat_toggle_btn.clicked.connect(self._toggle_chat_panel)
        toggle_row.addWidget(self.chat_toggle_btn)

        right_layout.addLayout(toggle_row)

        # 스택 위젯 (아웃라인 뷰 / 요약 뷰 / 셀 뷰)
        self.view_stack = QStackedWidget()

        # --- [0] 아웃라인 뷰 ---
        self._build_outline_view()
        self.view_stack.addWidget(self.outline_tree)

        # --- [1] 요약 보기 ---
        self.summary_web = QWebEngineView()
        self.summary_web.setPage(_LinkPage(self.summary_web))
        self.summary_web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        if getattr(sys, "frozen", False):
            _base = Path(sys._MEIPASS)
        else:
            _base = Path(__file__).parent.parent
        html_path = _base / "resources" / "summary.html"
        self.summary_web.setUrl(QUrl.fromLocalFile(str(html_path.resolve())))
        self.summary_web.loadFinished.connect(self._on_summary_page_loaded)
        self.view_stack.addWidget(self.summary_web)

        # --- [2] 셀 뷰 (뷰어만, 채팅 패널은 content_splitter에서 공유) ---
        self._build_viewer_web()
        self.view_stack.addWidget(self.viewer_web)

        # view_stack + 공유 채팅 패널을 수평 스플리터로 묶기
        self._content_splitter = _CollapsibleSplitter(Qt.Orientation.Horizontal, collapse_index=1, secondary_collapse_index=0)
        self._content_splitter.setStyleSheet("QSplitter::handle { background: #2a3045; }")
        self._content_splitter.addWidget(self.view_stack)
        self._build_chat_panel()   # self._content_splitter에 chat_panel 추가
        self._content_splitter.setSizes([1000, 0])   # 기본: 채팅 접힘

        right_layout.addWidget(self._content_splitter)
        self._list_splitter.addWidget(right_panel)

        self._list_splitter.setSizes([220, 780])
        layout.addWidget(self._list_splitter, 1)

        # 단축키
        QShortcut(QKeySequence("Ctrl+="), self).activated.connect(self._zoom_in)
        QShortcut(QKeySequence("Ctrl++"), self).activated.connect(self._zoom_in)
        QShortcut(QKeySequence("Ctrl+-"), self).activated.connect(self._zoom_out)
        QShortcut(QKeySequence("Ctrl+0"), self).activated.connect(self._zoom_reset)

    def _build_outline_view(self):
        """아웃라인 트리 위젯 생성"""
        self.outline_tree = QTreeWidget()
        self.outline_tree.setHeaderHidden(True)
        self.outline_tree.setIndentation(16)
        self.outline_tree.setStyleSheet(_OUTLINE_TREE_STYLE)
        self.outline_tree.itemClicked.connect(self._on_outline_item_single_clicked)
        self.outline_tree.itemDoubleClicked.connect(self._on_outline_item_double_clicked)
        self.outline_tree.itemChanged.connect(self._on_outline_item_check_changed)
        self._suppress_outline_check = False
        self._just_toggled_outline_check = False
        self._outline_items: list[QTreeWidgetItem] = []
        self._outline_max_idx: int = -1
        placeholder = QTreeWidgetItem(["노트북을 선택하세요."])
        placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
        self.outline_tree.addTopLevelItem(placeholder)

    def _render_outline(self, nb_name: str):
        """마크다운 셀에서 헤더를 파싱해 아웃라인 트리를 구성"""
        import re
        self._suppress_outline_check = True
        try:
            self.outline_tree.clear()
            self._outline_items = []
            nb_cells = sorted(
                [c for c in self._cells if c["notebook"] == nb_name],
                key=lambda x: x["cell_idx"]
            )
            self._outline_max_idx = nb_cells[-1]["cell_idx"] if nb_cells else -1
            header_re = re.compile(r'^(#{1,6})\s+(.+)', re.MULTILINE)
            # (level, QTreeWidgetItem) 스택으로 계층 추적
            stack: list[tuple[int, QTreeWidgetItem]] = []

            level_colors = {1: "#93c5fd", 2: "#c4b5fd", 3: "#86efac",
                            4: "#fde68a", 5: "#fca5a5", 6: "#94a3b8"}

            # 1단계: 모든 헤더를 평면 리스트로 수집 (level, start_idx, item)
            flat_headers: list[tuple[int, int, QTreeWidgetItem]] = []

            for cell in nb_cells:
                if cell["cell_type"] != "markdown":
                    continue
                for m in header_re.finditer(cell["source"]):
                    level = len(m.group(1))
                    text = m.group(2).strip()
                    prefix = "#" * level + " "
                    item = QTreeWidgetItem([prefix + text])
                    item.setData(0, Qt.ItemDataRole.UserRole, cell["cell_idx"])
                    item.setToolTip(0, text)
                    color = level_colors.get(level, "#94a3b8")
                    item.setForeground(0, QColor(color))
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(0, Qt.CheckState.Unchecked)

                    while stack and stack[-1][0] >= level:
                        stack.pop()

                    if stack:
                        stack[-1][1].addChild(item)
                    else:
                        self.outline_tree.addTopLevelItem(item)

                    stack.append((level, item))
                    flat_headers.append((level, cell["cell_idx"], item))
                    self._outline_items.append(item)

            # 2단계: 각 헤더의 end_idx 계산 (다음 동급/상위 헤더 직전 셀까지)
            n = len(flat_headers)
            for i, (level, start_idx, item) in enumerate(flat_headers):
                end_idx = self._outline_max_idx
                for j in range(i + 1, n):
                    nlevel, nstart, _ = flat_headers[j]
                    if nlevel <= level:
                        end_idx = nstart - 1
                        break
                item.setData(0, Qt.ItemDataRole.UserRole + 1, end_idx)

            self.outline_tree.expandAll()

            if self.outline_tree.topLevelItemCount() == 0:
                placeholder = QTreeWidgetItem(["(마크다운 헤더 없음)"])
                placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
                self.outline_tree.addTopLevelItem(placeholder)
        finally:
            self._suppress_outline_check = False
        self._apply_outline_selection_mode()

    def _on_outline_item_single_clicked(self, item: QTreeWidgetItem, col: int):
        """아웃라인 항목 단일 클릭 → 자식이 있으면 expand/collapse 토글.
        체크박스 클릭은 itemChanged 직후 itemClicked가 따라오므로 플래그로 무시."""
        if self._just_toggled_outline_check:
            self._just_toggled_outline_check = False
            return
        if item.childCount() > 0:
            item.setExpanded(not item.isExpanded())

    def _on_outline_item_double_clicked(self, item: QTreeWidgetItem, col: int):
        """아웃라인 항목 더블 클릭 → 셀 보기로 전환 후 해당 셀로 스크롤."""
        cell_idx = item.data(0, Qt.ItemDataRole.UserRole)
        if cell_idx is None:
            return
        self._switch_view(2)
        self._run_viewer_js(f"scrollToCell({cell_idx})")

    def _on_outline_item_check_changed(self, item: QTreeWidgetItem, col: int):
        """아웃라인 체크박스 토글 → 해당 섹션 셀 일괄 선택/해제."""
        if self._suppress_outline_check:
            return
        # 사용자가 체크박스를 직접 토글했음을 표시 → 뒤따르는 itemClicked의 스크롤 억제
        self._just_toggled_outline_check = True
        start = item.data(0, Qt.ItemDataRole.UserRole)
        end = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if start is None or end is None:
            return
        state = item.checkState(0)
        # PartiallyChecked는 사용자가 직접 만들 수 없지만 안전하게 Checked로 처리
        checked = state != Qt.CheckState.Unchecked
        js_bool = "true" if checked else "false"
        self._run_viewer_js(f"setRangeChecked({int(start)}, {int(end)}, {js_bool})")
        # 셀 상태 변경 후 모든 아웃라인 트리스테이트 갱신
        self._refresh_outline_check_states()

    def _refresh_outline_check_states(self):
        """뷰어 체크박스 현황을 읽어 각 아웃라인 항목의 트리스테이트를 갱신."""
        if not self._outline_items or not self._selection_mode:
            return
        self._run_viewer_js("getAllCheckedIndices()", self._apply_outline_check_states)

    def _apply_outline_check_states(self, result):
        try:
            checked_list = json.loads(result) if result else []
        except (TypeError, ValueError):
            checked_list = []
        checked_set = set(int(x) for x in checked_list)
        self._suppress_outline_check = True
        try:
            for item in self._outline_items:
                start = item.data(0, Qt.ItemDataRole.UserRole)
                end = item.data(0, Qt.ItemDataRole.UserRole + 1)
                if start is None or end is None:
                    continue
                total = 0
                on = 0
                for idx in range(int(start), int(end) + 1):
                    total += 1
                    if idx in checked_set:
                        on += 1
                if total == 0 or on == 0:
                    new_state = Qt.CheckState.Unchecked
                elif on == total:
                    new_state = Qt.CheckState.Checked
                else:
                    new_state = Qt.CheckState.PartiallyChecked
                if item.checkState(0) != new_state:
                    item.setCheckState(0, new_state)
        finally:
            self._suppress_outline_check = False

    def _apply_outline_selection_mode(self):
        """선택 모드에 따라 아웃라인 항목의 체크박스 표시/숨김을 토글."""
        if not self._outline_items:
            return
        self._suppress_outline_check = True
        try:
            for item in self._outline_items:
                flags = item.flags()
                if self._selection_mode:
                    item.setFlags(flags | Qt.ItemFlag.ItemIsUserCheckable)
                    if item.data(0, Qt.ItemDataRole.CheckStateRole) is None:
                        item.setCheckState(0, Qt.CheckState.Unchecked)
                else:
                    item.setFlags(flags & ~Qt.ItemFlag.ItemIsUserCheckable)
                    item.setData(0, Qt.ItemDataRole.CheckStateRole, None)
        finally:
            self._suppress_outline_check = False

    def _on_selection_mode_toggled(self):
        self._selection_mode = not self._selection_mode
        self.selection_mode_btn.setChecked(self._selection_mode)
        self.selection_mode_btn.setStyleSheet(
            _TOGGLE_ACTIVE if self._selection_mode else _TOGGLE_INACTIVE
        )
        js_bool = "true" if self._selection_mode else "false"
        self._run_viewer_js(f"setSelectionMode({js_bool})")
        self._apply_outline_selection_mode()

    def _on_viewer_selection_changed(self):
        """뷰어에서 셀 체크 상태 변경 통지 → 아웃라인 트리스테이트 갱신."""
        if not self._outline_items:
            return
        self._refresh_outline_check_states()

    def _build_viewer_web(self):
        """셀 뷰어 QWebEngineView 생성 (채팅 패널은 _build_chat_panel에서 별도 생성)"""
        if getattr(sys, "frozen", False):
            _base = Path(sys._MEIPASS)
        else:
            _base = Path(__file__).parent.parent

        self.viewer_web = QWebEngineView()
        self.viewer_web.setPage(_ViewerLinkPage(self, self.viewer_web))
        self.viewer_web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        viewer_html = _base / "resources" / "notebook_viewer.html"
        self.viewer_web.setUrl(QUrl.fromLocalFile(str(viewer_html.resolve())))
        self.viewer_web.loadFinished.connect(self._on_viewer_page_loaded)

    def _build_chat_panel(self):
        """공유 채팅 패널 생성 후 self._content_splitter에 추가"""
        if getattr(sys, "frozen", False):
            _base = Path(sys._MEIPASS)
        else:
            _base = Path(__file__).parent.parent

        chat_panel = QWidget()
        chat_layout = QVBoxLayout(chat_panel)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(4)

        # 채팅 헤더
        chat_header = QLabel("💬 셀 Q&A")
        chat_header.setStyleSheet(
            "color: #e2e8f0; font-size: 12px; font-weight: 600; "
            "padding: 4px 8px; background: #111827; "
            "border: 1px solid #2a3045; border-radius: 6px 6px 0 0;"
        )
        chat_layout.addWidget(chat_header)

        # 컨텍스트 모드 토글 (요약 모드 / 전체 모드)
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(4)
        mode_label = QLabel("컨텍스트:")
        mode_label.setStyleSheet("color: #94a3b8; font-size: 11px; padding: 0 2px;")
        self.summary_mode_btn = QPushButton("요약 모드")
        self.summary_mode_btn.setStyleSheet(_TOGGLE_ACTIVE)
        self.summary_mode_btn.clicked.connect(lambda: self._set_context_mode("summary"))
        self.full_mode_btn = QPushButton("전체 모드")
        self.full_mode_btn.setStyleSheet(_TOGGLE_INACTIVE)
        self.full_mode_btn.clicked.connect(lambda: self._set_context_mode("full"))
        mode_row.addWidget(mode_label)
        mode_row.addWidget(self.summary_mode_btn)
        mode_row.addWidget(self.full_mode_btn)
        mode_row.addStretch()
        chat_layout.addLayout(mode_row)

        # 채팅 디스플레이 (QWebEngineView) — 저장 버튼 콘솔 메시지를 받기 위해 _ChatLinkPage 사용
        self.chat_web = QWebEngineView()
        self.chat_web.setPage(_ChatLinkPage(self, self.chat_web))
        self.chat_web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        chat_html = _base / "resources" / "notebook_chat.html"
        self.chat_web.setUrl(QUrl.fromLocalFile(str(chat_html.resolve())))
        self.chat_web.loadFinished.connect(self._on_chat_page_loaded)
        chat_layout.addWidget(self.chat_web, 1)

        # 채팅 상태 레이블
        self.chat_status = QLabel("")
        self.chat_status.setStyleSheet("color: #64748b; font-size: 10px; padding: 0 4px;")
        self.chat_status.hide()
        chat_layout.addWidget(self.chat_status)

        # 입력 영역
        input_row = QHBoxLayout()
        input_row.setSpacing(4)

        self.chat_input = _AutoExpandingEdit()
        self.chat_input.setStyleSheet(
            "QPlainTextEdit { background: #111827; color: #e2e8f0; "
            "border: 1px solid #2a3045; border-radius: 6px; "
            "padding: 6px 8px; font-size: 12px; "
            "font-family: 'Pretendard','Malgun Gothic',sans-serif; }"
            "QPlainTextEdit:focus { border-color: #4f8ef7; }"
        )
        self.chat_input.returnPressed.connect(self._on_chat_send)
        input_row.addWidget(self.chat_input)

        self.mic_btn = STTButton()
        self.mic_btn.record_start.connect(self._on_mic_start)
        self.mic_btn.record_stop.connect(self._on_mic_stop)
        input_row.addWidget(self.mic_btn)

        self.send_btn = QPushButton("전송")
        self.send_btn.setStyleSheet(_SEND_BTN_STYLE)
        self.send_btn.setFixedWidth(60)
        self.send_btn.clicked.connect(self._on_chat_send)
        input_row.addWidget(self.send_btn)

        chat_layout.addLayout(input_row)

        # 채팅 초기화 버튼
        clear_row = QHBoxLayout()
        clear_row.addStretch()
        self.clear_chat_btn = QPushButton("🗑 대화 초기화")
        self.clear_chat_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #64748b; border: none; "
            "font-size: 10px; padding: 2px 6px; }"
            "QPushButton:hover { color: #94a3b8; }"
        )
        self.clear_chat_btn.clicked.connect(self._on_clear_chat)
        clear_row.addWidget(self.clear_chat_btn)
        chat_layout.addLayout(clear_row)

        self._content_splitter.addWidget(chat_panel)

    # ── 페이지 로드 콜백 ─────────────────────────────────────────────────────

    def _on_viewer_page_loaded(self, ok: bool):
        if ok:
            self._viewer_page_ready = True
            js_bool = "true" if self._selection_mode else "false"
            self._run_viewer_js(f"setSelectionMode({js_bool})")
            if self._current_nb:
                self._render_notebook(self._current_nb)

    def _on_chat_page_loaded(self, ok: bool):
        if ok:
            self._chat_page_ready = True
            if self._pending_restore_nb:
                nb = self._pending_restore_nb
                self._pending_restore_nb = ""
                self._restore_notebook_chat(nb)

    def _on_summary_page_loaded(self, ok: bool):
        if ok:
            self._summary_page_ready = True
            self._run_summary_js(f"setFontSize({self._summary_font_size})")
            self._rebuild_summary_view()

    # ── JS 실행 헬퍼 ─────────────────────────────────────────────────────────

    def _run_viewer_js(self, script: str, callback=None):
        if self._viewer_page_ready:
            if callback:
                self.viewer_web.page().runJavaScript(script, callback)
            else:
                self.viewer_web.page().runJavaScript(script)

    def _run_chat_js(self, script: str):
        if self._chat_page_ready:
            self.chat_web.page().runJavaScript(script)

    def _run_summary_js(self, script: str):
        if self._summary_page_ready:
            self.summary_web.page().runJavaScript(script)

    # ── 줌 ───────────────────────────────────────────────────────────────────

    def _zoom_in(self):
        idx = self.view_stack.currentIndex()
        if idx == 2:
            if self._viewer_font_size < 24:
                self._viewer_font_size += 1
                self._run_viewer_js(f"setFontSize({self._viewer_font_size})")
            if self._chat_font_size < 24:
                self._chat_font_size += 1
                self._run_chat_js(f"setFontSize({self._chat_font_size})")
        elif idx == 1:
            if self._summary_font_size < 24:
                self._summary_font_size += 1
                self._run_summary_js(f"setFontSize({self._summary_font_size})")

    def _zoom_out(self):
        idx = self.view_stack.currentIndex()
        if idx == 2:
            if self._viewer_font_size > 8:
                self._viewer_font_size -= 1
                self._run_viewer_js(f"setFontSize({self._viewer_font_size})")
            if self._chat_font_size > 8:
                self._chat_font_size -= 1
                self._run_chat_js(f"setFontSize({self._chat_font_size})")
        elif idx == 1:
            if self._summary_font_size > 8:
                self._summary_font_size -= 1
                self._run_summary_js(f"setFontSize({self._summary_font_size})")

    def _zoom_reset(self):
        idx = self.view_stack.currentIndex()
        if idx == 2:
            self._viewer_font_size = 13
            self._chat_font_size = 13
            self._run_viewer_js("setFontSize(13)")
            self._run_chat_js("setFontSize(13)")
        elif idx == 1:
            self._summary_font_size = 13
            self._run_summary_js("setFontSize(13)")

    # ── 뷰 전환 ──────────────────────────────────────────────────────────────

    def _switch_view(self, idx: int):
        self.view_stack.setCurrentIndex(idx)
        self.outline_view_btn.setStyleSheet(
            _TOGGLE_ACTIVE if idx == 0 else _TOGGLE_INACTIVE
        )
        self.summary_view_btn.setStyleSheet(
            _TOGGLE_ACTIVE if idx == 1 else _TOGGLE_INACTIVE
        )
        self.cell_view_btn.setStyleSheet(
            _TOGGLE_ACTIVE if idx == 2 else _TOGGLE_INACTIVE
        )
        if idx == 1 and self._summary_page_ready and self._summary_view_dirty:
            self._rebuild_summary_view()

    def _toggle_chat_panel(self):
        """Q&A 버튼 클릭 시 채팅 패널 펼침/접힘 토글"""
        sizes = self._content_splitter.sizes()
        total = sum(sizes)
        if total == 0:
            return
        if sizes[1] == 0:
            self._content_splitter.setSizes([total * 58 // 100, total * 42 // 100])
        else:
            self._content_splitter.setSizes([total, 0])

    def _set_context_mode(self, mode: str):
        """채팅 컨텍스트 모드 전환 ('summary' | 'full')."""
        if mode not in ("summary", "full"):
            return
        self._context_mode = mode
        self.summary_mode_btn.setStyleSheet(
            _TOGGLE_ACTIVE if mode == "summary" else _TOGGLE_INACTIVE
        )
        self.full_mode_btn.setStyleSheet(
            _TOGGLE_ACTIVE if mode == "full" else _TOGGLE_INACTIVE
        )

    # ── 체크박스 로직 (좌측 노트북 목록) ─────────────────────────────────────

    def _on_select_all(self, state):
        check = Qt.CheckState.Checked if state else Qt.CheckState.Unchecked
        self.nb_list.blockSignals(True)
        for i in range(self.nb_list.count()):
            self.nb_list.item(i).setCheckState(check)
        self.nb_list.blockSignals(False)
        self._update_generate_btn_label()
        self._update_selected_count_label()
        self._rebuild_summary_view()

    def _on_item_check_changed(self, _item):
        self._update_generate_btn_label()
        self._rebuild_summary_view()
        total = self.nb_list.count()
        checked = sum(
            1 for i in range(total)
            if self.nb_list.item(i).checkState() == Qt.CheckState.Checked
        )
        self.select_all_cb.blockSignals(True)
        if checked == total:
            self.select_all_cb.setCheckState(Qt.CheckState.Checked)
        elif checked == 0:
            self.select_all_cb.setCheckState(Qt.CheckState.Unchecked)
        else:
            self.select_all_cb.setCheckState(Qt.CheckState.PartiallyChecked)
        self.select_all_cb.blockSignals(False)
        self.selected_count_label.setText(f"{checked}개 선택")

    def _update_selected_count_label(self):
        count = sum(
            1 for i in range(self.nb_list.count())
            if self.nb_list.item(i).checkState() == Qt.CheckState.Checked
        )
        self.selected_count_label.setText(f"{count}개 선택")

    def _get_checked_names(self) -> list[str]:
        names = []
        for i in range(self.nb_list.count()):
            item = self.nb_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                names.append(item.text())
        return names

    def _update_generate_btn_label(self):
        checked = self._get_checked_names()
        to_gen = [
            n for n in checked
            if n not in self._summaries or n in self._stale_summaries
        ]
        if to_gen:
            self.generate_btn.setText(f"📝 요약 생성 ({len(to_gen)}개)")
        else:
            self.generate_btn.setText("📝 요약 생성")

    # ── 디스크 캐시 ─────────────────────────────────────────────────────────

    def set_cache_dir(self, path: str):
        self._cache_dir = path
        self.chat_input.set_history_file(Path(path) / "notebook_chat_input_history.json")
        self._history_cache = NotebookChatCache(path, "notebook_chat_history.json")

    def _summary_cache_path(self) -> Path:
        return Path(self._cache_dir) / "summaries.json"

    def _get_nb_path(self, notebook_name: str) -> str | None:
        for c in self._cells:
            if c["notebook"] == notebook_name:
                return c.get("notebook_path")
        return None

    def _load_summary_cache(self):
        cache_path = self._summary_cache_path()
        if not cache_path.exists():
            return
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return

        from rag_core import get_file_md5, get_summary_prompt_hash
        current_prompt_hash = get_summary_prompt_hash()
        for name, entry in data.items():
            if name in self._summaries:
                continue
            nb_path = self._get_nb_path(name)
            if nb_path and os.path.exists(nb_path):
                current_hash = get_file_md5(nb_path)
                if entry.get("hash") == current_hash:
                    self._summaries[name] = entry["summary"]
                    entry_prompt_hash = entry.get("prompt_hash", "")
                    self._summary_prompt_hashes[name] = entry_prompt_hash
                    if entry_prompt_hash != current_prompt_hash:
                        self._stale_summaries.add(name)

    def _save_summary_to_cache(self, notebook_name: str, summary: str, prompt_hash: str):
        os.makedirs(self._cache_dir, exist_ok=True)
        cache_path = self._summary_cache_path()

        data: dict = {}
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        nb_path = self._get_nb_path(notebook_name)
        file_hash = ""
        if nb_path and os.path.exists(nb_path):
            from rag_core import get_file_md5
            file_hash = get_file_md5(nb_path)

        data[notebook_name] = {
            "hash": file_hash,
            "prompt_hash": prompt_hash,
            "summary": summary,
        }

        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── 프롬프트 파일 감시 (핫 리로드 + stale 재평가) ──────────────────────────

    _SUMMARY_PROMPT_PATH = "prompts/summary_prompt.txt"

    def _setup_prompt_watcher(self):
        """prompts/summary_prompt.txt 변경을 감시해 기존 요약들을 stale로 즉시 전환."""
        self._prompt_watcher = QFileSystemWatcher(self)
        if os.path.exists(self._SUMMARY_PROMPT_PATH):
            self._prompt_watcher.addPath(self._SUMMARY_PROMPT_PATH)
        self._prompt_watcher.fileChanged.connect(self._on_summary_prompt_changed)

    def _on_summary_prompt_changed(self, path: str):
        from rag_core import get_summary_prompt_hash
        current = get_summary_prompt_hash()
        for name in list(self._summaries.keys()):
            if self._summary_prompt_hashes.get(name, "") != current:
                self._stale_summaries.add(name)
            else:
                self._stale_summaries.discard(name)
        self._update_all_indicators()
        self._rebuild_summary_view()

        # atomic-rename 저장(VS Code 등) 시 watcher에서 경로가 탈락하므로 재등록
        if os.path.exists(path) and path not in self._prompt_watcher.files():
            self._prompt_watcher.addPath(path)

    # ── 시각적 표시 (요약 완료 색상) ──────────────────────────────────────────

    def _update_all_indicators(self):
        for i in range(self.nb_list.count()):
            item = self.nb_list.item(i)
            name = item.text()
            if name in self._stale_summaries:
                item.setForeground(_STALE_COLOR)
            elif name in self._summaries:
                item.setForeground(_SUMMARIZED_COLOR)
            else:
                item.setForeground(_DEFAULT_COLOR)

    def _update_item_indicator(self, notebook_name: str):
        for i in range(self.nb_list.count()):
            item = self.nb_list.item(i)
            if item.text() == notebook_name:
                if notebook_name in self._stale_summaries:
                    item.setForeground(_STALE_COLOR)
                else:
                    item.setForeground(_SUMMARIZED_COLOR)
                break

    # ── 아이템 클릭 → 셀 보기 ────────────────────────────────────────────────

    def _on_item_clicked(self, item: QListWidgetItem):
        nb = item.text()
        if nb and nb != self._current_nb:
            self._current_nb = nb
            self._render_outline(nb)
            self._render_notebook(nb)
            self._switch_view(0)
            # 노트북 전환 시 해당 노트북의 대화 이력 복원
            self._restore_notebook_chat(nb)

    # ── 요약 생성 ────────────────────────────────────────────────────────────

    def _on_edit_prompt(self):
        fp = Path("prompts/summary_prompt.txt")
        if not fp.exists():
            from rag_core import load_summary_prompt
            fp.write_text(load_summary_prompt(), encoding="utf-8")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(fp.resolve())))

    def _on_generate_click(self):
        checked = self._get_checked_names()
        to_generate = {}
        for name in checked:
            if name not in self._summaries or name in self._stale_summaries:
                nb_cells = sorted(
                    [c for c in self._cells if c["notebook"] == name],
                    key=lambda x: x["cell_idx"]
                )
                to_generate[name] = nb_cells

        if not to_generate:
            self._rebuild_summary_view()
            self._switch_view(1)
            return

        self.generate_btn.setEnabled(False)
        self.progress_bar.setMaximum(len(to_generate))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0/%m")
        self.progress_bar.show()
        self.stop_btn.show()
        self.status_label.setText("⏳ 요약 생성 중...")

        self.summary_requested.emit(to_generate)

    # ── 셀 채팅 ──────────────────────────────────────────────────────────────

    def _on_chat_send(self):
        if self._is_streaming:
            return
        raw = self.chat_input.toPlainText().strip()
        # 빈 입력이면 자동 설명 모드 sentinel 사용
        question = raw if raw else _AUTO_EXPLAIN_SENTINEL

        if raw:
            self.chat_input.add_to_history(raw)

        # 선택된 셀 가져오기 (비동기 JS 콜백)
        self._run_viewer_js("getSelectedCells()", lambda result: self._on_cells_selected(result, question))

    def _on_word_graph_requested(self, word: str):
        """더블클릭 + Ctrl+W로 선택된 단어의 연관 관계 분석 요청"""
        if self._is_streaming or not word or not self._current_nb:
            return
        question = (
            f"`{word}` 의 연관 관계 분석\n\n"
            f"`{word}` 를 중심으로 노트북 전체 흐름에서의 연관 관계를 설명해 주세요.\n\n"
            f"분석 방식:\n"
            f"- `{word}` 가 노트북에서 **처음 등장하는 지점**을 찾아 시작점으로 삼습니다\n"
            f"- `{word}` 가 중간에 등장한다면, 그것과 연결된 코드를 역으로 거슬러 올라가 **진짜 시작점**을 찾습니다\n"
            f"- `{word}` 가 마지막에 등장한다면, 그것을 만들어낸 코드를 역추적하여 **처음부터** 설명합니다\n"
            f"- 항상 **코드의 처음 시작점 → `{word}` 관련 중간 과정 → 최종 결과**의 흐름으로 설명합니다\n"
            f"- **같은 클래스·모듈·인터페이스에 속하거나 같은 데이터 구조를 다루는 형제 함수/변수**도 반드시 포함합니다\n"
            f"  (예: `search`를 분석할 때 같은 메모리 객체를 다루는 `put`, `get`, `delete` 등도 연관 관계에 포함)\n"
            f"- 직접 호출 관계뿐 아니라 **공통 컨텍스트(같은 객체 인스턴스, 같은 데이터, 같은 목적)**로 연결된 코드도 포함합니다\n"
            f"- 관련 변수·함수들의 연결 관계를 포함하여 전체 데이터 흐름을 빠짐없이 보여주세요\n"
            f"- **연관 관계는 반드시 화살표(→) 또는 Mermaid flowchart로 시각화**해 주세요\n"
            f"  (관계가 단순하면 화살표, 복잡하거나 분기·병합이 있으면 Mermaid flowchart 사용)"
        )
        self._run_viewer_js(
            "getSelectedCells()",
            lambda result: self._on_cells_selected(result, question)
        )

    def _on_define_requested(self, word: str):
        """더블클릭 + Ctrl+D로 선택된 단어의 Python 정의/문법 설명 요청"""
        if self._is_streaming or not word or not self._current_nb:
            return
        question = (
            f"`{word}` 정의 및 Python 문법 설명\n\n"
            f"**`{word}`** 의 정의와 Python 문법을 설명해 주세요.\n\n"
            f"다음 항목을 포함하세요:\n"
            f"- **정의**: `{word}` 가 무엇인지 한 문장으로 설명\n"
            f"- **Python 문법**: 선언/사용 방법 (코드 예시 포함)\n"
            f"- **주요 특징**: 언제, 왜 사용하는지\n"
            f"- **노트북 내 사용 예**: 현재 노트북에서 `{word}` 가 어떻게 사용되고 있는지"
        )
        self._run_viewer_js(
            "getSelectedCells()",
            lambda result: self._on_cells_selected(result, question)
        )

    def _on_explain_requested(self, text: str):
        """텍스트 선택 + Ctrl+S로 선택된 내용을 단계별로 상세 설명 요청"""
        if self._is_streaming or not text or not self._current_nb:
            return
        question = (
            f"선택된 내용 단계별 상세 설명\n\n"
            f"다음 내용을 노트북의 문맥 안에서 **아주 자세하게, 단계별(step-by-step)로** 설명해 주세요:\n\n"
            f"```\n{text}\n```\n\n"
            f"설명 형식:\n"
            f"- **Step 1 — 개요**: 이 코드/문장이 전체 흐름에서 어떤 역할을 하는지\n"
            f"- **Step 2 — 구성 요소 분석**: 각 부분(키워드·함수·변수·연산자 등)의 의미를 하나씩 분해\n"
            f"- **Step 3 — 실행 순서**: 코드라면 실행되는 순서를 줄 단위로 추적\n"
            f"- **Step 4 — 입력과 출력**: 무엇을 받아서 무엇을 반환/생성하는지\n"
            f"- **Step 5 — 노트북 문맥**: 앞뒤 셀과의 연결 — 이 부분이 왜 이 위치에 있는지\n"
            f"- **Step 6 — 핵심 포인트**: 처음 보는 사람이 놓치기 쉬운 점, 주의사항"
        )
        self._run_viewer_js(
            "getSelectedCells()",
            lambda result: self._on_cells_selected(result, question)
        )

    def _on_paste_to_input(self, text: str):
        """선택된 텍스트를 채팅 입력창에 삽입"""
        if not text:
            return
        self.chat_input.insertPlainText(text)
        self.chat_input.setFocus()

    def _on_cells_selected(self, result, question: str):
        """viewer JS에서 선택된 셀 데이터를 받은 후 처리"""
        try:
            selected = json.loads(result) if isinstance(result, str) else result
        except (json.JSONDecodeError, TypeError):
            selected = []

        nb_name = self._current_nb
        summary = self._summaries.get(nb_name, "")

        # 자동 설명 모드 판별: 화면에는 마커만, LLM에는 확장된 지시문
        is_auto = (question == _AUTO_EXPLAIN_SENTINEL)
        display_q = _AUTO_EXPLAIN_DISPLAY if is_auto else question
        llm_q     = _AUTO_EXPLAIN_QUESTION if is_auto else question

        # 채팅 UI에 사용자 메시지 표시
        if selected:
            cell_indices = [c.get("cell_idx", "?") for c in selected]
            ctx_text = f"선택된 셀: {', '.join(f'#{i}' for i in cell_indices)} ({nb_name})"
        elif self._context_mode == "full":
            ctx_text = f"전체 노트북 질문 ({nb_name})"
        else:
            ctx_text = f"요약 기반 질문 ({nb_name})"
        escaped_ctx = json.dumps(ctx_text)
        self._run_chat_js(f"showSelectedContext({escaped_ctx})")

        escaped_q = json.dumps(display_q)
        self._run_chat_js(f"appendUserMessage({escaped_q})")

        self.chat_input.clear()

        # 요약 모드에서 요약이 없으면 자동 생성 후 채팅
        # (전체 모드는 요약 불필요 → 바로 채팅)
        if self._context_mode == "summary" and not summary:
            self._pending_chat_question = llm_q
            self._pending_chat_cells = selected
            self._run_chat_js('showStatus("⏳ 노트북 요약 생성 중...")')
            self._auto_generate_summary(nb_name)
            return

        self._start_chat_request(llm_q, selected, nb_name, summary)

    def _auto_generate_summary(self, nb_name: str):
        """채팅을 위해 요약을 자동 생성 (단일 노트북)"""
        nb_cells = sorted(
            [c for c in self._cells if c["notebook"] == nb_name],
            key=lambda x: x["cell_idx"]
        )
        self.summary_requested.emit({nb_name: nb_cells})

    def _start_chat_request(self, question: str, selected_cells: list[dict],
                            nb_name: str, summary: str):
        """채팅 요청 시그널 emit"""
        self._is_streaming = True
        self._last_chat_question = question
        self._pending_nb_name = nb_name
        self._pending_cell_indices = [
            c.get("cell_idx") for c in selected_cells
            if c.get("cell_idx") is not None
        ]
        self._update_chat_btn_streaming()

        self.notebook_chat_requested.emit(
            question, selected_cells, nb_name, summary,
            self._chat_history[-6:]  # 최근 3턴 (6 메시지)
        )

    def _update_chat_btn_streaming(self):
        """전송 버튼 → 중지 버튼으로 전환"""
        self.send_btn.setText("⏹")
        self.send_btn.setStyleSheet(_CHAT_STOP_BTN_STYLE)
        self.send_btn.clicked.disconnect()
        self.send_btn.clicked.connect(self._on_chat_stop)
        self.chat_input.setEnabled(False)
        self.mic_btn.set_enabled_stt(False)

    def _restore_chat_btn(self):
        """중지 버튼 → 전송 버튼으로 복원"""
        self._is_streaming = False
        self.send_btn.setText("전송")
        self.send_btn.setStyleSheet(_SEND_BTN_STYLE)
        try:
            self.send_btn.clicked.disconnect()
        except TypeError:
            pass
        self.send_btn.clicked.connect(self._on_chat_send)
        self.chat_input.setEnabled(True)
        self.mic_btn.set_enabled_stt(True)
        self.chat_input.setFocus()

    def _on_chat_stop(self):
        """채팅 스트리밍 중지"""
        self.notebook_chat_stop.emit()

    def _on_clear_chat(self):
        """채팅 초기화 — 현재 노트북의 자동 이력도 삭제."""
        self._chat_history.clear()
        self._last_chat_question = ""
        self._run_chat_js("clearChat()")
        self._restore_chat_btn()
        if self._history_cache and self._current_nb:
            self._history_cache.delete_notebook(self._current_nb)

    def _restore_notebook_chat(self, nb: str):
        """노트북 전환 시 해당 노트북의 저장된 대화 이력을 복원."""
        if self._is_streaming:
            self._restore_chat_btn()

        self._chat_history.clear()
        self._last_chat_question = ""

        if not self._chat_page_ready:
            self._pending_restore_nb = nb
            return

        self._run_chat_js("clearChat()")

        if not self._history_cache:
            return

        entries = self._history_cache.get_notebook(nb)
        if not entries:
            return

        # Cached Responses Tab에 저장된 항목 ID 집합 (alreadyCached 판정용)
        cached_ids: set[str] = set()
        cached_responses = NotebookChatCache(self._cache_dir)
        for nb_entries in cached_responses.get_all().values():
            for e in nb_entries:
                eid = e.get("id")
                if eid:
                    cached_ids.add(eid)

        for entry in entries:
            question = entry.get("question") or ""
            answer   = entry.get("answer") or ""
            msg_id   = entry.get("id") or str(uuid.uuid4())
            cell_indices = entry.get("cell_indices") or []

            if not question or not answer:
                continue

            self._run_chat_js(f"appendUserMessage({json.dumps(question)})")
            already_cached = msg_id in cached_ids
            self._run_chat_js(
                f"appendFinishedAiMessage("
                f"{json.dumps(answer)}, "
                f"{json.dumps(msg_id)}, "
                f"{'true' if already_cached else 'false'})"
            )

            self._chat_history.append({"role": "user", "content": question})
            self._chat_history.append({"role": "assistant", "content": answer})

            self._recent_messages[msg_id] = {
                "nb": nb,
                "question": question,
                "answer": answer,
                "cell_indices": cell_indices,
            }

        while len(self._recent_messages) > 100:
            self._recent_messages.pop(next(iter(self._recent_messages)))

    # ── STT (음성 입력) ───────────────────────────────────────────────────────

    def set_stt_language(self, language: str):
        self._stt_language = language

    def _on_mic_start(self):
        from workers.stt_worker import AudioRecorder
        if self._recorder and self._recorder.isRunning():
            return
        self._recorder = AudioRecorder(self)
        self._recorder.finished.connect(self._on_recording_done)
        self._recorder.error.connect(self._on_stt_error)
        self._recorder.start()
        self.mic_btn.set_recording(True)

    def _on_mic_stop(self):
        if self._recorder and self._recorder.isRunning():
            self._recorder.stop_recording()
        self.mic_btn.set_enabled_stt(False)

    def _on_recording_done(self, audio_bytes: bytes):
        self.mic_btn.set_recording(False)
        from workers.stt_worker import STTWorker
        self._stt_worker = STTWorker(audio_bytes, self._stt_language, self)
        self._stt_worker.finished.connect(self._on_transcription_done)
        self._stt_worker.error.connect(self._on_stt_error)
        self._stt_worker.start()
        self.chat_status.setText("🎙️ 음성 변환 중…")
        self.chat_status.show()

    def _on_transcription_done(self, text: str):
        self.chat_status.hide()
        cursor = self.chat_input.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.chat_input.setTextCursor(cursor)
        existing = self.chat_input.toPlainText()
        if existing and not existing.endswith(" "):
            self.chat_input.insertPlainText(" " + text)
        else:
            self.chat_input.insertPlainText(text)
        self.mic_btn.set_enabled_stt(True)

    def _on_stt_error(self, msg: str):
        self.mic_btn.set_recording(False)
        self.mic_btn.set_enabled_stt(True)
        self.chat_status.setText(f"🎙️ STT 오류: {msg}")
        self.chat_status.show()

    # ── 채팅 스트리밍 콜백 (MainWindow에서 호출) ──────────────────────────────

    def on_chat_streaming_start(self):
        """스트리밍 시작"""
        self._run_chat_js("removeStatus()")
        self._run_chat_js("startAiMessage()")

    def on_chat_chunk(self, chunk: str):
        """스트리밍 토큰 수신"""
        self._run_chat_js(f"streamingBuffer += {json.dumps(chunk)}; renderStreamingBuffer();")

    def on_chat_finished(self, answer: str):
        """스트리밍 완료 — 캐시 저장용 message_id를 발급해 JS로 넘김."""
        msg_id = str(uuid.uuid4())
        self._run_chat_js(f"finishAiMessage({json.dumps(msg_id)})")
        self._restore_chat_btn()

        # 대화 기록에 추가
        question = self._last_chat_question
        if question:
            self._chat_history.append({"role": "user", "content": question})
        self._chat_history.append({"role": "assistant", "content": answer})

        # 저장 버튼 클릭 시 조회할 수 있도록 메시지 캐시
        nb = self._pending_nb_name or self._current_nb
        self._recent_messages[msg_id] = {
            "nb": nb,
            "question": question,
            "answer": answer,
            "cell_indices": list(self._pending_cell_indices),
        }
        if len(self._recent_messages) > 100:
            self._recent_messages.pop(next(iter(self._recent_messages)))

        # 자동 이력 저장 (per-notebook persistent history)
        if self._history_cache and question and answer:
            self._history_cache.add(
                nb,
                question,
                answer,
                list(self._pending_cell_indices),
                entry_id=msg_id,
            )

        self._last_chat_question = ""
        self._pending_nb_name = ""
        self._pending_cell_indices = []

    def on_chat_error(self, msg: str):
        """채팅 에러"""
        escaped = json.dumps(f"❌ {msg}")
        self._run_chat_js(f"showStatus({escaped})")
        self._restore_chat_btn()

    # ── 캐시 저장/삭제 (HTML 💾 버튼 → _ChatLinkPage → 여기로) ────────────────

    def _handle_save_request(self, message_id: str):
        entry = self._recent_messages.get(message_id)
        if not entry:
            return
        cache = NotebookChatCache(self._cache_dir)
        # 같은 id가 이미 저장되어 있으면 중복 저장 방지 (idempotent)
        for entries in cache.get_all().values():
            if any(e.get("id") == message_id for e in entries):
                return
        cache.add(
            entry.get("nb") or "(unknown)",
            entry.get("question") or "",
            entry.get("answer") or "",
            entry.get("cell_indices") or [],
            entry_id=message_id,
        )
        self.cache_updated.emit()

    def _handle_unsave_request(self, message_id: str):
        cache = NotebookChatCache(self._cache_dir)
        if cache.delete_by_id(message_id):
            self.cache_updated.emit()

    def on_cache_entry_deleted(self, scope: str, entry_id: str):
        """CachedResponsesTab.entry_deleted 수신 — 해당 버블의 💾 버튼 상태 복원."""
        if scope != "notebook":
            return
        self._run_chat_js(f"markCached({json.dumps(entry_id)}, false)")

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def load_cells(self, cells: list[dict]):
        self._cells = cells

        new_nbs = sorted(set(c["notebook"] for c in cells))
        self._summaries = {
            k: v for k, v in self._summaries.items() if k in new_nbs
        }
        self._stale_summaries = {k for k in self._stale_summaries if k in new_nbs}

        self._load_summary_cache()

        self.nb_list.blockSignals(True)
        self.nb_list.clear()
        for nb in new_nbs:
            item = QListWidgetItem(nb)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.nb_list.addItem(item)
        self.nb_list.blockSignals(False)

        self.select_all_cb.blockSignals(True)
        self.select_all_cb.setCheckState(Qt.CheckState.Unchecked)
        self.select_all_cb.blockSignals(False)
        self._update_selected_count_label()

        self._update_all_indicators()
        self._update_generate_btn_label()

        if new_nbs:
            self._current_nb = new_nbs[0]
            self.nb_list.setCurrentRow(0)
            self._render_outline(new_nbs[0])
            self._render_notebook(new_nbs[0])
            self._switch_view(0)
            # 초기 노트북의 대화 이력 복원 (페이지 준비 전이면 지연 처리)
            self._restore_notebook_chat(new_nbs[0])

        self._rebuild_summary_view()

    def set_summary(self, notebook_name: str, summary: str, prompt_hash: str = ""):
        """워커에서 호출: 하나의 노트북 요약 결과를 캐시 + 표시

        prompt_hash: 이 요약 생성 시점에 사용된 프롬프트의 MD5. 런타임 프롬프트 변경
        감지(QFileSystemWatcher)가 stale 판정에 사용한다.
        """
        self._summaries[notebook_name] = summary
        self._summary_prompt_hashes[notebook_name] = prompt_hash
        self._stale_summaries.discard(notebook_name)
        self._save_summary_to_cache(notebook_name, summary, prompt_hash)
        self._update_item_indicator(notebook_name)
        self._rebuild_summary_view()
        self._update_generate_btn_label()

        # 대기 중인 채팅 질문이 있으면 이제 처리
        if (self._pending_chat_question
                and notebook_name == self._current_nb):
            question = self._pending_chat_question
            cells = self._pending_chat_cells
            self._pending_chat_question = ""
            self._pending_chat_cells = []
            self._start_chat_request(question, cells, notebook_name, summary)

    def update_progress(self, processed: int, total: int):
        self.progress_bar.setValue(processed)
        self.progress_bar.setFormat(f"{processed}/{total}")
        self.status_label.setText(f"⏳ {processed}/{total} 노트북 처리 중...")

    def on_generation_finished(self):
        self.generate_btn.setEnabled(True)
        self.progress_bar.hide()
        self.stop_btn.hide()
        self.status_label.setText("✅ 요약 생성 완료")
        # 대기 중인 채팅이 없고 스트리밍 중이 아닐 때만 요약 보기로 전환
        if not self._pending_chat_question and not self._is_streaming:
            self._switch_view(1)

    def on_error(self, msg: str):
        self.generate_btn.setEnabled(True)
        self.progress_bar.hide()
        self.stop_btn.hide()
        self.status_label.setText(f"❌ {msg}")

    # ── 셀 렌더링 (QWebEngineView) ───────────────────────────────────────────

    def _render_notebook(self, nb_name: str):
        nb_cells = sorted(
            [c for c in self._cells if c["notebook"] == nb_name],
            key=lambda x: x["cell_idx"]
        )
        nb_path = self._get_nb_path(nb_name)
        if nb_path:
            base_url = QUrl.fromLocalFile(str(Path(nb_path).parent)).toString() + "/"
            self._run_viewer_js(f"setNotebookBaseDir({json.dumps(base_url)})")
        cells_json = json.dumps([
            {
                "cell_idx": c["cell_idx"],
                "cell_type": c["cell_type"],
                "source": c["source"],
                **({"attachments": c["attachments"]} if c.get("attachments") else {}),
            }
            for c in nb_cells
        ], ensure_ascii=False)
        self._run_viewer_js(f"loadCells({cells_json})")

    # ── 요약 뷰 렌더링 ───────────────────────────────────────────────────────

    def _rebuild_summary_view(self):
        if not self._summary_page_ready:
            self._summary_view_dirty = True
            return
        self._summary_view_dirty = False

        self._run_summary_js("clearCards()")

        checked = self._get_checked_names()
        has_summary = False

        for name in checked:
            if name in self._summaries:
                has_summary = True
                escaped = json.dumps(name)
                md_escaped = json.dumps(self._summaries[name])
                is_stale = str(name in self._stale_summaries).lower()
                self._run_summary_js(
                    f"addSummaryCard({escaped},{md_escaped},{is_stale})"
                )

        if not has_summary:
            self._run_summary_js(
                'showPlaceholder("\\uD83D\\uDCDD 노트북을 선택하고 \'요약 생성\'을 클릭하세요.")'
            )
