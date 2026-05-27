"""
KnowledgeGraphTab - 지식 그래프 시각화 탭
D3.js 인터랙티브 그래프 + 노드 상세 + Q&A 패널
"""

import json
from pathlib import Path

from env_loader import get_resource_path
from ui._svg_save import _SAVE_SVG_PREFIX, handle_save_svg_payload
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLabel, QProgressBar, QPlainTextEdit,
    QCheckBox, QMessageBox, QApplication, QTableWidget, QTableWidgetItem,
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
        # Log JavaScript errors to help debug crashes
        from PyQt6.QtWebEngineCore import QWebEnginePage as QWEPage
        if level == QWEPage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            print(f"[JS Error] Line {lineNumber}: {message}")
        elif level == QWEPage.JavaScriptConsoleMessageLevel.WarningMessageLevel:
            print(f"[JS Warning] Line {lineNumber}: {message}")

        # Protocol: JS sends "NODE_CLICK::<json>" via console.log
        if message.startswith("NODE_CLICK::"):
            try:
                payload = json.loads(message[len("NODE_CLICK::"):])
                self.node_clicked.emit(payload)
            except Exception as e:
                print(f"[Error] Failed to parse NODE_CLICK payload: {e}")


_COPY_PREFIX = "__COPY__:"


class _WikiNodePage(QWebEnginePage):
    """Intercepts __COPY__ and __SAVE_SVG__ from wiki_node.html"""
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        if message.startswith(_COPY_PREFIX):
            QApplication.clipboard().setText(message[len(_COPY_PREFIX):])
        elif message.startswith(_SAVE_SVG_PREFIX):
            handle_save_svg_payload(message[len(_SAVE_SVG_PREFIX):])


