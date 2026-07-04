# Phase 3 — JD Extraction: Design

Status: Approved by user, pending spec review
Date: 2026-07-05
Scope: Pasted-JD-text structuring into a canonical `JobPostingDocument`, wired into the real `jd_extraction` stage. No URL fetching (Greenhouse, Lever, LinkedIn, Workday, Ashby, SmartRecruiters), no headless-browser rendering, no auth-wall handling, no anti-bot mitigation in this phase.

## 1. Context

Phase 1 built `POST /job-postings`, which already accepts either `source_url` or `raw_text` and has an unused `parsed_json` column on the `JobPosting` table. Phase 2 made `resume_parsing` real; Phase 3 makes `jd_extraction` real, following the identical shape: pasted text → AI Orchestrator → structured document → persisted → wired into `run_stage`.

URL fetching is explicitly deferred to its own future phase, for the same reason Phase 2 deferred DOCX: prove the extraction/structuring core first, without taking on unrelated complexity (headless-browser rendering for JS-heavy job boards, login walls, anti-bot measures) in the same phase as the core JD schema design.

## 2. Canonical JD Schema

A new `JobPostingDocument` Pydantic model, mirroring `ResumeDocument`'s design from Phase 1 (including a `schema_version` field for the same future-migration reasons — see `app/models/resume.py`'s `migrate_resume_document` pattern, which this schema's own future migrator function will follow if it's ever needed):

- `schema_version: int` — versioned like `ResumeDocument`.
- `title: str` — **required**. A job posting always has a title; this is the one required field.
- `company: Optional[str]` — optional (some postings are anonymized, e.g. "Confidential").
- `location: Optional[str]`
- `employment_type: Optional[str]` — free text ("Full-time", "Contract", "Remote"), not an enum, matching `ResumeDocument`'s preference for free-text over premature enums.
- `requirements: list[str]`, `responsibilities: list[str]`, `qualifications: list[str]`, `keywords: list[str]` — all default to empty lists.

## 3. Prompt Requirements (hard requirements, not style preferences)

Same anti-fabrication discipline as Phase 2's `resume_parsing` prompt: the model must leave fields null/empty rather than invent structure. Two specific risks are called out explicitly for this schema, both requiring concrete, testable prompt behavior (not just an abstract instruction):

**3.1 Requirements/qualifications tie-breaking.** JDs frequently blur "requirements" and "qualifications" into one undifferentiated list, or use only one of the two headers. The prompt must instruct: if the source text doesn't clearly distinguish the two, put every item under `requirements` and leave `qualifications` empty — never split one list into two, and never duplicate items across both. This rule must be accompanied by **1-2 concrete worked examples embedded directly in the prompt template** (a short "source text says X → requirements gets [...], qualifications stays []" example), not just described abstractly — an LLM follows a demonstrated pattern more reliably than a prose rule alone. The test suite's "blurred requirements/qualifications" fixture must assert the model actually followed this rule (all items land in `requirements`, `qualifications == []`), not merely that valid JSON came back.

**3.2 Title is the highest-fabrication-risk field.** `title` is the schema's *only* required field, which means it is the one place fabrication pressure is structurally highest — a model asked to produce required output has more incentive to invent a plausible-looking value than for any optional field, especially when handed text that isn't a real job posting at all. This is called out explicitly as the highest-risk case in this phase, on the same footing as Phase 2's sparse/missing-section fabrication guard. The "clearly not a job posting" fixture test must specifically assert the model did **not** fabricate a plausible-looking title to satisfy the required-field constraint — not just that the response validated against the schema. If the real model cannot comply with both "produce a required title" and "never fabricate," the automated test (which mocks the orchestrator) encodes the desired behavior either way; the manual smoke script is where this gets checked against the real model's actual behavior.

## 4. Architecture / Data Flow

A new `backend/app/services/jd_extractor.py` module (the "JD Extractor" logical service from the Phase 1 architecture), directly parallel to Phase 2's `resume_parser.py`:

1. Take the `JobPosting.raw_text` already stored (pasted at creation time via the existing `POST /job-postings` endpoint) — no extraction step is needed here, unlike PDF parsing, since there's no binary format to decode.
2. Render a new `jd_extraction` prompt template via the existing `PromptRegistry`, call the `AIOrchestrator` with `TaskConfig(task_type="jd_extraction", provider="nvidia", response_schema=JobPostingDocument, fallback_providers=[])`, matching `resume_parsing`'s provider/fallback configuration exactly.
3. On success: persist directly into the existing `JobPosting.parsed_json` column (update in place).
4. On `OrchestratorError`: wrap as `JDExtractionError`, mark the `pipeline_runs` row failed — identical failure-policy shape to `resume_parsing`.

**No fail-fast/empty-text guard is needed.** Unlike `resume_parsing`'s blank-PDF check (`has_extractable_text`), there is no equivalent "nothing to extract from" case here: `POST /job-postings` already rejects a request with neither `source_url` nor `raw_text` (Phase 1's `require_url_or_text` validator), so a `JobPosting` row with empty `raw_text` cannot exist. Text that's too short or not actually a job description is handled entirely by the anti-fabrication prompt rule (§3.2), not a separate detection step.

