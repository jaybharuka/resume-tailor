# Phase 7 — Document Generation (LaTeX → PDF): Design

Status: Approved by user, pending spec review
Date: 2026-07-09
Scope: Render the tailored resume (`resume_versions`, `produced_by_stage="tailoring_rewrite"`) into a polished PDF via a LaTeX template compiled by Tectonic. First phase producing a user-facing deliverable file rather than structured DB data. One default template only — the architecture leaves room for more later, without building a template registry now.

## 1. Context

Per the original architecture (Resume JSON → Template Engine → LaTeX → PDF), this phase has no LLM involvement at all — pure deterministic rendering, the same "lightweight, no fabrication risk" shape as Phase 6, but for a different reason: Phase 6 was light because it only made an HTTP call; this phase is light because it's a compile step, not a network call.

Two real gaps were found in exploration, not assumed away:
- **Tectonic is not installed anywhere in this project** — not in `requirements.txt`, not in `backend/Dockerfile`, not on the dev machine. This phase adds it.
- **`generated_documents` (Phase 1's schema) has `session_id` but no `resume_version_id`** — unlike `gap_analyses` and `evaluation_runs`, which both link back to the specific resume version they were produced from. This phase closes that gap via a new migration (§5).

## 2. Template Rendering

A **new, separate Jinja2 `Environment`** — not `PromptRegistry`. `PromptRegistry` is LLM-prompt-specific machinery (its templates get synced into `prompt_versions`/`llm_calls` for LLM-call audit purposes); this phase makes no LLM call, so reusing it would be a semantic mismatch, not just a technical inconvenience.

The new environment is configured with **LaTeX-safe delimiters**, since Jinja2's defaults (`{{ }}`, `{% %}`) collide with LaTeX's own use of curly braces (`\textbf{...}`, grouping) and percent signs (LaTeX comments):

```python
jinja2.Environment(
    loader=jinja2.FileSystemLoader("backend/latex_templates"),
    variable_start_string="<<", variable_end_string=">>",
    block_start_string="<%", block_end_string="%>",
    comment_start_string="<#", comment_end_string="#>",
)
```

Templates live in `backend/latex_templates/`, separate from `backend/prompts/`. This phase ships exactly one template, `backend/latex_templates/resume/default.tex`, selected by a `template_name` concept hardcoded to `"default"` for now — not a template registry. A future template is just a new `.tex` file and a new lookup key; no premature abstraction is built to support templates that don't exist yet.

## 3. LaTeX Escaping

A dedicated, independently-tested module, `backend/app/services/latex_escape.py`: `escape_latex(text: str) -> str`, exposed as a Jinja2 filter (`<< field | latex_escape >>`) applied to every user-supplied string inserted into the template — never to the template's own literal LaTeX scaffolding.

Must correctly handle: `& % $ # _ { } ~ ^ \`. **Order matters**: backslash must be escaped first (`\` → `\textbackslash{}`), before any other substitution — escaping the other characters first would corrupt already-escaped backslash sequences, since several of their replacements themselves contain backslashes (e.g. `&` → `\&`). Tilde and caret need special-cased LaTeX-safe replacements (`~` → `\textasciitilde{}`, `^` → `\textasciicircum{}`) since a bare `\~`/`\^` in LaTeX is an accent command, not a literal character.

## 4. Compilation

1. Render the `.tex` template with the tailored `ResumeDocument`'s fields into a string.
2. Write that string to a `.tex` file in a fresh temporary directory (Tectonic needs a working directory for intermediate files).
3. Invoke the real Tectonic binary via `subprocess.run([...], cwd=temp_dir, timeout=..., capture_output=True)`.
4. On success: read back the resulting `.pdf` file's bytes.
5. On any failure (non-zero exit code, missing binary, `subprocess.TimeoutExpired`): wrap as `DocumentGenerationError` (inherits `StageExecutionError`), including Tectonic's captured stderr in the error message for debuggability.
6. Clean up the temporary directory in a `finally` block, regardless of outcome.

**Tectonic package-caching tradeoff — explicit, not discovered later.** Tectonic fetches needed LaTeX packages from a bundle on first use and caches them locally (`~/.cache/Tectonic` by default) for subsequent compiles. This phase makes a deliberate choice about when that first network fetch happens:

- **`backend/Dockerfile` pre-warms the cache at build time**: a `RUN` step compiles a trivial throwaway `.tex` file during the image build, so the package cache is already populated before the container ever serves a real request. This means the production/deployed container never needs network access to compile a resume — the one-time network cost is paid once, at build time, not on every fresh deploy or every incoming request.
- **Local dev / fresh checkouts do not pre-warm the cache.** The first time a developer runs the test suite (or the manual smoke script) after installing Tectonic locally, that first real compile will need network access to populate the local cache; every compile after that is offline and fast. This is an accepted, documented tradeoff — not a surprise a developer discovers when a fresh clone's test suite is unexpectedly slow or fails in a network-restricted environment. If a future CI environment restricts network access, it will need its own cache pre-warming step (out of scope for this phase to solve now, but the constraint is written down here so it isn't rediscovered from scratch).

## 5. Schema — `generated_documents.resume_version_id` (New Migration)

New Alembic migration adding a nullable `resume_version_id` column (`ForeignKey("resume_versions.id", ondelete="CASCADE")`) to the existing `generated_documents` table. Nullable because this is a genuine schema gap being retrofitted (mirroring how Phase 5 added `resume_versions.session_id` as nullable for the same reason) — not because new rows created going forward should ever leave it null.

**`generated_documents.version_number` is deliberately scoped differently from `resume_versions.version_number`, and this is intentional, not an oversight.** `resume_versions.version_number` (established in Phase 5) is a *global counter per resume*, spanning every session that resume has ever been tailored in. `generated_documents` has no equivalent resume-spanning identity — it only has `session_id` (and, as of this phase, `resume_version_id`) — so its `version_number` is scoped one level down: `max(version_number for this session_id + document_type) + 1`. Regenerating the PDF for the same session (e.g. after a re-tailor) produces version 2, 3, etc. *within that session*; a different session's PDF always starts at 1, even for the same underlying resume. This mirrors the "new row every run, no dedup" precedent from `gap_analyses`/`evaluation_runs`, just scoped to what this table actually has an identity over.

## 6. Storage

Reuses the existing `Storage` protocol / `LocalDiskStorage` (Phase 2's abstraction) — no new storage mechanism. Key pattern: `generated_documents/{session_id}/{document_type}_v{version_number}.pdf`, matching the existing `resumes/{id}/resume.pdf` convention. `document_type` is `"resume_pdf"` for this phase's output.

## 7. Data Flow & Dependency Guard

New `backend/app/services/document_generator.py`, parallel to `evaluator.py`. `DocumentGenerationError` inherits `StageExecutionError`.

1. Look up the session's most recent `resume_versions` row with `session_id=session.id, produced_by_stage="tailoring_rewrite"` (same session-scoped query shape established in Phase 6's `evaluator.py`). If none exists, raise `DocumentGenerationError("tailoring_rewrite has not succeeded for this session yet")` before any rendering or compilation.
2. Render the `.tex` template with the tailored `resume_json`.
3. Compile via Tectonic (§4).
4. Persist the resulting PDF bytes via `Storage.save(...)`, then insert a `generated_documents` row with `session_id`, `resume_version_id`, `document_type="resume_pdf"`, `storage_path`, `version_number` (§5), `content=None` (this column is for text-based documents; a PDF's bytes live on disk via `storage_path`, not in this `Text` column).

## 8. API Integration

`STAGE_RUNNERS["document_generation"] = _run_document_generation` — finally implementing the placeholder stage name `test_run_stage_returns_501_for_unimplemented_stage` has used since Phase 6. Reuses `STAGE_TIMEOUT_SECONDS`/`ThreadPoolExecutor`/fresh-session-on-timeout unchanged. The 501 test moves to yet another placeholder name for whatever Phase 8 turns out to be.

## 9. Testing

- **`escape_latex()` unit tests**: a fixture string containing every special character (`& % $ # _ { } ~ ^ \`) individually, plus a realistic "in the wild" composite case (e.g. a bullet reading "Improved throughput 40% using C++ & Python, cost $50/mo, see `file_name.py`"), asserting the exact expected escaped output — not just "doesn't crash."
- **Template-rendering test**: a fully-populated `ResumeDocument` renders to a `.tex` string containing no unresolved Jinja2 syntax and no missing-variable errors.
- **Optional-field / sparse-resume rendering test** (per this spec's addition): a `ResumeDocument` with several optional fields at their empty/`None` default — `ContactInfo.phone=None`, `ContactInfo.location=None`, a `WorkExperience` entry with `bullets=[]`, no `projects`, no `education`, no `certifications` — renders without error and without emitting stray empty LaTeX sections (e.g. no dangling `\subsection{Projects}` with nothing under it). This is the first phase rendering the full breadth of `ResumeDocument`'s optional fields into a document a real user actually sees, so the template's conditional logic around missing fields needs to be verified directly, not assumed to degrade gracefully.
- **Real Tectonic compile test**: render a fixture resume, actually invoke Tectonic, assert the output file exists, is non-trivially sized (not a truncated/empty file), and starts with a valid `%PDF-` header.
- **Dependency-guard test**: no `tailoring_rewrite` version for the session → `DocumentGenerationError`, Tectonic never invoked.
- **API integration tests**: success/failure/timeout for the `document_generation` stage, mirroring the existing pattern for prior stages. Update the stale 501 test to a new placeholder stage name.
- **Manual smoke script**: exercises the full pipeline against the real Tectonic binary and prints the resulting PDF's file size and path for a human to open and eyeball.

## 10. Ledger Cleanup (Task 1)

Before starting the new document-generation work, this phase's first task:
- Closes 4 test-strictness gaps flagged by Phase 6's final review: the `resume_parsing` fabrication test's keyword-only check, `parse_resume`'s fabrication guard asserting only `projects == []`, the gap-analysis schema roundtrip test's un-bumped `schema_version`, and the missing `orchestrator.calls` assertion in `test_analyze_gap_wraps_orchestrator_error`.
- Formally closes 2 by-design items as won't-fix (documented as accepted, not silently dropped): `certifications`' count-only identity check, and the substring-within-a-token skills-matching behavior in the tailoring engine's skills guard.

This keeps the cross-phase follow-up backlog from growing unboundedly — it shrinks from 10 items to 4 remaining (the ones not closed by this task), rather than accumulating an 11th and 12th item on top of an already-large pile.

## 11. Explicitly Out of Scope

- Multiple templates / a template-selection mechanism beyond a single hardcoded `"default"` (§2 — deliberate, revisit when a second template is actually needed).
- Cover letters or any other `document_type` (this phase produces `"resume_pdf"` only).
- CI-specific Tectonic cache pre-warming beyond the Docker build step (§4 — the constraint is documented; solving it for a hypothetical network-restricted CI environment is deferred until that environment actually exists).
- Any change to `tailoring_engine.py`, `evaluator.py`, the timeout/thread-safety design, or the `Storage` protocol beyond reusing them as-is.
