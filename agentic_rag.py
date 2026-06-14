"""
Agentic RAG (계획 기반 에이전트 검색)

`D:\\2026_Agent\\1_Understanding_fast\\pure_planning_agentic_rag` 의 순수 계획형
agentic RAG 루프를 이 앱의 노트북 RAG 인덱스 위에서 동작하도록 이식한 모듈.

    계획/질의 재작성 (하위 질문 -> 검색어)
        -> 검색 팬아웃 (검색어별 top-k, 병렬, 중복 제거)
        -> 충분성 게이트 -> (부족하면 후속 검색어로 다시 검색)
        -> 합성 (근거 기반 답변, 스트리밍)

기존 프로젝트와 달리 (a) 검색은 PDF 페이지가 아니라 노트북 셀(`rag_sys`의 retriever)을
대상으로 하고, (b) LLM은 모듈 전역 클라이언트가 아니라 호출자가 넘겨준
`ChatOpenAI` 인스턴스(`self.state.llm`)를 사용한다. 새 의존성은 없다.
"""
from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from rag_core import RAG_CONFIG


# ─────────────────────────────────────────────────────────────────────────────
# 설정 (config.txt 의 RAG_CONFIG 공유)
# ─────────────────────────────────────────────────────────────────────────────

def _cfg_int(key: str, default: int) -> int:
    try:
        return int(RAG_CONFIG.get(key, str(default)))
    except (ValueError, TypeError):
        return default


# 오케스트레이터가 (팬아웃 -> 평가 -> 보강)을 반복할 수 있는 최대 횟수.
MAX_ITERS: int = _cfg_int("AGENTIC_MAX_ITERS", 3)
# 검색어 하나가 벡터 인덱스에서 가져오는 청크 수.
FANOUT_TOP_K: int = _cfg_int("AGENTIC_FANOUT_K", 5)
# 작업 컨텍스트에 유지하는 누적 근거의 상한 (점수 높은 것 우선).
MAX_SNIPPETS: int = _cfg_int("AGENTIC_MAX_SNIPPETS", 24)
# 한 패스에서 계획/재작성기가 내놓을 수 있는 검색어 수 상한.
MAX_QUERIES_PER_PASS: int = _cfg_int("AGENTIC_MAX_QUERIES", 8)


# ─────────────────────────────────────────────────────────────────────────────
# 검색 도구 어댑터 (기존 노트북 retriever 재사용)
# ─────────────────────────────────────────────────────────────────────────────

class NotebookRetrieverAdapter:
    """`rag_sys` 의 ensemble(vector+BM25) retriever 를 감싸 topk() 인터페이스 제공.

    Ensemble retriever 는 명시적 점수를 주지 않으므로 순위 기반 의사 점수
    (1/(rank+1)) 를 부여한다 — 루프의 중복 제거/병합 정렬에는 충분하다."""

    def __init__(self, rag_sys: dict[str, Any]):
        self._retriever = (
            rag_sys.get("ensemble_retriever")
            or rag_sys.get("vector_retriever")
        )

    def topk(self, query: str, k: int = FANOUT_TOP_K) -> list[dict]:
        if self._retriever is None:
            return []
        try:
            docs = self._retriever.invoke(query)
        except Exception:
            return []
        out: list[dict] = []
        for rank, d in enumerate(docs[:k]):
            meta = getattr(d, "metadata", {}) or {}
            out.append({
                "text":      d.page_content,
                "notebook":  meta.get("notebook", "?"),
                "cell_idx":  meta.get("cell_idx", "?"),
                "cell_type": meta.get("cell_type", ""),
                "source":    meta.get("source", d.page_content[:60]),
                "doc":       d,
                "score":     1.0 / (rank + 1),
            })
        return out


# ─────────────────────────────────────────────────────────────────────────────
# 근거(evidence) 관리
# ─────────────────────────────────────────────────────────────────────────────

