# SPEC Review Report: SPEC-SETTINGS-003
Iteration: 1/3
Verdict: FAIL
Overall Score: 0.35

Reasoning context ignored per M1 Context Isolation. This audit is based solely on `spec.md` (with `acceptance.md` and `plan.md` read for cross-reference, as permitted by the Input Contract).

## Must-Pass Results

- [PASS] MP-1 REQ number consistency: `spec.md` §3 contains REQ-001 (L104) through REQ-013 (L150) with no gaps, no duplicates, consistent 3-digit zero-padding (REQ-001…REQ-013 verified sequentially at L104, L107, L110, L112, L115, L121, L124, L130, L134, L136, L142, L146, L150).

- [FAIL] MP-2 EARS format compliance: Every acceptance criterion in `acceptance.md` is written as a Given/When/Then test scenario, not as one of the five EARS patterns (Ubiquitous/Event-driven/State-driven/Optional/Unwanted). `acceptance.md:L3` states outright: "`spec.md`의 REQ-XXX별 **Given-When-Then 시나리오**." Every AC block (AC-REQ-001 `acceptance.md:L12-15`, AC-REQ-002/003 `L17-22`, AC-REQ-004 `L24-28`, AC-REQ-005 `L30-33`, AC-REQ-006/007 `L39-46`, AC-REQ-008 `L52-59`, AC-REQ-009 `L61-65`, AC-REQ-010 `L67-71`, AC-REQ-011 `L77-81`, AC-REQ-012 `L83-89`, AC-REQ-013 `L91-94`) uses "**Given** / **When** / **Then**" headers rather than EARS phrasing such as "When [trigger], the system shall [response]". Per M3 rubric this is explicitly the named failure mode: "Given/When/Then test scenarios mislabeled as EARS." This is a document-wide pattern, not an isolated slip — 11/11 AC blocks fail.

- [FAIL] MP-3 YAML frontmatter validity: `spec.md:L1-10` frontmatter is missing two of the six required fields.
  - `labels` is entirely absent from the frontmatter block (`spec.md:L1-10` contains `id`, `version`, `status`, `created`, `updated`, `author`, `priority`, `issue_number` — no `labels` key anywhere).
  - `created_at` is required by name; the document instead uses `created: 2026-07-11` (`spec.md:L5`), a different key name. A strict schema check for `created_at` finds no match.
  Two missing required fields = automatic FAIL per MP-3 definition ("Any missing required field = FAIL").

- [N/A] MP-4 Section 22 language neutrality: N/A — this SPEC is scoped to a single project's settings-reference documentation (env.txt/config.txt/prompt files for this codebase), not multi-language dev-tooling. No language-specific tool names (gopls, pylsp, etc.) appear anywhere in `spec.md`.

## Category Scores (0.0-1.0, rubric-anchored)

| Dimension | Score | Rubric Band | Evidence |
|-----------|-------|-------------|----------|
| Clarity | 0.50 | 0.50 — "Multiple requirements require interpretation" | The qualifier "high-level" is used as the *sole* boundary between required detail and prohibited content in REQ-002 (`spec.md:L107-109`), REQ-003 (`L110-111`), REQ-005 (`L115-117`, "구현 코드 전문 복붙이나 줄 단위 스키마 덤프를 포함해서는 안 된다"), and again in AC-REQ-005 (`acceptance.md:L32`, "high-level 설명 텍스트로 구성되며"). No measurable threshold is given for what counts as "high-level" vs. a forbidden "줄 단위 스키마 덤프", so two engineers could write reference-doc entries of very different depth and both plausibly satisfy the requirement. |
| Completeness | 0.50 | 0.50 — "frontmatter missing one or two fields" | All structural sections are present (HISTORY `L14-19`, Context/Problem/Solution `L25-63`, Scope `L71-97`, Requirements `L100-152`, Exclusions `L173-193`, plus `acceptance.md` for AC), but frontmatter is missing `labels` and `created_at` as named fields (`spec.md:L1-10`), which per the Completeness rubric caps the score at the 0.50 band regardless of section completeness. |
| Testability | 0.75 | 0.75 — "One AC is not precisely binary-testable but measurable with minor interpretation" | Most ACs are mechanically verifiable (file existence checks, string/signal assertions, e.g. AC-REQ-001 `acceptance.md:L12-15`, AC-REQ-009 `L61-65`). AC-REQ-002/003 (`L17-22`, "각 항목은 '무엇/소비 위치/흐름' 구조... 담는다") and AC-REQ-005 (`L30-33`, "high-level 설명 텍스트로 구성되며") require a judgment call about whether a prose section adequately captures the required structure/depth, rather than a strict binary check. |
| Traceability | 0.75 | 0.75 — "one AC references a REQ that exists but the mapping is indirect" | All REQ-001…REQ-013 have at least one AC and no AC references a non-existent REQ. However, AC-REQ-002/003 (`acceptance.md:L17-22`) merges REQ-002 and REQ-003 into a single combined AC block, and AC-REQ-006/007 (`L39-46`) merges REQ-006 and REQ-007 similarly — two instances of indirect, collapsed 1:many-REQ-to-1-AC mapping rather than a dedicated AC per REQ. |

## Defects Found

D1. spec.md:L1-10 — YAML frontmatter is missing the required `labels` field entirely (no array or string value present under this key anywhere in the frontmatter block) — Severity: critical (MP-3)

D2. spec.md:L5 — YAML frontmatter uses `created:` instead of the required `created_at:` field name; no field satisfying the `created_at` requirement exists — Severity: critical (MP-3)

