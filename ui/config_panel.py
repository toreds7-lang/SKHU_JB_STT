"""
ConfigPanel - 좌측 설정 패널
Streamlit sidebar 대체
"""

import os
from env_loader import save_env_models
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QGroupBox, QFileDialog, QScrollArea,
    QFrame, QSizePolicy, QProgressBar, QSpinBox
)
from PyQt6.QtCore import pyqtSignal, Qt, QSettings
from PyQt6.QtGui import QFont


class _SectionLabel(QLabel):
    def __init__(self, text: str):
        super().__init__(text)
        self.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600; "
                           "text-transform: uppercase; letter-spacing: 1px; "
                           "margin-top: 8px; margin-bottom: 2px;")


class _FieldLabel(QLabel):
    def __init__(self, text: str):
        super().__init__(text)
        self.setStyleSheet("color: #64748b; font-size: 11px; margin-bottom: 1px;")


class MetricWidget(QFrame):
    """단일 지표 카드"""
    def __init__(self, value: str, label: str):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame { background: #161922; border: 1px solid #2a3045; "
            "border-radius: 6px; padding: 4px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(1)

        self.val_label = QLabel(value)
        self.val_label.setStyleSheet(
            "color: #4f8ef7; font-size: 18px; font-weight: 700; "
            "font-family: 'JetBrains Mono', Consolas, monospace;"
        )
        self.val_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        lbl = QLabel(label)
        lbl.setStyleSheet("color: #64748b; font-size: 10px;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.val_label)
        layout.addWidget(lbl)

    def set_value(self, v: str):
        self.val_label.setText(v)


class ConfigPanel(QWidget):
    build_requested = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.setMinimumWidth(220)
        self.setMaximumWidth(320)
        self._metric_widgets: dict[str, MetricWidget] = {}
        self._build_ui()
        self.load_settings()

    def _build_ui(self):
        # 스크롤 가능한 내부 컨텐츠
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setSpacing(4)

        lay = self._layout

        # ── 제목 ──────────────────────────────────────────────────────────────
        title = QLabel("⚙️  설정")
        title.setStyleSheet(
            "color: #e2e8f0; font-size: 14px; font-weight: 700; margin-bottom: 4px;"
        )
        lay.addWidget(title)
        lay.addWidget(self._divider())

        # ── 노트북 디렉토리 ───────────────────────────────────────────────────
        lay.addWidget(_SectionLabel("📁  노트북 디렉토리"))
        dir_row = QHBoxLayout()
        self.nb_dir_edit = QLineEdit("work")
        self.nb_dir_edit.setPlaceholderText("/path/to/notebooks")
        dir_row.addWidget(self.nb_dir_edit)
        browse_btn = QPushButton("…")
        browse_btn.setFixedWidth(28)
        browse_btn.setToolTip("폴더 선택")
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(browse_btn)
        lay.addLayout(dir_row)
        self.nb_dir_edit.textChanged.connect(self._sync_cache_dir)

        lay.addWidget(_FieldLabel("캐시 디렉토리"))
        self.cache_dir_edit = QLineEdit(".rag_cache")
        lay.addWidget(self.cache_dir_edit)

        # ── LLM 설정 ──────────────────────────────────────────────────────────
        lay.addWidget(_SectionLabel("🤖  LLM 설정"))
        self.llm_url_edit = QLineEdit()
        self.llm_url_edit.setPlaceholderText("http://localhost:8000/v1 (비워두면 OpenAI)")

        lay.addWidget(_FieldLabel("모델명"))
        self.llm_model_edit = QLineEdit()
        self.llm_model_edit.setPlaceholderText("gpt-4o-mini")
        lay.addWidget(self.llm_model_edit)

        self.llm_key_edit = QLineEdit()
        self.llm_key_edit.setPlaceholderText("sk-… or dummy")
        self.llm_key_edit.setEchoMode(QLineEdit.EchoMode.Password)

        # ── Embedding 설정 ────────────────────────────────────────────────────
        lay.addWidget(_SectionLabel("🔢  Embedding 설정"))
        self.emb_url_edit = QLineEdit()
        self.emb_url_edit.setPlaceholderText("http://localhost:8001/v1")

        lay.addWidget(_FieldLabel("Embedding 모델명"))
        self.emb_model_edit = QLineEdit("text-embedding-ada-002")
        lay.addWidget(self.emb_model_edit)

        self.emb_key_edit = QLineEdit()
        self.emb_key_edit.setPlaceholderText("sk-…")
        self.emb_key_edit.setEchoMode(QLineEdit.EchoMode.Password)

        # ── 검색 모드 ──────────────────────────────────────────────────────────
        lay.addWidget(_SectionLabel("🔍  검색 모드"))
        self.retrieval_combo = QComboBox()
        self.retrieval_combo.addItem("🔀 통합 (Vector + BM25 + Graph)", "all")
        self.retrieval_combo.addItem("📐 Vector RAG만", "vector")
        self.retrieval_combo.addItem("🔤 BM25만", "bm25")
        self.retrieval_combo.addItem("🕸️ Graph RAG만", "graph")
        lay.addWidget(self.retrieval_combo)

        # ── Force Mode 설정 ─────────────────────────────────────────────────
        lay.addWidget(_SectionLabel("⚡  Force Mode"))
        lay.addWidget(_FieldLabel("병렬 워커 수"))
        self.force_workers_spin = QSpinBox()
        self.force_workers_spin.setRange(1, 10)
        self.force_workers_spin.setValue(3)
        self.force_workers_spin.setToolTip(
            "Force Mode에서 동시에 LLM을 호출하는 병렬 스레드 수 (1-10)"
        )
        lay.addWidget(self.force_workers_spin)

        # ── STT 설정 ──────────────────────────────────────────────────────────
        lay.addWidget(_SectionLabel("🎤  STT"))
        lay.addWidget(_FieldLabel("언어"))
        self.stt_language_combo = QComboBox()
        self.stt_language_combo.addItem("한국어  (Korean + English)", "ko")
        self.stt_language_combo.addItem("English", "en")
        lay.addWidget(self.stt_language_combo)

        lay.addWidget(self._divider())

        # ── 빌드 버튼 ──────────────────────────────────────────────────────────
        self.build_btn = QPushButton("🚀 RAG 시스템 구축")
        self.build_btn.setMinimumHeight(36)
        self.build_btn.clicked.connect(self._on_build_clicked)
        lay.addWidget(self.build_btn)

        # 진행 상태
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)   # indeterminate
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(6)
        lay.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(
            "color: #4f8ef7; font-size: 11px; font-family: 'JetBrains Mono', Consolas;"
        )
        self.status_label.setWordWrap(True)
        lay.addWidget(self.status_label)

        # ── 통계 그룹 ──────────────────────────────────────────────────────────
        self.stats_group = QGroupBox("📊  인덱스 통계")
        self.stats_group.setVisible(False)
        self.stats_group.setStyleSheet(
            "QGroupBox { color: #94a3b8; font-size: 11px; font-weight: 600; "
            "border: 1px solid #2a3045; border-radius: 6px; margin-top: 8px; "
            "padding-top: 12px; } "
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; }"
        )
        stats_layout = QVBoxLayout(self.stats_group)
        stats_layout.setSpacing(4)

        row1 = QHBoxLayout()
        self._metric_widgets["nb_count"]   = MetricWidget("0", "노트북")
        self._metric_widgets["cell_count"] = MetricWidget("0", "총 셀")
        row1.addWidget(self._metric_widgets["nb_count"])
        row1.addWidget(self._metric_widgets["cell_count"])

        row2 = QHBoxLayout()
        self._metric_widgets["code_count"] = MetricWidget("0", "코드 셀")
        self._metric_widgets["md_count"]   = MetricWidget("0", "마크다운 셀")
        row2.addWidget(self._metric_widgets["code_count"])
        row2.addWidget(self._metric_widgets["md_count"])

        self.graph_info_label = QLabel()
        self.graph_info_label.setStyleSheet(
            "color: #a78bfa; font-size: 11px; font-family: 'JetBrains Mono', Consolas;"
        )

        stats_layout.addLayout(row1)
        stats_layout.addLayout(row2)
        stats_layout.addWidget(self.graph_info_label)

        lay.addWidget(self.stats_group)
        lay.addStretch()

    # ── 내부 메서드 ────────────────────────────────────────────────────────────

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #2a3045;")
        return line

    def _browse_dir(self):
        path = QFileDialog.getExistingDirectory(self, "노트북 디렉토리 선택",
                                                self.nb_dir_edit.text())
        if path:
            self.nb_dir_edit.setText(path)

    def _sync_cache_dir(self, nb_dir_text: str):
        text = nb_dir_text.strip().rstrip("/\\")
        if text:
            parent = os.path.dirname(text)
            self.cache_dir_edit.setText(
                os.path.join(parent, ".rag_cache") if parent else ".rag_cache"
            )

    def _on_build_clicked(self):
        cfg = self.get_config()
        if not cfg["emb_api_key"]:
            self.status_label.setText("❌ OpenAI API Key를 입력해 주세요.")
            return
        if not os.path.isdir(cfg["nb_dir"]):
            self.status_label.setText(f"❌ 디렉토리 없음: {cfg['nb_dir']}")
            return
        self.build_requested.emit(cfg)

    # ── 공개 API ───────────────────────────────────────────────────────────────

    def get_config(self) -> dict:
        return {
            "nb_dir":        self.nb_dir_edit.text().strip(),
            "llm_base_url":  self.llm_url_edit.text().strip(),
            "llm_model":     self.llm_model_edit.text().strip() or "gpt-4o-mini",
            "llm_api_key":   self.llm_key_edit.text().strip(),
            "emb_base_url":  self.emb_url_edit.text().strip(),
            "emb_model":     self.emb_model_edit.text().strip() or "text-embedding-ada-002",
            "emb_api_key":   self.emb_key_edit.text().strip(),
            "retrieval_mode": self.retrieval_combo.currentData(),
            "cache_dir":     self.cache_dir_edit.text().strip() or ".rag_cache",
            "force_workers": self.force_workers_spin.value(),
            "stt_language":  self.stt_language_combo.currentData(),
        }

    def set_build_enabled(self, enabled: bool):
        self.build_btn.setEnabled(enabled)
        self.progress_bar.setVisible(not enabled)
        if enabled:
            self.status_label.setText("")

    def set_new_files_detected(self, detected: bool):
        if detected:
            self.build_btn.setText("🔄 새 파일 감지 — 재구축")
        else:
            self.build_btn.setText("🔄 RAG 재구축")

    def update_stats(self, rag_sys: dict):
        import networkx as nx
        self._metric_widgets["nb_count"].set_value(str(rag_sys.get("nb_count", 0)))
        self._metric_widgets["cell_count"].set_value(str(rag_sys.get("cell_count", 0)))
        self._metric_widgets["code_count"].set_value(str(rag_sys.get("code_count", 0)))
        self._metric_widgets["md_count"].set_value(str(rag_sys.get("md_count", 0)))

        G: nx.DiGraph = rag_sys.get("graph")
        if G:
            self.graph_info_label.setText(
                f"🕸️ 노드 {G.number_of_nodes()} · 🔗 엣지 {G.number_of_edges()}"
            )
        self.stats_group.setVisible(True)

    def mark_rag_ready(self):
        self.build_btn.setText("🔄 RAG 재구축")
        self.set_build_enabled(True)

    def load_settings(self):
        s = QSettings("SKHynix", "SKHU_Agent")
        self.nb_dir_edit.setText(s.value("nb_dir", "work"))
        self.llm_url_edit.setText(s.value("llm_url", os.getenv("LLM_BASE_URL", "")))
        self.llm_model_edit.setText(os.getenv("LLM_MODEL") or s.value("llm_model", "gpt-4o-mini"))
        self.emb_url_edit.setText(s.value("emb_url", os.getenv("EMBEDDING_BASE_URL", "")))
        self.emb_model_edit.setText(os.getenv("EMBEDDING_MODEL") or s.value("emb_model", "text-embedding-ada-002"))
        self.cache_dir_edit.setText(s.value("cache_dir", ".rag_cache"))
        mode = s.value("retrieval_mode", "all")
        idx = self.retrieval_combo.findData(mode)
        if idx >= 0:
            self.retrieval_combo.setCurrentIndex(idx)
        # Force Mode 병렬 워커 수 (QSettings → env.txt → 기본값 3)
        fw_default = int(os.getenv("FORCE_WORKERS", "3"))
        self.force_workers_spin.setValue(int(s.value("force_workers", fw_default)))
        # STT 언어 (QSettings → 기본값 ko)
        stt_idx = self.stt_language_combo.findData(s.value("stt_language", "ko"))
        if stt_idx >= 0:
            self.stt_language_combo.setCurrentIndex(stt_idx)
        # API 키는 env에서만 로드 (저장 안 함)
        self.llm_key_edit.setText(os.getenv("OPENAI_API_KEY", ""))
        self.emb_key_edit.setText(os.getenv("OPENAI_API_KEY", ""))

    def save_settings(self):
        s = QSettings("SKHynix", "SKHU_Agent")
        s.setValue("nb_dir",         self.nb_dir_edit.text())
        s.setValue("llm_url",        self.llm_url_edit.text())
        s.setValue("llm_model",      self.llm_model_edit.text())
        s.setValue("emb_url",        self.emb_url_edit.text())
        s.setValue("emb_model",      self.emb_model_edit.text())
        s.setValue("cache_dir",      self.cache_dir_edit.text())
        s.setValue("retrieval_mode", self.retrieval_combo.currentData())
        s.setValue("force_workers",  self.force_workers_spin.value())
        s.setValue("stt_language",   self.stt_language_combo.currentData())
        save_env_models(self.llm_model_edit.text(), self.emb_model_edit.text())
