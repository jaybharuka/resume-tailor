# Phase 9 — Frontend: Design

Status: Approved by user, pending spec review
Date: 2026-07-11
Scope: A single-flow Next.js UI for the resume-tailoring pipeline — upload resume, paste job description, run every backend stage in order, view/download results. First pass proves the flow works end-to-end; it is deliberately not a multi-page app with auth, session history, or editing.

## 1. Context

Every backend phase (1–8) built a stage or a read endpoint with no UI to drive it — the pipeline has been exercised entirely through automated tests and manual `curl`/smoke scripts. This phase builds the first real UI: upload → paste JD → run resume_parsing → jd_extraction → gap_analysis → tailoring_rewrite → evaluation → document_generation → cover_letter → recruiter_summary → interview_questions → view/download results.

Two real gaps were found in exploration (not assumed away):

- **No CORS middleware exists** on the backend. A separately-hosted Next.js frontend calling the API directly would be blocked.
- **No file-download endpoint exists.** `GET /sessions/{id}/documents` (Phase 7/8) returns `storage_path`, a server-local filesystem path — not anything a browser can fetch. The generated PDF is currently retrievable only via shell access to the container.

Both are addressed below (§3, §5) — this phase is not purely frontend-only; it includes one small, necessary backend addition.

**Phase-numbering note**: Phase 1's spec labeled the frontend scaffold "Phase 10," and Phase 6's spec assigned the n8n retry-loop to "Phase 10" too — the original roadmap's later phases were never precisely pinned. This phase proceeds as "Phase 9," ahead of the retry-loop/orchestration work, per explicit direction; the two docs' inconsistent Phase 10 labels are noted here, not resolved.

## 2. Stack

Next.js 14+ (App Router), TypeScript, Tailwind CSS, shadcn/ui (copied-in components on Tailwind + Radix primitives — not a runtime dependency — giving accessible buttons/cards/spinners/alerts for a multi-stage flow with loading states, without hand-rolling every interactive primitive). Scaffolded fresh into `frontend/`, which has sat empty since Phase 1.

## 3. Backend Addition: PDF Download Endpoint