D3. acceptance.md:L12-94 (all 11 AC blocks: AC-REQ-001, 002/003, 004, 005, 006/007, 008, 009, 010, 011, 012, 013) — Every acceptance criterion is written as a Given/When/Then test scenario instead of matching one of the five EARS patterns (Ubiquitous/Event-driven/State-driven/Optional/Unwanted); `acceptance.md:L3` self-labels this as "Given-When-Then 시나리오", confirming this is by design, not an oversight — Severity: critical (MP-2)

D4. spec.md:L134, L136, L146, L150 — REQ-009, REQ-010, REQ-012, and REQ-013 embed concrete implementation symbols directly in normative requirement text: `_on_ask_clicked` (L134), `_append_qa_history` (L136-137), `find_config_key_in_question`, `validate_kv_text`, `classify_config_changes`, `reset_config_defaults`, `mask_sensitive_value` (L146-148, five function names in one REQ), and `load_system_prompt` (L150). This is HOW, not WHAT/WHY, and violates the Requirements Quality checklist (RQ-3/RQ-4: "no function names, class names... in requirements") — Severity: major

D5. spec.md:L107-117, acceptance.md:L32 — The undefined qualifier "high-level" is the only boundary condition distinguishing required documentation depth from the explicitly prohibited "구현 코드 전문 복붙이나 줄 단위 스키마 덤프" (REQ-005, L115-117). No measurable criterion (e.g., max lines per section, prohibited content patterns) is given, so this determination is left to human judgment — Severity: major

D6. acceptance.md:L17-22 and L39-46 — AC-REQ-002/003 and AC-REQ-006/007 each combine two distinct REQ-XXX identifiers into a single AC scenario rather than providing one AC per REQ, weakening 1:1 traceability — Severity: minor

D7. spec.md:L107-114 — REQ-002, REQ-003, and REQ-004 are labeled "(Ubiquitous)" but do not use the canonical EARS Ubiquitous subject "The [system] shall..."; instead the grammatical subject is "문서의 각 파라미터 항목은..." (L107) and "문서가 인용하는... 이름은..." (L112), i.e., the document/its content rather than the system itself — Severity: minor

## Chain-of-Verification Pass

Second-look findings: Re-read all 13 REQ entries individually a second time (spec.md:L102-152) to confirm sequential numbering end-to-end (confirmed REQ-001 through REQ-013, no gaps) and re-checked that each REQ maps to at least one AC by cross-referencing every AC-REQ-XXX heading in acceptance.md against the REQ list (confirmed full coverage, no orphaned ACs, no uncovered REQs). Re-read the Exclusions section (spec.md:L173-193) a second time — all 8 entries are specific (named files, named tools, explicit git/branch policy), not vague boilerplate, so no additional Completeness defect there. Searched for weasel words from the banned list ("적절/합리적/충분히/알맞/타당") across spec.md and acceptance.md — no exact matches found, so AC-3 is not independently violated by the literal banned-word list (the "high-level" ambiguity is reported separately under Clarity/Testability rather than as an AC-3 weasel-word violation). No new must-pass defects were found on the second pass beyond D1-D7 already listed; the MP-2 and MP-3 failures found in pass one remain the primary blockers.

## Recommendation

This SPEC cannot be approved in its current form because two must-pass criteria (MP-2, MP-3) fail. Required fixes for manager-spec, in priority order:

1. **Fix YAML frontmatter (spec.md:L1-10)**: Add a `labels` field (array or string, e.g. `labels: [settings, qa, documentation]`). Rename `created:` to `created_at:` (or add `created_at:` alongside `created:` if `created` is used elsewhere) so the exact required field name is present.

2. **Rewrite all acceptance criteria in EARS format (acceptance.md, all 11 AC blocks)**: Convert every Given/When/Then scenario into one of the five EARS patterns. For example, AC-REQ-001 (`acceptance.md:L12-15`) should become something like: "The system shall include exactly one `settings_reference.txt` file at the project root, not split per parameter or file." AC-REQ-008 (`acceptance.md:L52-59`) should become an Event-driven statement: "When a settings Q&A question does not match any known config/env key, the system shall route it through `build_settings_qa_grounded_prompt(...)` via the `qa_requested` signal instead of emitting the hardcoded rejection message." Given/When/Then content can be retained as illustrative test notes underneath each EARS statement, but the criterion itself must be the EARS sentence.

3. **Remove embedded implementation symbols from REQ-009, REQ-010, REQ-012, REQ-013 (spec.md:L134, L136, L146-148, L150)**: Restate these as behavior/outcome requirements without naming specific functions (e.g., REQ-012 should describe "existing config validation, classification, reset, and masking behavior" as an outcome constraint rather than listing five function names). Implementation-level symbol references belong in `plan.md`, which already covers this appropriately (e.g., `plan.md:L38-45` lists concrete symbols correctly, since `plan.md` is the HOW document).

4. **Define "high-level" measurably (spec.md:L107-117, REQ-005; acceptance.md:L32, AC-REQ-005)**: Replace the undefined "high-level" qualifier with a concrete, checkable boundary — for example, a maximum line count per parameter/file section, or an explicit rule such as "no verbatim source code blocks; prose only, cross-referencing source locations by name without reproducing code."

5. **Split combined AC blocks (acceptance.md:L17-22 and L39-46)**: Provide one dedicated AC per REQ-XXX for REQ-002/REQ-003 and REQ-006/REQ-007 respectively, rather than merging two REQs into a single AC scenario.

6. (Minor, optional) Rephrase REQ-002/REQ-003/REQ-004 (spec.md:L107-114) to use "The system shall..." as the grammatical subject to match the canonical EARS Ubiquitous template, rather than "문서의 각 항목은...".
