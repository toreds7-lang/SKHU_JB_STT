"""
KnowledgeGraphTab - 지식 그래프 시각화 탭
D3.js 인터랙티브 그래프 + 노드 상세 + Q&A 패널
"""

import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLabel, QProgressBar, QPlainTextEdit,
    QTextBrowser, QCheckBox, QMessageBox,
)
from PyQt6.QtCore import Qt, QEvent, pyqtSignal, QUrl
from PyQt6.QtGui import QWheelEvent, QKeyEvent
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage


class _QAInputEdit(QPlainTextEdit):
    """Q&A input with Enter-to-send support"""
    send_requested = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.send_requested.emit()
            return
        super().keyPressEvent(event)


SPLITTER_STYLE = """
QSplitter::handle:horizontal { background: #2a3045; width: 6px; margin: 0px; }
QSplitter::handle:vertical   { background: #2a3045; height: 6px; margin: 0px; }
QSplitter::handle:hover      { background: #4f8ef7; }
"""

BTN_STYLE = """
QPushButton {
    background: #4f8ef7; color: white; border: none; border-radius: 4px;
    padding: 6px 12px; font-weight: 600; font-size: 12px;
}
QPushButton:hover { background: #3b82d6; }
QPushButton:pressed { background: #2563eb; }
QPushButton:disabled { background: #64748b; }
"""

STOP_BTN_STYLE = """
QPushButton {
    background: #ef4444; color: white; border: none; border-radius: 4px;
    padding: 6px 12px; font-weight: 600; font-size: 12px;
}
QPushButton:hover { background: #dc2626; }
QPushButton:pressed { background: #b91c1c; }
"""


class _WikiGraphPage(QWebEnginePage):
    """Custom QWebEnginePage to intercept Node Click events via console.log protocol"""
    node_clicked = pyqtSignal(dict)

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        # Protocol: JS sends "NODE_CLICK::<json>" via console.log
        if message.startswith("NODE_CLICK::"):
            try:
                payload = json.loads(message[len("NODE_CLICK::"):])
                self.node_clicked.emit(payload)
            except Exception:
                pass


