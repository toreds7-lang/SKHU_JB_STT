"""
QThread 기반 LLM / RAG 워커
- LLMWorker: 에이전트 검색 + LLM 스트리밍
- RagBuildWorker: RAG 시스템 구축
- ExampleQuestionsWorker: 예시 질문 생성
- SuggestedQueriesWorker: 후속 쿼리 생성
- SummaryWorker: 노트북 요약 생성
"""

import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


class RagBuildWorker(QThread):
    """RAG 시스템 구축 (노트북 파싱 + FAISS + BM25 + Graph)"""
    progress_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(object)   # rag_sys dict or None
    error_signal    = pyqtSignal(str)

    def __init__(self, nb_dir: str, emb_base_url: str, emb_api_key: str,
                 cache_dir: str, emb_model: str, clear_cache: bool = False):
        super().__init__()
        self.nb_dir       = nb_dir
        self.emb_base_url = emb_base_url
        self.emb_api_key  = emb_api_key
        self.cache_dir    = cache_dir
        self.emb_model    = emb_model
        self.clear_cache  = clear_cache

    def run(self):
        try:
            # 캐시 초기화
            if self.clear_cache:
                faiss_path = os.path.join(self.cache_dir, "faiss_index")
                bm25_path  = os.path.join(self.cache_dir, "bm25.pkl")
                if os.path.exists(faiss_path):
                    shutil.rmtree(faiss_path)
                if os.path.exists(bm25_path):
                    os.remove(bm25_path)

            # rag_core를 여기서 import (kiwipiepy 초기화 지연)
            from rag_core import build_rag_system
            rag_sys = build_rag_system(
                nb_dir          = self.nb_dir,
                embedding_base_url = self.emb_base_url,
                openai_api_key  = self.emb_api_key,
                cache_path      = self.cache_dir,
                embedding_model = self.emb_model,
                progress_callback = lambda msg: self.progress_signal.emit(msg),
            )
            self.finished_signal.emit(rag_sys)
        except Exception as e:
            self.error_signal.emit(str(e))


