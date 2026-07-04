# Phase 5 — Resume Tailoring Engine: Design

Status: Approved by user, pending spec review
Date: 2026-07-07
Scope: Consume a resume's original parsed `ResumeDocument`, a job posting's `JobPostingDocument`, and a session's `GapAnalysisDocument` (all now available from Phases 2-4) and produce a tailored `ResumeDocument`, persisted as a new versioned `resume_versions` row with an accompanying explainability record. No structural deletion of content, no numeric/categorical scoring (still Phase 6's job).

## 1. Context

This is the highest-stakes phase yet for hallucination risk: Phases 2-4 classify and compare already-true content, but this phase actively rewrites it. The core product rule governs every design decision here: **"Can this keyword be honestly supported? YES → rewrite. NO → don't include."** Two enforcement layers exist because of this elevated risk — prompt discipline (as in every prior phase) plus, for the first time, a code-level post-generation validation guard for one specific fabrication vector (unearned skills/technologies).

## 2. Rewrite Scope

The tailoring engine may **reword and reorder, but never delete**:
- Every `work_experience`, `project`, `education`, and `certification` entry from the original resume is preserved in the tailored output — same count in, same count out.
- Bullets may be rewritten (stronger action verbs, `recommended_keywords` woven in where honestly supportable) and reordered within their entry.
- Entries themselves (projects, work experience, etc.) may be reordered by relevance (most relevant first), per `gap_analysis.relevant_projects`/`irrelevant_projects`.
- No entry is ever silently dropped, even one gap analysis marked `irrelevant_projects` — that judgment is left to a human reviewing the output, not to this phase. This keeps the phase's job bounded and its guarantees testable via a simple entry-count invariant.

## 3. Schema Changes

**3.1 `resume_versions` gains a `session_id` column** (nullable, `ForeignKey("tailoring_sessions.id", ondelete="CASCADE")`). Nullable because the original Phase 2 parse isn't tied to any session (a `Resume` can be parsed once and reused across many `TailoringSession`s); every tailored version sets this to the session that produced it. This closes the traceability gap where, previously, a resume tailored for two different jobs would have no way to tell which version belonged to which job application.

**3.2 `version_number` is a global per-resume counter**, computed as `max(version_number for this resume_id across all sessions) + 1`. Finally generalizes the version-numbering logic that has been hardcoded to `version_number=1` since Phase 2's `resume_parser.py` (flagged as tech debt at the time). `version_number` remains a simple, ever-increasing, resume-scoped identifier; `session_id` is how you filter to one job's history.

**3.3 New `tailoring_changes` table** — the explainability record, one row per changed field, mirroring the `gap_analyses`-over-`generated_documents` precedent from Phase 4 (a dedicated table for structured phase-specific output, not an overload of the output-artifact store):

```python
class TailoringChange(Base):
    __tablename__ = "tailoring_changes"

    id = Column(Integer, primary_key=True)
    resume_version_id = Column(Integer, ForeignKey("resume_versions.id", ondelete="CASCADE"), nullable=False)
    field_changed = Column(String, nullable=False)
    original_text = Column(Text, nullable=True)
    tailored_text = Column(Text, nullable=False)
    rationale = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
```

`original_text` is nullable to allow for a bullet that's new phrasing of an implicit point rather than a 1:1 rewording of a single prior sentence; `tailored_text` and `rationale` are always required — every change must be explainable, per the product's "every change should be explainable" requirement.

**3.4 `field_changed` path format — identity-anchored, not raw positional indices.** Because entries can be reordered, a purely positional path like `work_experience[0].bullets[2]` would be ambiguous: does `[0]` mean position in the *original* document or the *tailored* one? Either choice is a trap — original-position paths become stale/misleading once the reader looks at the actual (reordered) tailored resume; tailored-position paths computed carelessly during generation can drift from their true target if the engine doesn't track identity through the reorder.