def _clean_queries(raw: Any) -> list[str]:
    """LLM이 준 검색어 목록을 비어있지 않은 문자열의 중복 제거 리스트로 정리(순서 유지)."""
    out: list[str] = []
    seen: set[str] = set()
    for x in raw if isinstance(raw, list) else []:
        q = str(x).strip()
        key = q.lower()
        if q and key not in seen:
            seen.add(key)
            out.append(q)
    return out[:MAX_QUERIES_PER_PASS]


def _evidence_key(e: dict[str, Any]) -> str:
    """중복 식별: 같은 셀(source 노드 ID)이면 어떤 검색어로 나왔든 동일 청크."""
    src = str(e.get("source", "")).strip()
    if src:
        return src
    body = str(e.get("text", "")).strip()
    return hashlib.md5(body.encode("utf-8")).hexdigest()


def _merge_evidence(existing: list[dict], new: list[dict]) -> list[dict]:
    """기존+신규 근거를 합치되 충돌 시 높은 점수를 유지하고, 점수 내림차순으로
    상위 MAX_SNIPPETS개만 반환."""
    by_key: dict[str, dict] = {}
    for e in existing + new:
        k = _evidence_key(e)
        if k not in by_key or e.get("score", 0.0) > by_key[k].get("score", 0.0):
            by_key[k] = e
    merged = sorted(by_key.values(), key=lambda e: e.get("score", 0.0), reverse=True)
    return merged[:MAX_SNIPPETS]


def _render_evidence(evidence: list[dict]) -> str:
    """근거를 번호가 매겨진 노트북/셀 태그 블록으로 포맷(LLM 프롬프트용)."""
    if not evidence:
        return "(검색된 근거 없음)"
    lines = []
    for i, e in enumerate(evidence, 1):
        nb = e.get("notebook", "?")
        cidx = e.get("cell_idx", "?")
        ctype = e.get("cell_type", "")
        tag = f"노트북: {nb} · 셀 #{cidx}" + (f" ({ctype})" if ctype else "")
        lines.append(f"[{i}] ({tag})\n{str(e.get('text', '')).strip()}")
    return "\n\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 시스템 프롬프트 로더 (prompts/ 파일 우선, 없으면 기본값)
# ─────────────────────────────────────────────────────────────────────────────

def _load_prompt(filename: str, default: str) -> str:
    fp = Path("prompts") / filename
    if fp.exists():
        return fp.read_text(encoding="utf-8").strip()
    return default


_DEFAULT_PLANNER = """당신은 노트북 강의 자료에 대한 질문에 답하는 에이전트 RAG 시스템의 '계획 수립 + 질의 재작성' 담당입니다.
검색 도구는 의미 기반 유사도 검색(dense vector)만 제공하며, 검색어와 의미적으로 가까운 셀을 반환할 뿐입니다.
따라서 최종 답변의 품질은 질문을 얼마나 잘 분해하고 검색어로 재작성하느냐에 거의 전적으로 달려 있습니다.

두 가지 작업을 수행하세요:
1. 분해(DECOMPOSE): 사용자의 질문을, 완전히 답하기 위해 각각 해결해야 하는 별개의 하위 질문들로 나눕니다.
   단순 조회는 하위 질문 1개로 충분하지만, 비교/다중 단계/"X에 대해 모두 나열" 같은 질문은 여러 개가 필요합니다.
2. 재작성(REWRITE): 각 하위 질문을 1~3개의 검색어로 바꿉니다. 짧고 핵심어 중심이며 독립적으로 이해되는 표현으로
   작성하고, 같은 하위 질문이라도 동의어·다른 표현을 활용해 검색 범위를 넓히세요.

지침:
- 모호한 검색어보다 구체적이고 내용이 담긴 검색어를 선호하세요.
- 검색어 개수는 질문의 복잡도에 비례하게 하고, 불필요하게 늘리지 마세요.
- 각 검색어는 독립적으로 검색되므로 대명사·지시어를 풀어 자체적으로 완결되게 작성하세요.

다음 형태의 JSON만 출력하세요:
{
  "reasoning": "<질문을 어떻게 분해했는지 1~2문장>",
  "subquestions": [
    {"q": "<자연어 하위 질문>", "queries": ["<검색어>", "..."]}
  ]
}"""