class LLMWorker(QThread):
    """에이전트 검색 + LLM 스트리밍"""
    status_signal   = pyqtSignal(str)        # "🔍 검색 중…"
    chunk_received  = pyqtSignal(str)        # 토큰 단위 스트리밍
    finished_signal = pyqtSignal(str, dict)  # (full_answer, result_state)
    error_signal    = pyqtSignal(str)

    def __init__(self, agent, llm, sys_prompt: str, llm_only_prompt: str,
                 query: str, retrieval_mode: str, is_suggested: bool,
                 conversation_history: list[dict] | None = None):
        super().__init__()
        self.agent            = agent
        self.llm              = llm
        self.sys_prompt       = sys_prompt
        self.llm_only_prompt  = llm_only_prompt
        self.query            = query
        self.retrieval_mode   = retrieval_mode
        self.is_suggested     = is_suggested
        self.conversation_history = conversation_history or []
        self._stopped         = False

    def _build_history_messages(self) -> list:
        """Convert conversation history dicts to LangChain message objects."""
        msgs = []
        for m in self.conversation_history:
            if m["role"] == "user":
                msgs.append(HumanMessage(content=m["content"]))
            elif m["role"] == "assistant":
                msgs.append(AIMessage(content=m["content"]))
        return msgs

    def stop(self):
        self._stopped = True

    def run(self):
        try:
            # 1. Retrieval (blocking)
            self.status_signal.emit("🔍 검색 중…")
            result = self.agent.invoke({
                "query":          self.query,
                "retrieval_mode": self.retrieval_mode,
                "vector_docs":    [],
                "bm25_docs":      [],
                "graph_docs":     [],
                "all_docs":       [],
                "context":        "",
                "answer":         "",
                "steps":          [],
            })

            if self._stopped:
                self.finished_signal.emit("", result)
                return

            context_found = len(result.get("all_docs", [])) > 0
            rag_not_found = lambda a: any(kw in a for kw in [
                "찾을 수 없습니다", "찾지 못했습니다", "찾을수 없습니다",
                "관련된 내용이 없", "관련 내용을 찾", "직접적인 답변을 찾",
                "해당하는 내용이 없", "관련 정보가 없",
            ])

            self.status_signal.emit("🤖 답변 생성 중…")

            def stream_messages(messages) -> str:
                buf = ""
                for chunk in self.llm.stream(messages):
                    if self._stopped:
                        break
                    buf += chunk.content
                    self.chunk_received.emit(chunk.content)
                return buf

            answer = ""

            if context_found:
                rag_prompt = (
                    f"컨텍스트:\n{result['context']}\n\n"
                    f"질문: {self.query}\n\n"
                    f"위 컨텍스트를 바탕으로 질문에 답변해 주세요."
                )
                answer = stream_messages(
                    [SystemMessage(content=self.sys_prompt)]
                    + self._build_history_messages()
                    + [HumanMessage(content=rag_prompt)]
                )

                if rag_not_found(answer):
                    if self.is_suggested:
                        # 스트리밍 버퍼 초기화 신호
                        self.chunk_received.emit("\x00RESET\x00")
                        answer = stream_messages(
                            [SystemMessage(content=self.llm_only_prompt)]
                            + self._build_history_messages()
                            + [HumanMessage(content=self.query)]
                        )
                else:
                    # 출처 추가
                    src_map: dict[str, list] = {}
                    for d in result["all_docs"]:
                        nb   = d.metadata.get("notebook", "unknown")
                        cidx = d.metadata.get("cell_idx", "?")
                        src_map.setdefault(nb, []).append(cidx)
                    src_parts = [
                        f"{nb} (셀 {', '.join(f'#{c}' for c in sorted(set(idxs)))})"
                        for nb, idxs in src_map.items()
                    ]
                    citation = "\n\n---\n📎 **출처**: " + " · ".join(src_parts)
                    answer += citation
                    self.chunk_received.emit("\x00CITATION\x00" + citation)

            elif self.is_suggested:
                answer = stream_messages(
                    [SystemMessage(content=self.llm_only_prompt)]
                    + self._build_history_messages()
                    + [HumanMessage(content=self.query)]
                )
            else:
                answer = "🔍 관련 문서를 찾지 못했습니다. 노트북 내용과 관련된 질문을 해주세요."
                self.chunk_received.emit(answer)

            self.finished_signal.emit(answer, result)

        except Exception as e:
            self.error_signal.emit(str(e))


class ForceWorker(QThread):
    """Force Mode: 전수 검색 (N개 병렬 sub-worker로 LLM 관련성 판단)"""
    progress_signal  = pyqtSignal(int, int)      # (processed, total)
    result_signal    = pyqtSignal(dict)           # 관련 청크 발견 시
    preview_signal   = pyqtSignal(str)            # 누적 결과 미리보기 마크다운
    finished_signal  = pyqtSignal(str)            # 최종 포맷된 답변
    error_signal     = pyqtSignal(str)

    def __init__(self, llm, query: str, nb_dir: str, max_workers: int = 3):
        super().__init__()
        self.llm         = llm
        self.query       = query
        self.nb_dir      = nb_dir
        self.max_workers = max(1, min(max_workers, 10))
        self._stopped    = False

    def stop(self):
        self._stopped = True

    def run(self):
        try:
            from rag_core import (
                load_force_prompt, prepare_force_chunks,
                process_force_chunk, format_force_results,
            )

            force_prompt = load_force_prompt()
            chunks = prepare_force_chunks(self.nb_dir)

            if not chunks:
                self.finished_signal.emit(
                    "📂 노트북 파일을 찾을 수 없습니다. 디렉토리를 확인하세요."
                )
                return

            total = len(chunks)
            results = []
            processed_count = 0
            lock = threading.Lock()

            def _process(chunk):
                """Sub-worker: plain thread 내에서 단일 청크 처리."""
                if self._stopped:
                    return None
                try:
                    return process_force_chunk(
                        self.llm, force_prompt, self.query, chunk
                    )
                except Exception:
                    return None  # 실패한 청크는 건너뜀

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {
                    executor.submit(_process, chunk): chunk
                    for chunk in chunks
                }

                for future in as_completed(futures):
                    if self._stopped:
                        for f in futures:
                            f.cancel()
                        answer = format_force_results(
                            results, (processed_count, total), stopped=True
                        )
                        self.finished_signal.emit(answer)
                        return

                    result = future.result()

                    with lock:
                        processed_count += 1
                        if result is not None:
                            results.append(result)
                            self.result_signal.emit(result)

                    self.progress_signal.emit(processed_count, total)

                    # 관련 결과 발견 시 또는 일정 간격마다 미리보기 갱신
                    if (result is not None
                            or processed_count % self.max_workers == 0
                            or processed_count == total):
                        preview = format_force_results(
                            list(results), (processed_count, total),
                            stopped=False,
                        )
                        self.preview_signal.emit(preview)

            answer = format_force_results(
                results, (total, total), stopped=False
            )
            self.finished_signal.emit(answer)

        except Exception as e:
            self.error_signal.emit(str(e))


