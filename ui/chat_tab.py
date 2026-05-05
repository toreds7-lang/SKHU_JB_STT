"""
ChatTab - 채팅 탭 (QWebEngineView + marked.js + highlight.js)
"""

import sys
import json
import uuid
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QTextBrowser, QScrollArea, QGroupBox,
    QFrame, QSizePolicy, QApplication, QProgressBar, QSplitter, QSplitterHandle, QListWidget
)
from PyQt6.QtCore import Qt, pyqtSignal, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtWebEngineWidgets import QWebEngineView
from ui.stt_button import STTButton

from cache_store import ChatCache


class _AutoExpandingEdit(QPlainTextEdit):
    """ChatGPT-style input: grows vertically up to 4 lines, Enter sends."""
    returnPressed = pyqtSignal()

    # Fallbacks used before the widget is shown; overwritten in showEvent
    _MIN_HEIGHT = 36
    _MAX_HEIGHT = 144  # 4 × 36

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("질문을 입력하세요…")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(self._MIN_HEIGHT)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.document().contentsChanged.connect(self._adjust_height)

    def showEvent(self, event):
        super().showEvent(event)
        # Recalculate limits now that the font and style are fully applied
        line_h = self.fontMetrics().lineSpacing()
        if line_h >= 8:  # sanity check
            margins = self.contentsMargins()
            v_pad = margins.top() + margins.bottom() + 4
            self._MIN_HEIGHT = line_h + v_pad
            self._MAX_HEIGHT = line_h * 4 + v_pad
            self.setFixedHeight(self._MIN_HEIGHT)

    def _adjust_height(self):
        # document().size().height() for QPlainTextDocumentLayout returns block count,
        # not pixel height — so we count actual visual lines from each block's layout.
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
        # Width changes affect word-wrap, so recalculate height
        self._adjust_height()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)  # Shift+Enter → newline
            else:
                self.returnPressed.emit()
        else:
            super().keyPressEvent(event)


_COPY_PREFIX = "__COPY__:"
_SAVE_PREFIX = "__SAVE_CHAT__:"
_UNSAVE_PREFIX = "__UNSAVE_CHAT__:"

class _ExternalLinkPage(QWebEnginePage):
    """링크 클릭 시 시스템 기본 브라우저로 열기 + console 메시지로 클립보드/캐시 처리.

    save/unsave 콜백을 ChatTab에서 주입받아 호출한다.
    """
    def __init__(self, parent=None, save_handler=None, unsave_handler=None):
        super().__init__(parent)
        self._save_handler = save_handler
        self._unsave_handler = unsave_handler

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    def javaScriptConsoleMessage(self, level, message, line, source):
        if message.startswith(_COPY_PREFIX):
            QApplication.clipboard().setText(message[len(_COPY_PREFIX):])
            return
        if message.startswith(_SAVE_PREFIX) and self._save_handler:
            self._save_handler(message[len(_SAVE_PREFIX):])
            return
        if message.startswith(_UNSAVE_PREFIX) and self._unsave_handler:
            self._unsave_handler(message[len(_UNSAVE_PREFIX):])
            return
        # 다른 콘솔 메시지는 무시 (디버그용으로 super 호출 가능)


