# Phase 5 — Resume Tailoring Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consume the original parsed `ResumeDocument`, `JobPostingDocument`, and `GapAnalysisDocument` to produce a tailored `ResumeDocument`, persisted as a new session-scoped `resume_versions` row with a per-field explainability record.

**Architecture:** A new `backend/app/services/tailoring_engine.py`, parallel to `gap_analyzer.py`: a three-prerequisite dependency guard, a new combined `TailoringResult` orchestrator response schema (tailored resume + per-change rationale), a code-level skills/entry-identity validation guard that rejects the whole run rather than mutating output, and persistence into a session-scoped `resume_versions` row plus `tailoring_changes` rows.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, Jinja2 (existing stack — no new dependencies).

## Global Constraints

- Rewrite scope: reword + reorder only, never delete an entry (spec §2).
- `resume_versions.session_id`: nullable FK to `tailoring_sessions.id`, `ondelete="CASCADE"` (spec §3.1).
- `version_number`: global per-resume counter, `max(version_number for this resume_id across all sessions) + 1` (spec §3.2).
- `tailoring_changes` table: `id, resume_version_id (FK CASCADE), field_changed, original_text (nullable), tailored_text, rationale, created_at` (spec §3.3).
- `field_changed` uses identity-anchored paths (project name / company+title / institution), never raw positional indices (spec §3.4).
- Orchestrator response schema is `TailoringResult { tailored_resume: ResumeDocument, changes: list[TailoringChangeRecord] }`, not a bare `ResumeDocument` (spec §5).
- Three-prerequisite dependency guard (resume_parsing, jd_extraction, gap_analysis), each with a distinct named error, all checked before any orchestrator call (spec §6).
- Code-level skills guard rejects the entire run as `TailoringError` if it finds an unearned skill — never silently strips (spec §4.2).
- No code-level metric-fabrication guard exists — prompt-only enforcement, documented residual risk (spec §4.3).
- Re-tailoring always sources from the `produced_by_stage="resume_parsing"` row — never chains off a prior tailored version (spec §7).
- Orchestrator call: `provider="nvidia"`, `model="z-ai/glm-5.2"`, `temperature=0.1`, `fallback_providers=[]` (spec §6).
- Reuses `STAGE_TIMEOUT_SECONDS`/`ThreadPoolExecutor`/fresh-session-on-timeout unchanged (spec §9).
- `test_run_stage_returns_501_for_unimplemented_stage` must target a still-unimplemented stage name other than `tailoring_rewrite` (spec §9).
- Windows test runner for this repo: `py -3 -m pytest` (or venv-equivalent), run from `backend/`.
- Baseline before Task 1: 117 passed, 1 skipped (Postgres-dependent migration test).

---

### Task 1: Ledger cleanup (3 items from the cross-phase follow-up backlog)

**Files:**
- Modify: `backend/app/core/llm/provider.py`
- Modify: `backend/tests/test_provider.py`
- Modify: `backend/tests/fixtures/pdf_fixtures.py`
- Modify: `backend/tests/test_pdf_extractor.py`
- Modify: `backend/tests/test_jd_extraction_prompt.py`

**Interfaces:**
- Consumes: nothing new — pure cleanup of existing Phase 2-4 code.
- Produces: nothing new — no later task depends on this task's changes.

This task closes 3 more items from the follow-up ledger (spec §10): `strip_json_code_fence`'s opening-fence-with-attached-content case, the PDF fixture builder's untested overflow branch + missing `try/finally`, and an automated JSON-shape test for the `jd_extraction` prompt.

- [ ] **Step 1: Write the failing test for the opening-fence bug**

Add to `backend/tests/test_provider.py`:

```python
def test_strip_json_code_fence_handles_content_attached_to_opening_fence():
    text = '```json{"a": 1}\n```'
    assert strip_json_code_fence(text) == '{"a": 1}'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_provider.py -v` (from `backend/`)
Expected: the new test FAILS — the current code drops the whole opening-fence line (including its attached content), returning `""`.

- [ ] **Step 3: Fix `strip_json_code_fence`**

Replace the function in `backend/app/core/llm/provider.py`:

```python
def strip_json_code_fence(text: str) -> str:
    """Strip a leading/trailing markdown code fence (```json ... ``` or ``` ... ```), if present."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    if "\n" not in stripped:
        # Single-line fence: the entire payload sits between the opening and
        # closing ``` with no line breaks at all, e.g. '```json{"a": 1}```'.
        inner = stripped[3:]
        if inner.endswith("```"):
            inner = inner[:-3]
        if inner.lower().startswith("json"):
            inner = inner[4:]
        return inner.strip()

    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        first_line_rest = lines[0][3:]
        if first_line_rest.lower().startswith("json"):
            first_line_rest = first_line_rest[4:]
        if first_line_rest.strip():
            # Content attached to the opening fence line (e.g. '```json{"a": 1}') -
            # keep it rather than dropping the whole line.
            lines[0] = first_line_rest
        else:
            lines = lines[1:]
    if lines:
        last = lines[-1].rstrip()
        if last == "```":
            lines = lines[:-1]
        elif last.endswith("```"):
            # Closing fence attached to the same line as trailing content,
            # e.g. the last line is '{"a": 1}```' rather than '```' alone.
            lines[-1] = last[:-3]
    return "\n".join(lines).strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_provider.py -v`
Expected: all 7 tests in this file PASS (6 pre-existing plus the new one).

- [ ] **Step 5: Fix the PDF fixture builder's missing try/finally and add an overflow test**

Replace the entire contents of `backend/tests/fixtures/pdf_fixtures.py`:

```python
"""Synthetic PDF resume fixtures for tests. All names, companies, and content
below are fabricated placeholders — not real people, not scrubbed real resumes."""
import pymupdf


def _build_pdf(lines: list[str]) -> bytes:
    doc = pymupdf.open()
    try:
        page = doc.new_page()
        y = 50
        for line in lines:
            page.insert_text((50, y), line, fontsize=11)
            y += 18
            if y > 780:
                page = doc.new_page()
                y = 50
        return doc.tobytes()
    finally:
        doc.close()


def build_normal_resume_pdf() -> bytes:
    return _build_pdf([
        "Jane Doe",
        "jane.doe@example.com | (555) 123-4567 | Springfield",
        "",
        "Summary",
        "Backend engineer with 5 years of experience building distributed systems.",
        "",
        "Experience",
        "Acme Corp - Senior Backend Engineer (2021-2024)",
        "- Designed and shipped a payments processing service handling 2M requests/day",
        "- Led migration from monolith to microservices, cutting deploy time by 60%",
        "",
        "Globex Inc - Backend Engineer (2018-2021)",
        "- Built internal analytics pipeline processing 500GB/day of event data",
        "",
        "Education",
        "State University - B.S. Computer Science (2014-2018)",
        "",
        "Projects",
        "Open Source Task Queue - a lightweight distributed task queue in Python",
        "- 400+ GitHub stars, used in production by three startups",
        "",
        "Skills",
        "Python, PostgreSQL, Docker, Kubernetes, AWS",
    ])


def build_no_summary_resume_pdf() -> bytes:
    return _build_pdf([
        "John Smith",
        "john.smith@example.com",
        "",
        "Experience",
        "Initech - Software Engineer (2020-2024)",
        "- Maintained a Django monolith serving 10k daily active users",
        "",
        "Education",
        "Tech Institute - B.S. Software Engineering (2016-2020)",
        "",
        "Skills",
        "Java, Spring, MySQL",
    ])


def build_sparse_bullets_resume_pdf() -> bytes:
    return _build_pdf([
        "Alex Lee",
        "alex.lee@example.com",
        "",
        "Experience",
        "Startup Co - Engineer (2022-2024)",
        "- Worked on backend",
        "",
        "Education",
        "Community College - A.S. Information Technology (2020-2022)",
    ])


def build_missing_section_resume_pdf() -> bytes:
    # Deliberately has no projects section at all.
    return _build_pdf([
        "Sam Rivera",
        "sam.rivera@example.com",
        "",
        "Summary",
        "Full-stack developer.",
        "",
        "Experience",
        "Widget LLC - Full-Stack Developer (2019-2024)",
        "- Built customer-facing dashboards using React and FastAPI",
        "",
        "Education",
        "Metro University - B.S. Information Systems (2015-2019)",
        "",
        "Skills",
        "JavaScript, React, FastAPI, PostgreSQL",
    ])


def build_many_pages_resume_pdf() -> bytes:
    """Forces the page-overflow branch in _build_pdf (y > 780) by exceeding ~40
    lines on a single page, so multi-page PDFs are actually exercised by a test."""
    lines = ["Alpha Marker"] + [f"Filler line {i}" for i in range(43)] + ["Omega Marker"]
    return _build_pdf(lines)


def build_blank_pdf() -> bytes:
    doc = pymupdf.open()
    try:
        doc.new_page()
        return doc.tobytes()
    finally:
        doc.close()
