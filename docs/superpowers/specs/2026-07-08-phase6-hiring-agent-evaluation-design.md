# Phase 6 — Hiring-Agent Integration (Evaluation): Design

Status: Approved by user, pending spec review
Date: 2026-07-08
Scope: Wire the tailored `ResumeDocument` through the existing `hiring-agent-service` HTTP wrapper (built in Phase 1's Task 11) to get real evaluation scores, persisted into the existing `evaluation_runs` table. Evaluate-only — no "re-tailor if score is low" loop.

## 1. Context

This closes the loop the original product vision described: tailor → evaluate → improve if needed. Phase 6 implements only the "evaluate" step. Every prior phase since Phase 3 has deferred a harder problem to a later phase (Phase 3 deferred URL fetching, Phase 5 deferred iterative refinement); this phase follows the same discipline and defers the "re-tailor and re-evaluate" loop to a later phase or to n8n orchestration (Phase 10). This phase proves synchronous evaluation of one tailored resume; composing that into a retry loop is a separate, deliberate future decision.

Unlike every phase since Phase 2, this phase makes **no LLM Orchestrator call, no prompt template, and has no fabrication-guard concerns** — the only external call is a synchronous HTTP POST to `hiring-agent-service`, which itself is the one making the LLM call internally. This makes Phase 6 the lightest-weight phase since Phase 1.

## 2. The Real Contract (Verified Against Actual Code)

`hiring-agent-service/app.py`'s `POST /evaluate` (confirmed by reading the file directly, not assumed):

**Request:** `{"resume_text": str, "github_username": str | None}`

**Response:** `overall_score`, `open_source_score`, `projects_score`, `production_score`, `technical_skills_score`, `evidence` (per-category evidence dict), `bonus_points`, `deductions`, `rubric_version`, `hiring_agent_service_version`, `raw` (the full underlying `EvaluationData` dump).

This confirms the input-format mismatch this phase must solve: the wrapper expects raw prose (`resume_text: str`), not the structured `ResumeDocument` this pipeline has used since Phase 2. A rendering step is required (§3).

**`github_username` is a confirmed dead field, not merely optional.** Reading `hiring-agent-service/app.py`'s handler: `evaluation = evaluator.evaluate_resume(request.resume_text)` — only `resume_text` is passed to `ResumeEvaluator`. Reading `hiring-agent-imp/evaluator.py`: `evaluate_resume(self, resume_text: str) -> EvaluationData` — the method signature doesn't accept a `github_username` parameter at all. The field exists on the wrapper's request model but is never read or forwarded anywhere in the call chain. **Passing `None` therefore has zero effect on any score, including `open_source_score`** — not "neutral," genuinely inert, since the value is discarded before evaluation happens. This phase passes `github_username=None` and this is confirmed safe, not an assumption.

## 3. Rendering: `ResumeDocument` → `resume_text`

New `backend/app/services/resume_renderer.py`: `render_resume_to_text(resume_json: dict) -> str`. Walks the tailored resume's fields (contact, summary, work experience with bullets, projects, skills, education, certifications) and produces plain, readable prose — similar in spirit to what `pymupdf4llm` originally extracted from a real PDF in Phase 2, since `ResumeEvaluator` was built and tuned against that kind of natural-language resume text, not raw JSON. Deterministic and field-by-field testable; no LLM call needed.

**Information-loss risk (a distinct risk from every prior phase's fabrication risk).** This phase has no hallucination surface — it doesn't generate new content, only reformats existing structured data into prose. But it has a different risk: `render_resume_to_text()` could *under-represent* signal that's genuinely present in the structured `ResumeDocument` but gets lost or flattened in the text conversion (e.g., a project's `technologies` list rendered as an afterthought instead of prominently, in a way `ResumeEvaluator`'s rubric — which specifically looks for open-source/production/technical-skills indicators — might not pick up on as strongly as it would from differently-phrased prose). This is not a correctness bug the automated test suite can catch on its own (rendering "correctly" per a field-by-field unit test doesn't prove the rendered prose actually surfaces every scoring-relevant signal to the real evaluator). **This phase's manual smoke script (§7) must include a validation step**: run a real fixture resume with clear, known production/open-source/technical-skills indicators through the actual `render_resume_to_text()` → real `hiring-agent-service` → and manually eyeball whether the resulting scores/evidence plausibly reflect the fixture's known content, not just that the pipeline runs end-to-end without erroring. This is explicitly about catching information loss, not fabrication.

## 4. Storage — Reuses the Existing `evaluation_runs` Table

**Verified against the actual Phase 1 migration** (`backend/alembic/versions/0001_initial_schema.py`), not assumed: `evaluation_runs` already has `id`, `session_id`, `resume_version_id`, `overall_score`, `open_source_score`, `projects_score`, `production_score`, `technical_skills_score`, `raw_response_json`, `rubric_version`, `hiring_agent_service_version`, `created_at` — every field this phase needs, with types that match the wrapper's response shape exactly (`Float` for scores, `JSON` for the raw blob, `String` for the two version fields). **No new migration is needed for this phase** — Phase 1's schema design already anticipated this response shape correctly. This is the first phase since Phase 1 to reuse an existing table rather than add a new one.

`raw_response_json` stores the entire `/evaluate` response body (including `evidence`, `bonus_points`, `deductions`, and the nested `raw` field) — the full audit trail, not just the top-level scores, mirroring how `llm_calls.response_payload` and other phases' `*_json` columns store complete responses rather than partial extracts.

Each evaluation run inserts a new `evaluation_runs` row — no dedup, no update-in-place — matching the `gap_analyses`/tailored-`resume_versions` precedent from Phases 4-5: re-evaluating after a re-tailor is just another row, distinguishable by `resume_version_id` and `created_at`.

## 5. Dependency Guard — Single Prerequisite

New `backend/app/services/evaluator.py`, parallel to the other stage services. `EvaluationError` inherits `StageExecutionError`, same as `TailoringError`/`GapAnalysisError`/etc.

1. Look up the session's most recent `resume_versions` row with `produced_by_stage="tailoring_rewrite"` (same query shape as `tailoring_engine.py`'s own `produced_by_stage="resume_parsing"` lookup, just filtering the other stage — confirming a *tailored* version exists, not just any parsed version). If none exists, raise `EvaluationError("tailoring_rewrite has not succeeded for this session yet")` before any HTTP call.
2. Render the tailored resume's `resume_json` to text via `render_resume_to_text()`.
3. POST to `{hiring_agent_service_url}/evaluate` with `{"resume_text": rendered_text, "github_username": None}`.
4. On any `httpx.HTTPError` (connection failure, timeout) or non-200 response: wrap as `EvaluationError`.
5. On success: insert a new `evaluation_runs` row with all fields mapped from the response.