# ── 출처 카드 (sources_display용, QTextBrowser에서 계속 사용) ─────────────────
def _doc_card(doc, tag_class: str, tag_name: str) -> str:
    nb    = doc.metadata.get("notebook", "?")
    cidx  = doc.metadata.get("cell_idx", "?")
    ctype = doc.metadata.get("cell_type", "?")
    preview = doc.page_content[:200].replace("<", "&lt;").replace(">", "&gt;")
    tag_colors = {
        "tag-vector": ("color:#60a5fa;background:#1e3a5f;border:1px solid #1d4ed8;"),
        "tag-bm25":   ("color:#34d399;background:#1a3a2a;border:1px solid #059669;"),
        "tag-graph":  ("color:#a78bfa;background:#2d1a3a;border:1px solid #7c3aed;"),
    }
    tag_style = tag_colors.get(tag_class, "color:#e2e8f0;background:#333;")
    ctype_style = ("color:#fb923c;background:#2a1a10;border:1px solid #c2410c;"
                   if ctype == "code" else
                   "color:#5eead4;background:#1a2a2a;border:1px solid #0d9488;")
    code_style = (
        "background:#111827;border-left:3px solid #fb923c;border-radius:0 4px 4px 0;padding:6px 8px;"
        if ctype == "code" else
        "border-left:3px solid #a78bfa;padding-left:8px;color:#c4b5fd;"
    )
    return (
        f'<div style="background:#161922;border:1px solid #2a3045;border-radius:8px;'
        f'padding:8px 10px;margin:4px 0;">'
        f'<span style="font-size:10px;font-family:JetBrains Mono,Consolas,monospace;'
        f'padding:2px 6px;border-radius:3px;margin-right:4px;{tag_style}">{tag_name}</span>'
        f'<span style="font-size:10px;font-family:JetBrains Mono,Consolas,monospace;'
        f'padding:2px 6px;border-radius:3px;margin-right:4px;{ctype_style}">{ctype.upper()}</span>'
        f'<span style="font-size:10px;color:#94a3b8;font-family:JetBrains Mono,Consolas,monospace;">'
        f'📓 {nb} · 셀 #{cidx}</span>'
        f'<div style="{code_style}margin-top:4px;font-size:11px;font-family:JetBrains Mono,Consolas,monospace;">'
        f'{preview}</div>'
        f'</div>'
    )


# ── 접이식 스플리터 ───────────────────────────────────────────────────────────