_DEFAULT_SUFFICIENCY = """당신은 에이전트 RAG 시스템의 '충분성 판단' 게이트입니다.
사용자의 질문과 지금까지 검색된 근거(번호가 매겨진 노트북 셀들)가 주어집니다.
일반적인 RAG는 근거가 불완전해도 그냥 답변하지만, 당신의 역할은 그것을 막는 것입니다.

다음을 수행하세요:
1. 현재 근거로 만들 수 있는 최선의 답을 머릿속으로 작성합니다.
2. 그 답을 질문이 실제로 요구하는 모든 부분과 비교해, 아직 근거로 뒷받침되지 않은 부분
   (누락된 사실, 검색되지 않은 하위 주제, 한쪽만 찾은 비교 등)을 찾습니다.
3. 근거가 질문에 완전하고 정확하게 답하기에 충분한지 판단합니다.

엄격하되 현실적으로:
- 질문의 모든 부분을 근거가 실제로 다룰 때에만 "sufficient": true 로 표시하세요.
- 노트북에 해당 내용이 명백히 없고 더 검색해도 나올 가능성이 낮다면, 역시 "sufficient": true 로 표시해
  합성 단계가 솔직하게 "다루지 않음"이라고 말하게 하세요. 없는 정보를 무한정 찾지 마세요.
- 그 외에는 "sufficient": false 로 표시하고, 누락된 부분을 정확히 겨냥한 후속 검색어를 제안하세요.
  이미 실패한 검색어와는 다른, 구체적이고 핵심어 중심의 독립적 표현으로 작성하세요.

다음 형태의 JSON만 출력하세요:
{
  "sufficient": true | false,
  "missing": ["<각 누락 부분 짧은 설명>", ...],
  "followup_queries": ["<겨냥한 검색어>", ...]
}
"sufficient"가 true이면 "missing"과 "followup_queries"는 빈 배열이어야 합니다."""


_DEFAULT_SYNTHESIS = """당신은 에이전트 RAG 시스템의 '합성' 담당으로, 노트북 강의 자료를 분석하는 친절한 한국어 AI 튜터입니다.
사용자의 질문에 대한 최종 답변을, 검색된 근거(번호가 매겨진 노트북 셀들)에만 근거하여 작성하세요.

규칙:
- 근거로 뒷받침되는 정보만 사용하세요. 외부 지식이나 추측을 더하지 마세요. 근거가 불완전하거나 질문을
  다루지 않으면, 지어내지 말고 그 사실을 솔직하게 말하세요.
- 정확하고 구체적으로 답하고, 가능하면 노트북에서 쓰인 용어를 그대로 사용하세요.
- 코드가 근거에 있으면 코드 블록으로 인용하고 설명하세요.
- 질문에 맞게 구조화하세요: 단순 질문은 간결한 산문으로, 다중 항목·비교·나열형 질문은 짧은 소제목이나 불릿으로.
- "근거", "셀", "검색" 같은 내부 과정 용어를 언급하지 말고, 자료를 충분히 읽은 전문가처럼 답하세요.
- 답변은 한국어로 작성합니다."""


def load_agentic_planner_prompt() -> str:
    return _load_prompt("agentic_planner_prompt.txt", _DEFAULT_PLANNER)


def load_agentic_sufficiency_prompt() -> str:
    return _load_prompt("agentic_sufficiency_prompt.txt", _DEFAULT_SUFFICIENCY)


def load_agentic_synthesis_prompt() -> str:
    return _load_prompt("agentic_synthesis_prompt.txt", _DEFAULT_SYNTHESIS)


