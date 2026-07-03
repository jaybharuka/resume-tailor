# Phase 1 — Architecture Design: AI Resume Tailoring Platform

Status: Approved by user, pending spec review
Date: 2026-07-03
Scope: Architecture skeleton only. No parsing, extraction, tailoring, LaTeX/PDF, reports, n8n, or frontend logic is implemented in this phase.

## 1. Context

This platform wraps around the existing `hiring-agent` repository (resume-to-score evaluator: `score.py`, `evaluator.py`, `github.py`, etc.), which stays untouched in its own repo. The new platform is a separate repo (`resume-tailor`, sibling directory, own git history) that orchestrates resume tailoring end-to-end and calls into `hiring-agent` only through a thin HTTP wrapper.

Target user for v1: single user, local-first (no auth, no multi-tenancy, no cloud accounts required to start). Everything runs via Docker Compose on the local machine; Supabase/cloud storage can replace local disk later via config, not a rewrite.

## 2. Hiring Agent Integration

`hiring-agent-service/` is a small FastAPI shim living in its own container, with its own venv/dependencies (kept in sync with the `hiring-agent` repo's requirements, e.g. via a git submodule or a documented "install alongside" step — decided in Phase 6 when this is actually built). It exposes exactly one endpoint:

```
POST /evaluate
  body: { resume_json: <canonical Resume JSON>, github_username: str | null }
  returns: { overall_score, open_source_score, projects_score,
             production_score, technical_skills_score, evidence,
             bonus_points, deductions, rubric_version,
             hiring_agent_service_version, raw }
```

It calls `score.py`'s functions in-process and returns structured JSON instead of CSV/stdout. It never modifies the evaluator's core logic — it is a read-only caller. The main backend talks to it over the Docker Compose network (`http://hiring-agent-service:PORT`).

## 3. Canonical Resume JSON

A single Pydantic model, `ResumeDocument`, is the internal lingua franca. Every parser (PDF, DOCX) converts its input into this shape, and every downstream service (analyzer, gap analyzer, tailoring engine, hiring-agent adapter, template renderer) consumes and/or produces this shape — never raw text. This is what gets versioned in `resume_versions` (see §5).

Fields (high level, refined in Phase 2 when the parser is built): contact info, summary, work experience (company, title, dates, bullets), projects, skills, education, certifications. Loosely modeled on JSON Resume, matching the pattern `transform.py` already uses in the hiring-agent repo.

**Versioning:** every `ResumeDocument` instance carries a top-level `schema_version` int field, set at construction time. Consumers (analyzer, tailoring engine, template renderer, etc.) check `schema_version` and apply a migration function if they receive an older version than they expect, rather than assuming the current shape. This means a `resume_versions.resume_json` row written under `schema_version: 1` stays readable after the model gains fields in a later phase — new optional fields default sensibly, and any renamed/restructured field gets an explicit migrator function registered in `backend/app/schemas/resume_migrations.py` (created when the first breaking change happens, not in Phase 1).

## 4. Service Boundaries

Each stage is a distinct Python module behind a narrow interface (a "logical service"), not a separate network microservice — running everything as separate containers for a single-user local tool would be over-engineering. Each module is written so it *could* be extracted into its own deployable service later without changing its interface:

- **Resume Parser** — file (PDF/DOCX) → `ResumeDocument`
- **JD Extractor** — URL or pasted text → structured job posting (title, requirements, responsibilities, keywords)
- **Resume Analyzer** — `ResumeDocument` + job posting → relevance analysis
- **Gap Analyzer** — analysis output → missing/matched skills
- **Tailoring Engine** — `ResumeDocument` + gap analysis → rewritten `ResumeDocument` (bullets only reworded where evidence already exists; nothing fabricated)
- **Hiring Agent Adapter** — calls `hiring-agent-service` over HTTP, normalizes response
- **Resume Optimizer** — ATS keyword placement pass over the tailored `ResumeDocument`
- **Template Renderer** — `ResumeDocument` → LaTeX source
- **PDF Generator** — LaTeX source → PDF (via Tectonic)
- **Report Generator** — produces ATS report, skill gap report, cover letter, recruiter summary, interview questions

Only the **Hiring Agent Adapter** crosses a real network boundary (to `hiring-agent-service`); the rest are in-process calls within the `backend` FastAPI app.

## 5. AI Orchestrator

Replaces a flat "provider" abstraction with a task-driven orchestrator. Each AI task (e.g. `resume_parsing`, `jd_extraction`, `gap_analysis`, `tailoring_rewrite`, `cover_letter_generation`) is declared with:

- `provider` (gemini | claude | openai | nvidia)
- `model`
- `temperature`
- `response_schema` (a Pydantic model the raw LLM output is validated against, with one retry-with-correction on validation failure)
- `prompt_name` (resolved via the Prompt Registry, §6)

The orchestrator resolves the provider adapter, renders the prompt, calls the model, validates the response, and logs the call (§7, `llm_calls`). Provider adapters implemented in Phase 1: **Gemini** (reusing this repo's known-good backoff/rate-limit pattern), **NVIDIA** (OpenAI-compatible client against `https://integrate.api.nvidia.com/v1`, model configurable — e.g. `z-ai/glm-5.2` — key read from `NVIDIA_API_KEY` env var, never hardcoded). Claude and OpenAI adapters are stubbed with the same interface, wired in a later phase.

**Failure policy:** each task declares an ordered `fallback_providers` list (may be empty). On a call failure (timeout, rate-limit, schema-validation failure after its one retry), the orchestrator:
1. Retries the *same* provider once with backoff (reusing the existing Gemini rate-limit/jitter pattern for all providers, not just Gemini).
2. If that also fails and `fallback_providers` is non-empty, tries the next provider in the list with the same prompt/schema.
3. If all providers are exhausted, the orchestrator raises a typed `OrchestratorError`, the calling stage marks its `pipeline_runs` row `status = failed` with `error_message` set, and the pipeline stops — it does not silently continue with a partial/unvalidated result.
Every attempt (success or failure, same-provider retry or fallback) gets its own `llm_calls` row, so the full attempt sequence for a given `pipeline_run` is reconstructable from `llm_calls.session_id` + `task_type` + `created_at` ordering. In Phase 1, `fallback_providers` is exercised by config alone (e.g. `nvidia` falls back to `gemini`); no task logic depends on it yet since no real tasks exist until Phase 2+.

## 6. Prompt Registry

Prompts live outside the codebase-as-logic, under `backend/prompts/`, as Jinja2 templates (mirroring the hiring-agent repo's `prompts/templates` pattern) — never hardcoded in Python. Templates are organized and looked up by `{task_type}/{version}.jinja2` (e.g. `prompts/tailoring_rewrite/v1.jinja2`), not by an arbitrary filename — the registry key is always `(task_type, version)`. On startup, the `PromptRegistry` scans this layout and upserts a row per template into `prompt_versions` (`task_type`, `name` = the task_type, `version`, `template_path`), so the DB catalog always mirrors what's on disk. The AI Orchestrator resolves a task's active prompt via `PromptRegistry.get(task_type, version="latest" | pinned_version)`, and the resulting `prompt_versions.id` is what gets attached to the corresponding `llm_calls` row — so any tailoring decision traces back to the exact `(task_type, version)` pair that produced it, not just a filename.

## 7. Data Model (Postgres, local via Docker)

- **resumes** — id, original_filename, storage_path, raw_text, created_at
- **resume_versions** — id, resume_id (FK), version_number, resume_json (canonical `ResumeDocument`), produced_by_stage, created_at
- **job_postings** — id, source_url, source_provider, raw_text, parsed_json, created_at
- **tailoring_sessions** — id, resume_id (FK), job_posting_id (FK), status, created_at, updated_at — the root entity tying one resume+job run together
- **pipeline_runs** — id, session_id (FK), stage_name, status (pending/running/succeeded/failed), started_at, completed_at, error_message — gives every stage an async-ready, pollable status row even before a real queue exists (§8)
- **evaluation_runs** — id, session_id (FK), resume_version_id (FK), overall_score, open_source_score, projects_score, production_score, technical_skills_score, raw_response_json, rubric_version, hiring_agent_service_version, created_at. The 5 named score columns are a denormalized convenience for querying/sorting; `raw_response_json` stores the **entire** unmodified `/evaluate` response body (evidence, bonus points, deductions, per-category rationale, everything `hiring-agent-service` returns) so that if the hiring-agent scoring rubric changes categories later, historical runs remain fully reconstructable from `raw_response_json` alone — the 5 named columns are a read-optimization, not the source of truth. `rubric_version` and `hiring_agent_service_version` are echoed back from the wrapper's response so old rows stay interpretable if the rubric changes.
- **generated_documents** — id, session_id (FK), document_type (tailored_resume_pdf | cover_letter | ats_report | skill_gap_report | recruiter_summary | interview_questions), storage_path, content, version_number, created_at — one row per output artifact, independently regenerable/versioned
- **prompt_versions** — id, task_type, name, version, template_path, created_at
- **llm_calls** — id, session_id (FK), prompt_version_id (FK), provider, model, task_type, temperature, request_payload, response_payload, validated (bool), latency_ms, created_at

## 8. API Shape (session/job-oriented, async-ready)

Even though Phase 1 ships no real queue, the contract is designed so one can be added later (Celery/RQ/arq) without breaking callers:

```
POST /resumes                          upload a resume file
POST /job-postings                     submit a JD (URL or pasted text)
POST /sessions                         create a tailoring session (resume_id + job_posting_id) -> 201 + session_id
POST /sessions/{id}/run-stage/{stage}  kick off one pipeline stage -> 202 + pipeline_run_id
GET  /sessions/{id}/status             poll overall + per-stage status
GET  /sessions/{id}/documents          list/fetch generated_documents for a session
GET  /health                           DB + hiring-agent-service connectivity check
```

In Phase 1, `run-stage` endpoints exist for routing/contract purposes but return `501 Not Implemented` for stages not yet built (all of them, until Phase 2+). This avoids stubbing real logic prematurely while locking the contract early.

## 9. Future n8n Mapping (documentation only, not built)

Each endpoint above maps to a future n8n node so orchestration can be added without touching the backend:

| n8n node (future) | Backend call |
|---|---|
| Upload Resume | `POST /resumes` |
| Extract JD | `POST /job-postings` |
| Start Session | `POST /sessions` |
| Run Stage (x N) | `POST /sessions/{id}/run-stage/{stage}` |
| Poll Status | `GET /sessions/{id}/status` |
| Fetch Documents | `GET /sessions/{id}/documents` |

## 10. Storage

A `Storage` protocol (`save`/`load`/`delete`) with a `LocalDiskStorage` implementation writing under `./storage/{session_id}/`. Swapping to Supabase Storage later means writing one new adapter class, not touching callers.

## 11. Extensibility Notes

- New AI task types register new orchestrator config — no core orchestrator changes.
- New document types extend the `document_type` enum on `generated_documents` — no schema migration pattern change.
- New LaTeX templates: a `template_id` field can be added to `generated_documents`/render requests when Phase 7 (LaTeX generation) is built.
- Future features (job tracking, interview prep history, multi-template support, n8n automation) attach to the existing `tailoring_sessions` root entity rather than requiring new root concepts.

## 12. Repo Layout

```
resume-tailor/
  backend/
    app/
      api/                # routers: resumes, job_postings, sessions, health
      core/
        config.py         # env-driven settings (Pydantic BaseSettings)
        llm/               # AI Orchestrator + provider adapters (gemini, nvidia, claude*, openai*)
        storage.py         # Storage protocol + LocalDiskStorage
      services/            # one module per logical service (empty/stubbed until its phase)
      models/               # SQLAlchemy models
      schemas/              # Pydantic schemas incl. ResumeDocument
      db/                   # session factory, Alembic migrations
    prompts/                # Jinja2 prompt templates (empty until Phase 2+)
    tests/
    Dockerfile
    .env.example
  hiring-agent-service/
    app.py                  # POST /evaluate wrapper
    Dockerfile
  frontend/                 # empty, scaffolded in Phase 10
  infra/
    docker-compose.yml      # postgres, hiring-agent-service, backend
  docs/superpowers/specs/
  .gitignore                # includes .env
```
(* = stubbed interface only, not wired to a real API key in Phase 1)

## 13. Phase 1 Deliverables (concrete)

1. Repo skeleton above, committed.
2. Alembic migration creating all 9 tables in §7.
3. `ResumeDocument` Pydantic schema (fields refined in Phase 2, but the shape exists now so `resume_versions.resume_json` has a real type).
4. AI Orchestrator + Prompt Registry classes, with **Gemini** and **NVIDIA** adapters implemented and smoke-tested against a trivial prompt (including the same-provider-retry → fallback-provider → `OrchestratorError` failure path, §5); Claude/OpenAI adapters stubbed (same interface, `NotImplementedError` body).
5. `Storage` protocol + `LocalDiskStorage`.
6. `hiring-agent-service` wrapper with a working `/evaluate` endpoint, smoke-tested against the existing `hiring-agent` repo's `score.py`.
7. `docker-compose.yml` bringing up Postgres + `hiring-agent-service` + `backend` locally.
8. `GET /health` confirming DB + `hiring-agent-service` connectivity.
9. `run-stage` routing skeleton returning `501` for all stages (contract only).

**Explicitly NOT in Phase 1:** any real parsing, extraction, analysis, tailoring, LaTeX/PDF, report content, n8n workflows, or frontend UI. Those are Phases 2–10, each with its own spec once Phase 1 is built and reviewed.

## 14. Security Note

The NVIDIA API key provided during design must never be committed to source. It is read from `NVIDIA_API_KEY` in `backend/.env` (gitignored), with `.env.example` documenting the variable name only. Given the key was shared in a plaintext chat message, it should be rotated in the NVIDIA console after initial testing.

## 15. Known Follow-Ups for Later Phases

- **`llm_calls.prompt_version_id` cascade policy.** Task 4's implementation (post-review) applies `ondelete="CASCADE"` to every foreign key, per an explicit "CASCADE everywhere" decision made during Phase 1 implementation. This is correct for most of the schema, but it means deleting a `prompt_versions` row would cascade-delete every `llm_calls` row that references it — silently destroying the audit trail of what prompt actually produced a given AI-driven change, which conflicts with this project's "every modification should be explainable" principle (see the AI Design section above). Nothing deletes `prompt_versions` rows in Phase 1, so this is not yet a live bug. When a later phase introduces prompt-version cleanup/deprecation, revisit this FK specifically: change it to `ondelete="RESTRICT"` (block deleting a prompt version while `llm_calls` still reference it) or nullify the FK on delete instead of cascading, so historical audit rows survive.