class AgenticWorker(QThread):
    """Agentic Mode: 계획 → 검색 팬아웃 → 충분성 게이트 → 합성 (스트리밍).

    기존 노트북 RAG 인덱스(rag_sys)를 검색 도구로 재사용한다. LangGraph RAG
    파이프라인과는 독립적이며, ForceWorker 와 동일한 워커 패턴을 따른다.
    """
    status_signal   = pyqtSignal(str)         # 단계 상태 메시지
    trace_signal    = pyqtSignal(str, dict)   # (stage, payload) — 추론 과정 트레이스
    chunk_received  = pyqtSignal(str)          # 토큰 단위 스트리밍 (ChatTab.on_chunk_received 재사용)
    finished_signal = pyqtSignal(str, dict)    # (full_answer, result)
    error_signal    = pyqtSignal(str)

    def __init__(self, llm, rag_sys: dict, query: str,
                 conversation_history: list | None = None,
                 max_iters: int | None = None, fanout_k: int | None = None):
        super().__init__()
        self.llm                  = llm
        self.rag_sys              = rag_sys
        self.query                = query
        self.conversation_history = conversation_history or []
        self.max_iters            = max_iters
        self.fanout_k             = fanout_k
        self._stopped             = False

    def stop(self):
        self._stopped = True

    def run(self):
        try:
            from agentic_rag import NotebookRetrieverAdapter, run_agentic_rag

            adapter = NotebookRetrieverAdapter(self.rag_sys)

            def trace_cb(stage: str, payload):
                """dataclass/ dict payload 를 UI용 순수 dict 로 변환해 emit."""
                if self._stopped:
                    return
                if stage == "plan":
                    p = payload if isinstance(payload, dict) else {}
                    self.trace_signal.emit("plan", {
                        "reasoning": str(p.get("reasoning", "")),
                        "subquestions": [
                            {"q": str(s.get("q", "")),
                             "queries": [str(q) for q in s.get("queries", [])]}
                            for s in p.get("subquestions", []) if isinstance(s, dict)
                        ],
                    })
                    self.status_signal.emit("🧭 계획 수립 중…")
                elif stage == "iteration":
                    self.trace_signal.emit("iteration", {
                        "index":            payload.index,
                        "queries":          list(payload.queries),
                        "n_evidence":       payload.n_evidence,
                        "sufficient":       payload.sufficient,
                        "missing":          list(payload.missing),
                        "followup_queries": list(payload.followup_queries),
                    })
                    self.status_signal.emit(f"🔍 검색 반복 {payload.index + 1}…")
                elif stage == "synthesis_start":
                    self.trace_signal.emit("synthesis_start", {"n_evidence": int(payload)})
                    self.status_signal.emit("🤖 답변 생성 중…")

            self.status_signal.emit("🧭 계획 수립 중…")

            evidence_out: list = []
            answer = ""
            for token in run_agentic_rag(
                llm          = self.llm,
                adapter      = adapter,
                question     = self.query,
                history      = self.conversation_history,
                trace_cb     = trace_cb,
                is_stopped   = lambda: self._stopped,
                max_iters    = self.max_iters,
                fanout_k     = self.fanout_k,
                evidence_out = evidence_out,
            ):
                if self._stopped:
                    break
                answer += token
                self.chunk_received.emit(token)

            # 출처 표기 (중지되지 않았고 근거가 있을 때만)
            if not self._stopped and evidence_out and answer:
                src_map: dict = {}
                for e in evidence_out:
                    nb   = e.get("notebook", "unknown")
                    cidx = e.get("cell_idx", "?")
                    src_map.setdefault(nb, []).append(cidx)
                src_parts = [
                    f"{nb} (셀 {', '.join(f'#{c}' for c in sorted(set(idxs), key=str))})"
                    for nb, idxs in src_map.items()
                ]
                citation = "\n\n---\n📎 **출처**: " + " · ".join(src_parts)
                answer += citation
                self.chunk_received.emit("\x00CITATION\x00" + citation)

            docs = [e["doc"] for e in evidence_out if e.get("doc") is not None]
            self.finished_signal.emit(answer, {"all_docs": docs, "agentic_docs": docs})

        except Exception as e:
            self.error_signal.emit(str(e))