```

- [ ] **Step 6: Add the overflow-branch test**

Add to `backend/tests/test_pdf_extractor.py`, and update its import line:

```python
from app.services.pdf_extractor import extract_text_from_pdf, has_extractable_text
from tests.fixtures.pdf_fixtures import build_normal_resume_pdf, build_blank_pdf, build_many_pages_resume_pdf
```

```python
def test_build_pdf_overflow_branch_creates_multiple_pages_and_extracts_all_content():
    """Ledger item: the page-overflow branch in _build_pdf (y > 780, triggering a
    new page) was previously untested/dead in practice. This fixture has 45 lines,
    well past the ~40-line-per-page threshold, forcing multi-page generation."""
    text = extract_text_from_pdf(build_many_pages_resume_pdf())
    assert "Alpha Marker" in text
    assert "Omega Marker" in text
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_pdf_extractor.py -v`
Expected: all 6 tests in this file PASS (5 pre-existing plus the new one).

- [ ] **Step 8: Add the jd_extraction prompt JSON-shape test**

Add to `backend/tests/test_jd_extraction_prompt.py`, and add an import at the top:

```python
import re
from app.models.job_posting import JobPostingDocument
```

```python
def test_jd_extraction_prompt_json_shape_matches_job_posting_document_fields():
    """Ledger item: previously the JSON-shape correctness of this prompt's output
    block was only verified manually during code review, not by an automated
    test. This ties the prompt's declared field list directly to
    JobPostingDocument's actual fields, so schema drift between the two would
    fail this test."""
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render("jd_extraction", "v1", raw_text="Barista at Corner Cafe.")
    shape_block = re.search(r"\{[^{}]*\}", rendered, re.DOTALL).group(0)
    keys_in_prompt = re.findall(r'"(\w+)":', shape_block)
    assert keys_in_prompt == list(JobPostingDocument.model_fields.keys())
```

- [ ] **Step 9: Run the full suite to confirm no regressions**

Run: `py -3 -m pytest -q` (from `backend/`)
Expected: 120 passed, 1 skipped (117 baseline + 3 new tests: opening-fence test, overflow test, JSON-shape test).

- [ ] **Step 10: Commit**

```bash
git add backend/app/core/llm/provider.py backend/tests/test_provider.py backend/tests/fixtures/pdf_fixtures.py backend/tests/test_pdf_extractor.py backend/tests/test_jd_extraction_prompt.py
git commit -m "fix: strip_json_code_fence opening-fence case; PDF fixture try/finally + overflow test; jd_extraction JSON-shape test"
```

---

### Task 2: `TailoringResult` / `TailoringChangeRecord` schema

**Files:**
- Create: `backend/app/models/tailoring_result.py`
- Test: `backend/tests/test_tailoring_result_schema.py`

**Interfaces:**
- Consumes: `ResumeDocument` (from `app.models.resume`, already exists).
- Produces: `TailoringResult`, `TailoringChangeRecord`, `CURRENT_TAILORING_RESULT_SCHEMA_VERSION: int`, `UnsupportedTailoringResultSchemaVersion` (exception), `migrate_tailoring_result(data: dict) -> TailoringResult`. Consumed by Task 6 (`tailoring_engine.py`'s `response_schema`).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_tailoring_result_schema.py`:

```python
import pytest
from app.models.resume import ResumeDocument, ContactInfo
from app.models.tailoring_result import (
    TailoringResult,
    TailoringChangeRecord,
    CURRENT_TAILORING_RESULT_SCHEMA_VERSION,
    migrate_tailoring_result,
    UnsupportedTailoringResultSchemaVersion,
)


def _minimal_resume() -> ResumeDocument:
    return ResumeDocument(contact=ContactInfo(full_name="Jane Doe"))


def test_tailoring_result_defaults_to_current_schema_version():
    result = TailoringResult(tailored_resume=_minimal_resume())
    assert result.schema_version == CURRENT_TAILORING_RESULT_SCHEMA_VERSION
    assert result.changes == []


def test_tailoring_change_record_allows_null_original_text():
    record = TailoringChangeRecord(
        field_changed="summary", tailored_text="Rewritten summary.",
        rationale="Emphasized backend experience.",
    )
    assert record.original_text is None


def test_tailoring_result_roundtrips_through_json():
    result = TailoringResult(
        tailored_resume=_minimal_resume(),
        changes=[
            TailoringChangeRecord(
                field_changed='projects["Inventory Tracker"].bullets[0]',
                original_text="Worked on a project.",
                tailored_text="Built an inventory tracking system used by 3 teams.",
                rationale="Incorporated recommended keyword 'inventory' and strengthened the verb.",
            ),
        ],
    )
    restored = TailoringResult.model_validate_json(result.model_dump_json())
    assert restored == result


def test_migrate_tailoring_result_accepts_current_version():
    raw = {"schema_version": 1, "tailored_resume": _minimal_resume().model_dump(), "changes": []}
    result = migrate_tailoring_result(raw)
    assert result.changes == []


def test_migrate_tailoring_result_rejects_unknown_future_version():
    raw = {"schema_version": 999, "tailored_resume": _minimal_resume().model_dump(), "changes": []}
    with pytest.raises(UnsupportedTailoringResultSchemaVersion):
        migrate_tailoring_result(raw)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_tailoring_result_schema.py -v` (from `backend/`)
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.tailoring_result'`

- [ ] **Step 3: Write the schema**

`backend/app/models/tailoring_result.py`:

```python
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field
from app.models.resume import ResumeDocument

CURRENT_TAILORING_RESULT_SCHEMA_VERSION = 1


class TailoringChangeRecord(BaseModel):
    field_changed: str
    original_text: Optional[str] = None
    tailored_text: str
    rationale: str


class TailoringResult(BaseModel):
    schema_version: int = CURRENT_TAILORING_RESULT_SCHEMA_VERSION
    tailored_resume: ResumeDocument
    changes: list[TailoringChangeRecord] = Field(default_factory=list)


class UnsupportedTailoringResultSchemaVersion(Exception):
    pass


def migrate_tailoring_result(data: dict) -> TailoringResult:
    """Load a raw dict of any known schema_version into the current TailoringResult
    shape. New migrators get registered here the first time schema_version is
    bumped past 1 — mirrors app/models/resume.py's migrate_resume_document.
    """
    version = data.get("schema_version", CURRENT_TAILORING_RESULT_SCHEMA_VERSION)
    if version == CURRENT_TAILORING_RESULT_SCHEMA_VERSION:
        return TailoringResult.model_validate(data)
    raise UnsupportedTailoringResultSchemaVersion(
        f"No migrator registered for tailoring result schema_version={version}"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_tailoring_result_schema.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/tailoring_result.py backend/tests/test_tailoring_result_schema.py
git commit -m "feat: add TailoringResult/TailoringChangeRecord orchestrator response schema"
```

---

### Task 3: `resume_versions.session_id` column + `tailoring_changes` table

**Files:**
- Modify: `backend/app/models/db_models.py`
- Create: `backend/alembic/versions/0004_resume_version_session_and_tailoring_changes.py`
- Modify: `backend/tests/test_db_models.py`
- Create: `backend/tests/test_migration_0004_resume_version_session_and_tailoring_changes.py`

**Interfaces:**
- Consumes: `Base` (from `app.models.db_models`, already exists).
- Produces: `ResumeVersion.session_id` column; `TailoringChange` ORM class (`app.models.db_models.TailoringChange`) with columns `id, resume_version_id, field_changed, original_text, tailored_text, rationale, created_at`. Consumed by Task 6 (`tailoring_engine.py` sets `session_id` and constructs `TailoringChange` rows).

- [ ] **Step 1: Write the failing test**

Replace the entire contents of `backend/tests/test_db_models.py`:

