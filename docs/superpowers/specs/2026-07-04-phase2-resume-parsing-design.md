# Phase 2 — Resume Parsing: Design

Status: Approved by user, pending spec review
Date: 2026-07-04
Scope: PDF-only resume text extraction and LLM-based structuring into the canonical `ResumeDocument`, wired into the real `resume_parsing` stage. No DOCX support, no OCR, no GitHub-profile linkage, no true async execution (queue/worker) in this phase.

## 1. Context

Phase 1 built the architecture skeleton: `POST /resumes` saves an uploaded file but never parses it, and `POST /sessions/{id}/run-stage/{stage_name}` unconditionally returns `501` for every stage (including `resume_parsing`, already used as the example stage name in Phase 1's own tests). Phase 2 makes `resume_parsing` real: extract text from an uploaded PDF, structure it into a `ResumeDocument` via the AI Orchestrator built in Phase 1, and persist the result.

This phase also closes two items from Phase 1's deferred follow-up backlog, since they touch the same area this phase is already working in:
- `prompt_versions` gets a missing `UniqueConstraint(task_type, version)`.
- `llm_calls.prompt_version_id`'s foreign key changes from `ondelete="CASCADE"` to `ondelete="RESTRICT"`, so deleting a prompt version can no longer silently destroy the audit rows that reference it.

## 2. Data Flow / Architecture

A new `backend/app/services/resume_parser.py` module (the "Resume Parser" logical service named in the Phase 1 architecture) implements:

1. **Load** the uploaded PDF's bytes from `Storage` via the `Resume` row's `storage_path`.
2. **Extract** markdown-ish text via `pymupdf4llm` — the same library `hiring-agent-imp` already uses (`pymupdf_rag.py`/`pdf.py`), reusing a proven extraction pattern rather than introducing a new one. `PyMuPDF`/`pymupdf4llm` get added to `backend/requirements.txt` (they are not currently a `backend/` dependency, only a `hiring-agent-service/` one).
3. **Fail fast on empty text.** If the extracted text is empty or below a minimum-length/whitespace threshold, mark the `pipeline_runs` row `status="failed"` with a clear `error_message` ("no extractable text — this PDF may be scanned/image-based") and stop — no LLM call is made. OCR is explicitly out of scope for this phase.
4. **Structure via the AI Orchestrator.** Otherwise, call `AIOrchestrator.run(...)` with a new `resume_parsing` `TaskConfig`: `provider="nvidia"`, `response_schema=ResumeDocument`, prompt rendered from a new `prompts/resume_parsing/v1.jinja2` template (registered via the Phase 1 `PromptRegistry`) with the extracted text as template context. The orchestrator's existing schema-validation-with-retry, same-provider-retry, fallback, and audit-logging behavior (all built in Phase 1) apply automatically — no new orchestrator logic is needed.
5. **On success:** persist `resume.raw_text` (a column that has existed since Phase 1 but has always been `None` until now — this is where it gets populated for the first time), create a `resume_versions` row (`version_number=1`, `resume_json=<ResumeDocument>`, `produced_by_stage="resume_parsing"`), and mark `pipeline_runs.status="succeeded"`.
6. **On any failure** (extraction error, or `OrchestratorError` after the orchestrator exhausts retries/fallback): mark `pipeline_runs.status="failed"` with the error message. Never a partial or silent result — consistent with Phase 1's failure-policy principle.

**`version_number=1` is hardcoded in this phase.** Parsing only ever happens once per resume today, so there is exactly one `resume_versions` row per resume. This is a known, deliberate simplification — Phase 6 (Resume Optimizer), which will create version 2, 3, etc. as a resume gets tailored, must generalize this to an actual incrementing counter (e.g. `max(version_number) + 1` scoped to the resume). Flagging this now so it doesn't quietly become forgotten tech debt.

## 3. Prompt Requirements (hard requirement, not a style preference)

The `resume_parsing` prompt template must explicitly instruct the model to leave `ResumeDocument` fields `null`/empty when information is absent or ambiguous in the extracted text, rather than inferring or fabricating plausible-sounding content. This is a direct extension of the project's foundational "never fabricate experience" principle (Phase 0) into the parsing stage specifically — parsing is the first place fabrication risk enters the pipeline, since every later phase (tailoring, evaluation, PDF generation) builds on whatever this stage produces.

This requirement must be explicitly tested against the **"sparse bullets"** and **"missing section"** fixtures (§6), not just the "normal" fixture — a resume_parsing prompt most commonly hallucinates content precisely when trying to fill a gap in a sparse or incomplete resume, not when parsing a complete one. A test asserting "no fabricated content appears for absent sections" is part of this phase's required test coverage, not optional coverage.

## 4. API Integration

`POST /sessions/{id}/run-stage/{stage_name}` gets one real branch: when `stage_name == "resume_parsing"`, the handler looks up the session's `resume_id`, calls the parser service **synchronously**, creates/updates the `pipeline_runs` row, and returns the result inline. Every other `stage_name` still returns `501` exactly as before.

**Synchronous execution is intentional for this phase.** No queue/worker infrastructure exists yet (deferred per Phase 1's async-ready-but-not-yet-async design) — a single LLM call taking a few seconds is acceptable to block on for a single-user local tool. True async (Celery/RQ) can be introduced in a later phase without changing the API contract, since Phase 1's session/job-oriented shape was designed to support that swap.

**Request timeout.** The worst case must account for the *full* orchestrator sequence (Phase 1, Task 6), not just one provider's internal backoff: `AIOrchestrator.run()` builds `provider_order = [task.provider, task.provider] + task.fallback_providers` — the primary provider appears **twice** (the "retry same provider once" step), and each entry in that list is a full call to the provider's own `generate()`, which for `NvidiaProvider` wraps `with_backoff` internally (5 attempts, sleeps of 10s/20s/40s/80s between them ≈ 150 seconds to fully exhaust one provider). So one entry in `provider_order` can itself take ~150s worst-case, and the primary appears twice before any fallback is even tried: **~150s × 2 ≈ 300 seconds** worst-case before the orchestrator even reaches a fallback provider.

This phase configures `resume_parsing`'s `TaskConfig` with **`fallback_providers=[]`** — Gemini/Claude/OpenAI are still non-functional stubs (Phase 1) that raise `NotImplementedError` immediately with no retry wrapper, so listing one as a fallback would add negligible time but also provide no real redundancy; it's more honest to configure no fallback until a second real provider adapter exists. With no fallback, ~300 seconds is the full worst case.

The `run_stage` handler wraps the parsing call in an explicit timeout (`anyio.fail_after` or equivalent) set generously above this worst case — **330 seconds** — so a bad LLM day fails with a clear, bounded error (`pipeline_runs.status="failed"`, `error_message` noting the timeout) rather than hanging the HTTP connection indefinitely. This bounded-but-generous number is a deliberate tradeoff specific to the synchronous approach, and is itself another reason a later phase will want real async execution instead of a wider timeout.

`GET /sessions/{id}/status` needs no changes — it already surfaces `pipeline_runs` from Phase 1, and will simply start showing real rows instead of an always-empty list.

## 5. Prompt Registry Startup Wiring

Phase 1 built `PromptRegistry.sync_to_db()` but nothing calls it automatically. This phase adds a FastAPI startup hook (`main.py`) that calls it once on app boot, so the new `resume_parsing/v1.jinja2` template gets registered without a manual step.

- **Idempotent and cheap:** `sync_to_db()` already checks for an existing `(task_type, version)` row before inserting (Phase 1 behavior, now backed by the new unique constraint from §1) — repeated boots do not create duplicate rows or meaningfully slow down local dev restarts (a handful of template files, one query each).
- **Must not crash startup if the DB isn't reachable yet — but must NOT silently swallow a genuine schema mismatch.** These are different failure modes and must be handled differently, not caught by one broad `except Exception`:
  - **DB not yet reachable** (connection refused, DNS failure, timeout — surfaces as `sqlalchemy.exc.OperationalError` at the connection level) is a timing race, not a bug. The hook catches specifically this and logs a warning, continuing app startup rather than crashing. In the Docker Compose stack this path won't normally trigger (Postgres `condition: service_healthy` plus the Phase 1 fix that runs `alembic upgrade head` before `uvicorn` starts already order things correctly), but a local (non-Docker) `uvicorn` run without Postgres already up must not crash on this.
  - **A genuine schema/migration mismatch** (e.g. the `prompt_versions` table or a expected column doesn't exist — surfaces as `sqlalchemy.exc.ProgrammingError` or similar) is a real deployment bug, not a timing issue, and must **fail loudly**: let it propagate and crash app startup, rather than being caught by the same tolerant path. Silently continuing with a broken schema would hide a problem that needs immediate attention, and is exactly the kind of silent-degradation failure this project's principles reject elsewhere (e.g. the orchestrator's own "never a silent/partial result" rule).
  - Only `OperationalError` (or an equivalently narrow, connection-specific exception) is caught and tolerated; everything else propagates.
  - Tolerating the connection-error case is safe because nothing in the orchestrator's current audit-logging path (`llm_calls.prompt_version_id`) is populated yet regardless (a known Phase 1 gap, tracked separately) — so a missed prompt-sync at boot does not break `resume_parsing` functionality, only the traceability of which prompt version ran, which can be re-synced by restarting once the DB is reachable.

## 6. Testing

- **New synthetic PDF fixtures**, checked into the repo, containing **fabricated placeholder identities only — not real personal data, and not scrubbed real resumes.** Fixtures:
  - `normal.pdf` — a complete, well-structured resume.
  - `no_summary.pdf` — missing the summary section.
  - `sparse_bullets.pdf` — work experience entries with minimal or single-word bullets.
  - `missing_section.pdf` — no projects section at all.
  - `blank.pdf` — empty/near-empty page(s), for the no-extractable-text failure path.
- **Unit tests mock the `AIOrchestrator`/`NvidiaProvider`** (same pattern as Phase 1's provider tests) — no real API calls in the automated suite.
- **Fabrication guard test:** using the `sparse_bullets.pdf` and `missing_section.pdf` fixtures specifically, assert that fields with no corresponding source content in the extracted text come back `null`/empty in the resulting `ResumeDocument`, not populated with invented content (verified against a fixed, known-correct mocked LLM response for these fixtures, plus a prompt-content test asserting the null/empty instruction is present in the rendered `resume_parsing` prompt).
- **One manual smoke-test script** (matching Phase 1's `smoke_test_nvidia.py` pattern) that runs a real fixture through the real NVIDIA API, for manual verification only — not part of the automated suite.

## 7. Explicitly Out of Scope

- DOCX or any non-PDF input format.
- OCR / scanned-image resumes.
- GitHub-profile linkage or enrichment (a later phase's concern, closer to the Hiring Agent Adapter).
- True async execution (background workers, queues) — synchronous only, per §4.
- Generalizing `resume_versions.version_number` beyond the hardcoded `1` (Phase 6's concern, per §2).
