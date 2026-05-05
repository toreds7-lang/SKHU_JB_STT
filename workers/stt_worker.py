"""STT workers: AudioRecorder (mic recording) + STTWorker (transcription via subprocess)."""
import atexit
import json
import os
import subprocess
import sys
import tempfile
import threading
import traceback
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal


_PROJECT_ROOT = Path(__file__).parent.parent
_LOG_PATH = _PROJECT_ROOT / "stt_debug.log"
_SUBPROCESS_SCRIPT = Path(__file__).parent / "stt_subprocess.py"


def _log(msg: str) -> None:
    try:
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
            f.flush()
    except Exception:
        pass


class _SubprocessManager:
    """Owns a single long-running stt_subprocess.py child process.

    Restarts the child on demand if the language changes or the process dies.
    Isolates ctranslate2 from Qt's process — required because WhisperModel
    initialization hard-aborts when called from a QThread inside the Qt app.
    """

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._language: str | None = None
        self._lock = threading.Lock()

    def _start(self, language: str) -> None:
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW

        # Ensure the child writes UTF-8 to stdout/stderr regardless of the
        # system locale (CP949 on Korean Windows would corrupt JSON responses).
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        # In a PyInstaller bundle, sys.executable is SKHU_Agent.exe (not python),
        # so we re-invoke ourselves with a sentinel flag and resolve models/ next
        # to the exe instead of the _MEIPASS extraction dir.
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).parent
            cmd = [sys.executable, "--stt-subprocess", language]
            cwd = str(exe_dir)
            env["STT_MODELS_DIR"] = str(exe_dir / "models")
        else:
            cmd = [sys.executable, str(_SUBPROCESS_SCRIPT), language]
            cwd = str(_PROJECT_ROOT)
            env["STT_MODELS_DIR"] = str(_PROJECT_ROOT / "models")

        _log(f"_SubprocessManager: starting subprocess (language={language})")
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            cwd=cwd,
            creationflags=creationflags,
            env=env,
        )

        ready_line = proc.stdout.readline()
        if not ready_line:
            stderr = proc.stderr.read() if proc.stderr else ""
            proc.terminate()
            raise RuntimeError(f"STT 서브프로세스가 시작 전 종료됨: {stderr}")

        try:
            ready = json.loads(ready_line)
        except json.JSONDecodeError:
            stderr = proc.stderr.read() if proc.stderr else ""
            proc.terminate()
            raise RuntimeError(f"STT 서브프로세스 응답 오류: {ready_line!r} {stderr}")

        if not ready.get("ready"):
            err = ready.get("error", "unknown")
            proc.terminate()
            raise RuntimeError(f"STT 모델 로드 실패: {err}")

        _log(f"_SubprocessManager: ready (pid={proc.pid})")
        self._proc = proc
        self._language = language

    def transcribe(self, audio_bytes: bytes, language: str) -> str:
        import numpy as np

        with self._lock:
            need_restart = (
                self._proc is None
                or self._proc.poll() is not None
                or self._language != language
            )
            if need_restart:
                if self._proc is not None and self._proc.poll() is None:
                    try:
                        self._proc.terminate()
                        self._proc.wait(timeout=2)
                    except Exception:
                        pass
                self._start(language)

            audio = np.frombuffer(audio_bytes, dtype=np.float32)

            with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                np.save(tmp_path, audio)
                req = json.dumps({"path": tmp_path})
                _log(f"_SubprocessManager: sending request (samples={len(audio)})")
                self._proc.stdin.write(req + "\n")
                self._proc.stdin.flush()

                response_line = self._proc.stdout.readline()
                if not response_line:
                    stderr = self._proc.stderr.read() if self._proc.stderr else ""
                    raise RuntimeError(f"STT 서브프로세스 응답 없음: {stderr}")

                resp = json.loads(response_line)
                if not resp.get("ok"):
                    raise RuntimeError(resp.get("error", "unknown"))
                return resp.get("text", "")
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def shutdown(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.stdin.write("EXIT\n")
                    self._proc.stdin.flush()
                    self._proc.wait(timeout=2)
                except Exception:
                    try:
                        self._proc.terminate()
                    except Exception:
                        pass


_manager = _SubprocessManager()
atexit.register(_manager.shutdown)


class AudioRecorder(QThread):
    """Records microphone audio at 16 kHz mono float32 until stop_recording() is called."""

    finished = pyqtSignal(bytes)
    error    = pyqtSignal(str)

    SAMPLE_RATE = 16_000
    CHANNELS    = 1
    DTYPE       = "float32"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_flag = False
        self._frames: list = []

    def stop_recording(self):
        self._stop_flag = True

    def run(self):
        try:
            import sounddevice as sd
            import numpy as np

            self._frames = []
            self._stop_flag = False

            def _callback(indata, frames, time, status):
                self._frames.append(indata.copy())

            with sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=self.CHANNELS,
                dtype=self.DTYPE,
                callback=_callback,
                blocksize=1024,
            ):
                while not self._stop_flag:
                    self.msleep(50)

            if self._frames:
                audio = np.concatenate(self._frames, axis=0).flatten()
                _log(f"AudioRecorder: captured {len(audio)} samples ({len(audio)/self.SAMPLE_RATE:.2f}s)")
                self.finished.emit(audio.tobytes())
            else:
                self.error.emit("녹음된 오디오가 없습니다.")
        except Exception as e:
            _log(f"AudioRecorder ERROR: {e}\n{traceback.format_exc()}")
            self.error.emit(str(e))


class STTWorker(QThread):
    """Sends recorded audio to the STT subprocess and emits the transcription."""

    finished = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, audio_bytes: bytes, language: str, parent=None):
        super().__init__(parent)
        self.audio_bytes = audio_bytes
        self.language    = language

    def run(self):
        try:
            _log(f"STTWorker.run START — language={self.language} bytes={len(self.audio_bytes)}")
            text = _manager.transcribe(self.audio_bytes, self.language)
            _log(f"STTWorker: text={text!r}")

            if not text:
                self.error.emit("음성을 인식하지 못했습니다. 다시 시도해 주세요.")
                return

            self.finished.emit(text)
        except Exception as e:
            _log(f"STTWorker ERROR: {e}\n{traceback.format_exc()}")
            self.error.emit(str(e))
