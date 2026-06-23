# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 빌드 스펙 파일
사용법:
  pyinstaller build.spec
결과물:
  dist/SKHU_Agent/SKHU_Agent.exe
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

block_cipher = None

# kiwipiepy + kiwipiepy_model 데이터 파일 경로 자동 탐색
def _collect_kiwipiepy():
    result = []
    for pkg_name in ["kiwipiepy", "kiwipiepy_model"]:
        try:
            pkg = __import__(pkg_name)
            pkg_dir = Path(pkg.__file__).parent
            for pattern in ["**/*.dict", "**/*.bin", "**/*.json", "**/*.txt",
                            "**/*.mdl", "**/*.morph"]:
                for f in pkg_dir.glob(pattern):
                    dest = str(f.parent.relative_to(pkg_dir.parent))
                    result.append((str(f), dest))
        except ImportError:
            pass
    return result


# faster-whisper / ctranslate2 / sounddevice 등 STT 의존성 수집
# (네이티브 DLL: libctranslate2, libportaudio / 데이터: silero VAD onnx 등)
def _collect_stt():
    datas, binaries, hiddenimports = [], [], []
    for pkg in ("faster_whisper", "ctranslate2", "onnxruntime", "tokenizers"):
        try:
            d, b, h = collect_all(pkg)
            datas += d
            binaries += b
            hiddenimports += h
        except Exception:
            pass
    try:
        d, b, h = collect_all("_sounddevice_data")
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass
    return datas, binaries, hiddenimports


_stt_datas, _stt_binaries, _stt_hiddenimports = _collect_stt()


a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=_stt_binaries,
    datas=[
        # 리소스 파일
        ("SK_Hynix.png",          "."),
        ("prompts/system_prompt.txt",  "prompts"),
        ("prompts/force_prompt.txt",   "prompts"),
        ("prompts/summary_prompt.txt",        "prompts"),
        ("prompts/notebook_chat_prompt.txt", "prompts"),
        ("prompts/notebook_run_predict_prompt.txt", "prompts"),
        ("resources/dark_theme.qss", "resources"),
        ("resources/chat.html",            "resources"),
        ("resources/summary.html",         "resources"),
        ("resources/notebook_viewer.html", "resources"),
        ("resources/notebook_chat.html",   "resources"),
        ("resources/cached_response.html", "resources"),
        ("resources/knowledge_graph.html", "resources"),
        ("resources/wiki_node.html",       "resources"),
        ("resources/js",             "resources/js"),
        ("resources/css",            "resources/css"),
        # STT 서브프로세스 스크립트 (참조용 — 실행은 --stt-subprocess sentinel 경유)
        ("workers/stt_subprocess.py", "workers"),
        # kiwipiepy 모델 데이터
        *_collect_kiwipiepy(),
        # faster-whisper / ctranslate2 / onnxruntime / tokenizers 데이터
        *_stt_datas,
    ],
    hiddenimports=[
        # FAISS
        "faiss",
        "faiss.swigfaiss",
        # LangChain 생태계
        "langchain_community.retrievers.bm25",
        "langchain_classic.retrievers",
        "langchain_openai",
        "langchain_core.messages",
        "langchain_core.documents",
        "langchain_text_splitters",
        "langgraph.graph",
        "langgraph.graph.state",
        # kiwipiepy
        "kiwipiepy",
        "kiwipiepy_model",
        # networkx
        "networkx",
        "networkx.algorithms",
        # numpy / scipy
        "numpy",
        "scipy.sparse",
        # nbformat
        "nbformat",
        "nbformat.v4",
        # tiktoken
        "tiktoken",
        "tiktoken_ext.openai_public",
        "tiktoken_ext",
        # Pillow
        "PIL.Image",
        # PyQt6
        "PyQt6.QtCore",
        "PyQt6.QtWidgets",
        "PyQt6.QtGui",
        # STT (faster-whisper subprocess 경유)
        "workers.stt_subprocess",
        "workers.stt_worker",
        "sounddevice",
        "_cffi_backend",
        *_stt_hiddenimports,
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "streamlit",
        "tornado",
        "altair",
        "bokeh",
        "matplotlib",
        "tkinter",
        "jupyter",
        "notebook",
        "IPython",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SKHU_Agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,      # 배포용 - 콘솔 창 없음
    icon="SK_Hynix.ico" if os.path.exists("SK_Hynix.ico") else None,
    version_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SKHU_Agent",
)

# ──────────────────────────────────────────────────────────────────────────────
# 빌드 전 준비 사항:
#
# 1. ICO 파일 생성 (PNG → ICO):
#    python -c "from PIL import Image; Image.open('SK_Hynix.png').save('SK_Hynix.ico')"
#
# 2. PyInstaller 설치:
#    pip install pyinstaller>=6.8.0
#
# 3. 빌드 실행:
#    pyinstaller build.spec
#
# 4. 배포:
#    dist/SKHU_Agent/ 폴더 전체를 배포
#    사용자는 SKHU_Agent.exe 옆에 env.txt, work/ 폴더, 그리고 models/ 폴더
#    (faster-whisper 모델 캐시)를 배치. models/ 가 없으면 첫 STT 실행 시
#    HuggingFace 에서 자동 다운로드되어 같은 위치에 캐시됨.
# ──────────────────────────────────────────────────────────────────────────────