# ─────────────────────────────────────────────────────────────────────────────
# 구조화 출력 헬퍼 (호출자가 넘긴 llm 사용)
# ─────────────────────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json(text: str) -> Any:
    """LLM 응답에서 첫 JSON 객체/배열을 최선을 다해 파싱. 실패 시 None."""
    if not text:
        return None
    candidates: list[str] = [text.strip()]
    m = _FENCE_RE.search(text)
    if m:
        candidates.append(m.group(1).strip())
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = text.find(opener), text.rfind(closer)
        if 0 <= i < j:
            candidates.append(text[i:j + 1])
    for cand in candidates:
        try:
            return json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def chat_json(llm, system: str, user: str) -> Any:
    """JSON 응답을 기대하는 채팅 호출. 파싱 실패 시 None(호출자가 폴백 결정)."""
    system = system.rstrip() + (
        "\n\n반드시 유효한 JSON만 출력하세요. 다른 설명이나 코드 펜스(```)는 절대 포함하지 마세요."
    )
    result = llm.invoke([SystemMessage(content=system), HumanMessage(content=user)])
    return _extract_json(result.content or "")


def _history_messages(history: list[dict] | None) -> list:
    """대화 히스토리 dict 를 LangChain 메시지 객체로 변환."""
    msgs = []
    for m in history or []:
        if m.get("role") == "user":
            msgs.append(HumanMessage(content=m["content"]))
        elif m.get("role") == "assistant":
            msgs.append(AIMessage(content=m["content"]))
    return msgs


# ─────────────────────────────────────────────────────────────────────────────
# 개별 에이전트
# ─────────────────────────────────────────────────────────────────────────────

def plan(llm, question: str) -> dict[str, Any]:
    """계획/질의 재작성: 질문을 하위 질문으로 분해하고 각각을 검색어로 재작성."""
    out = chat_json(llm, load_agentic_planner_prompt(), f"질문: {question}")
    subs: list[dict[str, Any]] = []
    raw_subs = out.get("subquestions") if isinstance(out, dict) else None
    for item in raw_subs or []:
        if not isinstance(item, dict):
            continue
        q = str(item.get("q") or item.get("question") or "").strip()
        queries = _clean_queries(item.get("queries"))
        if not queries and q:  # 재작성기가 검색어를 못 주면 하위 질문 자체로 검색
            queries = [q]
        if queries:
            subs.append({"q": q or queries[0], "queries": queries})
    if not subs:  # 계획 실패: 질문 전체를 그대로 검색
        return {"reasoning": "(계획 생성 실패 — 질문 전체로 검색)",
                "subquestions": [{"q": question, "queries": [question]}]}
    reasoning = str(out.get("reasoning", "")) if isinstance(out, dict) else ""
    return {"reasoning": reasoning, "subquestions": subs}


def search_fanout(adapter: NotebookRetrieverAdapter, queries: list[str],
                  fanout_k: int = FANOUT_TOP_K) -> list[dict]:
    """검색 팬아웃: 각 검색어를 벡터 top-k로 병렬 검색해 근거를 수집."""
    queries = _clean_queries(queries)
    if not queries:
        return []

    def run(query: str) -> list[dict]:
        hits = adapter.topk(query, k=fanout_k)
        for h in hits:
            h["query"] = query
        return hits

    with ThreadPoolExecutor(max_workers=min(4, len(queries))) as ex:
        batches = list(ex.map(run, queries))
    flat = [h for batch in batches for h in batch]
    return _merge_evidence([], flat)