class KnowledgeGraphTab(QWidget):
    """Wiki 지식 그래프 탭"""

    # Signals to MainWindow
    wiki_build_requested = pyqtSignal(dict)   # {cache_dir, nb_dir, overwrite}
    wiki_qa_requested    = pyqtSignal(str)    # question text
    stop_requested       = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cache_dir = None
        self.nb_dir = None
        self._pending_graph_data = None
        self._qa_buffer = ""

        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        """Build the main UI layout"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = self._build_toolbar()
        main_layout.addWidget(toolbar)

        # ── Main Splitter (Horizontal) ────────────────────────────────────────
        h_splitter = QSplitter(Qt.Orientation.Horizontal)
        h_splitter.setHandleWidth(6)
        h_splitter.setChildrenCollapsible(False)
        h_splitter.setStyleSheet(SPLITTER_STYLE)

        # Left: D3.js Graph
        self.graph_view = QWebEngineView()
        self.graph_page = _WikiGraphPage(self.graph_view)
        self.graph_view.setPage(self.graph_page)
        h_splitter.addWidget(self.graph_view)

        # Right: Vertical Splitter
        v_splitter = QSplitter(Qt.Orientation.Vertical)
        v_splitter.setHandleWidth(6)
        v_splitter.setChildrenCollapsible(False)
        v_splitter.setStyleSheet(SPLITTER_STYLE)

        # Right-Top: Node Detail Browser
        self.detail_browser = QWebEngineView()
        node_html = Path(__file__).resolve().parent.parent / "resources" / "wiki_node.html"
        self.detail_browser.setUrl(QUrl.fromLocalFile(str(node_html)))
        self.detail_browser.installEventFilter(self)  # Ctrl+Wheel zoom
        v_splitter.addWidget(self.detail_browser)

        # Right-Bottom: Q&A Panel
        qa_widget = self._build_qa_panel()
        v_splitter.addWidget(qa_widget)

        v_splitter.setSizes([400, 300])
        h_splitter.addWidget(v_splitter)
        h_splitter.setSizes([700, 400])  # 60/40 split

        main_layout.addWidget(h_splitter, 1)

    def _build_toolbar(self) -> QWidget:
        """Build toolbar widget"""
        toolbar = QWidget()
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Build button
        self.build_btn = QPushButton("🔨 Wiki 생성")
        self.build_btn.setStyleSheet(BTN_STYLE)
        self.build_btn.setMaximumWidth(120)
        self.build_btn.clicked.connect(self._on_build_clicked)
        layout.addWidget(self.build_btn)

        # Stop button (initially hidden)
        self.stop_btn = QPushButton("⏹ 중단")
        self.stop_btn.setStyleSheet(STOP_BTN_STYLE)
        self.stop_btn.setMaximumWidth(100)
        self.stop_btn.setVisible(False)
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        layout.addWidget(self.stop_btn)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet(
            "QProgressBar { height: 6px; border: none; background: #1e2330; }"
            "QProgressBar::chunk { background: #4f8ef7; }"
        )
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumWidth(200)
        layout.addWidget(self.progress_bar)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #94a3b8; font-size: 11px;")
        layout.addWidget(self.status_label)

        # Overwrite checkbox
        self.overwrite_cb = QCheckBox("덮어쓰기")
        self.overwrite_cb.setStyleSheet("color: #94a3b8; font-size: 11px;")
        layout.addWidget(self.overwrite_cb)

        layout.addStretch()
        return toolbar

    def _build_qa_panel(self) -> QWidget:
        """Build Q&A panel widget"""
        qa_widget = QWidget()
        qa_layout = QVBoxLayout(qa_widget)
        qa_layout.setContentsMargins(0, 0, 0, 0)
        qa_layout.setSpacing(8)

        # Label
        qa_label = QLabel("💬 Wiki Q&A")
        qa_label.setStyleSheet("color: #e2e8f0; font-weight: 600; font-size: 12px;")
        qa_layout.addWidget(qa_label)

        # Input + Button row
        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(4)

        self.qa_input = _QAInputEdit()
        self.qa_input.setStyleSheet(
            "QPlainTextEdit { background: #161922; color: #e2e8f0; border: 1px solid #2a3045; "
            "border-radius: 4px; padding: 8px; font-size: 11px; font-family: monospace; }"
        )
        self.qa_input.setMaximumHeight(60)
        self.qa_input.setPlaceholderText("질문을 입력하세요…")
        self.qa_input.send_requested.connect(self._on_send_qa)
        input_row.addWidget(self.qa_input)

        # Send button
        self.qa_send_btn = QPushButton("전송")
        self.qa_send_btn.setStyleSheet(BTN_STYLE)
        self.qa_send_btn.setFixedWidth(60)
        self.qa_send_btn.clicked.connect(self._on_send_qa)
        input_row.addWidget(self.qa_send_btn)

        qa_layout.addLayout(input_row)

        # Response
        self.qa_response = QTextBrowser()
        self.qa_response.setStyleSheet(
            "QTextBrowser { background: #0d0f14; color: #e2e8f0; border: 1px solid #2a3045; "
            "border-radius: 4px; padding: 8px; }"
        )
        qa_layout.addWidget(self.qa_response, 1)

        return qa_widget

    def _connect_signals(self):
        """Connect internal signals"""
        self.graph_page.node_clicked.connect(self._on_node_selected)

    def eventFilter(self, obj, event) -> bool:
        """Handle Ctrl+Wheel zoom for detail_browser"""
        if obj is self.detail_browser and event.type() == QEvent.Type.Wheel:
            we: QWheelEvent = event
            if we.modifiers() & Qt.KeyboardModifier.ControlModifier:
                delta = we.angleDelta().y()
                factor = 1.1 if delta > 0 else 1 / 1.1
                new_zoom = max(0.5, min(3.0, self.detail_browser.zoomFactor() * factor))
                self.detail_browser.setZoomFactor(new_zoom)
                return True  # Consume event (block scrolling)
        return super().eventFilter(obj, event)

    def set_cache_dir(self, cache_dir: str) -> None:
        """Set cache directory"""
        self.cache_dir = cache_dir

    def set_nb_dir(self, nb_dir: str) -> None:
        """Set notebook directory"""
        self.nb_dir = nb_dir

    def on_rag_ready_hint(self) -> None:
        """Show hint that Wiki can be generated"""
        self.status_label.setText("💡 RAG 준비 완료 — Wiki 생성 가능")

    # ── WikiBuildWorker Callbacks ─────────────────────────────────────────────

    def on_wiki_progress(self, percent: int, msg: str) -> None:
        """Update progress display"""
        self.progress_bar.setValue(percent)
        self.status_label.setText(msg)

    def on_page_created(self, slug: str) -> None:
        """Page created callback"""
        pass  # Optional: log page creation

    def on_wiki_finished(self, graph_data: dict) -> None:
        """Graph finished building — load HTML and inject data"""
        self.progress_bar.setVisible(False)
        self.build_btn.setVisible(True)
        self.stop_btn.setVisible(False)
        self.status_label.setText("✅ Wiki 생성 완료")

        self._load_graph_html(graph_data)

    def on_wiki_error(self, msg: str) -> None:
        """Error during wiki generation"""
        self.progress_bar.setVisible(False)
        self.build_btn.setVisible(True)
        self.stop_btn.setVisible(False)
        self.status_label.setText(f"❌ {msg}")
        QMessageBox.critical(self, "Wiki 생성 오류", msg)

    # ── WikiQAWorker Callbacks ────────────────────────────────────────────────

    def on_qa_chunk(self, chunk: str) -> None:
        """Append streaming chunk to response"""
        self._qa_buffer += chunk
        self.qa_response.setText(self._qa_buffer)
        # Auto-scroll to bottom
        self.qa_response.verticalScrollBar().setValue(
            self.qa_response.verticalScrollBar().maximum()
        )

    def on_qa_finished(self, answer: str) -> None:
        """Q&A finished"""
        self.qa_send_btn.setEnabled(True)
        self.qa_input.setEnabled(True)

    # ── Internal Slots ────────────────────────────────────────────────────────

    def _on_build_clicked(self) -> None:
        """Build Wiki button clicked"""
        if not self.cache_dir or not self.nb_dir:
            QMessageBox.information(self, "알림", "먼저 RAG를 구축해 주세요.")
            return

        self.build_btn.setVisible(False)
        self.stop_btn.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("📋 Wiki 생성 시작…")

        params = {
            "cache_dir": self.cache_dir,
            "nb_dir": self.nb_dir,
            "overwrite": self.overwrite_cb.isChecked(),
        }
        self.wiki_build_requested.emit(params)

    def _on_stop_clicked(self) -> None:
        """Stop button clicked"""
        self.stop_requested.emit()
        self.status_label.setText("⏹️ 중단 중…")

    def _on_send_qa(self) -> None:
        """Send Q&A button clicked"""
        question = self.qa_input.toPlainText().strip()
        if not question:
            return

        self.qa_send_btn.setEnabled(False)
        self.qa_input.setEnabled(False)
        self._qa_buffer = ""
        self.qa_response.setText("📝 응답 생성 중…")

        self.wiki_qa_requested.emit(question)

    def _on_node_selected(self, node_data: dict) -> None:
        """Node clicked in graph"""
        content = node_data.get("content", "")
        label = node_data.get("label", node_data.get("id", ""))
        node_type = node_data.get("type", "concept")

        # Render node detail via JavaScript
        escaped_content = json.dumps(content)
        escaped_label = json.dumps(label)
        escaped_type = json.dumps(node_type)
        self.detail_browser.page().runJavaScript(
            f"showNodeDetail({escaped_label}, {escaped_type}, {escaped_content})"
        )

        # Highlight node in graph
        node_id = node_data.get("id", "")
        self.graph_view.page().runJavaScript(f"highlightNode('{node_id}')")

    def _load_graph_html(self, graph_data: dict) -> None:
        """Load knowledge_graph.html and inject data"""
        html_path = Path(__file__).resolve().parent.parent / "resources" / "knowledge_graph.html"
        self.graph_view.setUrl(QUrl.fromLocalFile(str(html_path)))

        self._pending_graph_data = graph_data
        self.graph_view.loadFinished.connect(self._on_graph_loaded)

    def _on_graph_loaded(self, ok: bool) -> None:
        """Graph HTML loaded — inject data"""
        if ok and self._pending_graph_data:
            self._inject_graph_data(self._pending_graph_data)
        self._pending_graph_data = None
        self.graph_view.loadFinished.disconnect(self._on_graph_loaded)

    def _inject_graph_data(self, graph_data: dict) -> None:
        """Inject graph data into D3.js visualization"""
        json_str = json.dumps(graph_data, ensure_ascii=False)
        js_code = f"loadGraphData({json_str})"
        self.graph_view.page().runJavaScript(js_code)