`GET /sessions/{session_id}/documents/{document_id}/download` — new route on the existing `sessions` router. Looks up the `GeneratedDocument` row by `id` (404 if missing, or if it belongs to a different `session_id` than the URL's), reads its bytes via the existing `Storage.load(storage_path)` abstraction, and streams them back with `Content-Type: application/pdf` and a `Content-Disposition: attachment; filename=...` header derived from `document_type` and `version_number`.

**Missing-file handling**: if the `GeneratedDocument` row exists but `Storage.load()` raises (the file was moved/deleted from disk after the row was created — a real possibility since nothing currently guarantees storage and DB state stay in sync), the endpoint catches that specific failure and returns a clean 404 with a descriptive detail message, not an unhandled exception leaking a stack trace to a browser download click.

This endpoint only serves `resume_pdf`-type rows (the only type with a populated `storage_path`). The three text-type documents (cover letter, recruiter summary, interview questions) need no download endpoint — they're already fully retrievable via the existing `GET /documents`'s `content` field and are rendered/copied directly in the UI.

## 4. Frontend ↔ Backend Communication

`next.config.js` `rewrites()` proxies `/api/*` to the backend (`http://backend:8000` inside Docker Compose, `http://localhost:8020` for local `next dev` against a Dockerized backend). The browser only ever talks to the Next.js origin — no CORS middleware needed on the backend at all, and no backend change beyond §3's download endpoint.

## 5. Flow

One page, one linear client-side state machine, no routing between steps:

1. **Upload** — file input (resume PDF) → `POST /resumes` (multipart) → capture `resume_id`.
2. **Job posting** — textarea for pasted JD text → `POST /job-postings` with `{raw_text}` → capture `job_posting_id`.
3. **Create session** — `POST /sessions` with both IDs → capture `session_id`.
4. **Run stages sequentially** — a fixed ordered list of steps, each a button triggering `POST /sessions/{id}/run-stage/{stage_name}` for, in order: `resume_parsing`, `jd_extraction`, `gap_analysis`, `tailoring_rewrite`, `evaluation`, `document_generation`, `cover_letter`, `recruiter_summary`, `interview_questions`. Each step's UI state is one of: not-started / loading (spinner) / done (checkmark) / failed (error block, §6). A failed stage does not disable later steps — the UI imposes no gating beyond what the backend's own dependency guards already enforce, so a user can still attempt a later stage and see its own dependency-guard error naturally.
5. **Results** — a results panel appears once any stage has produced output: `GET /sessions/{id}/documents` renders a download link per `resume_pdf` row (via §3's endpoint) and the raw text of each `cover_letter`/`recruiter_summary`/`interview_questions` row (with a copy-to-clipboard action); `GET /sessions/{id}/reports/ats` and `GET /sessions/{id}/reports/skill-gap` render as simple read-only panels.

**Self-review addition**: a 404 from `/reports/ats` or `/reports/skill-gap` (the underlying `evaluation`/`gap_analysis` stage simply hasn't been run yet) is a normal, expected state, not a failure — these two panels render a muted "not generated yet" placeholder for a 404, not the §6 error block. §6's error-block treatment is reserved specifically for a stage-run `POST` failing (a real error worth surfacing prominently); a read endpoint's 404 for data that legitimately doesn't exist yet is a different kind of response and would be confusing to show as an alarming error.

No `GET /status` polling anywhere — every backend call in this design is a synchronous, blocking POST/GET per the established backend design (Phases 2–8). The frontend awaits each request directly and updates state from the response or the thrown error; there is no background job to poll.

## 6. Error Handling

Every fetch call catches a non-2xx response, extracts the FastAPI `{"detail": "..."}` string, and renders it **verbatim, in a consistent labeled error block** — no content-translation or pattern-matching layer that maps specific error strings to friendlier copy. This was a deliberate choice, confirmed by spot-checking real error strings across the codebase:

- Dependency-guard messages (`"tailoring_rewrite has not succeeded for this session yet"`) and fabrication-guard messages (`"tailored resume includes an unearned skill not present in the original resume or gap analysis matching_skills: 'Flask'"`) are legible prose as-is — no translation needed.
- Raw `OrchestratorError` text (`"All providers exhausted for task_type=X: tried Y (x2) then fallbacks Z"`) and Tectonic's LaTeX compiler stderr are not legible prose — they're internal implementation detail or compiler noise.

Given this range, the block is **presentational only**: a fixed "Stage failed" label, the stage name, and the raw detail text rendered in a distinct (monospace/muted) block — so a wall of compiler stderr reads as "here are the technical details of a failure," not as broken UI text or a crashed page. This adds no maintenance-cost mapping layer that has to track backend error-message wording as it evolves; it only standardizes presentation. 404/422/504 are all handled identically — same block, same raw text, no special-casing by HTTP status code for this first pass.

## 7. Explicitly Out of Scope

- Authentication, multi-user support, or any session-history/list view (single implicit session per page load).
- Editing a tailored resume, cover letter, or any generated content before download — results are read-only in this phase.
- Template selection (only one LaTeX template exists, per Phase 7).
- Retrying or re-running an individual stage after it has already succeeded (each stage button can be clicked again if the user wants to, which will simply create a new `GeneratedDocument`/`ResumeVersion` row per the existing versioning behavior — no special "re-run" UI is built).
- The "improve if needed" auto re-tailor/re-evaluate loop (deferred since Phase 6, still deferred — this is n8n/orchestration-phase territory).
- Mapping backend error strings to non-technical, translated copy (§6 — deliberate; revisit if this tool ever gets a non-technical user).
- Any change to existing stage logic, dependency guards, fabrication guards, or the timeout/thread-safety design — the one backend change in this phase is purely additive (§3's new download route).

## 8. Testing

**One Playwright E2E test**, covering the full happy path against the real Docker Compose backend: upload a real resume PDF → paste real JD text → create session → run all 9 stages successfully in order → download the generated PDF and confirm it's a valid, non-empty file. This is a deliberate minimum, not full coverage — a conscious tradeoff given this phase's goal is proving the flow works, not exhaustively testing every UI error state. No component-level (React Testing Library) tests this phase; verification of individual loading/error states beyond the one E2E path is manual click-through against the real running stack.

The new backend download endpoint (§3) gets standard backend-style tests mirroring the existing pattern: a happy-path test (valid document → correct bytes/content-type), a 404-for-unknown-document test, and a 404-for-missing-file test (row exists, `Storage.load` raises).