## 6. HTTP Client Dependency Injection

`evaluate_resume(db, session, http_client: httpx.Client, settings) -> EvaluationRun` — the HTTP client is injected the same way other services inject the `AIOrchestrator`: a real `httpx.Client` in production (matching the `httpx` usage already established in `backend/app/api/health.py`), a fake/mocked client in tests, so no real network calls happen in the automated suite.

## 7. API Integration

`STAGE_RUNNERS["evaluation"] = _run_evaluation` — finally implementing the stage name that `test_run_stage_returns_501_for_unimplemented_stage` has used as its "still not implemented" placeholder since Phase 5. Reuses the existing `STAGE_TIMEOUT_SECONDS`/`ThreadPoolExecutor`/fresh-session-on-timeout mechanism unchanged; the 501 test will need to move to yet another placeholder stage name for whatever Phase 7 turns out to be.

## 8. Testing

- **`render_resume_to_text()` unit tests**: field-by-field, deterministic — a resume with all fields populated, a sparse resume (missing summary/projects/education), asserting specific expected substrings/structure in the output.
- **Service tests** (mocked HTTP client, no real network calls):
  - Success path: persists all score fields + the full response body in `raw_response_json`, correctly linked to `session_id`/`resume_version_id`.
  - Dependency-guard test: no `tailoring_rewrite` version exists → `EvaluationError`, HTTP client never called.
  - HTTP-error-wrapping test: mocked client raises `httpx.HTTPError` (or returns a non-200 status) → `EvaluationError`, nothing persisted.
- **API integration tests**: success/failure/timeout for the `evaluation` stage, mirroring the existing pattern for `resume_parsing`/`jd_extraction`/`gap_analysis`/`tailoring_rewrite`. Update the stale 501 test to a new placeholder stage name.
- **One manual smoke script** (`backend/scripts/smoke_test_evaluation.py`) hitting the real, locally-running `hiring-agent-service` container (requires `GEMINI_API_KEY` set for that service, per its README) — this is also where the §3 information-loss validation step happens: run a fixture with known, clear production/open-source/technical-skills indicators and manually confirm the returned scores/evidence plausibly reflect that content.

## 9. Explicitly Out of Scope

- Any "re-tailor and re-evaluate if score is below threshold" loop (§1 — deferred to a later phase or n8n orchestration, Phase 10).
- Extracting `github_username` from `ContactInfo.links` (confirmed moot regardless, per §2 — the field is dead code in the wrapper today, so extracting it would have no effect on scores even if implemented).
- Any change to `hiring-agent-service`'s contract, `evaluation_runs`'s schema, or the timeout/thread-safety design beyond reusing them as-is.