```python
import pytest
from sqlalchemy.exc import IntegrityError

from app.core.db import make_engine, make_session_factory
from app.models.db_models import (
    Base, Resume, ResumeVersion, JobPosting, TailoringSession,
    PipelineRun, EvaluationRun, GeneratedDocument, PromptVersion, LLMCall, GapAnalysis,
    TailoringChange,
)


def test_all_tables_create_and_accept_a_linked_row():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        resume = Resume(original_filename="jane.pdf", storage_path="/tmp/jane.pdf")
        db.add(resume)
        db.flush()

        version = ResumeVersion(
            resume_id=resume.id, version_number=1,
            resume_json={"schema_version": 1, "contact": {"full_name": "Jane"}},
            produced_by_stage="upload",
        )
        job = JobPosting(source_url="https://example.com/job", source_provider="greenhouse")
        db.add_all([version, job])
        db.flush()

        session = TailoringSession(resume_id=resume.id, job_posting_id=job.id, status="created")
        db.add(session)
        db.flush()

        tailored_version = ResumeVersion(
            resume_id=resume.id, session_id=session.id, version_number=2,
            resume_json={"schema_version": 1, "contact": {"full_name": "Jane"}},
            produced_by_stage="tailoring_rewrite",
        )
        db.add(tailored_version)
        db.flush()

        pipeline_run = PipelineRun(session_id=session.id, stage_name="resume_parsing", status="succeeded")
        evaluation = EvaluationRun(
            session_id=session.id, resume_version_id=version.id,
            overall_score=85.0, raw_response_json={"overall_score": 85.0},
        )
        document = GeneratedDocument(
            session_id=session.id, document_type="ats_report",
            content="report body", version_number=1,
        )
        prompt_version = PromptVersion(
            task_type="tailoring_rewrite", name="tailoring_rewrite", version="v1",
            template_path="prompts/tailoring_rewrite/v1.jinja2",
        )
        gap_analysis = GapAnalysis(
            session_id=session.id, resume_version_id=version.id, job_posting_id=job.id,
            analysis_json={"schema_version": 1, "matching_skills": ["Python"]},
        )
        db.add_all([pipeline_run, evaluation, document, prompt_version, gap_analysis])
        db.flush()

        tailoring_change = TailoringChange(
            resume_version_id=tailored_version.id, field_changed="summary",
            original_text="Old summary.", tailored_text="New summary.",
            rationale="Emphasized backend experience.",
        )
        llm_call = LLMCall(
            session_id=session.id, prompt_version_id=prompt_version.id,
            provider="gemini", model="gemini-1.5-flash", task_type="tailoring_rewrite",
            temperature=0.7, request_payload={"prompt": "hi"}, response_payload={"text": "hello"},
            validated=True, latency_ms=250,
        )
        db.add_all([tailoring_change, llm_call])
        db.commit()

        assert db.query(Resume).count() == 1
        assert db.query(LLMCall).count() == 1
        assert db.query(EvaluationRun).first().overall_score == 85.0
        assert db.query(GapAnalysis).first().analysis_json["matching_skills"] == ["Python"]
        assert db.query(TailoringChange).first().tailored_text == "New summary."
        assert db.query(ResumeVersion).filter_by(id=tailored_version.id).one().session_id == session.id


def test_deleting_a_session_cascades_to_its_dependent_rows_including_tailored_version():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        resume = Resume(original_filename="jane.pdf", storage_path="/tmp/jane.pdf")
        db.add(resume)
        db.flush()

        version = ResumeVersion(
            resume_id=resume.id, version_number=1,
            resume_json={"schema_version": 1, "contact": {"full_name": "Jane"}},
            produced_by_stage="upload",
        )
        job = JobPosting(source_url="https://example.com/job", source_provider="greenhouse")
        db.add_all([version, job])
        db.flush()

        session = TailoringSession(resume_id=resume.id, job_posting_id=job.id, status="created")
        db.add(session)
        db.flush()

        tailored_version = ResumeVersion(
            resume_id=resume.id, session_id=session.id, version_number=2,
            resume_json={"schema_version": 1, "contact": {"full_name": "Jane"}},
            produced_by_stage="tailoring_rewrite",
        )
        db.add(tailored_version)
        db.flush()

        pipeline_run = PipelineRun(session_id=session.id, stage_name="resume_parsing", status="succeeded")
        evaluation = EvaluationRun(
            session_id=session.id, resume_version_id=version.id,
            overall_score=85.0, raw_response_json={"overall_score": 85.0},
        )
        document = GeneratedDocument(
            session_id=session.id, document_type="ats_report",
            content="report body", version_number=1,
        )
        prompt_version = PromptVersion(
            task_type="tailoring_rewrite", name="tailoring_rewrite", version="v1",
            template_path="prompts/tailoring_rewrite/v1.jinja2",
        )
        gap_analysis = GapAnalysis(
            session_id=session.id, resume_version_id=version.id, job_posting_id=job.id,
            analysis_json={"schema_version": 1, "matching_skills": ["Python"]},
        )
        db.add_all([pipeline_run, evaluation, document, prompt_version, gap_analysis])
        db.flush()

        tailoring_change = TailoringChange(
            resume_version_id=tailored_version.id, field_changed="summary",
            original_text="Old summary.", tailored_text="New summary.",
            rationale="Emphasized backend experience.",
        )
        llm_call = LLMCall(
            session_id=session.id, prompt_version_id=prompt_version.id,
            provider="gemini", model="gemini-1.5-flash", task_type="tailoring_rewrite",
            temperature=0.7, request_payload={"prompt": "hi"}, response_payload={"text": "hello"},
            validated=True, latency_ms=250,
        )
        db.add_all([tailoring_change, llm_call])
        db.commit()

        session_id = session.id
        resume_id = resume.id
        job_id = job.id
        version_id = version.id
        tailored_version_id = tailored_version.id
        prompt_version_id = prompt_version.id

        db.delete(session)
        db.commit()

    with SessionFactory() as db:
        assert db.query(PipelineRun).filter_by(session_id=session_id).count() == 0
        assert db.query(EvaluationRun).filter_by(session_id=session_id).count() == 0
        assert db.query(GeneratedDocument).filter_by(session_id=session_id).count() == 0
        assert db.query(LLMCall).filter_by(session_id=session_id).count() == 0
        assert db.query(GapAnalysis).filter_by(session_id=session_id).count() == 0
        assert db.query(ResumeVersion).filter_by(id=tailored_version_id).count() == 0
        assert db.query(TailoringChange).filter_by(resume_version_id=tailored_version_id).count() == 0

        assert db.query(Resume).filter_by(id=resume_id).count() == 1
        assert db.query(JobPosting).filter_by(id=job_id).count() == 1
        assert db.query(ResumeVersion).filter_by(id=version_id).count() == 1
        assert db.query(PromptVersion).filter_by(id=prompt_version_id).count() == 1


def test_prompt_version_unique_constraint_rejects_duplicates():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        db.add(PromptVersion(
            task_type="resume_parsing", name="resume_parsing", version="v1", template_path="a.jinja2",
        ))
        db.commit()

        db.add(PromptVersion(
            task_type="resume_parsing", name="resume_parsing", version="v1", template_path="b.jinja2",
        ))
        with pytest.raises(IntegrityError):
            db.commit()


def test_deleting_referenced_prompt_version_is_restricted():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        prompt_version = PromptVersion(
            task_type="resume_parsing", name="resume_parsing", version="v1", template_path="a.jinja2",
        )
        db.add(prompt_version)
        db.commit()

        llm_call = LLMCall(
            session_id=None, prompt_version_id=prompt_version.id, provider="nvidia",
            model="m1", task_type="resume_parsing", validated=True,
        )
        db.add(llm_call)
        db.commit()

        db.delete(prompt_version)
        with pytest.raises(IntegrityError):
            db.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_db_models.py -v` (from `backend/`)
Expected: FAIL with `ImportError: cannot import name 'TailoringChange' from 'app.models.db_models'`

- [ ] **Step 3: Add `session_id` to `ResumeVersion` and append the `TailoringChange` class**

In `backend/app/models/db_models.py`, modify the `ResumeVersion` class:

```python
class ResumeVersion(Base):
    __tablename__ = "resume_versions"

    id = Column(Integer, primary_key=True)
    resume_id = Column(Integer, ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(Integer, ForeignKey("tailoring_sessions.id", ondelete="CASCADE"), nullable=True)
    version_number = Column(Integer, nullable=False)
    resume_json = Column(JSON, nullable=False)
    produced_by_stage = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    resume = relationship("Resume", back_populates="versions")
```

Append to the end of the file (after the `GapAnalysis` class):

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

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_db_models.py -v`
Expected: 4 passed

- [ ] **Step 5: Write the Alembic migration**

`backend/alembic/versions/0004_resume_version_session_and_tailoring_changes.py`:

```python
"""resume_versions.session_id and tailoring_changes table

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-07

"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "resume_versions",
        sa.Column(
            "session_id", sa.Integer,
            sa.ForeignKey("tailoring_sessions.id", ondelete="CASCADE"), nullable=True,
        ),
    )
    op.create_table(
        "tailoring_changes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("resume_version_id", sa.Integer, sa.ForeignKey("resume_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_changed", sa.String, nullable=False),
        sa.Column("original_text", sa.Text, nullable=True),
        sa.Column("tailored_text", sa.Text, nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("tailoring_changes")
    op.drop_column("resume_versions", "session_id")
```

- [ ] **Step 6: Write the migration test**

`backend/tests/test_migration_0004_resume_version_session_and_tailoring_changes.py`:

```python
"""Migration test for 0004 (resume_versions.session_id + tailoring_changes table):
confirms upgrade() adds the column and creates the table, and downgrade() cleanly
reverses both. Like migration 0003, this migration doesn't depend on migration
0002's changes (0002 only alters prompt_versions/llm_calls, which 0004 never
touches), so - following the same precedent established for 0003's migration
test - only migration 0001 is replayed as setup, not 0002, avoiding SQLite's
inability to run 0002's raw ALTER-CONSTRAINT DDL outside batch mode."""
import importlib.util
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"
MIGRATION_0001_PATH = VERSIONS_DIR / "0001_initial_schema.py"
MIGRATION_0004_PATH = VERSIONS_DIR / "0004_resume_version_session_and_tailoring_changes.py"


