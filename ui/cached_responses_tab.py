"""
CachedResponsesTab - 캐시된 AI 응답 탐색/관리 탭
- 노트북별 서브탭: notebook_chat_cache.json 기반 트리 (노트북 → Q&A)
- 채팅 서브탭: chat_cache.jsonl 기반 시간순 리스트 (출처 노트북 칩 포함)

채팅/노트북 탭에서 emit하는 cache_updated 시그널 또는 QFileSystemWatcher로
실시간 갱신. 항목 삭제 시 entry_deleted 시그널을 emit해 원본 버블의 💾 버튼
상태를 동기화한다.
"""

import json
import os
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget, QTreeWidget,
    QTreeWidgetItem, QLineEdit, QPushButton, QComboBox, QListWidget,
    QListWidgetItem, QSplitter, QSizePolicy,
    QMessageBox, QApplication, QMenu,
)
from PyQt6.QtCore import Qt, pyqtSignal, QFileSystemWatcher, QTimer, QUrl
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage

from cache_store import NotebookChatCache, ChatCache


if getattr(sys, "frozen", False):
    _base = Path(sys._MEIPASS)
else:
    _base = Path(__file__).resolve().parent.parent
_VIEWER_HTML = _base / "resources" / "cached_response.html"


class _ExternalLinkPage(QWebEnginePage):
    """캐시 답변 내 링크 클릭을 시스템 브라우저로 라우팅."""

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


_TITLE_STYLE = "color: #e2e8f0; font-size: 14px; font-weight: 700;"
_SUB_STYLE   = "color: #94a3b8; font-size: 11px;"
_LINEEDIT_STYLE = (
    "QLineEdit { background: #1e2330; color: #e2e8f0; border: 1px solid #2a3045; "
    "border-radius: 4px; padding: 4px 8px; font-size: 12px; }"
    "QLineEdit:focus { border-color: #4f8ef7; }"
)
_BTN_STYLE = (
    "QPushButton { background: #4f8ef7; color: #fff; border: none; "
    "border-radius: 4px; padding: 4px 12px; font-size: 11px; font-weight: 600; }"
    "QPushButton:hover { background: #3b7be0; }"
    "QPushButton:disabled { background: #334155; color: #64748b; }"
)
_DEL_BTN_STYLE = (
    "QPushButton { background: #dc2626; color: #fff; border: none; "
    "border-radius: 4px; padding: 4px 12px; font-size: 11px; font-weight: 600; }"
    "QPushButton:hover { background: #b91c1c; }"
    "QPushButton:disabled { background: #334155; color: #64748b; }"
)
_COMBO_STYLE = (
    "QComboBox { background: #1e2330; color: #e2e8f0; border: 1px solid #2a3045; "
    "border-radius: 4px; padding: 3px 8px; font-size: 12px; min-width: 160px; }"
    "QComboBox::drop-down { border: none; }"
    "QComboBox QAbstractItemView { background: #1e2330; color: #e2e8f0; "
    "selection-background-color: #1e3a5f; }"
)
_TREE_STYLE = (
    "QTreeWidget { background: #0d0f14; border: 1px solid #2a3045; border-radius: 6px; "
    "color: #e2e8f0; font-size: 12px; }"
    "QTreeWidget::item { padding: 3px 4px; }"
    "QTreeWidget::item:selected { background: #1e3a5f; color: #93c5fd; }"
    "QHeaderView::section { background: #1e2330; color: #94a3b8; "
    "border: none; padding: 4px; font-size: 11px; }"
)
_LIST_STYLE = (
    "QListWidget { background: #0d0f14; border: 1px solid #2a3045; border-radius: 6px; "
    "color: #e2e8f0; font-size: 12px; outline: 0; }"
    "QListWidget::item { padding: 8px 10px; border-bottom: 1px solid #1a2030; }"
    "QListWidget::item:selected { background: #1e3a5f; color: #93c5fd; }"
)


