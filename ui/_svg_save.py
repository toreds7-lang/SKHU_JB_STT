"""Mermaid SVG 저장 헬퍼.

JS에서 `console.log("__SAVE_SVG__:<filename>|<base64-svg>")`로 전송한 payload를
받아 QFileDialog로 사용자에게 저장 경로를 묻고 .svg 파일로 기록한다.

주의: javaScriptConsoleMessage 콜백은 JS 엔진이 console.log를 처리하는 도중에
동기 호출되므로, 그 안에서 모달 QFileDialog를 열면 QtWebEngine이 충돌한다.
따라서 QTimer.singleShot(0)으로 다음 이벤트 루프 tick까지 다이얼로그를 지연한다.
parent로는 호출 시점의 QApplication.activeWindow()를 사용해 stale view 참조 위험을
회피한다.
"""
from __future__ import annotations

import base64
import pathlib
import traceback

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

_SAVE_SVG_PREFIX = "__SAVE_SVG__:"


def _do_save(name: str, svg_bytes: bytes) -> None:
    try:
        parent = QApplication.activeWindow()
        default_path = str(pathlib.Path.home() / f"{name}.svg")
        fname, _ = QFileDialog.getSaveFileName(
            parent, "SVG로 저장", default_path, "SVG Files (*.svg)"
        )
        if not fname:
            return
        if not fname.lower().endswith(".svg"):
            fname += ".svg"
        pathlib.Path(fname).write_bytes(svg_bytes)
    except Exception:
        traceback.print_exc()
        try:
            QMessageBox.warning(
                QApplication.activeWindow(),
                "저장 실패",
                "SVG 저장 중 오류가 발생했습니다.\n" + traceback.format_exc(),
            )
        except Exception:
            pass


def handle_save_svg_payload(payload: str, parent=None) -> None:
    """payload format: '<filename>|<base64-svg>'.

    parent는 호환성을 위해 받지만 사용하지 않는다 (activeWindow()로 동적 결정).
    """
    try:
        name, b64 = payload.split("|", 1)
        svg_bytes = base64.b64decode(b64)
    except Exception:
        traceback.print_exc()
        return
    # JS console 콜백 안에서 곧바로 모달 다이얼로그를 열면 QtWebEngine이 죽으므로
    # 다음 tick까지 미룬다.
    QTimer.singleShot(0, lambda: _do_save(name, svg_bytes))
