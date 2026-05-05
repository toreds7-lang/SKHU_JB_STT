"""
MainWindow - 메인 윈도우
QMainWindow + QSplitter (좌: ConfigPanel | 우: QTabWidget 5탭)
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QTabWidget,
    QMessageBox, QLabel
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon

from ui.config_panel   import ConfigPanel
from ui.chat_tab       import ChatTab
from ui.docs_tab       import DocsTab
from ui.graph_tab      import GraphTab
from ui.notebook_tab   import NotebookTab
from ui.dir_tab        import DirTab
from ui.cached_responses_tab import CachedResponsesTab
from workers.llm_worker import (
    RagBuildWorker, LLMWorker, ForceWorker,
    ExampleQuestionsWorker, SuggestedQueriesWorker, SummaryWorker,
    NotebookChatWorker,
)


@dataclass
class AppState:
    messages:           list[dict]  = field(default_factory=list)
    rag_sys:            Any         = None
    agent:              Any         = None
    llm:                Any         = None
    sys_prompt:         str         = ""
    llm_only_prompt:    str         = ""
    suggested_queries:  list[str]   = field(default_factory=list)
    example_questions:  list[str]   = field(default_factory=list)
    dir_hash:           str         = ""
    nb_dir_used:        str         = ""
    rag_ready:          bool        = False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.state = AppState()
        self._rag_worker:     RagBuildWorker | None = None
        self._llm_worker:     LLMWorker | None = None
        self._force_worker:   ForceWorker | None = None
        self._eq_worker:      ExampleQuestionsWorker | None = None
        self._sq_worker:      SuggestedQueriesWorker | None = None
        self._summary_worker: SummaryWorker | None = None
        self._nb_chat_worker: NotebookChatWorker | None = None
        self._last_config:    dict = {}
        self._init_ui()
        self._connect_signals()
        self._propagate_stt_language(self.config_panel.get_config().get("stt_language", "ko"))

    def _init_ui(self):
        self.setWindowTitle("SKHU Agent V1.0   박종범 강사(jongbum3.park@sk.com)")
        self.resize(1400, 900)

        # 아이콘
        icon_path = Path("SK_Hynix.png")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        central = QWidget()
        self.setCentralWidget(central)

        from PyQt6.QtWidgets import QHBoxLayout
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── 좌측: 설정 패널 ───────────────────────────────────────────────────
        self.config_panel = ConfigPanel()
        splitter.addWidget(self.config_panel)

        # ── 우측: 탭 위젯 ─────────────────────────────────────────────────────
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet(
            "QTabWidget::pane { border: none; background: #0d0f14; }"
            "QTabBar::tab { background: #161922; color: #64748b; "
            "padding: 8px 16px; border: none; font-size: 12px; }"
            "QTabBar::tab:selected { background: #1e2330; color: #e2e8f0; "
            "border-bottom: 2px solid #4f8ef7; }"
            "QTabBar::tab:hover { background: #1e2330; color: #94a3b8; }"
        )

        self.chat_tab     = ChatTab()
        self.docs_tab     = DocsTab()
        self.graph_tab    = GraphTab()
        self.notebook_tab = NotebookTab()
        self.dir_tab      = DirTab()
        self.cached_tab   = CachedResponsesTab()

        self.tab_widget.addTab(self.notebook_tab, "📓  노트북 뷰어")
        self.tab_widget.addTab(self.chat_tab,     "💬  채팅")
        self.tab_widget.addTab(self.docs_tab,     "📄  문서 탐색")
        self.tab_widget.addTab(self.graph_tab,    "🕸️  그래프 탐색")
        self.tab_widget.addTab(self.dir_tab,      "📁  디렉토리")
        self.tab_widget.addTab(self.cached_tab,   "💾  캐시 응답")

        self.tab_widget.tabBar().setTabVisible(2, False)  # 문서 탐색
        self.tab_widget.tabBar().setTabVisible(3, False)  # 그래프 탐색

        splitter.addWidget(self.tab_widget)
        splitter.setSizes([260, 1140])
        main_layout.addWidget(splitter)

        # ── 상태 바 ───────────────────────────────────────────────────────────
        self.statusBar().showMessage("⚠️  RAG 시스템을 초기화해 주세요. ← 좌측 설정 패널에서 구성 후 빌드하세요.")
        self.statusBar().setStyleSheet(
            "QStatusBar { background: #2d2a10; color: #fde68a; "
            "border-top: 1px solid #854d0e; font-size: 12px; font-weight: 600; padding: 4px 10px; }"
        )

        # ── 파일 변경 감지 타이머 (30초) ─────────────────────────────────────
        self._dir_watch_timer = QTimer()
        self._dir_watch_timer.setInterval(30_000)
        self._dir_watch_timer.timeout.connect(self._check_dir_hash)

    def _connect_signals(self):
        self.config_panel.build_requested.connect(self._on_build_rag)
        self.chat_tab.query_submitted.connect(self._on_query)
        self.chat_tab.force_stop_requested.connect(self._on_force_stop)
        self.chat_tab.llm_stop_requested.connect(self._on_llm_stop)
        self.notebook_tab.summary_requested.connect(self._on_summary_requested)
        self.notebook_tab.stop_requested.connect(self._on_summary_stop)
        self.notebook_tab.notebook_chat_requested.connect(self._on_notebook_chat)
        self.notebook_tab.notebook_chat_stop.connect(self._on_notebook_chat_stop)
        self.config_panel.stt_language_combo.currentIndexChanged.connect(
            lambda: self._propagate_stt_language(self.config_panel.stt_language_combo.currentData())
        )

        # 캐시 응답 동기화 (실시간)
        self.notebook_tab.cache_updated.connect(self.cached_tab.refresh)
        self.chat_tab.cache_updated.connect(self.cached_tab.refresh)
        self.cached_tab.entry_deleted.connect(self.notebook_tab.on_cache_entry_deleted)
        self.cached_tab.entry_deleted.connect(self.chat_tab.on_cache_entry_deleted)

    def _propagate_stt_language(self, language: str):
        self.chat_tab.set_stt_language(language)
        self.notebook_tab.set_stt_language(language)

    # ── RAG 빌드 ─────────────────────────────────────────────────────────────

    def _on_build_rag(self, config: dict):
        self._last_config = config

        # 기존 워커 정리
        if self._rag_worker and self._rag_worker.isRunning():
            return

        # 재구축 여부 (RAG 이미 구축된 상태면 캐시 삭제)
        clear_cache = self.state.rag_ready

        self.config_panel.set_build_enabled(False)
        self.statusBar().showMessage("RAG 시스템 구축 중…")

        self._rag_worker = RagBuildWorker(
            nb_dir      = config["nb_dir"],
            emb_base_url = config["emb_base_url"],
            emb_api_key = config["emb_api_key"],
            cache_dir   = config["cache_dir"],
            emb_model   = config["emb_model"],
            clear_cache = clear_cache,
        )
        self._rag_worker.progress_signal.connect(self.config_panel.status_label.setText)
        self._rag_worker.progress_signal.connect(lambda m: self.statusBar().showMessage(m))
        self._rag_worker.finished_signal.connect(self._on_rag_ready)
        self._rag_worker.error_signal.connect(self._on_rag_error)
        self._rag_worker.start()

    def _on_rag_ready(self, rag_sys):
        if rag_sys is None:
            self._on_rag_error("노트북 파일을 찾을 수 없습니다.")
            return

        cfg = self._last_config
        self.state.rag_sys = rag_sys

        # LangGraph 에이전트 생성
        from rag_core import make_agent, get_dir_hash
        agent, llm, sys_prompt, llm_only_prompt = make_agent(
            llm_base_url = cfg["llm_base_url"],
            llm_api_key  = cfg["llm_api_key"],
            llm_model    = cfg["llm_model"],
            rag_sys      = rag_sys,
        )
        self.state.agent          = agent
        self.state.llm            = llm
        self.state.sys_prompt     = sys_prompt
        self.state.llm_only_prompt = llm_only_prompt
        self.state.rag_ready      = True
        self.state.nb_dir_used    = cfg["nb_dir"]
        self.state.dir_hash       = get_dir_hash(cfg["nb_dir"])

        # 탭 데이터 주입
        self.config_panel.update_stats(rag_sys)
        self.config_panel.mark_rag_ready()
        self.docs_tab.load_cells(rag_sys["cells"])
        # 캐시 디렉토리 전파 (notebook_tab은 set_cache_dir() 별도, chat/cached는 새로 추가)
        self.chat_tab.set_cache_dir(cfg["cache_dir"])
        self.cached_tab.set_cache_dir(cfg["cache_dir"])
        self.graph_tab.load_graph(rag_sys["graph"])
        self.notebook_tab.set_cache_dir(cfg["cache_dir"])
        self.notebook_tab.load_cells(rag_sys["cells"])
        self.dir_tab.load_tree(cfg["nb_dir"], rag_sys["cells"])
        nb_names = sorted({c["notebook"] for c in rag_sys["cells"]})
        self.chat_tab.load_notebooks(nb_names)

        self.statusBar().showMessage(
            f"✅ 준비 완료 — 노트북 {rag_sys['nb_count']}개, 셀 {rag_sys['cell_count']}개 인덱싱"
        )

        # 예시 질문 백그라운드 생성
        self._eq_worker = ExampleQuestionsWorker(llm, rag_sys["docs"])
        self._eq_worker.finished_signal.connect(self.chat_tab.update_example_chips)
        self._eq_worker.start()

        # 파일 변경 감지 시작
        self._dir_watch_timer.start()

    def _on_rag_error(self, msg: str):
        self.config_panel.set_build_enabled(True)
        self.config_panel.status_label.setText(f"❌ {msg}")
        self.statusBar().showMessage(f"오류: {msg}")
        QMessageBox.critical(self, "RAG 구축 오류", msg)

    # ── 쿼리 처리 ────────────────────────────────────────────────────────────

    @staticmethod
    def _detect_force_mode(query: str):
        """'/f 질문' 형태 감지. Force Mode면 (True, 질문), 아니면 (False, query)."""
        q = query.strip()
        # 다양한 슬래시 변형을 반각으로 통일 (전각／, 나눗셈∕, fraction⁄ 등)
        q = re.sub(r'^[／∕⁄]', '/', q)
        if q.lower().startswith("/f ") or (q.lower().startswith("/f") and len(q) > 2):
            return True, q[2:].strip()
        return False, query

    def _on_query(self, query: str, is_suggested: bool):
        if self._llm_worker and self._llm_worker.isRunning():
            return
        if self._force_worker and self._force_worker.isRunning():
            return

        # /f 감지
        is_force, actual_query = self._detect_force_mode(query)

        if is_force:
            # Force Mode는 LLM만 필요 (RAG 인덱스 불필요)
            if not self.state.llm:
                QMessageBox.information(
                    self, "알림",
                    "LLM이 설정되지 않았습니다. RAG 시스템을 먼저 구축해 주세요."
                )
                return

            cfg = self._last_config
            nb_dir = cfg.get("nb_dir", self.state.nb_dir_used or "work")

            self.chat_tab.start_force_mode(actual_query)

            force_workers = self.config_panel.get_config().get("force_workers", 3)
            self._force_worker = ForceWorker(
                llm         = self.state.llm,
                query       = actual_query,
                nb_dir      = nb_dir,
                max_workers = force_workers,
            )
            self._force_worker.progress_signal.connect(self.chat_tab.update_force_progress)
            self._force_worker.preview_signal.connect(self.chat_tab.update_force_preview)
            self._force_worker.finished_signal.connect(self._on_force_finished)
            self._force_worker.error_signal.connect(self.chat_tab.on_error)
            self._force_worker.start()
            return

        # 일반 RAG 쿼리 (/lec 포함)
        if not self.state.rag_ready:
            QMessageBox.information(self, "알림", "먼저 RAG 시스템을 구축해 주세요.")
            return

        cfg = self._last_config
        retrieval_mode = cfg.get("retrieval_mode", "all")

        self.chat_tab.start_streaming(query)

        conversation_history = self.chat_tab.get_history_for_llm(max_turns=3)

        self._llm_worker = LLMWorker(
            agent                = self.state.agent,
            llm                  = self.state.llm,
            sys_prompt           = self.state.sys_prompt,
            llm_only_prompt      = self.state.llm_only_prompt,
            query                = query,
            retrieval_mode       = retrieval_mode,
            is_suggested         = is_suggested,
            conversation_history = conversation_history,
        )
        self._llm_worker.status_signal.connect(self.chat_tab.status_label.setText)
        self._llm_worker.chunk_received.connect(self.chat_tab.on_chunk_received)
        self._llm_worker.finished_signal.connect(self._on_llm_finished)
        self._llm_worker.error_signal.connect(self.chat_tab.on_error)
        self._llm_worker.start()

    def _on_force_finished(self, answer: str):
        self.chat_tab.finish_force_mode(answer)

    def _on_force_stop(self):
        if self._force_worker and self._force_worker.isRunning():
            self._force_worker.stop()

    def _on_llm_stop(self):
        if self._llm_worker and self._llm_worker.isRunning():
            self._llm_worker.stop()

    def _on_llm_finished(self, answer: str, result: dict):
        self.chat_tab.on_streaming_finished(answer, result)

        # 후속 쿼리 생성 (답변이 있을 때만)
        if answer and "🔍 관련 문서를" not in answer:
            last_query = ""
            for msg in reversed(self.chat_tab._messages):
                if msg["role"] == "user":
                    last_query = msg["content"]
                    break
            if last_query and self.state.llm:
                self._sq_worker = SuggestedQueriesWorker(
                    self.state.llm, last_query, answer
                )
                self._sq_worker.finished_signal.connect(
                    self.chat_tab.update_suggested_chips
                )
                self._sq_worker.start()

    # ── 노트북 요약 ──────────────────────────────────────────────────────────

    def _on_summary_requested(self, notebooks: dict):
        if not self.state.llm:
            QMessageBox.information(self, "알림", "LLM이 설정되지 않았습니다.")
            self.notebook_tab.on_error("LLM이 설정되지 않았습니다.")
            return
        if self._summary_worker and self._summary_worker.isRunning():
            return

        self._summary_worker = SummaryWorker(
            llm=self.state.llm,
            notebooks=notebooks,
        )
        self._summary_worker.progress_signal.connect(self.notebook_tab.update_progress)
        self._summary_worker.summary_signal.connect(self.notebook_tab.set_summary)
        self._summary_worker.finished_signal.connect(self.notebook_tab.on_generation_finished)
        self._summary_worker.error_signal.connect(self.notebook_tab.on_error)
        self._summary_worker.start()

    def _on_summary_stop(self):
        if self._summary_worker and self._summary_worker.isRunning():
            self._summary_worker.stop()

    # ── 노트북 셀 채팅 ──────────────────────────────────────────────────────────

    def _on_notebook_chat(self, question: str, selected_cells: list,
                          notebook_name: str, summary: str,
                          conversation_history: list):
        if not self.state.llm:
            self.notebook_tab.on_chat_error("LLM이 설정되지 않았습니다.")
            return
        if self._nb_chat_worker and self._nb_chat_worker.isRunning():
            return

        from rag_core import load_notebook_chat_prompt, prepare_notebook_chat_prompt

        sys_prompt = load_notebook_chat_prompt()

        mode = getattr(self.notebook_tab, "_context_mode", "summary")
        all_cells = None
        if mode == "full":
            all_cells = sorted(
                [c for c in self.notebook_tab._cells if c["notebook"] == notebook_name],
                key=lambda x: x["cell_idx"],
            )

        user_prompt = prepare_notebook_chat_prompt(
            notebook_name,
            selected_cells,
            question,
            context_mode=mode,
            summary=summary,
            all_cells=all_cells,
        )

        self._nb_chat_worker = NotebookChatWorker(
            llm=self.state.llm,
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            conversation_history=conversation_history,
        )

        # 스트리밍 시작 알림
        self.notebook_tab.on_chat_streaming_start()

        # 대기 중인 질문을 기록 (on_chat_finished에서 히스토리에 추가)
        self.notebook_tab._pending_chat_question = question

        self._nb_chat_worker.chunk_received.connect(self.notebook_tab.on_chat_chunk)
        self._nb_chat_worker.finished_signal.connect(self.notebook_tab.on_chat_finished)
        self._nb_chat_worker.error_signal.connect(self.notebook_tab.on_chat_error)
        self._nb_chat_worker.start()

    def _on_notebook_chat_stop(self):
        if self._nb_chat_worker and self._nb_chat_worker.isRunning():
            self._nb_chat_worker.stop()

    # ── 파일 변경 감지 ────────────────────────────────────────────────────────

    def _check_dir_hash(self):
        if not self.state.rag_ready or not self.state.nb_dir_used:
            return
        from rag_core import get_dir_hash
        curr = get_dir_hash(self.state.nb_dir_used)
        if curr != self.state.dir_hash:
            self.config_panel.set_new_files_detected(True)
            self.statusBar().showMessage(
                "⚠️ 새 노트북 파일이 감지되었습니다. 좌측 패널에서 재구축하세요."
            )

    # ── 윈도우 종료 ───────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self.config_panel.save_settings()
        # 실행 중인 워커 정리
        for worker in [self._rag_worker, self._llm_worker, self._force_worker,
                       self._eq_worker, self._sq_worker, self._summary_worker,
                       self._nb_chat_worker,
                       self.chat_tab._recorder, self.chat_tab._stt_worker,
                       self.notebook_tab._recorder, self.notebook_tab._stt_worker]:
            if worker and worker.isRunning():
                worker.quit()
                worker.wait(2000)
        super().closeEvent(event)