def _load_migration(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_0004_adds_session_id_and_creates_tailoring_changes_table():
    migration_0001 = _load_migration(MIGRATION_0001_PATH, "migration_0001_for_0004_test")
    migration_0004 = _load_migration(MIGRATION_0004_PATH, "migration_0004_under_test")

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))

        migration_context = MigrationContext.configure(connection)
        with Operations.context(migration_context):
            migration_0001.upgrade()
        connection.commit()

        inspector = inspect(engine)
        assert "session_id" not in [col["name"] for col in inspector.get_columns("resume_versions")]
        assert "tailoring_changes" not in inspector.get_table_names()

        migration_context = MigrationContext.configure(connection)
        with Operations.context(migration_context):
            migration_0004.upgrade()
        connection.commit()

        inspector = inspect(engine)
        assert "session_id" in [col["name"] for col in inspector.get_columns("resume_versions")]
        assert "tailoring_changes" in inspector.get_table_names()

        migration_context = MigrationContext.configure(connection)
        with Operations.context(migration_context):
            migration_0004.downgrade()
        connection.commit()

        inspector = inspect(engine)
        assert "session_id" not in [col["name"] for col in inspector.get_columns("resume_versions")]
        assert "tailoring_changes" not in inspector.get_table_names()
```

- [ ] **Step 7: Run the new migration test**

Run: `py -3 -m pytest tests/test_migration_0004_resume_version_session_and_tailoring_changes.py -v`
Expected: 1 passed

- [ ] **Step 8: Run the full suite**

Run: `py -3 -m pytest -q` (from `backend/`)
Expected: 126 passed, 1 skipped (120 after Task 1, +5 from Task 2, +1 net new here — `test_db_models.py`'s rewritten file keeps the same 4-test count, plus 1 new migration test).

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/db_models.py backend/alembic/versions/0004_resume_version_session_and_tailoring_changes.py backend/tests/test_db_models.py backend/tests/test_migration_0004_resume_version_session_and_tailoring_changes.py
git commit -m "feat: add resume_versions.session_id and tailoring_changes table"
```

---

### Task 4: Synthetic resume + JD + gap-analysis fixture triple

**Files:**
- Create: `backend/tests/fixtures/tailoring_fixtures.py`
- Test: `backend/tests/test_tailoring_fixtures.py`

**Interfaces:**
- Consumes: `ResumeDocument`, `ContactInfo`, `WorkExperience`, `Project` (`app.models.resume`), `JobPostingDocument` (`app.models.job_posting`), `GapAnalysisDocument` (`app.models.gap_analysis`) — all already exist.
- Produces: `base_tailoring_triple() -> tuple[ResumeDocument, JobPostingDocument, GapAnalysisDocument]`. Consumed by Task 6 (`test_tailoring_engine.py`) and Task 8 (smoke script).

**Important:** the resume has two projects — "Inventory Tracker" (technologies: `["Python"]`) and "Recipe Finder" (technologies: `["Python"]`, deliberately **not** `["Python", "Flask"]`). Task 6's "unearned adjacent skill" guard test adds `"Flask"` to a tailored output and asserts it gets rejected as unearned — that only works if `"Flask"` is genuinely absent from every part of the original resume and from `gap_analysis.matching_skills`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_tailoring_fixtures.py`:

```python
from tests.fixtures.tailoring_fixtures import base_tailoring_triple


def test_base_tailoring_triple_has_two_projects_for_reorder_testing():
    resume, job_posting, gap_analysis = base_tailoring_triple()
    assert [project.name for project in resume.projects] == ["Inventory Tracker", "Recipe Finder"]


def test_base_tailoring_triple_gap_analysis_names_a_missing_skill_not_in_resume():
    resume, job_posting, gap_analysis = base_tailoring_triple()
    assert "Docker" in gap_analysis.missing_skills
    assert "Docker" not in resume.skills


def test_base_tailoring_triple_has_no_flask_anywhere_in_resume_or_matching_skills():
    """Flask must be genuinely absent from the original resume (skills, bullets,
    and every project's technologies) and from gap_analysis.matching_skills, so
    Task 6's unearned-adjacent-skill guard test has a clean vector to add Flask
    to and assert it gets rejected as unearned."""
    resume, job_posting, gap_analysis = base_tailoring_triple()
    assert "Flask" not in resume.skills
    assert "Flask" not in gap_analysis.matching_skills
    for project in resume.projects:
        assert "Flask" not in project.technologies
        assert all("Flask" not in bullet for bullet in project.bullets)
    for entry in resume.work_experience:
        assert all("Flask" not in bullet for bullet in entry.bullets)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_tailoring_fixtures.py -v` (from `backend/`)
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.fixtures.tailoring_fixtures'`

- [ ] **Step 3: Write the fixture**

`backend/tests/fixtures/tailoring_fixtures.py`:

```python
"""Synthetic resume + JD + gap-analysis triples for tailoring-engine tests. All
names, companies, and content below are fabricated placeholders."""
from app.models.resume import ResumeDocument, ContactInfo, WorkExperience, Project
from app.models.job_posting import JobPostingDocument
from app.models.gap_analysis import GapAnalysisDocument


def base_tailoring_triple() -> tuple[ResumeDocument, JobPostingDocument, GapAnalysisDocument]:
    """A resume with two projects (used by the reorder-misattribution test to
    confirm identity-anchored change paths survive reordering), a JD requiring
    skills the resume doesn't have, and a matching gap analysis."""
    resume = ResumeDocument(
        contact=ContactInfo(full_name="Morgan Lee"),
        summary="Backend engineer.",
        work_experience=[
            WorkExperience(
                company="Acme Corp", title="Backend Engineer", start_date="2021", end_date="2024",
                bullets=["Worked on backend services"],
            ),
        ],
        projects=[
            Project(name="Inventory Tracker", bullets=["Built a tool to track inventory"], technologies=["Python"]),
            Project(name="Recipe Finder", bullets=["Built a recipe search tool"], technologies=["Python"]),
        ],
        skills=["Python", "Django", "PostgreSQL"],
    )
    job_posting = JobPostingDocument(
        title="Senior Backend Engineer",
        requirements=["Docker", "Kubernetes"],
    )
    gap_analysis = GapAnalysisDocument(
        matching_skills=["Python"],
        missing_skills=["Docker", "Kubernetes"],
        relevant_projects=["Inventory Tracker"],
        irrelevant_projects=["Recipe Finder"],
        recommended_keywords=["Docker", "distributed systems"],
    )
    return resume, job_posting, gap_analysis
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_tailoring_fixtures.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/tests/fixtures/tailoring_fixtures.py backend/tests/test_tailoring_fixtures.py
git commit -m "feat: add resume/JD/gap-analysis fixture triple for tailoring-engine tests"
```

---

### Task 5: `tailoring_rewrite` prompt template

**Files:**
- Create: `backend/prompts/tailoring_rewrite/v1.jinja2`
- Test: `backend/tests/test_tailoring_prompt.py`

