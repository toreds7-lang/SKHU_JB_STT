"""Long-running STT subprocess.

Loads a faster-whisper small model once and transcribes audio files on demand.
Runs in an isolated Python process to avoid ctranslate2 / Qt threading conflicts.

Protocol (line-delimited JSON over stdin/stdout):
  startup → emits {"ready": true} when model loaded
  request → reads {"path": "<.npy file path>"}
  response → emits {"ok": true, "text": "..."} or {"ok": false, "error": "..."}
  shutdown → reads "EXIT" or stdin close
"""
import json
import os
import sys
import traceback
from pathlib import Path

# Force UTF-8 stdio so Korean transcription output isn't encoded to CP949
# on Windows (which would break the parent's UTF-8 decode).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Force single-threaded math libs BEFORE importing numpy / faster_whisper
os.environ.setdefault("OMP_NUM_THREADS",      "1")
os.environ.setdefault("MKL_NUM_THREADS",      "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

_PROJECT_ROOT = Path(__file__).parent.parent

_REQUIRED_FILES = ["model.bin", "config.json", "tokenizer.json", "vocabulary.txt"]


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _get_models_dir() -> str:
    """Return path to the flat models/ directory, downloading files there if needed."""
    models_dir = Path(os.environ.get("STT_MODELS_DIR", str(_PROJECT_ROOT / "models")))
    models_dir.mkdir(exist_ok=True)

    if all((models_dir / f).exists() for f in _REQUIRED_FILES):
        return str(models_dir)

    # Copy from existing HF snapshot sub-folder if already downloaded
    snap_root = models_dir / "hub" / "models--Systran--faster-whisper-small" / "snapshots"
    if snap_root.exists():
        for snap in snap_root.iterdir():
            if snap.is_dir():
                import shutil
                for f in _REQUIRED_FILES:
                    src = snap / f
                    if src.exists() and not (models_dir / f).exists():
                        shutil.copy2(src, models_dir / f)
                if all((models_dir / f).exists() for f in _REQUIRED_FILES):
                    return str(models_dir)

    # Fresh download — files land directly in models/ without sub-folders
    from huggingface_hub import hf_hub_download
    for fname in _REQUIRED_FILES:
        hf_hub_download(
            repo_id="Systran/faster-whisper-small",
            filename=fname,
            local_dir=str(models_dir),
            local_dir_use_symlinks=False,
        )
    return str(models_dir)


def run_subprocess(language: str) -> int:
    try:
        import numpy as np
        from faster_whisper import WhisperModel

        model = WhisperModel(
            _get_models_dir(),
            device="cpu",
            compute_type="int8",
            cpu_threads=2,
            num_workers=1,
        )
        _emit({"ready": True})
    except Exception as e:
        _emit({"ok": False, "error": f"model load failed: {e}\n{traceback.format_exc()}"})
        return 1

    # "ko" → auto-detect (handles Korean + English); "en" → English only
    lang_code = None if language == "ko" else "en"

    for line in sys.stdin:
        line = line.strip()
        if not line or line == "EXIT":
            break
        try:
            req = json.loads(line)
            audio = np.load(req["path"])
            segments, _info = model.transcribe(
                audio,
                language=lang_code,
                task="transcribe",
                beam_size=1,
            )
            text = " ".join(seg.text for seg in list(segments)).strip()
            _emit({"ok": True, "text": text})
        except Exception as e:
            _emit({"ok": False, "error": f"{e}\n{traceback.format_exc()}"})

    return 0


def main() -> int:
    if len(sys.argv) < 2:
        _emit({"ok": False, "error": "usage: stt_subprocess.py <language>"})
        return 1
    return run_subprocess(sys.argv[1])


if __name__ == "__main__":
    sys.exit(main())
