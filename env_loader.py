"""env.txt 로더 — 경량 모듈, 외부 의존성 없음"""
import os
import sys
from pathlib import Path


def save_env_models(llm_model: str, emb_model: str, path: str = "env.txt") -> None:
    """LLM_MODEL / EMBEDDING_MODEL 값을 env.txt에 갱신(없으면 끝에 추가)."""
    targets = {"LLM_MODEL": llm_model, "EMBEDDING_MODEL": emb_model}
    lines = []
    found: set[str] = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if "=" in stripped and not stripped.startswith("#"):
                    key = stripped.partition("=")[0].strip()
                    if key in targets:
                        lines.append(f"{key}={targets[key]}\n")
                        found.add(key)
                        continue
                lines.append(line)
    for key, val in targets.items():
        if key not in found:
            lines.append(f"{key}={val}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def load_env_txt(path: str = "env.txt") -> dict[str, str]:
    """env.txt 파일에서 KEY=VALUE 형태의 설정을 읽어 os.environ에 반영."""
    env_vars = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    key, value = key.strip(), value.strip()
                    env_vars[key] = value
                    os.environ.setdefault(key, value)
    return env_vars


def get_resource_path(filename: str) -> Path:
    """Get absolute path to a resource file (supports both dev and PyInstaller exe)."""
    if getattr(sys, 'frozen', False):
        base_dir = Path(sys._MEIPASS)
    else:
        base_dir = Path(__file__).resolve().parent
    return base_dir / "resources" / filename