class _WikiQAPage(QWebEnginePage):
    """Intercepts __COPY__ from wiki_qa.html"""
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        if message.startswith(_COPY_PREFIX):
            QApplication.clipboard().setText(message[len(_COPY_PREFIX):])


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
        self._qa_page_loaded = False
        self._pending_qa_js = []
        self._node_map = {}  # node_id -> node_data mapping
        self._table_splitter = None  # Left side main splitter (tables + graph)

        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        """Build the main UI layout with tables + graph on left, details + QA on right"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = self._build_toolbar()
        main_layout.addWidget(toolbar)

        # ── Main Horizontal Splitter (Tables+Graph on left | Details+QA on right) ─
        h_splitter = QSplitter(Qt.Orientation.Horizontal)
        h_splitter.setHandleWidth(6)
        h_splitter.setChildrenCollapsible(False)
        h_splitter.setStyleSheet(SPLITTER_STYLE)

        # Left: Vertical Splitter (Tables on top | Graph below)
        self._table_splitter = QSplitter(Qt.Orientation.Vertical)
        self._table_splitter.setHandleWidth(6)
        self._table_splitter.setChildrenCollapsible(False)
        self._table_splitter.setStyleSheet(SPLITTER_STYLE)

        # Left-Top: Tables (Horizontal splitter: Notebooks | Concepts)
        tables_widget = self._build_tables_panel()
        self._table_splitter.addWidget(tables_widget)

        # Left-Bottom: D3.js Graph
        self.graph_view = QWebEngineView()
        self.graph_page = _WikiGraphPage(self.graph_view)
        self.graph_view.setPage(self.graph_page)
        self._table_splitter.addWidget(self.graph_view)

        self._table_splitter.setSizes([200, 300])  # Tables: 200px, Graph: 300px
        h_splitter.addWidget(self._table_splitter)

        # Right: Vertical Splitter (Detail browser on top | Q&A on bottom)
        v_splitter = QSplitter(Qt.Orientation.Vertical)
        v_splitter.setHandleWidth(6)
        v_splitter.setChildrenCollapsible(False)
        v_splitter.setStyleSheet(SPLITTER_STYLE)

        # Right-Top: Node Detail Browser
        self.detail_browser = QWebEngineView()
        self.detail_node_page = _WikiNodePage(self.detail_browser)
        self.detail_browser.setPage(self.detail_node_page)
        node_html = get_resource_path("wiki_node.html")
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

    def _build_tables_panel(self) -> QWidget:
        """Build the tables widget with Notebooks and Concepts side by side"""
        tables_widget = QWidget()
        layout = QHBoxLayout(tables_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Notebooks table
        self.nb_panel = self._make_table_panel("📓 Notebooks", "notebook")
        layout.addWidget(self.nb_panel, 1)

        # Concepts table
        self.concept_panel = self._make_table_panel("🔷 Concepts", "concept")
        layout.addWidget(self.concept_panel, 1)

        return tables_widget

    def _make_table_panel(self, title: str, node_type: str) -> QWidget:
        """Create a table panel with toggle button and QTableWidget"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Toggle button
        toggle_btn = QPushButton(f"{title} ▲")
        toggle_btn.setStyleSheet(
            "QPushButton { background: #2a3045; color: #e2e8f0; border: none; "
            "border-radius: 4px; padding: 6px 8px; font-weight: 600; font-size: 11px; text-align: left; }"
            "QPushButton:hover { background: #3d4558; }"
        )
        toggle_btn.setFixedHeight(28)
        layout.addWidget(toggle_btn)

        # Table widget
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["이름", "요약"])
        table.setColumnWidth(0, 100)

        # Make summary column stretch to fill available space
        from PyQt6.QtWidgets import QHeaderView
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setStyleSheet(
            "QTableWidget { background: #161922; color: #e2e8f0; border: 1px solid #2a3045; "
            "border-radius: 4px; gridline-color: #2a3045; }"
            "QHeaderView::section { background: #1e2330; color: #94a3b8; padding: 4px; "
            "border: none; font-weight: 600; font-size: 10px; }"
            "QTableWidget::item:selected { background: #4f8ef7; }"
            "QTableWidget::item { padding: 4px; }"
        )
        layout.addWidget(table)

        # Store references based on type
        if node_type == "notebook":
            self.nb_panel = panel
            self.nb_table = table
            self.nb_toggle_btn = toggle_btn
            self.nb_table_expanded = True
        else:  # concept
            self.concept_panel = panel
            self.concept_table = table
            self.concept_toggle_btn = toggle_btn
            self.concept_table_expanded = True

        # Connect toggle button (with default args to avoid lambda capture issues)
        toggle_btn.clicked.connect(
            lambda p=panel, t=table, b=toggle_btn, title_text=title, nt=node_type: self._toggle_table(
                p, t, b, self._table_splitter, title_text, nt
            )
        )

        # Connect table cell click (more reliable than itemSelectionChanged)
        table.cellClicked.connect(
            lambda row, col, nt=node_type: self._on_table_cell_clicked(row, nt)
        )

        return panel

    def _toggle_table(self, panel: QWidget, table: QTableWidget, btn: QPushButton,
                     splitter: QSplitter, title: str, node_type: str) -> None:
        """Toggle table visibility and update button icon"""
        try:
            is_expanded = table.isVisible()

            if is_expanded:
                # Collapse: hide table and adjust splitter
                table.setVisible(False)
                btn.setText(f"{title} ▼")

                # Get current splitter sizes
                sizes = splitter.sizes()
                if len(sizes) >= 2 and sizes[0] > 0:
                    # Make table area 0, graph takes all space
                    total = sizes[0] + sizes[1]
                    splitter.setSizes([0, total])
            else:
                # Expand: show table and adjust splitter
                table.setVisible(True)
                btn.setText(f"{title} ▲")

                # Get current splitter sizes
                sizes = splitter.sizes()
                if len(sizes) >= 2 and sizes[1] > 0:
                    # Restore table to ~200px, rest to graph
                    total = sizes[0] + sizes[1]
                    table_height = min(200, max(100, total // 3))
                    splitter.setSizes([table_height, total - table_height])
        except Exception as e:
            print(f"[Error] _toggle_table failed: {e}")
            import traceback
            traceback.print_exc()

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

        # Response (QWebEngineView for markdown rendering)
        self.qa_response = QWebEngineView()
        self.qa_response_page = _WikiQAPage(self.qa_response)
        self.qa_response.setPage(self.qa_response_page)
        qa_html = get_resource_path("wiki_qa.html")
        self.qa_response.setUrl(QUrl.fromLocalFile(str(qa_html)))
        self.qa_response.loadFinished.connect(self._on_qa_page_loaded)
        qa_layout.addWidget(self.qa_response, 1)

        # Input + Send row
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

        self.qa_send_btn = QPushButton("전송")
        self.qa_send_btn.setStyleSheet(BTN_STYLE)
        self.qa_send_btn.setFixedWidth(60)
        self.qa_send_btn.clicked.connect(self._on_send_qa)
        input_row.addWidget(self.qa_send_btn)

        qa_layout.addLayout(input_row)

        # Clear button row (right-aligned, transparent style)
        clear_row = QHBoxLayout()
        clear_row.setContentsMargins(0, 0, 0, 0)
        clear_row.addStretch()
        self.qa_clear_btn = QPushButton("🗑 대화 초기화")
        self.qa_clear_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #64748b; border: none; "
            "font-size: 10px; padding: 2px 6px; }"
            "QPushButton:hover { color: #94a3b8; }"
        )
        self.qa_clear_btn.clicked.connect(self._on_clear_qa)
        clear_row.addWidget(self.qa_clear_btn)
        qa_layout.addLayout(clear_row)

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
        escaped = json.dumps(self._qa_buffer)
        self._run_qa_js(f"streamingBuffer = {escaped}; renderStreamingBuffer();")

    def on_qa_finished(self, answer: str) -> None:
        """Q&A finished"""
        self._run_qa_js("finishAiMessage();")
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

        escaped_q = json.dumps(question)
        self._run_qa_js(f"appendUserMessage({escaped_q}); startAiMessage();")

        self.qa_input.setPlainText("")
        self.wiki_qa_requested.emit(question)

    def _on_clear_qa(self) -> None:
        """Clear Q&A conversation"""
        self._qa_buffer = ""
        self._run_qa_js("clearChat();")

    def _on_node_selected(self, node_data: dict) -> None:
        """Node clicked in graph"""
        # Display node detail
        self._display_node(node_data)

        # Sync table selection
        node_id = node_data.get("id", "")
        self._select_table_row(node_id)

    def _load_graph_html(self, graph_data: dict) -> None:
        """Load knowledge_graph.html and inject data"""
        html_path = get_resource_path("knowledge_graph.html")
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
        """Inject graph data into D3.js visualization and populate tables"""
        json_str = json.dumps(graph_data, ensure_ascii=False)
        js_code = f"loadGraphData({json_str})"
        self.graph_view.page().runJavaScript(js_code)

        # Populate tables with node data
        self._populate_tables(graph_data.get("nodes", []))

    def _on_qa_page_loaded(self, ok: bool) -> None:
        """Handle QA page load completion"""
        self._qa_page_loaded = ok
        for js in self._pending_qa_js:
            self.qa_response.page().runJavaScript(js)
        self._pending_qa_js.clear()

    def _run_qa_js(self, js: str) -> None:
        """Run JavaScript on QA page with load queue support"""
        if self._qa_page_loaded:
            self.qa_response.page().runJavaScript(js)
        else:
            self._pending_qa_js.append(js)

    # ── Table Interaction ─────────────────────────────────────────────────────

    def _populate_tables(self, nodes: list) -> None:
        """Populate Notebooks and Concepts tables from node data"""
        # Clear node map and tables
        self._node_map = {}
        self.nb_table.setRowCount(0)
        self.concept_table.setRowCount(0)

        # Sort nodes by label
        sorted_nodes = sorted(nodes, key=lambda n: n.get("label", "").lower())

        # Separate and populate tables
        for node in sorted_nodes:
            node_id = node.get("id", "")
            label = node.get("label", "")
            summary = node.get("summary", "")
            node_type = node.get("type", "concept")

            # Store in map
            self._node_map[node_id] = node

            # Truncate summary
            summary_text = summary[:80] if summary else "-"

            # Determine which table to add to
            table = self.nb_table if node_type == "notebook" else self.concept_table

            # Add row
            row = table.rowCount()
            table.insertRow(row)

            # Column 0: Name
            name_item = QTableWidgetItem(label)
            name_item.setData(Qt.ItemDataRole.UserRole, node_id)  # Store node_id
            table.setItem(row, 0, name_item)

            # Column 1: Summary
            summary_item = QTableWidgetItem(summary_text)
            summary_item.setData(Qt.ItemDataRole.UserRole, node_id)
            table.setItem(row, 1, summary_item)

        # Update table titles with counts
        nb_count = self.nb_table.rowCount()
        concept_count = self.concept_table.rowCount()
        self.nb_toggle_btn.setText(f"📓 Notebooks ({nb_count}) ▲")
        self.concept_toggle_btn.setText(f"🔷 Concepts ({concept_count}) ▲")

    def _on_table_cell_clicked(self, row: int, node_type: str) -> None:
        """Handle table cell click (cellClicked signal)"""
        # Determine which table was clicked
        table = self.nb_table if node_type == "notebook" else self.concept_table

        # Get node_id from the clicked row
        item = table.item(row, 0)
        if not item:
            return

        node_id = item.data(Qt.ItemDataRole.UserRole)
        if not node_id:
            return

        # Clear selection in other table
        other_table = self.concept_table if node_type == "notebook" else self.nb_table
        other_table.clearSelection()

        # Select this row in the current table
        table.selectRow(row)

        # Get node data and display
        if node_id in self._node_map:
            node_data = self._node_map[node_id]
            self._display_node(node_data)

    def _display_node(self, node_data: dict) -> None:
        """Display node detail in graph and detail browser"""
        node_id = node_data.get("id", "")
        label = node_data.get("label", "")
        node_type = node_data.get("type", "concept")
        content = node_data.get("content", "")

        # Update detail browser with node content
        escaped_content = json.dumps(content)
        escaped_label = json.dumps(label)
        escaped_type = json.dumps(node_type)
        self.detail_browser.page().runJavaScript(
            f"showNodeDetail({escaped_label}, {escaped_type}, {escaped_content})"
        )

        # Highlight node in graph and pan camera
        self.graph_view.page().runJavaScript(
            f"selectNodeExternal('{node_id}')"
        )

    def _select_table_row(self, node_id: str) -> None:
        """Select the table row corresponding to a graph node click"""
        if node_id not in self._node_map:
            return

        node_data = self._node_map[node_id]
        node_type = node_data.get("type", "concept")
        table = self.nb_table if node_type == "notebook" else self.concept_table

        # Find and select the row
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == node_id:
                table.selectRow(row)
                break

        # Clear other table
        other_table = self.concept_table if node_type == "notebook" else self.nb_table
        other_table.clearSelection()