class ExampleQuestionsWorker(QThread):
    """예시 질문 생성 (백그라운드)"""
    finished_signal = pyqtSignal(list)

    def __init__(self, llm, docs: list):
        super().__init__()
        self.llm  = llm
        self.docs = docs

    def run(self):
        try:
            from rag_core import generate_example_questions
            questions = generate_example_questions(self.llm, self.docs)
            self.finished_signal.emit(questions)
        except Exception:
            self.finished_signal.emit([])


class SuggestedQueriesWorker(QThread):
    """후속 검색 쿼리 생성 (백그라운드)"""
    finished_signal = pyqtSignal(list)

    def __init__(self, llm, query: str, answer: str):
        super().__init__()
        self.llm    = llm
        self.query  = query
        self.answer = answer

    def run(self):
        try:
            from rag_core import generate_suggested_queries
            queries = generate_suggested_queries(self.llm, self.query, self.answer)
            self.finished_signal.emit(queries)
        except Exception:
            self.finished_signal.emit([])


class NotebookChatWorker(QThread):
    """노트북 셀 기반 Q&A 채팅 (RAG 미사용, 직접 LLM 호출)"""
    chunk_received  = pyqtSignal(str)
    finished_signal = pyqtSignal(str)      # full answer
    error_signal    = pyqtSignal(str)

    def __init__(self, llm, system_prompt: str, user_prompt: str,
                 conversation_history: list[dict] | None = None):
        super().__init__()
        self.llm               = llm
        self.system_prompt     = system_prompt
        self.user_prompt       = user_prompt
        self.conversation_history = conversation_history or []
        self._stopped          = False

    def stop(self):
        self._stopped = True

    def _build_history_messages(self) -> list:
        msgs = []
        for m in self.conversation_history:
            if m["role"] == "user":
                msgs.append(HumanMessage(content=m["content"]))
            elif m["role"] == "assistant":
                msgs.append(AIMessage(content=m["content"]))
        return msgs

    def run(self):
        try:
            messages = (
                [SystemMessage(content=self.system_prompt)]
                + self._build_history_messages()
                + [HumanMessage(content=self.user_prompt)]
            )
            buf = ""
            for chunk in self.llm.stream(messages):
                if self._stopped:
                    break
                buf += chunk.content
                self.chunk_received.emit(chunk.content)
            self.finished_signal.emit(buf)
        except Exception as e:
            self.error_signal.emit(str(e))