The engine resolves this by using **identity anchors**, not indices, for any entry that can be reordered:
- `work_experience["<company> — <title>"].bullets[i]`
- `projects["<project name>"].bullets[i]`
- `education["<institution>"]`
- Flat, non-reorderable fields use their name directly: `skills`, `certifications`, `summary`.

The bullet-level index `[i]` refers to that bullet's position **in the final tailored output** (post-reorder), since that's what a user reviewing the tailored resume will actually see and need to locate. Because the entry itself is identified by name/company+title/institution rather than position, the path stays correct regardless of how the engine reordered entries — there is no positional drift to misattribute. The engine builds each `TailoringChange` row by matching tailored entries back to their original counterpart via this identity anchor (project name, company+title, or institution are all fields the tailoring engine does not alter), never via list position.

## 4. Anti-Fabrication: Two Enforcement Layers

**4.1 Prompt discipline** (`backend/prompts/tailoring_rewrite/v1.jinja2`), same pattern as Phases 2-4's CRITICAL RULEs with concrete worked examples, covering every fabrication vector named in this phase's brainstorm:
- Never invent a metric/number not present in the original resume (e.g. "improved performance by 40%" when no number was ever stated).
- Never add a skill/technology to a bullet that wasn't already in the original resume's skills, work experience bullets, or project technologies, *or* in `gap_analysis.matching_skills`.
- Never fabricate a new project or work experience entry.
- Never incorporate a `gap_analysis.missing_skill` as though the candidate already possesses it — a missing skill may inform what to emphasize among *existing* honest content, never be asserted as already-had.
- Every rewritten bullet must be traceable to something already true in the original resume; the model is instructed to justify each change in a way the engine can extract into a `rationale`.

**4.2 Code-level skills/keywords validation guard** — new for this phase, because unearned skills are the one fabrication vector that's mechanically checkable without semantic judgment. After the orchestrator returns, the tailoring service collects every skill/technology named anywhere in the tailored output (the top-level `skills` list, plus every `technologies` entry within `projects`) and verifies each one already appears in the original `ResumeDocument` (its `skills` list, any work experience bullet text, or any project's `technologies`) or in `gap_analysis.matching_skills`. Any skill that fails this check causes the **entire run to be rejected** as a `TailoringError` — never silently stripped. Silently filtering would introduce the first place in this codebase where a service *mutates* LLM output post-hoc rather than persisting it verbatim or rejecting it wholesale; that would contradict the "service persists the orchestrator's output verbatim, never substitutes/embellishes" invariant Phase 2-4's fabrication-guard tests exist to prove. Rejecting the whole run keeps that invariant intact: either the run is trustworthy and gets persisted as-is, or it isn't and gets discarded.

**4.3 Metric fabrication has no code-level check — this is a documented residual risk.** Unlike unearned skills (checkable against a finite list of known-true strings), a fabricated metric ("40% improvement") has no equivalent mechanical check: there is no closed set of "true numbers" to validate against, since a legitimately-present metric in the original resume is just as much a free-form number as a hallucinated one, and distinguishing them requires semantic understanding of whether *this specific number, in this specific context* was actually stated in the source. This phase does not attempt that check. Metric-fabrication prevention is enforced **by prompt discipline only**, and this is called out explicitly as a known gap: the "fabricated metric" fixture test (§7) is deliberately designed to be a **prompt-quality test**, not a service-layer guard test — it exists to catch prompt wording regressions (the prompt stops effectively discouraging invented metrics), not to prove any code-level enforcement, because none exists for this vector. If real-world use ever reveals the model fabricating metrics despite the prompt, closing this gap would require either a stricter generation constraint (e.g., requiring the model to echo back the exact source sentence a metric came from) or a separate numeric-provenance pass — out of scope for this phase.

## 5. Data Flow & Three-Prerequisite Dependency Guard

New `backend/app/services/tailoring_engine.py`, parallel to `gap_analyzer.py`. `TailoringError` inherits `StageExecutionError`, same as `GapAnalysisError`/`JDExtractionError`/`ResumeParsingError`.

