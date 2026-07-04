# Phase 4 — AI Analysis: Resume vs. JD Gap Analysis

Status: Approved by user, pending spec review
Date: 2026-07-06
Scope: Compare an already-structured `ResumeDocument` against an already-structured `JobPostingDocument` and produce a qualitative gap analysis. No numeric or categorical scoring signal is produced in this phase.

## 1. Context

Phase 2 made `resume_parsing` real; Phase 3 made `jd_extraction` real. Both sides of the comparison this phase needs now exist as structured, persisted documents: `ResumeDocument` (via `resume_versions.resume_json`) and `JobPostingDocument` (via `job_postings.parsed_json`). Phase 4 is the first stage that depends on **both** prior stages having succeeded for the same session, rather than depending on only one.

## 2. Scope Boundary (Purpose)

This phase answers "what's the gap between this resume and this JD," not "how good is the match." It produces:

- Matching skills (resume skills that satisfy a JD requirement)
- Missing skills (JD requirements not satisfied by the resume)
- Experience gap notes (freeform, e.g. years-of-experience shortfalls, seniority mismatches)
- Relevant vs. irrelevant projects (which of the resume's projects are worth highlighting for this JD)
- Recommended keywords (JD language worth incorporating)

**Explicitly not produced here:** any numeric score, percentage match, or categorical fit label (e.g. "strong"/"moderate"/"weak"). Actual ATS/hiring-match scoring is Phase 6's responsibility (`EvaluationRun.overall_score` and its sub-scores, produced by the Hiring Agent evaluation service). Keeping this boundary hard avoids a half-baked score here that would later be superseded or contradicted by Phase 6's real rubric-based evaluation.

## 3. Canonical Schema — `GapAnalysisDocument`

New file `backend/app/models/gap_analysis.py`, mirroring the `ResumeDocument`/`JobPostingDocument` pattern (`app/models/resume.py`, `app/models/job_posting.py`):

```python
from typing import Optional
from pydantic import BaseModel, Field

CURRENT_GAP_ANALYSIS_SCHEMA_VERSION = 1


class UnsupportedGapAnalysisSchemaVersion(Exception):
    """Raised when a persisted GapAnalysisDocument's schema_version is not handled by migrate_gap_analysis_document."""


class GapAnalysisDocument(BaseModel):
    schema_version: int = CURRENT_GAP_ANALYSIS_SCHEMA_VERSION
    matching_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    experience_gap_notes: Optional[str] = None
    relevant_projects: list[str] = Field(default_factory=list)
    irrelevant_projects: list[str] = Field(default_factory=list)
    recommended_keywords: list[str] = Field(default_factory=list)


def migrate_gap_analysis_document(data: dict) -> GapAnalysisDocument:
    version = data.get("schema_version", CURRENT_GAP_ANALYSIS_SCHEMA_VERSION)
    if version != CURRENT_GAP_ANALYSIS_SCHEMA_VERSION:
        raise UnsupportedGapAnalysisSchemaVersion(
            f"gap analysis schema_version {version} is not supported (current: {CURRENT_GAP_ANALYSIS_SCHEMA_VERSION})"
        )
    return GapAnalysisDocument.model_validate(data)
```

No field besides `schema_version` is required — an all-empty analysis (e.g. a resume that matches nothing) is a valid outcome, not a schema violation.

`relevant_projects`/`irrelevant_projects` reference `Project.name` (a required `str` field on `ResumeDocument.projects`, confirmed in `app/models/resume.py`). Duplicate project names within a single resume are a theoretical edge case this phase does not guard against — an accepted limitation, not a gap to fix here.

## 4. Storage

New table `gap_analyses`, one row per analysis run (not an update-in-place column, unlike `job_postings.parsed_json`):

```python
class GapAnalysis(Base):
    __tablename__ = "gap_analyses"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("tailoring_sessions.id", ondelete="CASCADE"), nullable=False)
    resume_version_id = Column(Integer, ForeignKey("resume_versions.id", ondelete="CASCADE"), nullable=False)
    job_posting_id = Column(Integer, ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False)
    analysis_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
```

New Alembic migration adding this table, with CASCADE on all three foreign keys — consistent with Phase 1's cascade-everything policy for this schema.

**No dedup, by design.** `gap_analyses` accumulates a new row on every run of `gap_analysis` for the same `resume_version_id`/`job_posting_id` pairing — there is no upsert, no uniqueness constraint, and no "latest analysis" pointer. This is deliberate for now (matching Phase 2/3's acceptance of single-shot execution as today's scope), not an oversight. If repeated re-analysis of the same session becomes a real use case — e.g. a UI that lets a user re-run gap analysis after editing their resume and wants to see history, or only the latest result — that should be a deliberate future decision (most likely: query the most recent row by `created_at`, or add a uniqueness constraint with an explicit re-run/replace policy), not something retrofitted silently.

## 5. Data Flow & Dependency Guard

New `backend/app/services/gap_analyzer.py`, directly parallel to `resume_parser.py`/`jd_extractor.py`:

1. Look up the session's most recent `resume_versions` row (by `resume_id`, ordered by `created_at` or `id` descending) and the associated `job_postings.parsed_json`.
2. **Explicit dependency guard**, checked before any orchestrator call: if no `resume_versions` row exists for this session's resume, raise `GapAnalysisError("resume_parsing has not succeeded for this session yet")`. If `job_postings.parsed_json` is null, raise `GapAnalysisError("jd_extraction has not succeeded for this session yet")`. Each condition gets its own distinct, named error message — not a single generic "prerequisites not met" string — so a caller can tell which stage still needs to run.
3. Render the `gap_analysis` prompt (via the existing `PromptRegistry`) with both the resume JSON and the JD JSON as template context.
4. Call `AIOrchestrator` with `TaskConfig(task_type="gap_analysis", provider="nvidia", model="z-ai/glm-5.2", temperature=0.1, response_schema=GapAnalysisDocument, fallback_providers=[])` — matching `resume_parsing`/`jd_extraction`'s provider/model/temperature configuration exactly.
5. On success: insert a new `GapAnalysis` row with `analysis_json = result.output.model_dump()`.
6. On `OrchestratorError`: wrap as `GapAnalysisError`, mark the `pipeline_runs` row failed — identical failure-policy shape to `resume_parsing`/`jd_extraction`.

`GapAnalysisError` inherits from the existing `StageExecutionError` base class (`app/services/errors.py`), so `run_stage` continues to catch one exception type regardless of which stage failed.

## 6. Prompt Requirements (hard requirements, not style preferences)

New `backend/prompts/gap_analysis/v1.jinja2`. The fabrication risk in this phase is different in kind from Phase 2/3: the risk isn't inventing resume or JD *content*, it's the model being dishonest or generous about the *comparison* between two already-accurate documents. Two specific risks, both requiring concrete, testable prompt behavior:

**6.1 Strict-match rule for `matching_skills`.** A skill counts as "matching" only if:
(a) it is stated explicitly in the resume, or
(b) it is an unambiguous synonym/abbreviation of a JD-required skill (e.g. "JS" ↔ "JavaScript", "k8s" ↔ "Kubernetes").

It must **never** be counted as matching on the basis of a related-but-different technology. The prompt must embed a concrete worked example of this distinction, e.g.:

```
Resume lists: Django
JD requires: Flask
→ Flask is NOT a match. Django and Flask are different frameworks,
  even though both are Python web frameworks.
```

And a second worked example demonstrating the synonym/abbreviation case correctly counting as a match:

```
JD requires: JS
Resume lists: JavaScript
→ JavaScript IS a match. "JS" is a standard abbreviation of "JavaScript",
  not a different or adjacent skill.
```

**6.2 Strict-subset rule for `missing_skills`.** `missing_skills` must only contain skills/requirements that are literally stated in the job posting text. The model must never add a skill it believes is "generally expected" for this type of role if the JD text doesn't mention it.

**Deliberate tradeoff, not a bug:** scoping `missing_skills` strictly to what the JD explicitly names means a poorly-written JD that never states an obviously-implied requirement (e.g. a senior backend role that never says "SQL" but clearly needs it) will produce a gap analysis that misses that gap. This phase is not responsible for inferring unstated, implied, or "commonly expected" requirements — only for comparing what's actually written in both documents. This is the same posture as Phase 2/3's anti-fabrication principle applied in the other direction: the model must not invent gaps any more than it may invent resume or JD content.

## 7. API Integration

`POST /sessions/{id}/run-stage/{stage_name}` gets a third real branch: `STAGE_RUNNERS["gap_analysis"] = _run_gap_analysis`. Reuses the existing `ThreadPoolExecutor` + `STAGE_TIMEOUT_SECONDS` + fresh-session-on-timeout pattern unchanged — no new timeout math needed, since gap analysis input (resume JSON + JD JSON) is comparable in size to Phase 2/3's inputs. Every other `stage_name` still returns `501`.

## 8. Testing

- New synthetic **resume + JD fixture pairs** (paired, not standalone — each pair is a matched scenario):
  - `clean_missing_skills_pair` — resume with Python/Django/PostgreSQL vs. a JD requiring Docker/Kubernetes, to exercise the straightforward "missing" case.
  - `adjacent_not_matching_pair` — resume with Django vs. a JD requiring Flask, to exercise the §6.1 strict-match guard: asserts the model does **not** count Django as satisfying Flask, and that Flask lands in `missing_skills`.
  - `synonym_matching_pair` — resume with "JavaScript" vs. a JD requiring "JS" (or resume with "Kubernetes" vs. JD requiring "k8s"), to exercise the reverse of the strict-match guard: asserts the model **correctly** counts the synonym/abbreviation as a match in `matching_skills`, not `missing_skills` — proving the strict-match rule isn't overcorrecting into false negatives.
- Unit tests mock the `AIOrchestrator` (same pattern as Phase 2/3) — no real API calls in the automated suite.
- **Dependency-guard tests**: assert `GapAnalysisError` fires with the correct named message when no `resume_versions` row exists, and separately when `job_postings.parsed_json` is null — both asserted to fire before any orchestrator call (e.g. via a mock that raises if called).
- **Adjacent-skill guard test** (§6.1): using the `adjacent_not_matching_pair` fixture's scenario, the mocked orchestrator returns a fixed, known-correct `GapAnalysisDocument` reflecting the correct behavior (Flask in `missing_skills`, not `matching_skills`); the test asserts the persisted document matches exactly. As with Phase 2/3's fabrication guards, this proves `gap_analyzer.py` persists the orchestrator's output verbatim — it does not prove real-model behavior, since the orchestrator is mocked.
- **Synonym-match guard test** (reverse case, per this spec's addition): using the `synonym_matching_pair` fixture's scenario, same structure — mocked orchestrator returns the correct-behavior document with the synonym counted as a match, test asserts exact persistence.
- One manual smoke-test script against the real NVIDIA API (matching Phase 2/3's `smoke_test_*.py` pattern), run against both the `adjacent_not_matching_pair` and `synonym_matching_pair` scenarios — this is the one place real-model strict-match behavior (in both directions: not overcounting, not overcorrecting into undercounting) actually gets observed by a human.

## 9. Ledger Cleanup (folded into this phase, Task 1)

Before starting the new gap-analysis work, this phase's first task fixes the 3 cheapest/highest-value items from the Phase 2/3 follow-up backlog:

1. `has_extractable_text`'s 19/20/21-character boundary around `MIN_EXTRACTED_TEXT_LENGTH` — add a boundary test.
2. `strip_json_code_fence` dropping the payload entirely for a single-line fence with no newlines — fix and add a regression test.
3. Unused `tmp_path` fixture parameter in the Phase 3 title-fabrication guard test — remove it.

The remaining 5 ledger items stay deferred (unchanged from Phase 3's final review triage):
- PDF fixture builder's untested overflow branch, no `try/finally` on `doc.close()`.
- `resume_parsing` fabrication test checks keywords only (mitigated by independent JSON-shape verification).
- `parse_resume` fabrication guard only asserts `projects == []`, not `education`/`certifications`.
- `jd_extraction` prompt tests assert rendered substrings only, not full JSON shape (mitigated by field-by-field schema/persistence tests).
- `Responsibilities:`/`Keywords:` labels in `complete_jd_text` fixture untested (plus a cosmetic report-artifact text-garbling issue, doc-only).

## 10. Explicitly Out of Scope

- Any numeric, percentage, or categorical match/fit score (Phase 6 — Hiring Agent evaluation).
- Tailored resume or cover-letter generation (Phase 5).
- Inferring unstated/implied JD requirements not literally present in the JD text (§6.2 — deliberate).
- Deduplication, upsert, or "latest analysis" logic for `gap_analyses` (§4 — deliberate, revisit if repeated re-analysis becomes a real use case).
- Any change to `resume_parsing`, `jd_extraction`, the timeout/thread-safety design, or the orchestrator/provider layer beyond reusing them as-is.
