"""AI 응답 캐시 영속 계층.

- NotebookChatCache: 노트북별 Q&A 캐시 (.rag_cache/notebook_chat_cache.json)
  단일 JSON dict, 키 = 노트북 이름 → 항목 리스트. 노트북에 항목이 없으면 키 자체를 제거.
- ChatCache: 채팅 탭 캐시 (.rag_cache/chat_cache.jsonl)
  JSONL, 추가는 O(1) append, 삭제는 rewrite-without-line. 빈 상태에서는 파일 자체를 삭제.

두 캐시 모두 파일이 비어있을 때는 파일을 만들지 않는다 — 첫 저장 시점에 처음 생성된다.
"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class NotebookChatCache:
    FILENAME = "notebook_chat_cache.json"

    def __init__(self, cache_dir: str, filename: str | None = None):
        self._cache_dir = cache_dir
        self._filename = filename or self.FILENAME
        self._lock = Lock()

    @property
    def path(self) -> Path:
        return Path(self._cache_dir) / self._filename

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
            return {}
        except Exception:
            return {}

    def _write(self, data: dict):
        if not data:
            if self.path.exists():
                try:
                    self.path.unlink()
                except OSError:
                    pass
            return
        os.makedirs(self._cache_dir, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def add(self, notebook: str, question: str, answer: str,
            cell_indices: list | None = None,
            entry_id: str | None = None) -> str:
        with self._lock:
            data = self._read()
            entry = {
                "id": entry_id or str(uuid.uuid4()),
                "ts": _now_iso(),
                "question": question,
                "answer": answer,
                "cell_indices": cell_indices or [],
            }
            data.setdefault(notebook, []).append(entry)
            self._write(data)
            return entry["id"]

    def delete(self, notebook: str, entry_id: str) -> bool:
        with self._lock:
            data = self._read()
            if notebook not in data:
                return False
            before = len(data[notebook])
            data[notebook] = [e for e in data[notebook] if e.get("id") != entry_id]
            after = len(data[notebook])
            if not data[notebook]:
                del data[notebook]
            self._write(data)
            return after < before

    def delete_by_id(self, entry_id: str) -> bool:
        """Notebook 키를 모르는 상태에서 id로 삭제."""
        with self._lock:
            data = self._read()
            removed = False
            for nb in list(data.keys()):
                kept = [e for e in data[nb] if e.get("id") != entry_id]
                if len(kept) != len(data[nb]):
                    removed = True
                    if kept:
                        data[nb] = kept
                    else:
                        del data[nb]
            if removed:
                self._write(data)
            return removed

    def delete_notebook(self, notebook: str) -> bool:
        with self._lock:
            data = self._read()
            if notebook not in data:
                return False
            del data[notebook]
            self._write(data)
            return True

    def delete_all(self):
        with self._lock:
            self._write({})

    def get_all(self) -> dict:
        with self._lock:
            return self._read()

    def get_notebook(self, notebook: str) -> list:
        """특정 노트북의 항목 리스트를 반환. 없으면 빈 리스트."""
        with self._lock:
            data = self._read()
            return list(data.get(notebook, []))


class ChatCache:
    FILENAME = "chat_cache.jsonl"

    def __init__(self, cache_dir: str):
        self._cache_dir = cache_dir
        self._lock = Lock()

    @property
    def path(self) -> Path:
        return Path(self._cache_dir) / self.FILENAME

    def _read_all(self) -> list:
        if not self.path.exists():
            return []
        entries = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return []
        return entries

    def _rewrite(self, entries: list):
        if not entries:
            if self.path.exists():
                try:
                    self.path.unlink()
                except OSError:
                    pass
            return
        os.makedirs(self._cache_dir, exist_ok=True)
        tmp = self.path.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        os.replace(tmp, self.path)

    def add(self, query: str, answer: str,
            source_notebooks: list | None = None,
            mode: str = "rag",
            entry_id: str | None = None) -> str:
        with self._lock:
            os.makedirs(self._cache_dir, exist_ok=True)
            entry = {
                "id": entry_id or str(uuid.uuid4()),
                "ts": _now_iso(),
                "query": query,
                "answer": answer,
                "source_notebooks": sorted(set(source_notebooks or [])),
                "mode": mode,
            }
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return entry["id"]

    def delete(self, entry_id: str) -> bool:
        with self._lock:
            entries = self._read_all()
            kept = [e for e in entries if e.get("id") != entry_id]
            if len(kept) == len(entries):
                return False
            self._rewrite(kept)
            return True

    def delete_all(self):
        with self._lock:
            self._rewrite([])

    def iter_entries(self) -> list:
        """전체 항목을 최신순으로 반환."""
        with self._lock:
            entries = self._read_all()
        entries.sort(key=lambda e: e.get("ts", ""), reverse=True)
        return entries

    def source_notebook_set(self) -> list:
        with self._lock:
            entries = self._read_all()
        s = set()
        for e in entries:
            for nb in e.get("source_notebooks", []) or []:
                s.add(nb)
        return sorted(s)


class SettingsChatCache:
    """Settings 탭 Q&A 히스토리 (SPEC-SETTINGS-001 §4.2).

    ChatCache와 동일한 JSONL append-only 패턴. 노트북별로 나뉘지 않는 단일
    채팅 패널이므로 {id, ts, file, question, answer} 평평한 레코드 하나로
    저장한다.
    """
    FILENAME = "settings_chat.jsonl"

    def __init__(self, cache_dir: str):
        self._cache_dir = cache_dir
        self._lock = Lock()

    @property
    def path(self) -> Path:
        return Path(self._cache_dir) / self.FILENAME

    def _read_all(self) -> list:
        if not self.path.exists():
            return []
        entries = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return []
        return entries

    def add(self, file: str, question: str, answer: str,
            entry_id: str | None = None) -> str:
        with self._lock:
            os.makedirs(self._cache_dir, exist_ok=True)
            entry = {
                "id": entry_id or str(uuid.uuid4()),
                "ts": _now_iso(),
                "file": file,
                "question": question,
                "answer": answer,
            }
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return entry["id"]

    def load(self) -> list:
        """전체 항목을 저장 순서대로 반환."""
        with self._lock:
            return self._read_all()

    def clear(self):
        with self._lock:
            if self.path.exists():
                try:
                    self.path.unlink()
                except OSError:
                    pass