1. Look up the resume's version with `produced_by_stage="resume_parsing"` (the original parse — never a prior tailored version, see §6). If none exists, raise `TailoringError("resume_parsing has not succeeded for this session yet")`.
2. Look up `job_posting.parsed_json`. If null, raise `TailoringError("jd_extraction has not succeeded for this session yet")`.
3. Look up the session's most recent `gap_analyses` row. If none exists, raise `TailoringError("gap_analysis has not succeeded for this session yet")`.
4. All three checks happen before any orchestrator call, each with its own distinct message (matching Phase 4's two-prerequisite guard, extended to three).
5. Render the `tailoring_rewrite` prompt with all three documents, call `AIOrchestrator` with `TaskConfig(task_type="tailoring_rewrite", provider="nvidia", model="z-ai/glm-5.2", temperature=0.1, response_schema=ResumeDocument, fallback_providers=[])`.
6. On `OrchestratorError`: wrap as `TailoringError`.
7. On success: run the §4.2 skills guard. If it fails, raise `TailoringError` naming the unearned skill — nothing is persisted.
8. If the guard passes: compute the next `version_number` (§3.2), insert a new `resume_versions` row (`session_id` set, `produced_by_stage="tailoring_rewrite"`, `resume_json` = the tailored document), and insert one `TailoringChange` row per changed field (§3.3-3.4).

## 6. Re-Tailoring Is Always a Fresh, Independent Attempt

**Re-running `tailoring_rewrite` for the same session always sources from the original `resume_parsing` version, never from a prior tailored version.** A second run produces a second, independent `resume_versions` row — not a refinement chained off the first tailored attempt. Each tailoring run is a clean rewrite of the same ground truth (the original parse), not an iterative polish of the model's own prior output. This is the intended behavior for now, not an oversight: it avoids compounding hallucination risk across generations (each rewrite would otherwise be rewriting another rewrite, and this phase's anti-fabrication guarantees would need to hold across N generations rather than just one), at the cost of not supporting "tighten this further" iterative refinement. **This is flagged for reconsideration if iterative refinement becomes a real product need later** — that would be a deliberate future decision (most likely: an explicit "refine mode" that opts into chaining, with its own guardrail analysis), not something to silently start doing by accident.

## 7. Testing

- Fixture triples (original resume + JD + gap analysis) with known-bad mocked outputs to guard against, each with its own test:
  - **Fabricated metric** — mocked orchestrator returns a bullet containing an invented number not in the original resume. Per §4.3, this test is deliberately a **prompt-quality test** (asserting the prompt template contains the anti-metric-fabrication instruction and a worked example), not a service-layer rejection test, since no code-level guard exists to reject this case.
  - **Missing-skill-claimed-as-possessed** — mocked orchestrator returns a bullet implying possession of a `gap_analysis.missing_skill`. Prompt-level test (same reasoning as above): asserts the prompt explicitly forbids this, since the code-level guard (§4.2) only checks whether a skill string is *unearned*, not whether it was specifically drawn from `missing_skills` — a skill that happens to also appear in the original resume's true content wouldn't be caught by §4.2 even if the model was "inspired" by the missing-skills list, so the prompt instruction is the only defense for this specific case too.
  - **Invented project** — mocked orchestrator returns a tailored document with a project entry whose name doesn't match any original project. Service-layer test: asserts `tailoring_engine.py`'s entry-count/identity-matching logic either rejects the run or fails the entry-count invariant (§2) — this one *is* code-checkable, since project identity is a finite, known set from the original document.
  - **Unearned adjacent skill** (e.g., tailored bullet claims "Flask" when only "Django" was in the original resume and gap analysis) — service-layer test exercising the §4.2 code-level guard directly: mocked orchestrator returns a tailored document with an unearned skill; test asserts `TailoringError` is raised and that **nothing is persisted** (no new `resume_versions` row, no `TailoringChange` rows). Unlike the dependency-guard tests, the orchestrator *is* called here — the skills guard runs on its output, not before it — so this test is not about preventing the call, but about the run being fully discarded once the guard rejects it.
