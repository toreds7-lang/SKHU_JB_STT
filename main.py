"""
SKHU Agent V1.0 - PyQt6 데스크탑 앱 진입점
"""

import os
import sys
import subprocess
import traceback
from pathlib import Path


# STT subprocess mode — must run BEFORE any heavy imports / pythonw relaunch / Qt init.
# When the frozen exe re-spawns itself as the faster-whisper child, route directly to
# the subprocess loop and skip GUI startup.
if "--stt-subprocess" in sys.argv:
    _idx = sys.argv.index("--stt-subprocess")
    if _idx + 1 < len(sys.argv):
        from workers.stt_subprocess import run_subprocess
        sys.exit(run_subprocess(sys.argv[_idx + 1]))
    sys.exit(2)


def _maybe_relaunch_with_pythonw():
    """콘솔 python.exe로 실행됐을 때 pythonw.exe로 재실행하여 터미널을 해방."""
    if sys.platform != "win32":
        return
    if getattr(sys, "frozen", False):
        return
    exe = sys.executable
    if "pythonw" in exe.lower():
        return
    pythonw = exe.replace("python.exe", "pythonw.exe")
    if not os.path.exists(pythonw):
        return
    subprocess.Popen(
        [pythonw] + sys.argv,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    sys.exit(0)


_maybe_relaunch_with_pythonw()


def _get_log_path():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "crash.log"
    return Path("crash.log")


def _get_resource_base() -> Path:
    """번들 리소스(datas) 경로 반환. PyInstaller는 sys._MEIPASS 사용."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


def _setup_paths():
    """
    PyInstaller 패키징 환경에서 경로 설정.
    사용자 파일(env.txt, work/)을 위해 exe 디렉토리를 CWD로 설정.
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
    else:
        exe_dir = Path(__file__).parent
    os.chdir(str(exe_dir))


try:
    _setup_paths()

    # env.txt 로드 — 경량 모듈로 분리하여 rag_core의 heavy import 방지
    from env_loader import load_env_txt
    load_env_txt("env.txt")

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon, QFont
    from PyQt6.QtCore import Qt

    from ui.main_window import MainWindow

    # rag_core를 메인 스레드에서 미리 로드 (DLL + kiwipiepy_model 초기화)
    import rag_core  # noqa: F401
except Exception:
    _get_log_path().write_text(traceback.format_exc(), encoding="utf-8")
    import time; time.sleep(5)
    raise


def main():
    # HiDPI 지원
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("SKHU Agent")
    app.setOrganizationName("SKHynix")
    app.setApplicationVersion("1.0")

    # 기본 폰트
    font = QFont("Pretendard", 10)
    try:
        font.setFallbackFamilies(["Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans CJK KR"])
    except AttributeError:
        font.setFamily("Malgun Gothic")
    app.setFont(font)

    # 다크 테마 QSS (번들 리소스)
    res_base = _get_resource_base()
    qss_path = res_base / "resources" / "dark_theme.qss"
    if qss_path.exists():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))

    # 앱 아이콘 (번들 리소스)
    icon_path = res_base / "SK_Hynix.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _get_log_path().write_text(traceback.format_exc(), encoding="utf-8")
        raise