class SummaryWorker(QThread):
    """노트북별 LLM 요약 생성 (백그라운드)"""
    progress_signal  = pyqtSignal(int, int)         # (processed, total)
    summary_signal   = pyqtSignal(str, str, str)    # (notebook_name, summary_text, prompt_hash)
    finished_signal  = pyqtSignal()
    error_signal     = pyqtSignal(str)

    def __init__(self, llm, notebooks: dict):
        """notebooks = {name: [cells]} — 요약할 노트북만 전달"""
        super().__init__()
        self.llm       = llm
        self.notebooks = notebooks
        self._stopped  = False

    def stop(self):
        self._stopped = True

    def run(self):
        try:
            import hashlib
            from rag_core import load_summary_prompt, prepare_notebook_summary_prompt

            names = list(self.notebooks.keys())
            total = len(names)

            for i, name in enumerate(names):
                if self._stopped:
                    self.finished_signal.emit()
                    return

                # 매 노트북 직전에 프롬프트 파일을 다시 읽어 핫 리로드 지원
                sys_prompt = load_summary_prompt()
                prompt_hash = hashlib.md5(sys_prompt.encode()).hexdigest()

                try:
                    prompt = prepare_notebook_summary_prompt(
                        name, self.notebooks[name]
                    )
                    response = self.llm.invoke([
                        SystemMessage(content=sys_prompt),
                        HumanMessage(content=prompt),
                    ])
                    self.summary_signal.emit(name, response.content.strip(), prompt_hash)
                except Exception as e:
                    self.summary_signal.emit(name, f"❌ 요약 생성 실패: {e}", prompt_hash)

                self.progress_signal.emit(i + 1, total)

            self.finished_signal.emit()

        except Exception as e:
            self.error_signal.emit(str(e))