- **Dependency-guard tests** for all three prerequisites (no resume_parsing version, no jd_extraction, no gap_analysis), each asserting the orchestrator is never called (`orchestrator.calls == []`).
- **Entry-count-preserved test**: tailored output has the same number of `work_experience`/`projects`/`education`/`certifications` entries as the original, for a passing (non-rejected) run.
- **Reorder-misattribution guard test** (per this spec's addition): construct an original resume with 2 projects (A at position 0, B at position 1); mock the orchestrator to return a tailored document with the projects reordered (B first, A second) and each project's bullets rewritten differently. Assert the resulting `TailoringChange` rows' `field_changed` paths correctly name each project by its identity anchor (`projects["B"]...`, `projects["A"]...`) with `tailored_text` matching *that specific project's* rewritten bullet — proving the identity-anchored path format (§3.4) doesn't misattribute a change to the wrong project after reordering.
- **Version-numbering test**: two sessions tailoring the same resume produce `version_number` 2 and 3 respectively (not both claiming 2), with each row's `session_id` correctly distinguishing which session produced it.
- **Re-tailoring-is-independent test** (per this spec's addition): tailor the same session twice; assert both resulting `resume_versions` rows have `produced_by_stage="resume_parsing"`-sourced content (i.e., both were built from the same original document, not from each other) and got distinct, sequential `version_number`s.
- Unit tests mock the `AIOrchestrator` — no real API calls in the automated suite.
- One manual smoke-test script against the real NVIDIA API.

## 8. API Integration

`STAGE_RUNNERS["tailoring_rewrite"] = _run_tailoring`, reusing the existing `ThreadPoolExecutor` + `STAGE_TIMEOUT_SECONDS` + fresh-session-on-timeout pattern unchanged. **`test_run_stage_returns_501_for_unimplemented_stage`** (which has posted to `tailoring_rewrite` as its "still unimplemented" example since Phase 2) must be updated to target a different, still-genuinely-unimplemented stage name (e.g. whatever Phase 6's stage will be called, or a clearly-fake placeholder name) since this phase implements `tailoring_rewrite` for real.

## 9. Ledger Cleanup (folded into this phase, Task 1)

Before starting the new tailoring-engine work, this phase's first task closes 3 more items from the cross-phase follow-up backlog:

1. PDF fixture builder's untested overflow branch and missing `try/finally` around `doc.close()` (Phase 2 item).
2. `jd_extraction` prompt tests upgraded from substring-only assertions to full JSON-shape correctness checks (Phase 3 item).
3. `strip_json_code_fence`'s opening-fence-with-attached-content case (e.g. `` ```json{"a": 1}\n``` `` — content attached to the *opening* fence rather than the closing one), surfaced as a Minor finding in Phase 4's final review.

The remaining 6 ledger items (resume_parsing fabrication test keyword-only check, `parse_resume` fabrication guard's narrow `projects == []` assertion, `Responsibilities:`/`Keywords:` fixture labels untested, schema roundtrip test's default `schema_version`, strict-match rule's clause (a) looseness, `test_analyze_gap_wraps_orchestrator_error`'s missing explicit assertion) stay deferred.

## 10. Explicitly Out of Scope

- Any numeric/categorical match score (still Phase 6 — Hiring Agent evaluation).
- Deleting/omitting entries the gap analysis marked irrelevant (§2 — deliberate, human judgment call).
- A code-level metric-fabrication guard (§4.3 — deliberate, documented residual risk, prompt-only enforcement).
- Iterative refinement / chaining off a prior tailored version (§6 — deliberate, revisit if it becomes a real product need).
- Any change to `resume_parsing`, `jd_extraction`, `gap_analysis`, the timeout/thread-safety design, or the orchestrator/provider layer beyond reusing them as-is.