def assess_sufficiency(llm, question: str, evidence: list[dict]) -> dict[str, Any]:
    """충분성 게이트: 근거가 질문에 충분한지 판단하고, 부족하면 후속 검색어 제안."""
    user = f"질문: {question}\n\n근거:\n{_render_evidence(evidence)}"
    out = chat_json(llm, load_agentic_sufficiency_prompt(), user)
    if not isinstance(out, dict):
        # 게이트 파싱 실패: 무한 루프 대신 충분하다고 보고 합성으로.
        return {"sufficient": True, "missing": [], "followup_queries": []}
    return {
        "sufficient": bool(out.get("sufficient", True)),
        "missing": [str(m) for m in (out.get("missing") or [])],
        "followup_queries": _clean_queries(out.get("followup_queries")),
    }


def synthesize(llm, question: str, evidence: list[dict],
               history: list[dict] | None = None,
               is_stopped: Callable[[], bool] | None = None) -> Iterator[str]:
    """합성: 근거 기반 최종 답변을 토큰 단위로 스트리밍."""
    user = (
        f"질문: {question}\n\n근거(노트북 셀):\n{_render_evidence(evidence)}\n\n"
        f"위 근거를 바탕으로 질문에 답변하세요."
    )
    messages = [SystemMessage(content=load_agentic_synthesis_prompt())]
    messages += _history_messages(history)
    messages.append(HumanMessage(content=user))
    for chunk in llm.stream(messages):
        if is_stopped is not None and is_stopped():
            break
        token = chunk.content or ""
        if token:
            yield token


# ─────────────────────────────────────────────────────────────────────────────
# 오케스트레이터
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class IterationTrace:
    index: int
    queries: list[str]
    n_evidence: int
    sufficient: bool
    missing: list[str] = field(default_factory=list)
    followup_queries: list[str] = field(default_factory=list)


# trace_cb(stage, payload): "plan" | "iteration" | "synthesis_start"
TraceCb = Callable[[str, Any], None]


def run_agentic_rag(
    llm,
    adapter: NotebookRetrieverAdapter,
    question: str,
    history: list[dict] | None = None,
    trace_cb: TraceCb | None = None,
    is_stopped: Callable[[], bool] | None = None,
    max_iters: int | None = None,
    fanout_k: int | None = None,
    evidence_out: list | None = None,
) -> Iterator[str]:
    """순수 계획형 agentic RAG 루프를 돌리고 최종 답변을 토큰 단위로 스트리밍.

    단계별 진행은 trace_cb(stage, payload)로 보고하고(None이면 조용히 실행),
    최종 근거 목록은 evidence_out 리스트에 채워 호출자(출처 표기용)에 전달한다."""
    if max_iters is None:
        max_iters = MAX_ITERS
    if fanout_k is None:
        fanout_k = FANOUT_TOP_K

    def emit(stage: str, payload: Any) -> None:
        if trace_cb is not None:
            trace_cb(stage, payload)

    def stopped() -> bool:
        return is_stopped is not None and is_stopped()

    p = plan(llm, question)
    emit("plan", p)
    if stopped():
        return

    # 첫 패스는 계획/재작성기가 만든 모든 검색어를 검색.
    queries = _clean_queries([q for sub in p["subquestions"] for q in sub["queries"]])
    evidence: list[dict] = []
    for i in range(max_iters):
        if stopped():
            break
        evidence = _merge_evidence(evidence, search_fanout(adapter, queries, fanout_k))
        if stopped():
            break
        verdict = assess_sufficiency(llm, question, evidence)
        emit("iteration", IterationTrace(
            index=i,
            queries=queries,
            n_evidence=len(evidence),
            sufficient=verdict["sufficient"],
            missing=verdict["missing"],
            followup_queries=verdict["followup_queries"],
        ))
        if verdict["sufficient"] or not verdict["followup_queries"]:
            break
        # 다음 패스는 게이트가 지목한 빈틈만 겨냥.
        queries = verdict["followup_queries"]

    if evidence_out is not None:
        evidence_out[:] = evidence

    emit("synthesis_start", len(evidence))
    if stopped():
        return
    yield from synthesize(llm, question, evidence, history, is_stopped)