**Deliberate architectural choice, not an oversight:** this phase does **not** introduce a `job_posting_versions` table analogous to `resume_versions`. `JobPosting.parsed_json` remains a single column, updated in place on each `jd_extraction` run, exactly as it already exists from Phase 1. This mirrors Phase 2's own `resume_versions.version_number` being hardcoded to `1` (parsing only happens once today) — but goes one step further here, since `JobPosting` never had a separate versioned table to begin with. This is a considered choice for this phase's scope, not a gap to "fix" by accident later: if a future phase needs JD re-extraction history (e.g., re-running `jd_extraction` after a prompt change, or supporting edited/re-pasted JD text), that decision should be made deliberately then, weighing it against the same tradeoffs Phase 2 flagged for `resume_versions.version_number` — not silently bolted on.

## 5. API Integration

`POST /sessions/{id}/run-stage/{stage_name}` gets a second real branch (`jd_extraction`), alongside the existing `resume_parsing` branch built in Phase 2. Both reuse the identical `ThreadPoolExecutor` + 330-second timeout + fresh-session-on-timeout pattern (including the `run_id`-capture-before-submit fix from Phase 2's follow-up work) — no new timeout math is needed since JD text is typically shorter than resume text, making the existing worst-case bound at least as conservative here. Every other `stage_name` still returns `501`.

## 6. Testing

- New synthetic **pasted-text** JD fixtures (no HTML, no URL fixtures, per the scope decision in §1):
  - `complete_jd` — a full, well-structured posting with clearly separated requirements and qualifications sections.
  - `no_requirements_header` — a posting whose requirements are stated inline without an explicit header.
  - `blurred_requirements_qualifications` — a posting that lists one undifferentiated list of must-haves with no separate "qualifications" section, to exercise the §3.1 tie-breaking rule.
  - `terse_jd` — an extremely short posting (title + one line).
  - `not_a_job_posting` — clearly non-JD text (e.g. a snippet of unrelated prose), to exercise the §3.2 fabrication guard.
- Unit tests mock the `AIOrchestrator`/`NvidiaProvider` (same pattern as Phase 2) — no real API calls in the automated suite.
- **Tie-breaking guard test** (§3.1): using the `blurred_requirements_qualifications` fixture's scenario, assert the persisted `JobPostingDocument` has all items in `requirements` and `qualifications == []` — not just that the response validated.
- **Title-fabrication guard test** (§3.2): using the `not_a_job_posting` fixture's scenario, the mocked orchestrator returns a fixed, known-correct `JobPostingDocument` whose `title` is an honest placeholder (e.g. `"Untitled"` or an equally non-fabricated marker, not a plausible-sounding invented job title), and the test asserts the persisted document's `title` matches that exact value byte-for-byte. This proves what Phase 2's fabrication-guard tests proved for `parse_resume`: that `jd_extractor.py` persists the orchestrator's output verbatim, with no code path that could substitute, embellish, or "clean up" a field — it does **not** prove real-model behavior, since the orchestrator is mocked. Real-model title-fabrication behavior is verified only by the manual smoke script (below), which is the sole place this tension is actually observed against the real NVIDIA API.
- One manual smoke-test script against the real NVIDIA API (matching Phase 2's `smoke_test_resume_parsing.py` pattern), explicitly run against the `not_a_job_posting` fixture as its primary use case — this is the one place real-model title-fabrication behavior actually gets observed by a human.

## 7. Explicitly Out of Scope

- All job-URL fetching (Greenhouse, Lever, LinkedIn, Workday, Ashby, SmartRecruiters).
- Headless-browser rendering, auth-wall detection/handling, anti-bot mitigation.
- A `job_posting_versions` table (§4 — deliberate, revisit later if re-extraction history is ever needed).
- Any change to `resume_parsing`, the timeout/thread-safety design, or the orchestrator/provider layer beyond reusing them as-is.

## 8. Phase 2 Follow-Up Backlog (carried forward, not lost)

These were deferred at the end of Phase 2's final review and remain open, tracked here so they don't get lost across phases:

1. `strip_json_code_fence` (Task 2, Phase 2) drops the payload entirely for a single-line fence with no newlines, and mishandles a same-line closing fence attached to content.
2. PDF fixture builder (Task 3, Phase 2): the page-overflow branch in `_build_pdf` is untested (dead code in practice); no `try/finally` around `doc.close()` in the fixture builders.
3. `has_extractable_text`'s (Task 4, Phase 2) 19/20/21-character boundary around `MIN_EXTRACTED_TEXT_LENGTH` is untested.
4. The `resume_parsing` fabrication-instruction test (Task 5, Phase 2) only checks keyword presence, not full JSON-shape parseability — mitigated by Phase 2's final review independently verifying the JSON shape matches `ResumeDocument` exactly, but the test itself remains keyword-only.
5. `parse_resume`'s (Task 6, Phase 2) fabrication guard only asserts `projects == []`, not also `education`/`certifications`.