class _CollapseHandle(QSplitterHandle):
    """스플리터 핸들 중앙에 ◀/▶ 버튼을 넣어 한 번 클릭으로 패널을 접고 펼친다."""

    def __init__(self, orientation, parent, collapse_index: int = 1):
        super().__init__(orientation, parent)
        self._collapse_index = collapse_index
        self._saved_sizes: list[int] | None = None

        arrow = "▶" if collapse_index == 1 else "◀"
        self._btn = QPushButton(arrow, self)
        self._btn.setFixedSize(12, 40)
        self._btn.setStyleSheet(
            "QPushButton { background: #374151; color: #9ca3af; border: none; "
            "border-radius: 3px; font-size: 9px; padding: 0; }"
            "QPushButton:hover { background: #4b5563; color: #e2e8f0; }"
        )
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.clicked.connect(self._toggle)
        self.splitter().splitterMoved.connect(self._sync_arrow)
        self.setCursor(Qt.CursorShape.SizeHorCursor)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._btn.move((self.width() - self._btn.width()) // 2, (self.height() - 40) // 2)

    def _sync_arrow(self):
        sizes = self.splitter().sizes()
        collapsed = sizes[self._collapse_index] == 0
        if self._collapse_index == 1:
            self._btn.setText("◀" if collapsed else "▶")
        else:
            self._btn.setText("▶" if collapsed else "◀")

    def _toggle(self):
        splitter = self.splitter()
        sizes = splitter.sizes()
        total = sum(sizes)
        if sizes[self._collapse_index] == 0:
            restored = self._saved_sizes or (
                [total * 22 // 100, total * 78 // 100]
                if self._collapse_index == 0
                else [total * 58 // 100, total * 42 // 100]
            )
            splitter.setSizes(restored)
        else:
            self._saved_sizes = list(sizes)
            new = [0, total] if self._collapse_index == 0 else [total, 0]
            splitter.setSizes(new)
        self._sync_arrow()


class _CollapsibleSplitter(QSplitter):
    """버튼으로 한 패널을 접을 수 있는 QSplitter."""

    def __init__(self, orientation, collapse_index: int = 1, parent=None):
        super().__init__(orientation, parent)
        self._collapse_index = collapse_index
        self.setHandleWidth(20)

    def createHandle(self):
        return _CollapseHandle(self.orientation(), self, self._collapse_index)


class ChatTab(QWidget):
    query_submitted = pyqtSignal(str, bool)   # (query, is_suggested)
    force_stop_requested = pyqtSignal()       # Force Mode 중지 요청
    llm_stop_requested = pyqtSignal()         # 일반 모드 스트리밍 중지 요청
    cache_updated = pyqtSignal()              # 캐시 저장/삭제 시 emit (CachedResponsesTab refresh용)

    def __init__(self):
        super().__init__()
        self._messages: list[dict] = []       # {"role": "user"|"assistant", "content": str}
        self._streaming_buf = ""
        self._is_streaming  = False
        self._page_loaded   = False
        self._pending_js: list[str] = []
        self._stt_language = "ko"
        self._recorder   = None
        self._stt_worker = None

        # 캐시 관련 상태
        self._cache_dir: str = ".rag_cache"
        self._last_source_notebooks: list = []   # 직전 RAG 응답의 출처 노트북 목록
        self._last_mode: str = "rag"             # "rag" | "force"
        self._recent_messages: dict = {}         # message_id → {query, answer, source_notebooks, mode}

        self._build_ui()

    # ── 캐시 디렉토리 ─────────────────────────────────────────────────────────

    def set_cache_dir(self, path: str):
        self._cache_dir = path

    # ── 노트북 목록 ───────────────────────────────────────────────────────────

    def load_notebooks(self, nb_names: list[str]):
        """RAG 구축 완료 후 노트북 이름 목록을 채팅 탭 좌측에 채움. 패널은 ▶ 버튼으로 직접 펼침."""
        self._nb_list.clear()
        for name in nb_names:
            self._nb_list.addItem(name)

    # ── JS 브릿지 헬퍼 ──────────────────────────────────────────────────────

    def _run_js(self, script: str):
        """JavaScript 실행 — 페이지 로드 전이면 큐에 저장."""
        if self._page_loaded:
            self.chat_display.page().runJavaScript(script)
        else:
            self._pending_js.append(script)

    def _on_page_loaded(self, ok: bool):
        """QWebEngineView 페이지 로드 완료 콜백."""
        if not ok:
            return
        self._page_loaded = True
        # 기존 메시지 히스토리 복원 (AI 메시지에는 새 message_id를 발급해 캐시 버튼 동작 가능)
        prev_user = ""
        for msg in self._messages:
            jtext = json.dumps(msg["content"])
            if msg["role"] == "user":
                prev_user = msg["content"]
                self.chat_display.page().runJavaScript(
                    f"appendUserMessage({jtext})"
                )
            else:
                msg_id = str(uuid.uuid4())
                # 모드 추정: 직전 user 메시지에 force prefix가 있으면 force
                mode = "force" if "\U0001f50d [Force Mode]" in prev_user else "rag"
                # 출처는 세션 내에서만 보유 — 복원 시 빈 리스트 (source_notebooks는 휘발성)
                self._recent_messages[msg_id] = {
                    "query": prev_user,
                    "answer": msg["content"],
                    "source_notebooks": [],
                    "mode": mode,
                }
                self.chat_display.page().runJavaScript(
                    f"appendFinishedAiMessage({jtext}, {json.dumps(msg_id)}, false)"
                )
                prev_user = ""
        # 대기 중이던 JS 실행
        for js in self._pending_js:
            self.chat_display.page().runJavaScript(js)
        self._pending_js.clear()

    # ── UI 구성 ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(6)

        if getattr(sys, "frozen", False):
            _base = Path(sys._MEIPASS)
        else:
            _base = Path(__file__).parent.parent

        # ── 좌우 스플리터 ──────────────────────────────────────────────────────
        self._viewer_splitter = _CollapsibleSplitter(Qt.Orientation.Horizontal, collapse_index=0)
        self._viewer_splitter.setStyleSheet(
            "QSplitter::handle { background: #2a3045; }"
            "QSplitter::handle:hover { background: #3a4055; }"
        )

        # ── 좌측: 노트북 목록 패널 (기본 숨김, ▶ 버튼으로 펼침) ────────────────
        self._nb_panel = QWidget()
        nb_layout = QVBoxLayout(self._nb_panel)
        nb_layout.setContentsMargins(0, 0, 4, 0)
        nb_layout.setSpacing(4)
        nb_header = QLabel("📓 노트북 목록")
        nb_header.setStyleSheet(
            "color: #94a3b8; font-size: 11px; font-weight: 600; padding: 4px 0;"
        )
        nb_layout.addWidget(nb_header)
        self._nb_list = QListWidget()
        self._nb_list.setStyleSheet(
            "QListWidget { background: #0d0f14; border: 1px solid #2a3045; "
            "border-radius: 4px; color: #e2e8f0; font-size: 11px; outline: 0; }"
            "QListWidget::item { padding: 4px 8px; border-bottom: 1px solid #1a2030; }"
            "QListWidget::item:hover { background: #1a2030; }"
        )
        self._nb_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self._nb_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        nb_layout.addWidget(self._nb_list, stretch=1)
        self._viewer_splitter.addWidget(self._nb_panel)

        # ── 우측: 기존 채팅 레이아웃 ───────────────────────────────────────────
        right_widget = QWidget()
        layout = QVBoxLayout(right_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._viewer_splitter.addWidget(right_widget)
        self._viewer_splitter.setStretchFactor(0, 0)
        self._viewer_splitter.setStretchFactor(1, 1)
        self._viewer_splitter.setSizes([0, 1])  # 초기: 노트북 목록 패널 숨김
        outer.addWidget(self._viewer_splitter)

        # ── 채팅 히스토리 (QWebEngineView) ────────────────────────────────────
        self.chat_display = QWebEngineView()
        self.chat_display.setPage(_ExternalLinkPage(
            self.chat_display,
            save_handler=self._handle_save_request,
            unsave_handler=self._handle_unsave_request,
        ))
        self.chat_display.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        html_path = _base / "resources" / "chat.html"
        self.chat_display.setUrl(QUrl.fromLocalFile(str(html_path.resolve())))
        self.chat_display.loadFinished.connect(self._on_page_loaded)
        layout.addWidget(self.chat_display, stretch=1)

        # ── 상태 레이블 ────────────────────────────────────────────────────────
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            "color: #4f8ef7; font-size: 11px; "
            "font-family: 'JetBrains Mono', Consolas, monospace;"
        )
        layout.addWidget(self.status_label)

        # ── Force Mode 진행률 바 + 중지 버튼 ────────────────────────────────────
        self.force_bar = QWidget()
        force_layout = QHBoxLayout(self.force_bar)
        force_layout.setContentsMargins(0, 2, 0, 2)
        force_layout.setSpacing(8)
        self.force_progress = QProgressBar()
        self.force_progress.setMinimum(0)
        self.force_progress.setMaximum(100)
        self.force_progress.setTextVisible(True)
        self.force_progress.setFormat("Force Mode 검색 중… %v/%m")
        self.force_progress.setStyleSheet(
            "QProgressBar { background: #1e2330; border: 1px solid #2a3045; "
            "border-radius: 4px; height: 22px; color: #e2e8f0; font-size: 11px; }"
            "QProgressBar::chunk { background: #4f8ef7; border-radius: 3px; }"
        )
        self.force_stop_btn = QPushButton("⏹️ 중지")
        self.force_stop_btn.setFixedWidth(72)
        self.force_stop_btn.setMinimumHeight(26)
        self.force_stop_btn.setStyleSheet(
            "QPushButton { background: #dc2626; color: white; border: none; "
            "border-radius: 4px; font-size: 11px; font-weight: 600; }"
            "QPushButton:hover { background: #ef4444; }"
        )
        self.force_stop_btn.clicked.connect(self.force_stop_requested.emit)
        force_layout.addWidget(self.force_progress, stretch=1)
        force_layout.addWidget(self.force_stop_btn)
        self.force_bar.setVisible(False)
        layout.addWidget(self.force_bar)

        # ── 출처 그룹 (접기/펼치기) — 입력창 위에 배치 ────────────────────────
        self.sources_group = QGroupBox("🔍 검색 결과 상세")
        self.sources_group.setCheckable(True)
        self.sources_group.setChecked(False)
        self.sources_group.setStyleSheet(
            "QGroupBox { color: #94a3b8; font-size: 11px; border: 1px solid #2a3045; "
            "border-radius: 6px; margin-top: 6px; padding-top: 12px; max-height: 260px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; }"
            "QGroupBox::indicator { width: 14px; height: 14px; }"
        )
        src_layout = QVBoxLayout(self.sources_group)
        self.sources_display = QTextBrowser()
        self.sources_display.setStyleSheet(
            "QTextBrowser { background: #0d0f14; border: none; "
            "color: #e2e8f0; font-size: 11px; }"
        )
        self.sources_display.setMaximumHeight(200)
        src_layout.addWidget(self.sources_display)
        self.sources_group.setVisible(False)
        layout.addWidget(self.sources_group)

        # ── 추천 검색어 칩 ─────────────────────────────────────────────────────
        self.chips_scroll = QScrollArea()
        self.chips_scroll.setWidgetResizable(True)
        self.chips_scroll.setFixedHeight(44)
        self.chips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chips_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.chips_scroll.setVisible(False)
        self._chips_widget = QWidget()
        self._chips_layout = QHBoxLayout(self._chips_widget)
        self._chips_layout.setContentsMargins(0, 4, 0, 4)
        self._chips_layout.setSpacing(6)
        self._chips_layout.addStretch()
        self.chips_scroll.setWidget(self._chips_widget)
        layout.addWidget(self.chips_scroll)

        # ── 예시 질문 바 ───────────────────────────────────────────────────────
        self.example_bar = QWidget()
        example_layout = QVBoxLayout(self.example_bar)
        example_layout.setContentsMargins(0, 0, 0, 0)
        example_layout.setSpacing(2)
        ex_hint = QLabel("예시 질문:")
        ex_hint.setStyleSheet("color: #475569; font-size: 11px;")
        example_layout.addWidget(ex_hint)
        self._example_chips_widget = QWidget()
        self._example_chips_layout = QHBoxLayout(self._example_chips_widget)
        self._example_chips_layout.setContentsMargins(0, 0, 0, 0)
        self._example_chips_layout.setSpacing(6)
        self._example_chips_layout.addStretch()
        example_layout.addWidget(self._example_chips_widget)
        self.example_bar.setVisible(False)
        layout.addWidget(self.example_bar)

        # ── 입력 행 (항상 하단 고정) ───────────────────────────────────────────
        input_row = QHBoxLayout()
        self.input_edit = _AutoExpandingEdit()
        self.input_edit.setStyleSheet(
            "QPlainTextEdit { border: 1px solid #2a3045; border-radius: 18px; "
            "padding: 6px 14px; background: #1e2330; color: #e2e8f0; }"
            "QPlainTextEdit:focus { border-color: #4f8ef7; }"
        )
        self.input_edit.viewport().setStyleSheet("background: transparent;")
        self.input_edit.returnPressed.connect(self._on_send)
        self.send_btn = QPushButton("전송")
        self.send_btn.setMinimumHeight(36)
        self.send_btn.setFixedWidth(64)
        self.send_btn.clicked.connect(self._on_send)
        self.clear_btn = QPushButton("🗑️")
        self.clear_btn.setMinimumHeight(36)
        self.clear_btn.setFixedWidth(40)
        self.clear_btn.setToolTip("대화 초기화")
        self.clear_btn.clicked.connect(self.clear_chat)
        self.mic_btn = STTButton()
        self.mic_btn.record_start.connect(self._on_mic_start)
        self.mic_btn.record_stop.connect(self._on_mic_stop)
        input_row.setAlignment(Qt.AlignmentFlag.AlignBottom)
        input_row.addWidget(self.input_edit)
        input_row.addWidget(self.mic_btn)
        input_row.addWidget(self.send_btn)
        input_row.addWidget(self.clear_btn)
        layout.addLayout(input_row)

    # ── 공개 API ───────────────────────────────────────────────────────────────

    def start_streaming(self, query: str):
        """검색+스트리밍 시작 시 호출"""
        self._append_user_message(query)
        self._streaming_buf = ""
        self._is_streaming  = True
        self._run_js("startAiMessage()")
        self.input_edit.setEnabled(False)
        self.mic_btn.set_enabled_stt(False)
        self.send_btn.setText("⏹")
        self.send_btn.setStyleSheet(
            "QPushButton { background: #dc2626; color: white; border: none; "
            "border-radius: 4px; font-size: 14px; font-weight: 600; }"
            "QPushButton:hover { background: #ef4444; }"
        )
        self.send_btn.setEnabled(True)
        self.sources_group.setVisible(False)

    def on_chunk_received(self, chunk: str):
        """LLMWorker.chunk_received 신호 수신"""
        if chunk == "\x00RESET\x00":
            self._streaming_buf = ""
            self._run_js("resetStreamingBuffer()")
            return
        if chunk.startswith("\x00CITATION\x00"):
            citation = chunk[len("\x00CITATION\x00"):]
            self._streaming_buf += citation
            return
        self._streaming_buf += chunk
        self._run_js(f"streamingBuffer={json.dumps(self._streaming_buf)};renderStreamingBuffer()")

    def on_streaming_finished(self, answer: str, result: dict):
        """LLMWorker.finished_signal 수신"""
        self._is_streaming = False
        self._streaming_buf = ""
        self._messages.append({"role": "assistant", "content": answer})

        # 출처 노트북 추출 (캐시 저장 시 인덱스로 사용)
        source_nbs = []
        if result:
            seen = set()
            for d in result.get("all_docs", []) or []:
                nb = getattr(d, "metadata", {}).get("notebook") if hasattr(d, "metadata") else None
                if nb and nb not in seen:
                    seen.add(nb)
                    source_nbs.append(nb)
        self._last_source_notebooks = source_nbs
        self._last_mode = "rag"

        # message_id 발급 + recent_messages에 캐시
        msg_id = str(uuid.uuid4())
        last_user = ""
        for m in reversed(self._messages[:-1]):
            if m["role"] == "user":
                last_user = m["content"]
                break
        self._recent_messages[msg_id] = {
            "query": last_user,
            "answer": answer,
            "source_notebooks": source_nbs,
            "mode": "rag",
        }
        if len(self._recent_messages) > 100:
            self._recent_messages.pop(next(iter(self._recent_messages)))

        # 최종 버퍼를 answer로 설정 후 finishAiMessage 호출 (msg_id 전달)
        self._run_js(
            f"streamingBuffer={json.dumps(answer)};"
            f"finishAiMessage({json.dumps(msg_id)})"
        )
        self._render_sources(result)
        self.input_edit.setEnabled(True)
        self._restore_send_btn()
        self.status_label.setText("")
        self.example_bar.setVisible(False)

    def _restore_send_btn(self):
        """전송 버튼을 원래 상태로 복원"""
        self.send_btn.setText("전송")
        self.send_btn.setStyleSheet("")
        self.send_btn.setEnabled(True)
        self.mic_btn.set_enabled_stt(True)

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
        self.status_label.setText("🎙️ 음성 변환 중…")

    def _on_transcription_done(self, text: str):
        self.status_label.setText("")
        cursor = self.input_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.input_edit.setTextCursor(cursor)
        existing = self.input_edit.toPlainText()
        if existing and not existing.endswith(" "):
            self.input_edit.insertPlainText(" " + text)
        else:
            self.input_edit.insertPlainText(text)
        self.mic_btn.set_enabled_stt(True)

    def _on_stt_error(self, msg: str):
        self.mic_btn.set_recording(False)
        self.mic_btn.set_enabled_stt(True)
        self.status_label.setText(f"🎙️ STT 오류: {msg}")

    # ── Force Mode API ────────────────────────────────────────────────────────

    def start_force_mode(self, query: str):
        """Force Mode 시작 시 호출"""
        self._append_user_message(f"🔍 [Force Mode] {query}")
        self._streaming_buf = ""
        self._is_streaming = True
        self._run_js("startAiMessage()")
        self.input_edit.setEnabled(False)
        self.send_btn.setEnabled(False)
        self.mic_btn.set_enabled_stt(False)
        self.sources_group.setVisible(False)
        self.force_bar.setVisible(True)
        self.force_progress.setValue(0)
        self.force_progress.setMaximum(1)

    def update_force_progress(self, processed: int, total: int):
        """Force Mode 진행률 업데이트"""
        self.force_progress.setMaximum(total)
        self.force_progress.setValue(processed)
        self.force_progress.setFormat(f"Force Mode 검색 중… {processed}/{total}")

    def update_force_preview(self, preview_md: str):
        """Force Mode 누적 결과 미리보기"""
        self._run_js(f"streamingBuffer={json.dumps(preview_md)};renderStreamingBuffer()")

    def finish_force_mode(self, answer: str):
        """Force Mode 완료"""
        self._is_streaming = False
        self._streaming_buf = ""
        self._messages.append({"role": "assistant", "content": answer})

        self._last_source_notebooks = []
        self._last_mode = "force"

        # message_id 발급 + recent_messages에 캐시 (Force는 RAG 출처 없음)
        msg_id = str(uuid.uuid4())
        last_user = ""
        for m in reversed(self._messages[:-1]):
            if m["role"] == "user":
                last_user = m["content"]
                # Force prefix 제거
                last_user = last_user.replace("\U0001f50d [Force Mode] ", "")
                break
        self._recent_messages[msg_id] = {
            "query": last_user,
            "answer": answer,
            "source_notebooks": [],
            "mode": "force",
        }
        if len(self._recent_messages) > 100:
            self._recent_messages.pop(next(iter(self._recent_messages)))

        self._run_js(
            f"streamingBuffer={json.dumps(answer)};"
            f"finishAiMessage({json.dumps(msg_id)})"
        )
        self.force_bar.setVisible(False)
        self.input_edit.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.mic_btn.set_enabled_stt(True)
        self.status_label.setText("")
        self.example_bar.setVisible(False)

    def on_error(self, msg: str):
        """LLMWorker.error_signal 수신"""
        self._is_streaming = False
        self._streaming_buf = ""
        self._run_js("finishAiMessage()")
        self.status_label.setText(f"❌ 오류: {msg}")
        self.input_edit.setEnabled(True)
        self.send_btn.setEnabled(True)
        self.mic_btn.set_enabled_stt(True)

    def update_suggested_chips(self, queries: list[str]):
        """추천 검색어 칩 업데이트"""
        self._clear_layout(self._chips_layout)
        self._chips_layout.addStretch()

        if not queries:
            self.chips_scroll.setVisible(False)
            return

        hint = QLabel("💡 추천 검색어:")
        hint.setStyleSheet("color: #64748b; font-size: 11px;")
        self._chips_layout.insertWidget(0, hint)

        for i, q in enumerate(queries):
            btn = QPushButton(q)
            btn.setStyleSheet(
                "QPushButton { background: #1e2330; border: 1px solid #4f8ef7; "
                "color: #4f8ef7; border-radius: 12px; padding: 4px 10px; font-size: 11px; }"
                "QPushButton:hover { background: #1e3a5f; }"
            )
            btn.clicked.connect(lambda checked, sq=q: self._on_chip_clicked(sq))
            self._chips_layout.insertWidget(i + 1, btn)

        self.chips_scroll.setVisible(True)

    def update_example_chips(self, questions: list[str]):
        """예시 질문 칩 업데이트 (RAG 구축 완료 후)"""
        self._clear_layout(self._example_chips_layout)
        self._example_chips_layout.addStretch()

        if not questions:
            return

        for i, q in enumerate(questions):
            btn = QPushButton(q)
            btn.setStyleSheet(
                "QPushButton { background: #1e2330; border: 1px solid #2a3045; "
                "color: #94a3b8; border-radius: 12px; padding: 4px 10px; font-size: 11px; }"
                "QPushButton:hover { background: #1e3a5f; border-color: #4f8ef7; color: #4f8ef7; }"
            )
            btn.clicked.connect(lambda checked, ex=q: self._on_example_clicked(ex))
            self._example_chips_layout.insertWidget(i, btn)

        if not self._messages:
            self.example_bar.setVisible(True)

    def clear_chat(self):
        self._messages.clear()
        self._run_js("clearChat()")
        self.chips_scroll.setVisible(False)
        self.sources_group.setVisible(False)
        self.status_label.setText("")
        # 예시 질문 복원
        if self._example_chips_layout.count() > 1:
            self.example_bar.setVisible(True)

    def get_history_for_llm(self, max_turns: int = 3, max_chars: int = 500) -> list[dict]:
        """Return last N conversation turns for LLM context (excludes current query)."""
        history = self._messages[:-1] if self._messages else []
        # Filter out Force Mode messages and their responses
        filtered = []
        skip_next = False
        for m in history:
            if skip_next:
                skip_next = False
                continue
            if m["role"] == "user" and "\U0001f50d [Force Mode]" in m["content"]:
                skip_next = True
                continue
            filtered.append(m)
        # Take last max_turns exchanges (2 messages per turn)
        filtered = filtered[-(max_turns * 2):]
        # Truncate long assistant messages
        result = []
        for m in filtered:
            if m["role"] == "assistant" and len(m["content"]) > max_chars:
                result.append({"role": m["role"], "content": m["content"][:max_chars] + "\u2026"})
            else:
                result.append(m)
        return result

    # ── 내부 메서드 ────────────────────────────────────────────────────────────

    def _on_send(self):
        if self._is_streaming:
            self.llm_stop_requested.emit()
            return
        query = self.input_edit.toPlainText().strip()
        if not query:
            return
        self.input_edit.clear()
        self.chips_scroll.setVisible(False)
        self.query_submitted.emit(query, False)

    def _on_chip_clicked(self, query: str):
        self.chips_scroll.setVisible(False)
        self.query_submitted.emit(query, True)

    def _on_example_clicked(self, query: str):
        self.example_bar.setVisible(False)
        self.query_submitted.emit(query, False)

    def _append_user_message(self, text: str):
        self._messages.append({"role": "user", "content": text})
        self._run_js(f"appendUserMessage({json.dumps(text)})")

    def _render_sources(self, result: dict):
        if not result:
            return
        html = '<html><body style="background:#0d0f14;margin:0;padding:4px;">'

        v_docs = result.get("vector_docs", [])[:3]
        b_docs = result.get("bm25_docs",   [])[:3]
        g_docs = result.get("graph_docs",  [])[:3]

        if v_docs:
            html += '<div style="font-weight:600;color:#60a5fa;margin:6px 0 2px;font-size:11px;">📐 Vector RAG</div>'
            for d in v_docs:
                html += _doc_card(d, "tag-vector", "Vector RAG")
        if b_docs:
            html += '<div style="font-weight:600;color:#34d399;margin:6px 0 2px;font-size:11px;">🔤 BM25</div>'
            for d in b_docs:
                html += _doc_card(d, "tag-bm25", "BM25")
        if g_docs:
            html += '<div style="font-weight:600;color:#a78bfa;margin:6px 0 2px;font-size:11px;">🕸️ Graph RAG</div>'
            for d in g_docs:
                html += _doc_card(d, "tag-graph", "Graph RAG")

        html += "</body></html>"

        if v_docs or b_docs or g_docs:
            self.sources_display.setHtml(html)

    def _clear_layout(self, layout):
        while layout.count() > 0:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # ── 캐시 저장/삭제 ────────────────────────────────────────────────────────

    def _handle_save_request(self, message_id: str):
        entry = self._recent_messages.get(message_id)
        if not entry:
            return
        cache = ChatCache(self._cache_dir)
        # 같은 id가 이미 저장돼 있으면 중복 저장 방지
        for e in cache.iter_entries():
            if e.get("id") == message_id:
                return
        cache.add(
            entry.get("query") or "",
            entry.get("answer") or "",
            source_notebooks=entry.get("source_notebooks") or [],
            mode=entry.get("mode") or "rag",
            entry_id=message_id,
        )
        self.cache_updated.emit()

    def _handle_unsave_request(self, message_id: str):
        cache = ChatCache(self._cache_dir)
        if cache.delete(message_id):
            self.cache_updated.emit()

    def on_cache_entry_deleted(self, scope: str, entry_id: str):
        """CachedResponsesTab.entry_deleted 수신 — 해당 버블의 💾 버튼 상태 복원."""
        if scope != "chat":
            return
        self._run_js(f"markCached({json.dumps(entry_id)}, false)")