**Interfaces:**
- Consumes: `PromptRegistry.render(task_type, version, **context)` (already exists) — context keys `resume_json: str`, `job_posting_json: str`, `gap_analysis_json: str` (pre-serialized JSON text).
- Produces: the rendered prompt text, consumed by Task 6 (`tailoring_engine.py`'s `orchestrator.run(task, prompt=prompt)` call).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_tailoring_prompt.py`:

```python
from app.core.llm.prompt_registry import PromptRegistry
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, PromptVersion


def _render():
    registry = PromptRegistry(prompts_root="prompts")
    return registry.render(
        "tailoring_rewrite", "v1",
        resume_json="{}", job_posting_json="{}", gap_analysis_json="{}",
    )


def test_tailoring_prompt_registers_via_sync_to_db():
    registry = PromptRegistry(prompts_root="prompts")
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        registry.sync_to_db(db)
        row = db.query(PromptVersion).filter_by(task_type="tailoring_rewrite", version="v1").one()
        assert row.template_path == "tailoring_rewrite/v1.jinja2"


def test_tailoring_prompt_instructs_against_fabricated_metrics():
    """Prompt-quality test (spec §4.3, §8): this is the ONLY defense against
    fabricated metrics, since no code-level guard exists for this vector."""
    rendered = _render()
    lowered = rendered.lower()
    assert "40%" in rendered  # the worked example's specific invented figure
    assert "fabricat" in lowered or "invent" in lowered
    assert "metric" in lowered or "number" in lowered or "percentage" in lowered


def test_tailoring_prompt_instructs_against_unearned_skills():
    rendered = _render()
    lowered = rendered.lower()
    assert "unearned" in lowered
    assert "matching_skills" in rendered


def test_tailoring_prompt_instructs_against_claiming_missing_skills():
    """Prompt-quality test (spec §4.1, §8): the code-level skills guard (§4.2)
    only checks whether a skill is unearned, not whether it specifically came
    from missing_skills, so this instruction is the only defense for this exact
    case (a skill that's also true content elsewhere wouldn't trip the guard)."""
    rendered = _render()
    lowered = rendered.lower()
    assert "missing_skills" in rendered
    assert "not" in lowered and "possess" in lowered


def test_tailoring_prompt_instructs_no_fabricated_entries_and_same_count():
    rendered = _render()
    lowered = rendered.lower()
    assert "same count" in lowered or "exactly the same" in lowered
    assert "may never add" in lowered


def test_tailoring_prompt_instructs_identity_anchored_change_paths():
    rendered = _render()
    assert 'projects["Inventory Tracker"].bullets[0]' in rendered
    assert "field_changed" in rendered
    assert "rationale" in rendered


def test_tailoring_prompt_embeds_all_three_input_documents():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render(
        "tailoring_rewrite", "v1",
        resume_json='{"skills": ["Python"]}',
        job_posting_json='{"title": "Backend Engineer"}',
        gap_analysis_json='{"missing_skills": ["Docker"]}',
    )
    assert '{"skills": ["Python"]}' in rendered
    assert '{"title": "Backend Engineer"}' in rendered
    assert '{"missing_skills": ["Docker"]}' in rendered
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_tailoring_prompt.py -v` (from `backend/`)
Expected: FAIL — `jinja2.exceptions.TemplateNotFound: tailoring_rewrite/v1.jinja2`

- [ ] **Step 3: Write the prompt template**

`backend/prompts/tailoring_rewrite/v1.jinja2`:

```
You are tailoring a candidate's resume for a specific job posting, using a
prior gap analysis that identifies matching skills, missing skills, relevant
projects, and recommended keywords. Your job is to reword and reorder the
resume to better highlight genuinely-true, already-present content - never to
invent new content.

CRITICAL RULE - No Fabricated Metrics: Never invent a number, percentage, or
metric that is not already stated in the original resume below. For example:

Original bullet: "Worked on backend services for the payments team"
WRONG tailored bullet: "Improved payments processing performance by 40%"
  (the 40% figure does not appear anywhere in the original resume - this is
  fabrication, even though it sounds plausible)
CORRECT tailored bullet: "Built backend services for the payments team,
  focusing on reliability and scalability"
  (stronger verbs and framing, but no invented number)

CRITICAL RULE - No Unearned Skills: Never add a skill or technology to a
bullet, project, or the top-level skills list unless it already appears
somewhere in the original resume (its skills list, a work experience bullet,
or a project's technologies) OR in the gap analysis's matching_skills. For
example:

Original resume skills: Python, Django
Gap analysis matching_skills: Python
WRONG: adding "Flask" to a tailored bullet or the skills list
  (Flask was never in the original resume or matching_skills - this is an
  unearned skill, even if Django and Flask are related frameworks)
CORRECT: rewording existing Django-related bullets more strongly, without
  introducing Flask

CRITICAL RULE - Never Claim a Missing Skill: The gap analysis's
missing_skills list names skills the candidate does NOT have. NEVER
incorporate a missing_skill into the tailored resume as though the candidate
already possesses it. missing_skills exists to inform what NOT to claim, not
as a checklist of skills to add.

CRITICAL RULE - No Fabricated Projects or Experience: The tailored resume
must contain exactly the same work_experience, projects, education, and
certifications entries as the original - same count, same identity (same
company/title, same project name, same institution). You may reword bullets
within an entry and reorder entries by relevance, but you may never add a
new entry or remove an existing one.

EXPLAINABILITY REQUIREMENT: For every bullet, summary, or other field you
change, you must report the change in the "changes" array with:
- "field_changed": an identity-anchored path, NOT a raw position index, so
  the path stays correct even if you reorder entries. Use this format:
  - work_experience: work_experience["<company> - <title>"].bullets[i]
  - projects: projects["<project name>"].bullets[i]
  - education: education["<institution>"]
  - flat fields: "skills", "certifications", "summary"
  where [i] is the bullet's position in your TAILORED output for that entry.
  Example: projects["Inventory Tracker"].bullets[0]
- "original_text": the original bullet/field text this change is based on
  (or null if this is genuinely new phrasing of an implicit point, not a
  1:1 reword of one prior sentence)
- "tailored_text": your rewritten text
- "rationale": why you made this change - which gap or recommended keyword
  it addresses, or why you reordered an entry

Output ONLY a single JSON object matching exactly this shape (no markdown
code fences, no explanation, no extra text before or after the JSON):

{
  "schema_version": 1,
  "tailored_resume": {
    "schema_version": 1,
    "contact": {"full_name": "string", "email": "string or null", "phone": "string or null", "location": "string or null", "links": ["array of strings, may be empty"]},
    "summary": "string or null",
    "work_experience": [{"company": "string", "title": "string", "start_date": "string or null", "end_date": "string or null", "bullets": ["array of strings"]}],
    "projects": [{"name": "string", "description": "string or null", "bullets": ["array of strings"], "technologies": ["array of strings"]}],
    "skills": ["array of strings"],
    "education": [{"institution": "string", "degree": "string or null", "field_of_study": "string or null", "start_date": "string or null", "end_date": "string or null"}],
    "certifications": ["array of strings"]
  },
  "changes": [
    {"field_changed": "string, identity-anchored path", "original_text": "string or null", "tailored_text": "string", "rationale": "string"}
  ]
}

Original resume (structured JSON):

{{ resume_json }}

Job posting (structured JSON):

{{ job_posting_json }}

Gap analysis (structured JSON):

{{ gap_analysis_json }}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_tailoring_prompt.py -v`
Expected: 7 passed

- [ ] **Step 5: Run the full suite**

Run: `py -3 -m pytest -q` (from `backend/`)
Expected: 136 passed, 1 skipped (129 after Task 4, + 7 from this task).

- [ ] **Step 6: Commit**

```bash
git add backend/prompts/tailoring_rewrite/v1.jinja2 backend/tests/test_tailoring_prompt.py
git commit -m "feat: add tailoring_rewrite prompt template with anti-fabrication and explainability rules"
```

---

### Task 6: Tailoring Engine service

**Files:**
- Create: `backend/app/services/tailoring_engine.py`
- Test: `backend/tests/test_tailoring_engine.py`

**Interfaces:**
- Consumes: `TailoringSession`, `JobPosting`, `ResumeVersion`, `GapAnalysis`, `TailoringChange` (`app.models.db_models`), `TailoringResult`/`TailoringChangeRecord` (Task 2), `AIOrchestrator`/`TaskConfig`/`OrchestratorError` (existing), `PromptRegistry` (existing), `StageExecutionError` (existing), `base_tailoring_triple` (Task 4, test-only).
- Produces: `tailor_resume(db: Session, session: TailoringSession, orchestrator: AIOrchestrator, prompt_registry: PromptRegistry) -> ResumeVersion`, `TailoringError` (exception, inherits `StageExecutionError`). Consumed by Task 7 (`sessions.py`'s `_run_tailoring`).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_tailoring_engine.py`:

```python
import pytest
from app.core.db import make_engine, make_session_factory
from app.models.db_models import (
    Base, Resume, ResumeVersion, JobPosting, TailoringSession, GapAnalysis, TailoringChange,
)
from app.core.llm.orchestrator import OrchestratorResult, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.resume import ResumeDocument
from app.models.tailoring_result import TailoringResult, TailoringChangeRecord
from app.services.tailoring_engine import tailor_resume, TailoringError
from tests.fixtures.tailoring_fixtures import base_tailoring_triple


class FakeOrchestrator:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.calls = []

    def run(self, task, prompt):
        self.calls.append((task, prompt))
        if self._error is not None:
            raise self._error
        return self._result


def _make_db():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def _make_session_with_all_prerequisites(db, resume_json, job_posting_json, gap_analysis_json):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json=job_posting_json)
    db.add_all([resume, job_posting])
    db.commit()

    original_version = ResumeVersion(
        resume_id=resume.id, version_number=1, resume_json=resume_json, produced_by_stage="resume_parsing",
    )
    db.add(original_version)
    db.commit()

    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    gap_analysis = GapAnalysis(
        session_id=session.id, resume_version_id=original_version.id, job_posting_id=job_posting.id,
        analysis_json=gap_analysis_json,
    )
    db.add(gap_analysis)
    db.commit()

    return session, original_version, job_posting, gap_analysis


def _passing_tailoring_result(resume: ResumeDocument) -> TailoringResult:
    """A tailored result that reorders and rewords nothing - a safe, always-
    passing baseline for tests that aren't specifically exercising a guard."""
    return TailoringResult(
        tailored_resume=resume,
        changes=[
            TailoringChangeRecord(
                field_changed="summary", original_text=resume.summary, tailored_text=resume.summary or "",
                rationale="No change needed for this test scenario.",
            ),
        ],
    )


def test_tailor_resume_persists_tailored_version_and_changes():
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, original_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    result_document = _passing_tailoring_result(resume_doc)
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    tailored_version = tailor_resume(db, session, orchestrator, prompt_registry)

    assert tailored_version.resume_id == session.resume_id
    assert tailored_version.session_id == session.id
    assert tailored_version.produced_by_stage == "tailoring_rewrite"
    assert tailored_version.version_number == 2
    assert db.query(TailoringChange).filter_by(resume_version_id=tailored_version.id).count() == 1


def test_tailor_resume_fails_fast_when_no_original_resume_version_without_calling_orchestrator():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(TailoringError, match="resume_parsing"):
        tailor_resume(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_tailor_resume_fails_fast_when_job_posting_not_extracted_without_calling_orchestrator():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json=None)
    db.add_all([resume, job_posting])
    db.commit()
    original_version = ResumeVersion(
        resume_id=resume.id, version_number=1,
        resume_json={"schema_version": 1, "contact": {"full_name": "Sam"}},
        produced_by_stage="resume_parsing",
    )
    db.add(original_version)
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(TailoringError, match="jd_extraction"):
        tailor_resume(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_tailor_resume_fails_fast_when_gap_analysis_missing_without_calling_orchestrator():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()
    original_version = ResumeVersion(
        resume_id=resume.id, version_number=1,
        resume_json={"schema_version": 1, "contact": {"full_name": "Sam"}},
        produced_by_stage="resume_parsing",
    )
    db.add(original_version)
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(TailoringError, match="gap_analysis"):
        tailor_resume(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_tailor_resume_rejects_unearned_adjacent_skill_and_persists_nothing():
    """Service-layer guard test (spec §4.2, §8): a tailored skill claiming 'Flask'
    when only 'Django' was in the original resume and gap analysis must be
    rejected outright - nothing persisted, not silently filtered."""
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, original_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    tailored_resume = resume_doc.model_copy(deep=True)
    tailored_resume.skills = tailored_resume.skills + ["Flask"]
    result_document = TailoringResult(
        tailored_resume=tailored_resume,
        changes=[
            TailoringChangeRecord(
                field_changed="skills", original_text=None, tailored_text="Flask", rationale="Added Flask.",
            ),
        ],
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(TailoringError, match="Flask"):
        tailor_resume(db, session, orchestrator, prompt_registry)

    assert db.query(ResumeVersion).filter_by(produced_by_stage="tailoring_rewrite").count() == 0
    assert db.query(TailoringChange).count() == 0


def test_tailor_resume_rejects_invented_project_and_persists_nothing():
    """Service-layer guard test (spec §8): a tailored project whose name doesn't
    match any original project is a fabricated entry - the entry-identity
    invariant catches this without needing semantic judgment."""
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, original_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    tailored_resume = resume_doc.model_copy(deep=True)
    tailored_resume.projects[1].name = "Completely Invented Project"
    result_document = TailoringResult(
        tailored_resume=tailored_resume,
        changes=[
            TailoringChangeRecord(
                field_changed='projects["Completely Invented Project"]', original_text=None,
                tailored_text="Completely Invented Project", rationale="Renamed.",
            ),
        ],
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(TailoringError, match="project names"):
        tailor_resume(db, session, orchestrator, prompt_registry)

    assert db.query(ResumeVersion).filter_by(produced_by_stage="tailoring_rewrite").count() == 0
    assert db.query(TailoringChange).count() == 0


def test_tailor_resume_preserves_entry_count_on_passing_run():
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, original_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    result_document = _passing_tailoring_result(resume_doc)
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    tailored_version = tailor_resume(db, session, orchestrator, prompt_registry)

    assert len(tailored_version.resume_json["projects"]) == len(resume_doc.projects)
    assert len(tailored_version.resume_json["work_experience"]) == len(resume_doc.work_experience)


def test_tailor_resume_version_numbering_increments_across_sessions_for_same_resume():
    """Version numbering test (spec §3.2, §8): two sessions tailoring the same
    resume must produce sequential version_numbers (2, then 3), each session_id
    correctly distinguishing which session produced which row."""
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    db.add(resume)
    db.commit()
    original_version = ResumeVersion(
        resume_id=resume.id, version_number=1, resume_json=resume_doc.model_dump(), produced_by_stage="resume_parsing",
    )
    db.add(original_version)
    db.commit()

    job_posting_a = JobPosting(raw_text="placeholder", parsed_json=job_posting_doc.model_dump())
    job_posting_b = JobPosting(raw_text="placeholder", parsed_json=job_posting_doc.model_dump())
    db.add_all([job_posting_a, job_posting_b])
    db.commit()

    session_a = TailoringSession(resume_id=resume.id, job_posting_id=job_posting_a.id, status="created")
    session_b = TailoringSession(resume_id=resume.id, job_posting_id=job_posting_b.id, status="created")
    db.add_all([session_a, session_b])
    db.commit()

    gap_analysis_a = GapAnalysis(
        session_id=session_a.id, resume_version_id=original_version.id, job_posting_id=job_posting_a.id,
        analysis_json=gap_analysis_doc.model_dump(),
    )
    gap_analysis_b = GapAnalysis(
        session_id=session_b.id, resume_version_id=original_version.id, job_posting_id=job_posting_b.id,
        analysis_json=gap_analysis_doc.model_dump(),
    )
    db.add_all([gap_analysis_a, gap_analysis_b])
    db.commit()

    result_document = _passing_tailoring_result(resume_doc)
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    tailored_a = tailor_resume(db, session_a, orchestrator, prompt_registry)
    tailored_b = tailor_resume(db, session_b, orchestrator, prompt_registry)

    assert tailored_a.version_number == 2
    assert tailored_b.version_number == 3
    assert tailored_a.session_id == session_a.id
    assert tailored_b.session_id == session_b.id


def test_tailor_resume_reorder_does_not_misattribute_change_paths():
    """Reorder-misattribution guard test (spec §3.4, §8): reordering the two
    projects in the tailored output must not cause a TailoringChange row to be
    attributed to the wrong project, since field_changed paths are identity-
    anchored (project name), not positional."""
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, original_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    # tailored_resume is an independent deep copy of resume_doc - reordering and
    # mutating ITS OWN project list never touches resume_doc's original objects.
    tailored_resume = resume_doc.model_copy(deep=True)
    tailored_resume.projects = [tailored_resume.projects[1], tailored_resume.projects[0]]
    tailored_resume.projects[0].bullets = ["Rewritten Recipe Finder bullet"]
    tailored_resume.projects[1].bullets = ["Rewritten Inventory Tracker bullet"]

    result_document = TailoringResult(
        tailored_resume=tailored_resume,
        changes=[
            TailoringChangeRecord(
                field_changed='projects["Recipe Finder"].bullets[0]',
                original_text=resume_doc.projects[1].bullets[0],
                tailored_text="Rewritten Recipe Finder bullet",
                rationale="Reworded.",
            ),
            TailoringChangeRecord(
                field_changed='projects["Inventory Tracker"].bullets[0]',
                original_text=resume_doc.projects[0].bullets[0],
                tailored_text="Rewritten Inventory Tracker bullet",
                rationale="Reworded and reordered second since Recipe Finder is more relevant.",
            ),
        ],
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    tailored_version = tailor_resume(db, session, orchestrator, prompt_registry)

    changes = {
        change.field_changed: change.tailored_text
        for change in db.query(TailoringChange).filter_by(resume_version_id=tailored_version.id).all()
    }
    assert changes['projects["Recipe Finder"].bullets[0]'] == "Rewritten Recipe Finder bullet"
    assert changes['projects["Inventory Tracker"].bullets[0]'] == "Rewritten Inventory Tracker bullet"


def test_tailor_resume_re_tailoring_is_independent_fresh_attempt():
    """Re-tailoring-is-independent test (spec §7, §8): running tailor_resume twice
    for the same session must both read from the ORIGINAL resume_parsing version,
    not chain off each other, and get distinct sequential version_numbers."""
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, original_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    result_document = _passing_tailoring_result(resume_doc)
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    first_run = tailor_resume(db, session, orchestrator, prompt_registry)
    second_run = tailor_resume(db, session, orchestrator, prompt_registry)

    assert first_run.version_number == 2
    assert second_run.version_number == 3
    # Both calls rendered a prompt built from the same original resume_json (not
    # from each other's output) - since the source document never changed
    # between calls, both prompts are byte-identical.
    assert orchestrator.calls[0][1] == orchestrator.calls[1][1]


def test_tailor_resume_wraps_orchestrator_error():
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, original_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    orchestrator = FakeOrchestrator(error=OrchestratorError("all providers exhausted"))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(TailoringError):
        tailor_resume(db, session, orchestrator, prompt_registry)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_tailoring_engine.py -v` (from `backend/`)
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.tailoring_engine'`

- [ ] **Step 3: Write the service**

`backend/app/services/tailoring_engine.py`:

```python
import json
from sqlalchemy.orm import Session
from app.core.llm.orchestrator import AIOrchestrator, TaskConfig, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import TailoringSession, JobPosting, ResumeVersion, GapAnalysis, TailoringChange
from app.models.tailoring_result import TailoringResult
from app.services.errors import StageExecutionError

TAILORING_MODEL = "z-ai/glm-5.2"
TAILORING_TEMPERATURE = 0.1


class TailoringError(StageExecutionError):
    """Raised when resume tailoring fails: unmet prerequisite stages, LLM-
    structuring failure, or a fabrication-guard rejection (unearned skill or an
    entry-identity mismatch)."""


def _collect_earned_skills(resume_json: dict, matching_skills: list[str]) -> tuple[set[str], str]:
    """Return (earned_skill_strings, all_bullet_text): the whitelist the
    code-level skills guard checks tailored skills against, and the concatenated
    bullet prose a skill can also be "earned" by appearing in (e.g. "Django"
    mentioned in a sentence but never listed in a dedicated skills/technologies
    field)."""
    earned = set(resume_json.get("skills", []))
    earned.update(matching_skills)
    bullet_text_parts = [
        bullet
        for entry in resume_json.get("work_experience", [])
        for bullet in entry.get("bullets", [])
    ]
    for project in resume_json.get("projects", []):
        earned.update(project.get("technologies", []))
        bullet_text_parts.extend(project.get("bullets", []))
    return earned, " ".join(bullet_text_parts)


def _find_unearned_skill(tailored_resume_json: dict, earned_skills: set[str], bullet_text: str) -> str | None:
    candidates = list(tailored_resume_json.get("skills", []))
    for project in tailored_resume_json.get("projects", []):
        candidates.extend(project.get("technologies", []))
    for skill in candidates:
        if skill in earned_skills or skill in bullet_text:
            continue
        return skill
    return None


def _validate_entries_preserved(original_resume_json: dict, tailored_resume_json: dict) -> None:
    for key in ("work_experience", "projects", "education", "certifications"):
        original_list = original_resume_json.get(key, [])
        tailored_list = tailored_resume_json.get(key, [])
        if len(original_list) != len(tailored_list):
            raise TailoringError(
                f"tailored resume changed the number of {key} entries "
                f"({len(original_list)} -> {len(tailored_list)}); entries may be reworded/reordered "
                f"but never added or removed"
            )

    original_project_names = {project["name"] for project in original_resume_json.get("projects", [])}
    tailored_project_names = {project["name"] for project in tailored_resume_json.get("projects", [])}
    if tailored_project_names != original_project_names:
        raise TailoringError(
            f"tailored resume's project names do not match the original: "
            f"expected {sorted(original_project_names)}, got {sorted(tailored_project_names)}"
        )

    original_experience_keys = {
        (entry["company"], entry["title"]) for entry in original_resume_json.get("work_experience", [])
    }
    tailored_experience_keys = {
        (entry["company"], entry["title"]) for entry in tailored_resume_json.get("work_experience", [])
    }
    if tailored_experience_keys != original_experience_keys:
        raise TailoringError(
            f"tailored resume's work experience entries do not match the original: "
            f"expected {sorted(original_experience_keys)}, got {sorted(tailored_experience_keys)}"
        )

    original_institutions = {entry["institution"] for entry in original_resume_json.get("education", [])}
    tailored_institutions = {entry["institution"] for entry in tailored_resume_json.get("education", [])}
    if tailored_institutions != original_institutions:
        raise TailoringError(
            f"tailored resume's education entries do not match the original: "
            f"expected {sorted(original_institutions)}, got {sorted(tailored_institutions)}"
        )


def _next_version_number(db: Session, resume_id: int) -> int:
    latest = (
        db.query(ResumeVersion)
        .filter_by(resume_id=resume_id)
        .order_by(ResumeVersion.version_number.desc())
        .first()
    )
    return (latest.version_number if latest else 0) + 1


def tailor_resume(
    db: Session,
    session: TailoringSession,
    orchestrator: AIOrchestrator,
    prompt_registry: PromptRegistry,
) -> ResumeVersion:
    original_version = (
        db.query(ResumeVersion)
        .filter_by(resume_id=session.resume_id, produced_by_stage="resume_parsing")
        .order_by(ResumeVersion.id.desc())
        .first()
    )
    if original_version is None:
        raise TailoringError("resume_parsing has not succeeded for this session yet")

    job_posting = db.get(JobPosting, session.job_posting_id)
    if job_posting is None or job_posting.parsed_json is None:
        raise TailoringError("jd_extraction has not succeeded for this session yet")

    gap_analysis = (
        db.query(GapAnalysis)
        .filter_by(session_id=session.id)
        .order_by(GapAnalysis.id.desc())
        .first()
    )
    if gap_analysis is None:
        raise TailoringError("gap_analysis has not succeeded for this session yet")

    prompt = prompt_registry.render(
        "tailoring_rewrite", "v1",
        resume_json=json.dumps(original_version.resume_json, indent=2),
        job_posting_json=json.dumps(job_posting.parsed_json, indent=2),
        gap_analysis_json=json.dumps(gap_analysis.analysis_json, indent=2),
    )
    task = TaskConfig(
        task_type="tailoring_rewrite",
        provider="nvidia",
        model=TAILORING_MODEL,
        temperature=TAILORING_TEMPERATURE,
        response_schema=TailoringResult,
        fallback_providers=[],
    )

    try:
        result = orchestrator.run(task, prompt=prompt)
    except OrchestratorError as exc:
        raise TailoringError(str(exc)) from exc

    tailored_resume_json = result.output.tailored_resume.model_dump()

    _validate_entries_preserved(original_version.resume_json, tailored_resume_json)

    earned_skills, bullet_text = _collect_earned_skills(
        original_version.resume_json, gap_analysis.analysis_json.get("matching_skills", [])
    )
    unearned_skill = _find_unearned_skill(tailored_resume_json, earned_skills, bullet_text)
    if unearned_skill is not None:
        raise TailoringError(
            f"tailored resume includes an unearned skill not present in the original resume "
            f"or gap analysis matching_skills: {unearned_skill!r}"
        )

    version_number = _next_version_number(db, session.resume_id)
    tailored_version = ResumeVersion(
        resume_id=session.resume_id,
        session_id=session.id,
        version_number=version_number,
        resume_json=tailored_resume_json,
        produced_by_stage="tailoring_rewrite",
    )
    db.add(tailored_version)
    db.flush()

    for change in result.output.changes:
        db.add(TailoringChange(
            resume_version_id=tailored_version.id,
            field_changed=change.field_changed,
            original_text=change.original_text,
            tailored_text=change.tailored_text,
            rationale=change.rationale,
        ))

    db.commit()
    db.refresh(tailored_version)
    return tailored_version
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_tailoring_engine.py -v`
Expected: 11 passed

- [ ] **Step 5: Run the full suite**

Run: `py -3 -m pytest -q` (from `backend/`)
Expected: 147 passed, 1 skipped (136 after Task 5, + 11 from this task).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/tailoring_engine.py backend/tests/test_tailoring_engine.py
git commit -m "feat: add tailoring engine service with three-prerequisite guard and fabrication guards"
```

---

### Task 7: Wire `tailoring_rewrite` into `run_stage`

**Files:**
- Modify: `backend/app/api/sessions.py`
- Modify: `backend/tests/test_api_sessions.py`

**Interfaces:**
- Consumes: `tailor_resume` (Task 6), `STAGE_RUNNERS`/`STAGE_TIMEOUT_SECONDS`/`run_stage` (existing, `app.api.sessions`).
- Produces: `STAGE_RUNNERS["tailoring_rewrite"]` entry; `POST /sessions/{id}/run-stage/tailoring_rewrite` returns `{"stage_name": "tailoring_rewrite", "status": "succeeded", "resume_version_id": <int>}` on success.

- [ ] **Step 1: Update the stale 501 test and add the new tailoring_rewrite tests**

In `backend/tests/test_api_sessions.py`, change `test_run_stage_returns_501_for_unimplemented_stage` (which currently posts to `tailoring_rewrite`, now implemented for real) to target a genuinely-still-unimplemented stage name:

```python
def test_run_stage_returns_501_for_unimplemented_stage(client, db_session):
    resume = Resume(original_filename="jane.pdf", storage_path="/tmp/jane.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    response = client.post(f"/sessions/{session_id}/run-stage/evaluation")

    assert response.status_code == 501
```

Add these new tests to the same file:

```python
def test_run_stage_tailoring_rewrite_succeeds(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(
        source_url="https://example.com/job", raw_text="Barista at Corner Cafe.",
        parsed_json={"title": "Barista"},
    )
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    class FakeResumeVersion:
        def __init__(self, id):
            self.id = id

    def fake_tailor_resume(db, session, orchestrator, prompt_registry):
        return FakeResumeVersion(id=11)

    monkeypatch.setattr(sessions_module, "tailor_resume", fake_tailor_resume)

    response = client.post(f"/sessions/{session_id}/run-stage/tailoring_rewrite")

    assert response.status_code == 200
    assert response.json() == {"stage_name": "tailoring_rewrite", "status": "succeeded", "resume_version_id": 11}

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert len(runs) == 1
    assert runs[0]["stage_name"] == "tailoring_rewrite"
    assert runs[0]["status"] == "succeeded"


def test_run_stage_tailoring_rewrite_reports_failure(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module
    from app.services.tailoring_engine import TailoringError

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def failing_tailor_resume(db, session, orchestrator, prompt_registry):
        raise TailoringError("resume_parsing has not succeeded for this session yet")

    monkeypatch.setattr(sessions_module, "tailor_resume", failing_tailor_resume)

    response = client.post(f"/sessions/{session_id}/run-stage/tailoring_rewrite")

    assert response.status_code == 422

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert runs[0]["status"] == "failed"


def test_run_stage_tailoring_rewrite_times_out(client, db_session, monkeypatch):
    import time
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job", parsed_json={"title": "Barista"})
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    class FakeResumeVersion:
        def __init__(self, id):
            self.id = id

    def slow_tailor_resume(db, session, orchestrator, prompt_registry):
        time.sleep(0.5)
        return FakeResumeVersion(id=1)

    monkeypatch.setattr(sessions_module, "tailor_resume", slow_tailor_resume)
    monkeypatch.setattr(sessions_module, "STAGE_TIMEOUT_SECONDS", 0.05)

    response = client.post(f"/sessions/{session_id}/run-stage/tailoring_rewrite")

    assert response.status_code == 504

    # See test_run_stage_resume_parsing_times_out_uses_captured_run_id_not_stale_object
    # for why this expire_all() is needed: the `client` fixture hands every request
    # the same `db_session` object, and the timeout branch commits the failure
    # through a separate `fresh_db` session.
    db_session.expire_all()
    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert runs[0]["status"] == "failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_api_sessions.py -v` (from `backend/`)
Expected: the 3 new tests FAIL with 501 responses (`tailoring_rewrite` not yet in `STAGE_RUNNERS`); the updated 501 test passes already (it doesn't depend on new code).

- [ ] **Step 3: Wire `tailoring_rewrite` into `sessions.py`**

In `backend/app/api/sessions.py`, add an import alongside the existing service imports:

```python
from app.services.tailoring_engine import tailor_resume
```

Add a new dispatcher function after `_run_gap_analysis` and before the `STAGE_RUNNERS` dict:

```python
def _run_tailoring(db: Session, session: TailoringSession, settings) -> dict:
    orchestrator = build_orchestrator(db, session_id=session.id)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)
    tailored_version = tailor_resume(db, session, orchestrator, prompt_registry)
    return {"resume_version_id": tailored_version.id}
```

Update the `STAGE_RUNNERS` dict:

```python
STAGE_RUNNERS = {
    "resume_parsing": _run_resume_parsing,
    "jd_extraction": _run_jd_extraction,
    "gap_analysis": _run_gap_analysis,
    "tailoring_rewrite": _run_tailoring,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_api_sessions.py -v`
Expected: all tests in this file pass (14 pre-existing + 3 new = 17 passed)

- [ ] **Step 5: Run the full suite**

Run: `py -3 -m pytest -q` (from `backend/`)
Expected: 150 passed, 1 skipped (147 after Task 6, + 3 from this task).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/sessions.py backend/tests/test_api_sessions.py
git commit -m "feat: wire tailoring_rewrite into run_stage via STAGE_RUNNERS"
```

---

### Task 8: Manual smoke-test script

**Files:**
- Create: `backend/scripts/smoke_test_tailoring.py`

**Interfaces:**
- Consumes: everything from Tasks 1-7. Not run by pytest — manual verification only, costs a real NVIDIA API call. This is the sole place real-model compliance with the prompt-only-enforced guardrails (no fabricated metrics, no missing-skill-claimed-as-possessed — spec §4.3, §8) actually gets observed by a human.

- [ ] **Step 1: Write the script**

`backend/scripts/smoke_test_tailoring.py`:

```python
"""Manual smoke test: run with `python scripts/smoke_test_tailoring.py` after
setting NVIDIA_API_KEY in backend/.env. Costs a real API call - not run by
pytest.

Runs the tailoring engine against the real NVIDIA API using the
base_tailoring_triple fixture, and prints both the tailored ResumeDocument and
the reported changes, so a human can manually verify the model (a) doesn't
fabricate metrics or unearned skills, (b) doesn't claim a missing_skill as
possessed, and (c) provides genuinely useful, honest rationale for its
changes - the automated test suite (which mocks the orchestrator) proves
tailor_resume persists the model's output verbatim and rejects unearned
skills/invented entries, but cannot prove real-model prompt compliance for
the vectors that have no code-level guard (see spec sections 4.3 and 8)."""
import json
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.core.llm.orchestrator_factory import build_orchestrator
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import Base, Resume, ResumeVersion, JobPosting, TailoringSession, GapAnalysis, TailoringChange
from app.services.tailoring_engine import tailor_resume
from tests.fixtures.tailoring_fixtures import base_tailoring_triple

if __name__ == "__main__":
    settings = get_settings()
    if not settings.nvidia_api_key:
        raise SystemExit("Set NVIDIA_API_KEY in backend/.env before running this script.")

    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = make_session_factory(engine)()

    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json=job_posting_doc.model_dump())
    db.add_all([resume, job_posting])
    db.commit()

    original_version = ResumeVersion(
        resume_id=resume.id, version_number=1,
        resume_json=resume_doc.model_dump(), produced_by_stage="resume_parsing",
    )
    db.add(original_version)
    db.commit()

    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    gap_analysis = GapAnalysis(
        session_id=session.id, resume_version_id=original_version.id, job_posting_id=job_posting.id,
        analysis_json=gap_analysis_doc.model_dump(),
    )
    db.add(gap_analysis)
    db.commit()

    orchestrator = build_orchestrator(db, session_id=session.id)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)

    tailored_version = tailor_resume(db, session, orchestrator, prompt_registry)

    print("--- Tailored resume ---")
    print(json.dumps(tailored_version.resume_json, indent=2))

    changes = db.query(TailoringChange).filter_by(resume_version_id=tailored_version.id).all()
    print("--- Changes ---")
    for change in changes:
        print(f"{change.field_changed}: {change.rationale}")
        print(f"  original: {change.original_text}")
        print(f"  tailored: {change.tailored_text}")
```

- [ ] **Step 2: Commit**

```bash
git add backend/scripts/smoke_test_tailoring.py
git commit -m "feat: add manual smoke-test script for tailoring_rewrite"
```

---

## Self-Review

**Spec coverage:**
- §2 (rewrite scope: reword + reorder, never delete) → Task 6 (`_validate_entries_preserved` enforces same-count/same-identity), Task 5 (prompt instructs this explicitly).
- §3.1-3.2 (`session_id` column, global per-resume `version_number`) → Task 3 (schema), Task 6 (`_next_version_number`), tested in Task 6's version-numbering test.
- §3.3-3.4 (`tailoring_changes` table, identity-anchored `field_changed` paths) → Task 3 (table), Task 5 (prompt instructs the exact format), Task 6 (persistence + reorder-misattribution test).
- §4.1-4.2 (prompt guardrails + code-level skills guard, reject-not-strip) → Task 5 (prompt), Task 6 (`_find_unearned_skill` + rejection test asserting nothing persisted).
- §4.3 (no code-level metric guard, documented residual risk) → Task 5 (prompt-only instruction), Task 5's fabricated-metrics test explicitly framed as prompt-quality, not service-layer.
- §5 (`TailoringResult`/`TailoringChangeRecord` response schema) → Task 2.
- §6 (three-prerequisite dependency guard, distinct messages, orchestrator config) → Task 6.
- §7 (re-tailoring always sources from `produced_by_stage="resume_parsing"`, fresh independent attempt) → Task 6 (`filter_by(produced_by_stage="resume_parsing")` structurally enforces this) + its own test.
- §8 (all named test scenarios: fabricated metric, missing-skill-claimed, invented project, unearned adjacent skill, dependency guards, entry-count, reorder-misattribution, version-numbering, re-tailoring-independence, wraps-orchestrator-error) → Tasks 5 and 6, mapped one-to-one above.
- §9 (API integration, reused timeout mechanism, stale 501 test fix) → Task 7.
- §10 (ledger cleanup, 3 items) → Task 1.
- §11 (out of scope: no score, no deletion, no code-level metric guard, no iterative refinement, no changes to prior stages/timeout/orchestrator) → confirmed no task introduces any of these; Task 7 reuses `STAGE_TIMEOUT_SECONDS`/`ThreadPoolExecutor` verbatim.

**Placeholder scan:** no TBD/TODO markers; every step has complete, runnable code.

**Type consistency:** `tailor_resume(db, session, orchestrator, prompt_registry) -> ResumeVersion` matches exactly between Task 6 (definition), Task 7 (`_run_tailoring` caller), and Task 8 (smoke script caller). `TailoringError` is defined once in Task 6 and imported (not redefined) in Task 7; it inherits `StageExecutionError` so Task 7's existing `except StageExecutionError` clause in `run_stage` catches it without modification. `TailoringResult`/`TailoringChangeRecord` (Task 2) field names (`tailored_resume`, `changes`, `field_changed`, `original_text`, `tailored_text`, `rationale`) are used identically in Task 5's prompt output-shape block and Task 6's persistence logic and test assertions. `base_tailoring_triple() -> tuple[ResumeDocument, JobPostingDocument, GapAnalysisDocument]` (Task 4) signature matches how it's called in Task 6 and Task 8. `ResumeVersion.session_id` and `TailoringChange` (Task 3) fields match exactly what Task 6's `tailor_resume` constructs.

---

**Plan complete and saved to `docs/superpowers/plans/2026-07-07-phase5-tailoring-engine.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