class WikiBuildWorker(QThread):
    """Wiki 지식 그래프 생성 워커 (4단계 파이프라인)"""
    progress_signal  = pyqtSignal(int, str)   # (percent 0-100, status_message)
    page_created     = pyqtSignal(str)        # slug of newly created page
    finished_signal  = pyqtSignal(dict)       # graph_data {"nodes": [...], "edges": [...]}
    error_signal     = pyqtSignal(str)

    def __init__(self, llm, cache_dir: str, nb_dir: str, *, overwrite: bool = False):
        super().__init__()
        self.llm        = llm
        self.cache_dir  = cache_dir
        self.nb_dir     = nb_dir
        self.overwrite  = overwrite
        self._stopped   = False

    def stop(self) -> None:
        self._stopped = True

    def run(self):
        try:
            import json
            from pathlib import Path
            from rag_core import (
                generate_notebook_wiki_page,
                extract_concepts_from_notebook,
                generate_concept_wiki_page,
                build_wiki_graph,
                save_wiki_index,
                append_wiki_log,
                load_wiki_concept_prompt,
                load_summary_prompt,
                prepare_notebook_summary_prompt,
                load_notebooks,
                get_file_md5,
                get_summary_prompt_hash,
                get_dir_hash,
                should_rebuild_wiki,
                load_wiki_graph_cache,
                load_wiki_metadata,
                save_wiki_metadata,
                save_wiki_graph_cache,
                slug,
            )
            from langchain_core.messages import HumanMessage, SystemMessage

            wiki_dir = Path(self.cache_dir) / "wiki"
            wiki_dir.mkdir(parents=True, exist_ok=True)

            # ── Check cache and skip rebuild if not needed ──────────────────────
            if not self.overwrite and not should_rebuild_wiki(self.cache_dir, self.nb_dir):
                self.progress_signal.emit(10, "💾 캐시에서 Wiki 로드 중…")
                cached_graph = load_wiki_graph_cache(self.cache_dir)
                if cached_graph:
                    self.progress_signal.emit(
                        100,
                        f"✅ 캐시 로드 완료 — 노드 {len(cached_graph.get('nodes', []))}개, 엣지 {len(cached_graph.get('edges', []))}개"
                    )
                    self.finished_signal.emit(cached_graph)
                    return
            else:
                if self.overwrite:
                    self.progress_signal.emit(5, "🔄 덮어쓰기 모드로 Wiki 재생성 중…")
                else:
                    self.progress_signal.emit(5, "🔄 변경된 노트북 감지 — Wiki 재생성 중…")

            # ── Phase 1: Load or Generate summaries ────────────────────────────
            self.progress_signal.emit(5, "📖 요약 준비 중…")
            summaries_path = Path(self.cache_dir) / "summaries.json"

            if summaries_path.exists():
                # 기존 summaries.json 로드
                self.progress_signal.emit(5, "📖 summaries.json 로드 중…")
                with open(summaries_path, encoding="utf-8") as f:
                    summaries = json.load(f)
            else:
                # summaries.json 없으면 자동 생성
                self.progress_signal.emit(5, "📝 노트북 요약 자동 생성 중…")

                # 노트북 파싱
                cells = load_notebooks(self.nb_dir, progress_callback=None)
                if not cells:
                    self.error_signal.emit("노트북을 찾을 수 없습니다.")
                    return

                # 노트북별로 그룹핑
                nb_dict = {}
                for cell in cells:
                    nb_name = cell.get("notebook", "")
                    if nb_name not in nb_dict:
                        nb_dict[nb_name] = []
                    nb_dict[nb_name].append(cell)

                summaries = {}
                sys_prompt = load_summary_prompt()
                prompt_hash = get_summary_prompt_hash()
                nb_names_to_summarize = list(nb_dict.keys())

                for i, nb_name in enumerate(nb_names_to_summarize):
                    if self._stopped:
                        return

                    try:
                        pct = 5 + int((i + 1) / len(nb_names_to_summarize) * 15)
                        self.progress_signal.emit(pct, f"요약 생성: {nb_name}")

                        user_prompt = prepare_notebook_summary_prompt(nb_name, nb_dict[nb_name])
                        response = self.llm.invoke([
                            SystemMessage(content=sys_prompt),
                            HumanMessage(content=user_prompt),
                        ])

                        # 노트북 파일 경로 찾기
                        nb_path = ""
                        for cell in nb_dict[nb_name]:
                            nb_path = cell.get("notebook_path", "")
                            if nb_path:
                                break

                        file_hash = get_file_md5(nb_path) if nb_path else ""

                        summaries[nb_name] = {
                            "hash": file_hash,
                            "prompt_hash": prompt_hash,
                            "summary": response.content.strip(),
                        }
                    except Exception as e:
                        self.progress_signal.emit(
                            5 + int((i + 1) / len(nb_names_to_summarize) * 15),
                            f"요약 생성 실패: {nb_name} ({str(e)[:30]})"
                        )
                        summaries[nb_name] = {
                            "hash": "",
                            "prompt_hash": prompt_hash,
                            "summary": f"(요약 생성 실패: {str(e)[:100]})",
                        }

                # summaries.json 저장
                Path(self.cache_dir).mkdir(parents=True, exist_ok=True)
                with open(summaries_path, "w", encoding="utf-8") as f:
                    json.dump(summaries, f, ensure_ascii=False, indent=2)

            # summaries: {nb_name: {hash, prompt_hash, summary}}
            nb_names = list(summaries.keys())

            # Build notebook wiki pages (no LLM)
            self.progress_signal.emit(20, "📑 노트북 페이지 생성 중…")
            for i, nb_name in enumerate(nb_names):
                if self._stopped:
                    return
                summary_text = summaries[nb_name].get("summary", "")
                path = generate_notebook_wiki_page(
                    nb_name, summary_text, wiki_dir, overwrite=self.overwrite
                )
                self.page_created.emit(slug(nb_name))
                pct = 20 + int((i + 1) / len(nb_names) * 15)  # 20→35%
                self.progress_signal.emit(pct, f"노트북 페이지 생성: {nb_name}")
                append_wiki_log(wiki_dir, "notebook_page", nb_name)

            # ── Phase 2: Extract concepts (one LLM call per notebook) ────────────
            self.progress_signal.emit(35, "🔍 개념 추출 중…")
            concept_prompt = load_wiki_concept_prompt()
            concept_map = {}  # concept_name → [nb_names that reference it]

            for i, nb_name in enumerate(nb_names):
                if self._stopped:
                    return
                summary_text = summaries[nb_name].get("summary", "")
                concepts = extract_concepts_from_notebook(
                    self.llm, nb_name, summary_text, concept_prompt
                )
                for concept in concepts:
                    concept_map.setdefault(concept, []).append(nb_name)
                pct = 35 + int((i + 1) / len(nb_names) * 30)  # 35→65%
                self.progress_signal.emit(pct, f"개념 추출: {nb_name} → {len(concepts)}개")

            # Deduplicate: keep concepts appearing in ≥1 notebook, limit to 40 total
            # Sort by frequency (most cross-referenced first)
            concept_names = sorted(
                concept_map.keys(),
                key=lambda c: len(concept_map[c]), reverse=True
            )[:40]

            # ── Phase 3: Generate concept wiki pages (one LLM call per concept) ──
            self.progress_signal.emit(65, "📝 개념 위키 페이지 생성 중…")
            existing_slugs = {slug(nb) for nb in nb_names}  # for valid [[link]] targets
            existing_slugs.update(slug(c) for c in concept_names)

            for i, concept in enumerate(concept_names):
                if self._stopped:
                    return
                related_nbs = concept_map[concept]
                path = generate_concept_wiki_page(
                    self.llm, concept, related_nbs, summaries, wiki_dir,
                    existing_slugs, overwrite=self.overwrite
                )
                if path:
                    self.page_created.emit(slug(concept))
                    append_wiki_log(wiki_dir, "concept_page", concept)
                pct = 65 + int((i + 1) / len(concept_names) * 25)  # 65→90%
                self.progress_signal.emit(pct, f"개념 페이지: {concept}")

            # ── Phase 4: Build graph JSON ─────────────────────────────────────────
            self.progress_signal.emit(90, "🗺️ 그래프 JSON 빌드 중…")
            graph_data = build_wiki_graph(wiki_dir)
            save_wiki_index(wiki_dir, graph_data["nodes"])

            # Save metadata and cache
            dir_hash = get_dir_hash(self.nb_dir)
            save_wiki_metadata(self.cache_dir, self.nb_dir, dir_hash)
            save_wiki_graph_cache(self.cache_dir, graph_data)

            self.progress_signal.emit(
                100,
                f"✅ 완료 — 노드 {len(graph_data['nodes'])}개, 엣지 {len(graph_data['edges'])}개"
            )
            self.finished_signal.emit(graph_data)

        except Exception as e:
            self.error_signal.emit(str(e))


class WikiQAWorker(QThread):
    """Wiki Q&A 스트리밍 워커"""
    chunk_received  = pyqtSignal(str)    # 토큰 단위 스트리밍
    finished_signal = pyqtSignal(str)    # 전체 응답
    error_signal    = pyqtSignal(str)

    def __init__(self, llm, question: str, cache_dir: str):
        super().__init__()
        self.llm       = llm
        self.question  = question
        self.cache_dir = cache_dir
        self._stopped  = False

    def stop(self) -> None:
        self._stopped = True

    def run(self):
        try:
            from pathlib import Path
            from rag_core import wiki_qa

            wiki_dir = Path(self.cache_dir) / "wiki"

            # 스트리밍 콜백
            def stream_callback(chunk: str):
                if not self._stopped:
                    self.chunk_received.emit(chunk)

            answer = wiki_qa(
                self.llm,
                self.question,
                wiki_dir,
                max_context_pages=5,
                stream_callback=stream_callback,
            )

            self.finished_signal.emit(answer)

        except Exception as e:
            self.error_signal.emit(str(e))
