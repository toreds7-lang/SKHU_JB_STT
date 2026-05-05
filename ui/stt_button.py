"""STTButton — reusable mic toggle button for voice input."""
from PyQt6.QtWidgets import QPushButton
from PyQt6.QtCore    import pyqtSignal, Qt

_IDLE_STYLE = (
    "QPushButton { background: #1e2330; color: #94a3b8; "
    "border: 1px solid #2a3045; border-radius: 6px; "
    "font-size: 16px; padding: 0; }"
    "QPushButton:hover { background: #2a3045; color: #e2e8f0; }"
    "QPushButton:disabled { background: #161922; color: #3a4055; "
    "border-color: #1e2330; }"
)
_RECORDING_STYLE = (
    "QPushButton { background: #dc2626; color: #ffffff; border: none; "
    "border-radius: 6px; font-size: 16px; padding: 0; font-weight: 700; }"
    "QPushButton:hover { background: #ef4444; }"
    "QPushButton:disabled { background: #7f1d1d; color: #fca5a5; }"
)


class STTButton(QPushButton):
    """Mic toggle button: click to start recording, click again to stop.

    Signals:
        record_start — user clicked to begin recording
        record_stop  — user clicked to stop recording
    """

    record_start = pyqtSignal()
    record_stop  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("🎤", parent)
        self._recording = False
        self.setFixedSize(36, 36)
        self.setToolTip("음성 입력 (클릭하여 녹음 시작)")
        self.setStyleSheet(_IDLE_STYLE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self):
        if self._recording:
            self.record_stop.emit()
        else:
            self.record_start.emit()

    def set_recording(self, recording: bool):
        self._recording = recording
        if recording:
            self.setText("⏹")
            self.setStyleSheet(_RECORDING_STYLE)
            self.setToolTip("클릭하여 녹음 중지 후 변환")
        else:
            self.setText("🎤")
            self.setStyleSheet(_IDLE_STYLE)
            self.setToolTip("음성 입력 (클릭하여 녹음 시작)")

    def set_enabled_stt(self, enabled: bool):
        self.setEnabled(enabled)
