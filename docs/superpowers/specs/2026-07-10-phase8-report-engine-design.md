# Phase 8 — Report Engine: Design

Status: Approved by user, pending spec review
Date: 2026-07-10
Scope: Five report/document types building on the pipeline's existing outputs — ATS report, skill-gap report, cover letter, recruiter summary, interview questions. Two are read-only reformatting views over data already produced by Phase 4/Phase 6; three are genuinely new LLM-generated documents.

## 1. Context

Per the original vision, this phase produces: ATS report, skill-gap report, cover letter, recruiter summary, interview questions. Exploration confirmed a real split in what each one requires:

- **ATS report / skill-gap report** are reformatting layers over data that already exists: `EvaluationRun` (Phase 6 — overall/sub-scores, evidence, bonus/deductions) and `GapAnalysis` (Phase 4 — `GapAnalysisDocument`'s matching/missing skills, experience gap notes, relevant/irrelevant projects, recommended keywords). No new LLM call, no new persistence — a read-only view computed at request time.
- **Cover letter** and **recruiter summary** are genuinely new: LLM-generated prose synthesizing the tailored resume + job posting + gap analysis into a document making claims about the candidate. Same fabrication-risk category as Phase 5's tailoring rewrite (inventing an achievement or skill not actually in the source documents), but the output is unstructured prose rather than a resume's discrete fields, so Phase 5's field-diffing guard doesn't port over mechanically.
- **Interview questions** are also new, but JD-driven rather than candidate-claims-driven — the risk is generic filler unrelated to the actual role, not fabricated candidate facts. A materially lower-risk category.

`generated_documents` (Phase 1's schema, extended in Phase 7) already has an unused `content: Text` column, added at the same time as `storage_path` specifically for text-based documents — Phase 7's PDF used `storage_path` and left `content` at `None` by design. This phase is the first to actually populate it.

## 2. API Shape

**Read-only, computed, not persisted:**
- `GET /sessions/{session_id}/reports/ats` — reformats the session's latest `EvaluationRun` row.
- `GET /sessions/{session_id}/reports/skill-gap` — reformats the session's latest `GapAnalysis` row.

Both return 404 if the underlying stage (`evaluation` / `gap_analysis`) hasn't produced a row yet for the session — a direct existence check, not the `StageExecutionError`/dependency-guard machinery the LLM-backed stages use, since these endpoints do no work of their own to guard. No `PipelineRun` tracking for these — they're not stages, they're views, and tracking a "stage" that always completes instantly and does no LLM work would pollute `pipeline_runs` with degenerate always-succeeds rows.

**New LLM-backed stages**, added to `STAGE_RUNNERS` exactly like every stage since Phase 2:
- `cover_letter`
- `recruiter_summary`
- `interview_questions`

Each gets the same dependency-guard-then-orchestrator-call shape as `tailoring_engine.py`/`evaluator.py`/`document_generator.py`, the same `STAGE_TIMEOUT_SECONDS`/`ThreadPoolExecutor`/fresh-session-on-timeout handling (unchanged, reused as-is), and is caught by the existing shared `except StageExecutionError` clause in `run_stage`.

A single combined "reports" stage was considered and rejected: it would bundle three LLM calls with different fabrication-risk profiles into one all-or-nothing unit, and force the two lower-risk report types to wait on cover-letter/recruiter-summary generation despite having no dependency on either.

## 3. Schema — Three New Response Models

Following the established `schema_version` + `migrate_*`/`Unsupported*SchemaVersion` pattern from `gap_analysis.py`/`tailoring_result.py`/`job_posting.py`:

```python
# app/models/cover_letter.py
class CoverLetterDocument(BaseModel):
    schema_version: int = CURRENT_COVER_LETTER_SCHEMA_VERSION
    body: str
```

```python
# app/models/recruiter_summary.py
class RecruiterSummaryDocument(BaseModel):
    schema_version: int = CURRENT_RECRUITER_SUMMARY_SCHEMA_VERSION
    body: str
```

Both are a single `body: str` field — the full prose (salutation/closing included in the cover letter's body, not split into separate fields). Splitting them buys no real benefit for a document whose only consumer is "render this text" and adds surface area for the LLM to produce internally-inconsistent output (e.g. a closing that doesn't match a separately-generated salutation).

```python
# app/models/interview_questions.py
class InterviewQuestionsDocument(BaseModel):
    schema_version: int = CURRENT_INTERVIEW_QUESTIONS_SCHEMA_VERSION
    questions: list[str] = Field(min_length=5)
```

`min_length=5` is the entire structural-validation guard for this document type — enforced by Pydantic during the orchestrator's response-schema validation, no separate code-level check needed.

`generated_documents.document_type` gains three new values: `"cover_letter"`, `"recruiter_summary"`, `"interview_questions"`, joining Phase 7's `"resume_pdf"`. All three populate `content` (the generated body / newline-joined questions) and leave `storage_path` `None` — the reverse of Phase 7's PDF, which populated `storage_path` and left `content` `None`. `version_number` scoping matches Phase 7's `generated_documents` precedent: `max(version_number for this session_id + document_type) + 1`, not a global counter.

## 4. Services

### `cover_letter_generator.py` / `recruiter_summary_generator.py`

`generate_cover_letter(db, session, orchestrator, prompt_registry) -> GeneratedDocument` and `generate_recruiter_summary(db, session, orchestrator, prompt_registry) -> GeneratedDocument`, near-identical shape:

1. Dependency guard: look up the session's latest `ResumeVersion` with `produced_by_stage="tailoring_rewrite"` and the session's latest `GapAnalysis` — identical query shape to `tailoring_engine.py`/`document_generator.py`. Raise `CoverLetterError`/`RecruiterSummaryError` (each a dedicated `StageExecutionError` subclass, matching the established one-class-per-stage precedent — `TailoringError`, `EvaluationError`, `DocumentGenerationError`) before any LLM call if either prerequisite is missing.
2. Render the stage's prompt (`backend/prompts/cover_letter/v1.jinja2` / `backend/prompts/recruiter_summary/v1.jinja2`) with the tailored resume JSON, job posting JSON, and gap analysis JSON.
3. Call the orchestrator with the corresponding response schema.
4. **Fabrication guard**: tokenize the generated `body` text using the same tokenization approach as `tailoring_engine.py`'s bullet-matching guard, and check every skill/technology-like token against the same "earned skills" set used there (skills/technologies explicitly listed in the resume, or mentioned in its bullet prose, plus `gap_analysis.matching_skills`). Reject with the stage's error class if any token isn't earned. This is a whole-prose scan, not a check against a separately-LLM-reported claims list — scanning what a human would actually read is more trustworthy than trusting the LLM to self-report its own claims accurately in a second field, which could silently drift from what it actually wrote.
5. Persist a `GeneratedDocument` row (`document_type="cover_letter"`/`"recruiter_summary"`, `content=body`, `storage_path=None`, versioned per §3).

Both cover letter and recruiter summary depend on `tailoring_rewrite` specifically (not the original `resume_parsing` output) — this keeps every candidate-facing artifact in a session (PDF, cover letter, recruiter summary) consistent with the same tailored resume version, and reuses the exact dependency-guard query shape already established for the PDF.

### `interview_questions_generator.py`

`generate_interview_questions(db, session, orchestrator, prompt_registry) -> GeneratedDocument`:

1. Dependency guard: look up the job posting's `parsed_json` (from `jd_extraction`) and the session's latest `GapAnalysis`. Raise `InterviewQuestionsError` if either is missing.
2. Render `backend/prompts/interview_questions/v1.jinja2` with the job posting JSON and gap analysis JSON (using `missing_skills`/`experience_gap_notes` to generate some gap-probing questions alongside general role-relevant ones).
3. Call the orchestrator with `InterviewQuestionsDocument` as the response schema — the `min_length=5` constraint is the entire guard; no code-level content-quality heuristic (a keyword-overlap check was considered and rejected as fragile and easy to satisfy without adding real protection).
4. Persist a `GeneratedDocument` row (`document_type="interview_questions"`, `content` = the questions newline-joined, versioned per §3).

### Shared tokenizer extraction

`_tokenize_for_skill_matching` (currently private to `tailoring_engine.py`) is extracted into a new shared module, `app/services/skill_matching.py`, exposing the tokenizer and the earned-skills-collection helper. `tailoring_engine.py`, `cover_letter_generator.py`, and `recruiter_summary_generator.py` all import from there instead of duplicating the logic — three call sites needing identical behavior is the trigger for this extraction, not a speculative refactor.

## 5. API Integration

`STAGE_RUNNERS` gains three entries: `"cover_letter"`, `"recruiter_summary"`, `"interview_questions"`, each a thin dispatcher matching the existing `_run_tailoring`/`_run_evaluation` shape (build orchestrator + prompt registry, call the service function, return the created row's id).

Two new `GET` routes on the existing `sessions` router: `/{session_id}/reports/ats` and `/{session_id}/reports/skill-gap`.

**Gap found in self-review, fixed here:** the existing `GET /{session_id}/documents` endpoint (Phase 7) only returns `document_type`, `storage_path`, and `version_number` — it never returned `content`, because Phase 7's PDF only ever populated `storage_path`. This phase's three new document types populate `content` exclusively and leave `storage_path` `None`, so without a change here their generated text would be produced, persisted, and completely unreachable through the API. This phase adds `content` to that endpoint's response (nullable — `None` for PDF-type documents, populated for text-type ones), rather than introducing a separate fetch-by-content endpoint for three document types that otherwise share every other characteristic with the existing list.

## 6. Ledger Cleanup (Task 1)

Before starting the new report-generation work, this phase's first task closes what's reasonably closeable from the 5-item follow-up backlog carried in from Phases 3–5 (the Phase 7 Tectonic-version-pin item was already closed in Phase 7 itself):
- Phase 3 (2 items): untested `Responsibilities:`/`Keywords:` fixture labels; cosmetic report-artifact text-garbling.
- Phase 4 (1 item): the strict-match rule's clause (a) lacks an explicit qualifier.
- Phase 5 (2 items): no explicit override-ordering between unearned-skills/missing-skill-claimed prompt rules; the metrics rule doesn't foreclose lifting a number from JD/gap-analysis JSON.

Each item gets either a real fix or an explicit won't-fix note, following the same pattern as every prior phase's Task 1.

## 7. Testing

- **ATS/skill-gap read endpoints**: fixture tests confirming correct reformatting of an `EvaluationRun`/`GapAnalysis` row into the response shape, plus a 404 test for the not-yet-run case.
- **Cover letter / recruiter summary**: mirrors Phase 5's fixture-triple pattern — (1) happy path produces a `GeneratedDocument` with `content` populated and the right `document_type`/version number, (2) dependency-guard test (missing `tailoring_rewrite` or missing `gap_analysis` → error, orchestrator never called), (3) fabrication-guard test (a fixture LLM response containing an invented skill/technology not in the resume or gap analysis → rejected, no row persisted).
- **Interview questions**: dependency-guard test, a structural-validation test (fewer than 5 questions → schema validation failure surfaces as `InterviewQuestionsError`), a happy-path test.
- **Shared tokenizer**: existing `tailoring_engine.py` tests continue to pass unchanged after the extraction (behavior-preserving refactor, verified by the full existing test suite, not new tests specifically for the extraction).
- **API integration tests**: success/failure/timeout for each of the three new stages, mirroring the existing per-stage pattern; success/404 for each of the two new GET endpoints.
- **`GET /{session_id}/documents` regression + addition**: existing test(s) updated to assert `content` is present in the response shape (rather than a spec change silently breaking existing consumers' expectations of the response shape), `None` for a PDF-type row, and populated for a text-type row.

## 8. Explicitly Out of Scope

- Persisting ATS/skill-gap reports (§2 — computed on read, to avoid staleness if the underlying `evaluation`/`gap_analysis` rows are ever regenerated).
- A combined "reports" stage bundling multiple document types into one call (§2 — rejected; different fabrication-risk profiles and independent dependency chains argue for separate stages).
- A content-quality/keyword-overlap guard for interview questions (§4 — considered, rejected as fragile).
- Structured claims-list fields (e.g. `referenced_skills`) on `CoverLetterDocument`/`RecruiterSummaryDocument` as an alternative to prose-scanning (§4 — rejected; trusting the LLM to self-report separately from what it wrote is less robust than scanning the actual output).
- Any change to `tailoring_engine.py`'s guard behavior itself, `evaluator.py`, `document_generator.py`, the timeout/thread-safety design, or the `Storage` protocol, beyond extracting the shared tokenizer helper.