class CachedResponsesTab(QWidget):
    """캐시된 AI 응답 탐색/관리 탭."""

    # scope: "notebook" | "chat"  ;  entry_id
    entry_deleted = pyqtSignal(str, str)

    def __init__(self, cache_dir: str = ".rag_cache"):
        super().__init__()
        self._cache_dir = cache_dir
        self._nb_cache = NotebookChatCache(cache_dir)
        self._chat_cache = ChatCache(cache_dir)

        self._nb_data: dict = {}
        self._chat_data: list = []
        self._selected_nb_entry: tuple | None = None  # (notebook, entry_id)
        self._selected_chat_id: str | None = None

        self._nb_page_loaded = False
        self._nb_pending_payload: dict | None = None
        self._chat_page_loaded = False
        self._chat_pending_payload: dict | None = None

        self._nb_expanded_set: set[str] = set()

        self._watcher: QFileSystemWatcher | None = None

        self._build_ui()
        self._setup_watcher()
        self.refresh()

    # ── 외부 API ──────────────────────────────────────────────────────────────

    def set_cache_dir(self, cache_dir: str):
        if cache_dir == self._cache_dir:
            return
        self._cache_dir = cache_dir
        self._nb_cache = NotebookChatCache(cache_dir)
        self._chat_cache = ChatCache(cache_dir)
        self._setup_watcher()
        self.refresh()

    def refresh(self):
        self._nb_data = self._nb_cache.get_all()
        self._chat_data = self._chat_cache.iter_entries()

        # 채팅 출처 필터 옵션 갱신
        cur = self._chat_filter.currentData() if self._chat_filter.count() else ""
        self._chat_filter.blockSignals(True)
        self._chat_filter.clear()
        self._chat_filter.addItem("전체", "")
        for nb in self._chat_cache.source_notebook_set():
            self._chat_filter.addItem(nb, nb)
        idx = self._chat_filter.findData(cur or "")
        if idx >= 0:
            self._chat_filter.setCurrentIndex(idx)
        self._chat_filter.blockSignals(False)

        self._render_nb_tree()
        self._render_chat_list()
        self._setup_watcher()
        self._update_count()

    # ── UI 빌드 ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(6)

        title = QLabel("💾  캐시 응답")
        title.setStyleSheet(_TITLE_STYLE)
        layout.addWidget(title)

        info = QLabel("저장한 AI 응답을 탐색·삭제합니다. 채팅·노트북 셀 Q&A에서 💾 버튼으로 저장.")
        info.setStyleSheet(_SUB_STYLE)
        layout.addWidget(info)

        self._inner_tabs = QTabWidget()
        self._inner_tabs.setStyleSheet(
            "QTabWidget::pane { border: 1px solid #2a3045; border-radius: 6px; "
            "background: #0d0f14; top: -1px; }"
            "QTabBar::tab { background: #161922; color: #64748b; "
            "padding: 6px 14px; border: none; font-size: 12px; }"
            "QTabBar::tab:selected { background: #1e2330; color: #e2e8f0; "
            "border-bottom: 2px solid #4f8ef7; }"
            "QTabBar::tab:hover { background: #1e2330; color: #94a3b8; }"
        )

        self._build_notebook_subtab()
        self._build_chat_subtab()

        self._inner_tabs.addTab(self._nb_subtab, "📓  노트북별")
        self._inner_tabs.addTab(self._chat_subtab, "💬  채팅")

        layout.addWidget(self._inner_tabs, 1)

        self._count_label = QLabel("")
        self._count_label.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self._count_label)

    def _build_notebook_subtab(self):
        self._nb_subtab = QWidget()
        v = QVBoxLayout(self._nb_subtab)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._nb_search = QLineEdit()
        self._nb_search.setPlaceholderText("질문/답변 검색…")
        self._nb_search.setStyleSheet(_LINEEDIT_STYLE)
        self._nb_search.textChanged.connect(self._render_nb_tree)
        row.addWidget(self._nb_search, 1)

        self._nb_clear_all_btn = QPushButton("🗑 전체 삭제")
        self._nb_clear_all_btn.setStyleSheet(_DEL_BTN_STYLE)
        self._nb_clear_all_btn.clicked.connect(self._on_nb_clear_all)
        row.addWidget(self._nb_clear_all_btn)

        v.addLayout(row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background: #2a3045; }")

        self._nb_tree = QTreeWidget()
        self._nb_tree.setHeaderLabels(["노트북 / 질문", "시간", "셀"])
        self._nb_tree.setColumnWidth(0, 200)
        self._nb_tree.setColumnWidth(1, 110)
        self._nb_tree.setStyleSheet(_TREE_STYLE)
        self._nb_tree.itemSelectionChanged.connect(self._on_nb_selection)
        self._nb_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._nb_tree.customContextMenuRequested.connect(self._on_nb_context_menu)
        self._nb_tree.itemExpanded.connect(self._on_nb_item_expanded)
        self._nb_tree.itemCollapsed.connect(self._on_nb_item_collapsed)
        self._nb_tree.itemClicked.connect(self._on_nb_item_clicked)
        splitter.addWidget(self._nb_tree)

        detail_panel = QWidget()
        dl = QVBoxLayout(detail_panel)
        dl.setContentsMargins(0, 4, 0, 0)
        dl.setSpacing(4)

        self._nb_detail = QWebEngineView()
        self._nb_detail.setPage(_ExternalLinkPage(self._nb_detail))
        self._nb_detail.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._nb_detail.setUrl(QUrl.fromLocalFile(str(_VIEWER_HTML.resolve())))
        self._nb_detail.loadFinished.connect(self._on_nb_page_loaded)
        dl.addWidget(self._nb_detail, 1)

        btn_row = QHBoxLayout()
        self._nb_copy_btn = QPushButton("📋 답변 복사 (MD)")
        self._nb_copy_btn.setStyleSheet(_BTN_STYLE)
        self._nb_copy_btn.setEnabled(False)
        self._nb_copy_btn.clicked.connect(self._on_nb_copy)
        btn_row.addWidget(self._nb_copy_btn)

        self._nb_delete_btn = QPushButton("🗑 이 항목 삭제")
        self._nb_delete_btn.setStyleSheet(_DEL_BTN_STYLE)
        self._nb_delete_btn.setEnabled(False)
        self._nb_delete_btn.clicked.connect(self._on_nb_delete_selected)
        btn_row.addWidget(self._nb_delete_btn)

        btn_row.addStretch()
        dl.addLayout(btn_row)

        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([320, 600])

        v.addWidget(splitter, 1)

    def _build_chat_subtab(self):
        self._chat_subtab = QWidget()
        v = QVBoxLayout(self._chat_subtab)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._chat_search = QLineEdit()
        self._chat_search.setPlaceholderText("질문/답변 검색…")
        self._chat_search.setStyleSheet(_LINEEDIT_STYLE)
        self._chat_search.textChanged.connect(self._render_chat_list)
        row.addWidget(self._chat_search, 1)

        filter_label = QLabel("출처:")
        filter_label.setStyleSheet(_SUB_STYLE)
        row.addWidget(filter_label)

        self._chat_filter = QComboBox()
        self._chat_filter.setStyleSheet(_COMBO_STYLE)
        self._chat_filter.addItem("전체", "")
        self._chat_filter.currentIndexChanged.connect(self._render_chat_list)
        row.addWidget(self._chat_filter)

        self._chat_clear_all_btn = QPushButton("🗑 전체 삭제")
        self._chat_clear_all_btn.setStyleSheet(_DEL_BTN_STYLE)
        self._chat_clear_all_btn.clicked.connect(self._on_chat_clear_all)
        row.addWidget(self._chat_clear_all_btn)

        v.addLayout(row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background: #2a3045; }")

        self._chat_list = QListWidget()
        self._chat_list.setStyleSheet(_LIST_STYLE)
        self._chat_list.itemSelectionChanged.connect(self._on_chat_selection)
        splitter.addWidget(self._chat_list)

        detail_panel = QWidget()
        dl = QVBoxLayout(detail_panel)
        dl.setContentsMargins(0, 4, 0, 0)
        dl.setSpacing(4)

        self._chat_detail = QWebEngineView()
        self._chat_detail.setPage(_ExternalLinkPage(self._chat_detail))
        self._chat_detail.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._chat_detail.setUrl(QUrl.fromLocalFile(str(_VIEWER_HTML.resolve())))
        self._chat_detail.loadFinished.connect(self._on_chat_page_loaded)
        dl.addWidget(self._chat_detail, 1)

        btn_row = QHBoxLayout()
        self._chat_copy_btn = QPushButton("📋 답변 복사 (MD)")
        self._chat_copy_btn.setStyleSheet(_BTN_STYLE)
        self._chat_copy_btn.setEnabled(False)
        self._chat_copy_btn.clicked.connect(self._on_chat_copy)
        btn_row.addWidget(self._chat_copy_btn)

        self._chat_delete_btn = QPushButton("🗑 이 항목 삭제")
        self._chat_delete_btn.setStyleSheet(_DEL_BTN_STYLE)
        self._chat_delete_btn.setEnabled(False)
        self._chat_delete_btn.clicked.connect(self._on_chat_delete_selected)
        btn_row.addWidget(self._chat_delete_btn)

        btn_row.addStretch()
        dl.addLayout(btn_row)

        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([320, 600])

        v.addWidget(splitter, 1)

    # ── 파일 시스템 감시 ─────────────────────────────────────────────────────

    def _setup_watcher(self):
        if self._watcher is None:
            self._watcher = QFileSystemWatcher(self)
            self._watcher.fileChanged.connect(self._on_cache_file_changed)
            self._watcher.directoryChanged.connect(self._on_cache_file_changed)
        try:
            cur_dirs = self._watcher.directories()
            if cur_dirs:
                self._watcher.removePaths(cur_dirs)
            cur_files = self._watcher.files()
            if cur_files:
                self._watcher.removePaths(cur_files)
        except Exception:
            pass

        if os.path.isdir(self._cache_dir):
            self._watcher.addPath(self._cache_dir)
        for p in (self._nb_cache.path, self._chat_cache.path):
            if p.exists():
                self._watcher.addPath(str(p))

    def _on_cache_file_changed(self, _path: str):
        # 디바운싱: 짧은 시간에 여러 이벤트가 묶일 수 있음
        QTimer.singleShot(150, self.refresh)

    # ── 카운트 ────────────────────────────────────────────────────────────────

    def _update_count(self):
        nb_total = sum(len(v) for v in self._nb_data.values())
        chat_total = len(self._chat_data)
        self._count_label.setText(
            f"노트북 캐시: {nb_total}건 ({len(self._nb_data)}개 노트북) · 채팅 캐시: {chat_total}건"
        )

    # ── 노트북 서브탭 ────────────────────────────────────────────────────────

    def _render_nb_tree(self):
        query = self._nb_search.text().strip().lower()
        prev_sel = self._selected_nb_entry

        self._nb_tree.clear()
        for nb in sorted(self._nb_data.keys()):
            entries = self._nb_data[nb]
            if query:
                entries = [
                    e for e in entries
                    if query in (e.get("question", "") + e.get("answer", "")).lower()
                ]
                if not entries:
                    continue
            top = QTreeWidgetItem([f"📓  {nb}", "", f"{len(entries)}건"])
            top.setForeground(0, QColor("#60a5fa"))
            top.setData(0, Qt.ItemDataRole.UserRole, ("nb", nb))
            for e in sorted(entries, key=lambda x: x.get("ts", ""), reverse=True):
                q_preview = (e.get("question") or "").splitlines()[0][:80]
                ts = (e.get("ts") or "").replace("T", " ")
                cells = e.get("cell_indices") or []
                cells_text = (",".join(str(c) for c in cells[:3])
                              + ("…" if len(cells) > 3 else "")) if cells else "—"
                child = QTreeWidgetItem([f"💬  {q_preview or '(질문 없음)'}", ts, cells_text])
                child.setForeground(0, QColor("#e2e8f0"))
                child.setData(0, Qt.ItemDataRole.UserRole,
                              ("entry", nb, e.get("id"), e))
                top.addChild(child)
            self._nb_tree.addTopLevelItem(top)
            top.setExpanded(nb in self._nb_expanded_set)

        if prev_sel:
            for i in range(self._nb_tree.topLevelItemCount()):
                top = self._nb_tree.topLevelItem(i)
                for j in range(top.childCount()):
                    child = top.child(j)
                    data = child.data(0, Qt.ItemDataRole.UserRole)
                    if data and data[0] == "entry" and (data[1], data[2]) == prev_sel:
                        self._nb_tree.setCurrentItem(child)
                        return
        self._update_nb_detail(None)

    def _on_nb_selection(self):
        item = self._nb_tree.currentItem()
        if not item:
            self._update_nb_detail(None)
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data[0] != "entry":
            self._update_nb_detail(None)
            return
        _kind, nb, _entry_id, entry = data
        self._update_nb_detail(entry, nb)

    def _on_nb_page_loaded(self, ok: bool):
        if not ok:
            return
        self._nb_page_loaded = True
        if self._nb_pending_payload is None:
            self._nb_detail.page().runJavaScript("clearViewer();")
        else:
            self._send_nb_payload(self._nb_pending_payload)
            self._nb_pending_payload = None

    def _send_nb_payload(self, payload: dict | None):
        if payload is None:
            js = "clearViewer();"
        else:
            js = f"renderEntry({json.dumps(payload, ensure_ascii=False)});"
        self._nb_detail.page().runJavaScript(js)

    def _update_nb_detail(self, entry: dict | None, nb: str = ""):
        if not entry:
            if self._nb_page_loaded:
                self._send_nb_payload(None)
            else:
                self._nb_pending_payload = None
            self._nb_copy_btn.setEnabled(False)
            self._nb_delete_btn.setEnabled(False)
            self._selected_nb_entry = None
            return
        self._selected_nb_entry = (nb, entry.get("id"))
        self._nb_copy_btn.setEnabled(True)
        self._nb_delete_btn.setEnabled(True)

        payload = {
            "kind": "notebook",
            "notebook": nb or "",
            "ts": (entry.get("ts") or "").replace("T", " "),
            "cells": entry.get("cell_indices") or [],
            "question": entry.get("question") or "",
            "answer": entry.get("answer") or "",
        }
        if self._nb_page_loaded:
            self._send_nb_payload(payload)
        else:
            self._nb_pending_payload = payload

    def _on_nb_context_menu(self, pos):
        item = self._nb_tree.itemAt(pos)
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        menu = QMenu(self)
        if data[0] == "nb":
            nb = data[1]
            act = menu.addAction(f"이 노트북 캐시 모두 삭제 ({nb})")
            act.triggered.connect(lambda: self._delete_nb_all(nb))
        elif data[0] == "entry":
            _kind, nb, eid, _e = data
            act = menu.addAction("이 항목 삭제")
            act.triggered.connect(lambda: self._delete_nb_entry(nb, eid))
        menu.exec(self._nb_tree.viewport().mapToGlobal(pos))

    def _on_nb_item_clicked(self, item: QTreeWidgetItem, column: int):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "nb":
            item.setExpanded(not item.isExpanded())

    def _on_nb_item_expanded(self, item: QTreeWidgetItem):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "nb":
            self._nb_expanded_set.add(data[1])

    def _on_nb_item_collapsed(self, item: QTreeWidgetItem):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "nb":
            self._nb_expanded_set.discard(data[1])

    def _on_nb_copy(self):
        if not self._selected_nb_entry:
            return
        nb, eid = self._selected_nb_entry
        for entry in self._nb_data.get(nb, []):
            if entry.get("id") == eid:
                QApplication.clipboard().setText(entry.get("answer") or "")
                self._nb_copy_btn.setText("✓ 복사됨")
                QTimer.singleShot(1500,
                    lambda: self._nb_copy_btn.setText("📋 답변 복사 (MD)"))
                return

    def _on_nb_delete_selected(self):
        if not self._selected_nb_entry:
            return
        nb, eid = self._selected_nb_entry
        self._delete_nb_entry(nb, eid)

    def _delete_nb_entry(self, nb: str, entry_id: str):
        if self._nb_cache.delete(nb, entry_id):
            self.entry_deleted.emit("notebook", entry_id)
            self.refresh()

    def _delete_nb_all(self, nb: str):
        ret = QMessageBox.question(
            self, "삭제 확인",
            f"{nb} 노트북의 모든 캐시 항목을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        ids = [e.get("id") for e in self._nb_data.get(nb, [])]
        if self._nb_cache.delete_notebook(nb):
            for eid in ids:
                if eid:
                    self.entry_deleted.emit("notebook", eid)
            self.refresh()

    def _on_nb_clear_all(self):
        if not self._nb_data:
            return
        ret = QMessageBox.question(
            self, "삭제 확인",
            "모든 노트북별 캐시 항목을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        all_ids = [e.get("id") for entries in self._nb_data.values() for e in entries]
        self._nb_cache.delete_all()
        for eid in all_ids:
            if eid:
                self.entry_deleted.emit("notebook", eid)
        self.refresh()

    # ── 채팅 서브탭 ──────────────────────────────────────────────────────────

    def _render_chat_list(self):
        prev_sel = self._selected_chat_id
        query = self._chat_search.text().strip().lower()
        nb_filter = self._chat_filter.currentData() if self._chat_filter.count() else ""

        self._chat_list.blockSignals(True)
        self._chat_list.clear()

        sel_idx = -1
        for entry in self._chat_data:
            if query:
                blob = (entry.get("query", "") + entry.get("answer", "")).lower()
                if query not in blob:
                    continue
            if nb_filter:
                srcs = entry.get("source_notebooks") or []
                if nb_filter not in srcs:
                    continue

            ts = (entry.get("ts") or "").replace("T", " ")
            mode = entry.get("mode", "rag")
            mode_tag = "  🔍 Force" if mode == "force" else ""
            q_preview = (entry.get("query") or "").splitlines()[0][:120]
            srcs = entry.get("source_notebooks") or []
            srcs_str = "  ".join(f"📓 {s}" for s in srcs[:3])
            if len(srcs) > 3:
                srcs_str += f"  +{len(srcs)-3}"
            elif not srcs:
                srcs_str = "(출처 없음)"

            text = f"🕒 {ts}{mode_tag}\n💬 {q_preview}\n{srcs_str}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, entry.get("id"))
            self._chat_list.addItem(item)
            if entry.get("id") == prev_sel:
                sel_idx = self._chat_list.count() - 1

        self._chat_list.blockSignals(False)

        if sel_idx >= 0:
            self._chat_list.setCurrentRow(sel_idx)
        else:
            self._update_chat_detail(None)

    def _on_chat_selection(self):
        item = self._chat_list.currentItem()
        if not item:
            self._update_chat_detail(None)
            return
        eid = item.data(Qt.ItemDataRole.UserRole)
        entry = next((e for e in self._chat_data if e.get("id") == eid), None)
        self._update_chat_detail(entry)

    def _on_chat_page_loaded(self, ok: bool):
        if not ok:
            return
        self._chat_page_loaded = True
        if self._chat_pending_payload is None:
            self._chat_detail.page().runJavaScript("clearViewer();")
        else:
            self._send_chat_payload(self._chat_pending_payload)
            self._chat_pending_payload = None

    def _send_chat_payload(self, payload: dict | None):
        if payload is None:
            js = "clearViewer();"
        else:
            js = f"renderEntry({json.dumps(payload, ensure_ascii=False)});"
        self._chat_detail.page().runJavaScript(js)

    def _update_chat_detail(self, entry: dict | None):
        if not entry:
            if self._chat_page_loaded:
                self._send_chat_payload(None)
            else:
                self._chat_pending_payload = None
            self._chat_copy_btn.setEnabled(False)
            self._chat_delete_btn.setEnabled(False)
            self._selected_chat_id = None
            return
        self._selected_chat_id = entry.get("id")
        self._chat_copy_btn.setEnabled(True)
        self._chat_delete_btn.setEnabled(True)

        payload = {
            "kind": "chat",
            "ts": (entry.get("ts") or "").replace("T", " "),
            "mode": entry.get("mode", "rag"),
            "sources": entry.get("source_notebooks") or [],
            "question": entry.get("query") or "",
            "answer": entry.get("answer") or "",
        }
        if self._chat_page_loaded:
            self._send_chat_payload(payload)
        else:
            self._chat_pending_payload = payload

    def _on_chat_copy(self):
        if not self._selected_chat_id:
            return
        entry = next(
            (e for e in self._chat_data if e.get("id") == self._selected_chat_id), None
        )
        if not entry:
            return
        QApplication.clipboard().setText(entry.get("answer") or "")
        self._chat_copy_btn.setText("✓ 복사됨")
        QTimer.singleShot(1500,
            lambda: self._chat_copy_btn.setText("📋 답변 복사 (MD)"))

    def _on_chat_delete_selected(self):
        if not self._selected_chat_id:
            return
        eid = self._selected_chat_id
        if self._chat_cache.delete(eid):
            self.entry_deleted.emit("chat", eid)
            self.refresh()

    def _on_chat_clear_all(self):
        if not self._chat_data:
            return
        ret = QMessageBox.question(
            self, "삭제 확인",
            "채팅 캐시 전체를 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        ids = [e.get("id") for e in self._chat_data]
        self._chat_cache.delete_all()
        for eid in ids:
            if eid:
                self.entry_deleted.emit("chat", eid)
        self.refresh()

