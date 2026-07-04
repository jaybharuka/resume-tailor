# Phase 4 — AI Analysis (Resume vs. JD Gap Analysis) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compare an already-structured `ResumeDocument` against an already-structured `JobPostingDocument` and produce a qualitative `GapAnalysisDocument` (matching/missing skills, experience gap notes, relevant/irrelevant projects, recommended keywords), persisted in a new `gap_analyses` table and wired into `run_stage` as a third real stage (`gap_analysis`).

**Architecture:** A new `backend/app/services/gap_analyzer.py`, directly parallel to Phase 2/3's `resume_parser.py`/`jd_extractor.py`: look up the session's latest `ResumeVersion` and the `JobPosting.parsed_json`, guard explicitly if either prerequisite stage hasn't succeeded yet, render a new `gap_analysis` prompt with both documents, call the existing `AIOrchestrator`, and persist a new `GapAnalysis` row (not an update-in-place column — each run gets its own row).

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Pydantic, Jinja2 (existing stack — no new dependencies).

## Global Constraints

- `GapAnalysisDocument.schema_version` is the only required field; every other field defaults to an empty list or `None` (spec §3).
- No numeric, percentage, or categorical match/fit score is produced by this phase — that's Phase 6's responsibility (spec §2, §10).
- `matching_skills` may only include explicit or unambiguous synonym/abbreviation matches — never adjacent/related-technology matches (spec §6.1).
- `missing_skills` may only include skills/requirements literally stated in the JD text — never skills the model believes are "generally expected" (spec §6.2, deliberate tradeoff).
- `gap_analyses` gets a new row on every run for the same `resume_version_id`/`job_posting_id` pairing — no dedup, no upsert (spec §4, deliberate).
- Orchestrator call uses `provider="nvidia"`, `model="z-ai/glm-5.2"`, `temperature=0.1`, `fallback_providers=[]` — matching Phase 2/3 exactly (spec §5).
- Reuses the existing `STAGE_TIMEOUT_SECONDS` + `ThreadPoolExecutor` + fresh-session-on-timeout pattern unchanged (spec §7).
- Windows test runner for this repo: `py -3 -m pytest` (not `python -m pytest` or bare `pytest`), run from `backend/`.
- Baseline before Task 1: 92 passed, 1 skipped (Postgres-dependent migration test).

---

### Task 1: Ledger cleanup (3 items from the Phase 2/3 follow-up backlog)

**Files:**
- Modify: `backend/app/core/llm/provider.py`
- Modify: `backend/tests/test_provider.py`
- Modify: `backend/tests/test_pdf_extractor.py`
- Modify: `backend/tests/test_jd_extractor.py`

**Interfaces:**
- Consumes: nothing new — pure cleanup of existing code from Phase 2/3.
- Produces: nothing new — no later task depends on this task's changes.

This task closes 3 of the 8 outstanding follow-up ledger items (spec §9): `strip_json_code_fence`'s single-line-fence bug, `has_extractable_text`'s untested boundary, and an unused `tmp_path` test parameter.

- [ ] **Step 1: Write failing tests reproducing the `strip_json_code_fence` bugs**

Add to `backend/tests/test_provider.py`:

```python
def test_strip_json_code_fence_handles_single_line_fence_with_no_newlines():
    text = '```json{"a": 1}```'
    assert strip_json_code_fence(text) == '{"a": 1}'


def test_strip_json_code_fence_handles_closing_fence_attached_to_content():
    text = '```json\n{"a": 1}```'
    assert strip_json_code_fence(text) == '{"a": 1}'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_provider.py -v` (from `backend/`)
Expected: the two new tests FAIL — the single-line case currently returns `""` (payload dropped entirely), and the attached-closing-fence case currently returns `'{"a": 1}```'` (fence not stripped).

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
Expected: all 6 tests in this file PASS (the 4 pre-existing tests plus the 2 new ones).

- [ ] **Step 5: Add the `has_extractable_text` boundary test**

Add to `backend/tests/test_pdf_extractor.py`:

```python
def test_has_extractable_text_boundary_at_min_length():
    """Coverage-only addition (ledger item, not a bug fix) — MIN_EXTRACTED_TEXT_LENGTH
    is 20; confirm the boundary is inclusive on the low side."""
    assert has_extractable_text("a" * 19) is False
    assert has_extractable_text("a" * 20) is True
    assert has_extractable_text("a" * 21) is True
```

Run: `py -3 -m pytest tests/test_pdf_extractor.py -v`
Expected: PASS immediately — `has_extractable_text`'s existing implementation (`len(text.strip()) >= MIN_EXTRACTED_TEXT_LENGTH`) is already correct; this closes a test-coverage gap, not a bug.

- [ ] **Step 6: Remove the unused `tmp_path` fixture parameter**

In `backend/tests/test_jd_extractor.py`, change:

```python
def test_extract_job_posting_title_fabrication_guard(tmp_path):
```

to:

```python
def test_extract_job_posting_title_fabrication_guard():
```

- [ ] **Step 7: Run the full suite to confirm no regressions**

Run: `py -3 -m pytest -q` (from `backend/`)
Expected: 95 passed, 1 skipped (92 + 3 new tests: 2 from Step 1, 1 from Step 5 — the `tmp_path` change in Step 6 doesn't remove a test, just a parameter).

- [ ] **Step 8: Commit**

```bash
git add backend/app/core/llm/provider.py backend/tests/test_provider.py backend/tests/test_pdf_extractor.py backend/tests/test_jd_extractor.py
git commit -m "fix: strip_json_code_fence single-line/attached-fence handling; close 2 more ledger items"
```

---

### Task 2: Canonical `GapAnalysisDocument` schema

**Files:**
- Create: `backend/app/models/gap_analysis.py`
- Test: `backend/tests/test_gap_analysis_schema.py`

**Interfaces:**
- Produces: `GapAnalysisDocument` (Pydantic model), `CURRENT_GAP_ANALYSIS_SCHEMA_VERSION: int`, `UnsupportedGapAnalysisSchemaVersion` (exception), `migrate_gap_analysis_document(data: dict) -> GapAnalysisDocument`. Consumed by Task 5 (prompt's `response_schema`) and Task 6 (`gap_analyzer.py`).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_gap_analysis_schema.py`:

```python
import pytest
from app.models.gap_analysis import (
    GapAnalysisDocument,
    CURRENT_GAP_ANALYSIS_SCHEMA_VERSION,
    migrate_gap_analysis_document,
    UnsupportedGapAnalysisSchemaVersion,
)


def test_gap_analysis_document_defaults_to_current_schema_version():
    doc = GapAnalysisDocument()
    assert doc.schema_version == CURRENT_GAP_ANALYSIS_SCHEMA_VERSION
    assert doc.matching_skills == []
    assert doc.missing_skills == []
    assert doc.experience_gap_notes is None
    assert doc.relevant_projects == []
    assert doc.irrelevant_projects == []
    assert doc.recommended_keywords == []


def test_gap_analysis_document_roundtrips_through_json():
    doc = GapAnalysisDocument(
        matching_skills=["Python", "PostgreSQL"],
        missing_skills=["Docker", "Kubernetes"],
        experience_gap_notes="JD wants 5+ years; resume shows 3 years.",
        relevant_projects=["Inventory Tracker"],
        irrelevant_projects=["Weekend Recipe App"],
        recommended_keywords=["distributed systems"],
    )
    restored = GapAnalysisDocument.model_validate_json(doc.model_dump_json())
    assert restored == doc


def test_migrate_gap_analysis_document_accepts_current_version():
    raw = {"schema_version": 1, "matching_skills": ["Python"]}
    doc = migrate_gap_analysis_document(raw)
    assert doc.matching_skills == ["Python"]


def test_migrate_gap_analysis_document_rejects_unknown_future_version():
    raw = {"schema_version": 999, "matching_skills": ["Python"]}
    with pytest.raises(UnsupportedGapAnalysisSchemaVersion):
        migrate_gap_analysis_document(raw)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_gap_analysis_schema.py -v` (from `backend/`)
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.gap_analysis'`

- [ ] **Step 3: Write the schema**

`backend/app/models/gap_analysis.py`:

```python
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field

CURRENT_GAP_ANALYSIS_SCHEMA_VERSION = 1


class GapAnalysisDocument(BaseModel):
    schema_version: int = CURRENT_GAP_ANALYSIS_SCHEMA_VERSION
    matching_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    experience_gap_notes: Optional[str] = None
    relevant_projects: list[str] = Field(default_factory=list)
    irrelevant_projects: list[str] = Field(default_factory=list)
    recommended_keywords: list[str] = Field(default_factory=list)


class UnsupportedGapAnalysisSchemaVersion(Exception):
    pass


def migrate_gap_analysis_document(data: dict) -> GapAnalysisDocument:
    """Load a raw analysis_json dict of any known schema_version into the current
    GapAnalysisDocument shape.

    New migrators get registered here the first time schema_version is bumped
    past 1 — mirrors `app/models/resume.py`'s `migrate_resume_document` and
    `app/models/job_posting.py`'s `migrate_job_posting_document`.
    """
    version = data.get("schema_version", CURRENT_GAP_ANALYSIS_SCHEMA_VERSION)
    if version == CURRENT_GAP_ANALYSIS_SCHEMA_VERSION:
        return GapAnalysisDocument.model_validate(data)
    raise UnsupportedGapAnalysisSchemaVersion(
        f"No migrator registered for gap analysis schema_version={version}"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_gap_analysis_schema.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/gap_analysis.py backend/tests/test_gap_analysis_schema.py
git commit -m "feat: add canonical GapAnalysisDocument schema with schema_version"
```

---

### Task 3: `gap_analyses` table (model + migration)

**Files:**
- Modify: `backend/app/models/db_models.py`
- Create: `backend/alembic/versions/0003_gap_analyses_table.py`
- Modify: `backend/tests/test_db_models.py`
- Test: `backend/tests/test_migration_0003_gap_analyses_table.py`

**Interfaces:**
- Consumes: `Base` (from `app.models.db_models`, already exists).
- Produces: `GapAnalysis` ORM class (`app.models.db_models.GapAnalysis`) with columns `id`, `session_id`, `resume_version_id`, `job_posting_id`, `analysis_json`, `created_at`. Consumed by Task 6 (`gap_analyzer.py` constructs and persists instances of this class).

- [ ] **Step 1: Write the failing test for the ORM model**

Replace the entire contents of `backend/tests/test_db_models.py` with:

```python
import pytest
from sqlalchemy.exc import IntegrityError

from app.core.db import make_engine, make_session_factory
from app.models.db_models import (
    Base, Resume, ResumeVersion, JobPosting, TailoringSession,
    PipelineRun, EvaluationRun, GeneratedDocument, PromptVersion, LLMCall, GapAnalysis,
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

        llm_call = LLMCall(
            session_id=session.id, prompt_version_id=prompt_version.id,
            provider="gemini", model="gemini-1.5-flash", task_type="tailoring_rewrite",
            temperature=0.7, request_payload={"prompt": "hi"}, response_payload={"text": "hello"},
            validated=True, latency_ms=250,
        )
        db.add(llm_call)
        db.commit()

        assert db.query(Resume).count() == 1
        assert db.query(LLMCall).count() == 1
        assert db.query(EvaluationRun).first().overall_score == 85.0
        assert db.query(GapAnalysis).first().analysis_json["matching_skills"] == ["Python"]


def test_deleting_a_session_cascades_to_its_dependent_rows():
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

        llm_call = LLMCall(
            session_id=session.id, prompt_version_id=prompt_version.id,
            provider="gemini", model="gemini-1.5-flash", task_type="tailoring_rewrite",
            temperature=0.7, request_payload={"prompt": "hi"}, response_payload={"text": "hello"},
            validated=True, latency_ms=250,
        )
        db.add(llm_call)
        db.commit()

        session_id = session.id
        resume_id = resume.id
        job_id = job.id
        version_id = version.id
        prompt_version_id = prompt_version.id

        db.delete(session)
        db.commit()

    with SessionFactory() as db:
        assert db.query(PipelineRun).filter_by(session_id=session_id).count() == 0
        assert db.query(EvaluationRun).filter_by(session_id=session_id).count() == 0
        assert db.query(GeneratedDocument).filter_by(session_id=session_id).count() == 0
        assert db.query(LLMCall).filter_by(session_id=session_id).count() == 0
        assert db.query(GapAnalysis).filter_by(session_id=session_id).count() == 0

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
Expected: FAIL with `ImportError: cannot import name 'GapAnalysis' from 'app.models.db_models'`

- [ ] **Step 3: Add the `GapAnalysis` ORM class**

Append to the end of `backend/app/models/db_models.py` (after the `LLMCall` class):

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

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_db_models.py -v`
Expected: 4 passed

- [ ] **Step 5: Write the Alembic migration**

`backend/alembic/versions/0003_gap_analyses_table.py`:

```python
"""gap_analyses table

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-06

"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "gap_analyses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("tailoring_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resume_version_id", sa.Integer, sa.ForeignKey("resume_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_posting_id", sa.Integer, sa.ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("analysis_json", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("gap_analyses")
```

- [ ] **Step 6: Write the migration test**

`backend/tests/test_migration_0003_gap_analyses_table.py`:

```python
"""Migration test for 0003 (gap_analyses table): confirms upgrade() creates the
table and downgrade() cleanly reverses it. Unlike migration 0002
(test_migration_data_preservation.py), this migration is a plain CREATE TABLE
with foreign keys declared inline - fully supported by SQLite outside batch
mode, so no Postgres/data-preservation concern applies here."""
import importlib.util
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"
MIGRATION_0001_PATH = VERSIONS_DIR / "0001_initial_schema.py"
MIGRATION_0002_PATH = VERSIONS_DIR / "0002_prompt_version_unique_and_llm_calls_restrict.py"
MIGRATION_0003_PATH = VERSIONS_DIR / "0003_gap_analyses_table.py"


def _load_migration(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_0003_creates_and_drops_gap_analyses_table():
    migration_0001 = _load_migration(MIGRATION_0001_PATH, "migration_0001_for_0003_test")
    migration_0002 = _load_migration(MIGRATION_0002_PATH, "migration_0002_for_0003_test")
    migration_0003 = _load_migration(MIGRATION_0003_PATH, "migration_0003_under_test")

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))

        migration_context = MigrationContext.configure(connection)
        with Operations.context(migration_context):
            migration_0001.upgrade()
            migration_0002.upgrade()
        connection.commit()

        assert "gap_analyses" not in inspect(engine).get_table_names()

        migration_context = MigrationContext.configure(connection)
        with Operations.context(migration_context):
            migration_0003.upgrade()
        connection.commit()

        assert "gap_analyses" in inspect(engine).get_table_names()

        migration_context = MigrationContext.configure(connection)
        with Operations.context(migration_context):
            migration_0003.downgrade()
        connection.commit()

        assert "gap_analyses" not in inspect(engine).get_table_names()
```

- [ ] **Step 7: Run the new migration test**

Run: `py -3 -m pytest tests/test_migration_0003_gap_analyses_table.py -v`
Expected: 1 passed

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/db_models.py backend/alembic/versions/0003_gap_analyses_table.py backend/tests/test_db_models.py backend/tests/test_migration_0003_gap_analyses_table.py
git commit -m "feat: add gap_analyses table (model + migration)"
```

---

### Task 4: Synthetic resume/JD fixture pairs

**Files:**
- Create: `backend/tests/fixtures/gap_analysis_fixtures.py`
- Test: `backend/tests/test_gap_analysis_fixtures.py`

**Interfaces:**
- Consumes: `ResumeDocument`, `ContactInfo`, `WorkExperience` (from `app.models.resume`), `JobPostingDocument` (from `app.models.job_posting`) — both already exist.
- Produces: `clean_missing_skills_pair() -> tuple[ResumeDocument, JobPostingDocument]`, `adjacent_not_matching_pair() -> tuple[ResumeDocument, JobPostingDocument]`, `synonym_matching_pair() -> tuple[ResumeDocument, JobPostingDocument]`. Consumed by Task 6 (`test_gap_analyzer.py`) and Task 8 (smoke script).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_gap_analysis_fixtures.py`:

```python
from tests.fixtures.gap_analysis_fixtures import (
    clean_missing_skills_pair, adjacent_not_matching_pair, synonym_matching_pair,
)


def test_clean_missing_skills_pair_has_no_overlap_between_resume_skills_and_jd_requirements():
    resume, job_posting = clean_missing_skills_pair()
    assert "Docker" not in resume.skills
    assert "Kubernetes" not in resume.skills
    assert "Docker" in job_posting.requirements
    assert "Kubernetes" in job_posting.requirements


def test_adjacent_not_matching_pair_has_different_frameworks_on_each_side():
    resume, job_posting = adjacent_not_matching_pair()
    assert "Django" in resume.skills
    assert "Flask" not in resume.skills
    assert "Flask" in job_posting.requirements


def test_synonym_matching_pair_has_genuine_abbreviation_relationship():
    resume, job_posting = synonym_matching_pair()
    assert "JavaScript" in resume.skills
    assert "JS" in job_posting.requirements
    assert "JS" not in resume.skills
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_gap_analysis_fixtures.py -v` (from `backend/`)
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.fixtures.gap_analysis_fixtures'`

- [ ] **Step 3: Write the fixtures**

`backend/tests/fixtures/gap_analysis_fixtures.py`:

```python
"""Synthetic resume/JD pairs for gap-analysis tests. All names, companies, and
content below are fabricated placeholders - not real resumes or job postings."""
from app.models.resume import ResumeDocument, ContactInfo, WorkExperience
from app.models.job_posting import JobPostingDocument


def clean_missing_skills_pair() -> tuple[ResumeDocument, JobPostingDocument]:
    """Resume skilled in Python/Django/PostgreSQL vs. a JD requiring Docker/Kubernetes -
    a straightforward, unambiguous missing-skills case."""
    resume = ResumeDocument(
        contact=ContactInfo(full_name="Jordan Kim"),
        work_experience=[
            WorkExperience(
                company="Startup Co", title="Backend Engineer", start_date="2021", end_date="2024",
                bullets=["Built REST APIs in Python and Django backed by PostgreSQL"],
            ),
        ],
        skills=["Python", "Django", "PostgreSQL"],
    )
    job_posting = JobPostingDocument(
        title="Platform Engineer",
        requirements=["Docker", "Kubernetes", "CI/CD pipeline experience"],
    )
    return resume, job_posting


def adjacent_not_matching_pair() -> tuple[ResumeDocument, JobPostingDocument]:
    """Resume with Django experience vs. a JD requiring Flask - two different Python web
    frameworks. Exercises the strict-match guard: Django must NOT be counted as
    satisfying the Flask requirement."""
    resume = ResumeDocument(
        contact=ContactInfo(full_name="Sam Rivera"),
        work_experience=[
            WorkExperience(
                company="Widget LLC", title="Backend Developer", start_date="2020", end_date="2024",
                bullets=["Built and maintained Django web applications"],
            ),
        ],
        skills=["Python", "Django"],
    )
    job_posting = JobPostingDocument(
        title="Backend Developer",
        requirements=["Flask", "3+ years Python experience"],
    )
    return resume, job_posting


def synonym_matching_pair() -> tuple[ResumeDocument, JobPostingDocument]:
    """Resume lists 'JavaScript' vs. a JD requiring 'JS' - an unambiguous abbreviation.
    Exercises the reverse of the strict-match guard: the synonym must be correctly
    counted as a match, not treated as missing."""
    resume = ResumeDocument(
        contact=ContactInfo(full_name="Alex Chen"),
        work_experience=[
            WorkExperience(
                company="Acme Corp", title="Frontend Engineer", start_date="2019", end_date="2024",
                bullets=["Built interactive UIs using JavaScript and React"],
            ),
        ],
        skills=["JavaScript", "React"],
    )
    job_posting = JobPostingDocument(
        title="Frontend Engineer",
        requirements=["JS", "React", "2+ years frontend experience"],
    )
    return resume, job_posting
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_gap_analysis_fixtures.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/tests/fixtures/gap_analysis_fixtures.py backend/tests/test_gap_analysis_fixtures.py
git commit -m "feat: add synthetic resume/JD fixture pairs for gap-analysis tests"
```

---

### Task 5: `gap_analysis` prompt template

**Files:**
- Create: `backend/prompts/gap_analysis/v1.jinja2`
- Test: `backend/tests/test_gap_analysis_prompt.py`

**Interfaces:**
- Consumes: `PromptRegistry.render(task_type, version, **context)` (already exists) — context keys `resume_json: str`, `job_posting_json: str` (pre-serialized JSON text, not raw dicts).
- Produces: the rendered prompt text, consumed by Task 6 (`gap_analyzer.py`'s `orchestrator.run(task, prompt=prompt)` call).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_gap_analysis_prompt.py`:

```python
from app.core.llm.prompt_registry import PromptRegistry
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, PromptVersion


def test_gap_analysis_prompt_registers_via_sync_to_db():
    registry = PromptRegistry(prompts_root="prompts")
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        registry.sync_to_db(db)
        row = db.query(PromptVersion).filter_by(task_type="gap_analysis", version="v1").one()
        assert row.template_path == "gap_analysis/v1.jinja2"


def test_gap_analysis_prompt_instructs_strict_matching_with_adjacent_example():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render("gap_analysis", "v1", resume_json="{}", job_posting_json="{}")
    lowered = rendered.lower()
    assert "django" in lowered and "flask" in lowered
    assert "not a match" in lowered or "not_a_match" in lowered or "not match" in lowered


def test_gap_analysis_prompt_embeds_synonym_worked_example():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render("gap_analysis", "v1", resume_json="{}", job_posting_json="{}")
    lowered = rendered.lower()
    assert "javascript" in lowered
    assert "abbreviation" in lowered or "synonym" in lowered


def test_gap_analysis_prompt_instructs_missing_skills_subset_rule():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render("gap_analysis", "v1", resume_json="{}", job_posting_json="{}")
    lowered = rendered.lower()
    assert "generally expected" in lowered
    assert "literally" in lowered


def test_gap_analysis_prompt_embeds_both_documents():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render(
        "gap_analysis", "v1",
        resume_json='{"skills": ["Python"]}',
        job_posting_json='{"title": "Backend Engineer"}',
    )
    assert '{"skills": ["Python"]}' in rendered
    assert '{"title": "Backend Engineer"}' in rendered
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_gap_analysis_prompt.py -v` (from `backend/`)
Expected: FAIL — `jinja2.exceptions.TemplateNotFound: gap_analysis/v1.jinja2`

- [ ] **Step 3: Write the prompt template**

`backend/prompts/gap_analysis/v1.jinja2`:

```
You are comparing a candidate's resume against a job posting to produce a
gap analysis: what skills match, what's missing, experience gaps, which
projects are relevant, and recommended keywords. Your job is to compare what
is already present in both documents below - do not fabricate resume or
job-posting content that isn't present in the data given to you.

CRITICAL RULE - Matching Skills: A skill counts as "matching" ONLY if:
(a) it is stated explicitly in the resume, OR
(b) it is an unambiguous synonym or abbreviation of a JD-required skill
    (e.g. "JS" <-> "JavaScript", "k8s" <-> "Kubernetes").

NEVER count a skill as matching based on a related or adjacent technology.
For example:

Resume lists: Django
JD requires: Flask
-> Flask is NOT a match. Django and Flask are different frameworks, even
   though both are Python web frameworks. Flask belongs in missing_skills,
   not matching_skills.

Resume lists: JavaScript
JD requires: JS
-> JS IS a match. "JS" is a standard abbreviation of "JavaScript", not a
   different or adjacent skill. JavaScript belongs in matching_skills, and
   JS must NOT also appear in missing_skills.

CRITICAL RULE - Missing Skills: missing_skills must ONLY contain skills or
requirements that are literally stated in the job posting text below. NEVER
add a skill you believe is "generally expected" for this type of role if the
job posting text doesn't mention it. It is always better to under-report a
gap than to invent one that isn't actually written in the job posting.

Output ONLY a single JSON object matching exactly this shape (no markdown
code fences, no explanation, no extra text before or after the JSON):

{
  "schema_version": 1,
  "matching_skills": ["array of strings, may be empty"],
  "missing_skills": ["array of strings, may be empty"],
  "experience_gap_notes": "string or null",
  "relevant_projects": ["array of strings, may be empty"],
  "irrelevant_projects": ["array of strings, may be empty"],
  "recommended_keywords": ["array of strings, may be empty"]
}

Resume (structured JSON):

{{ resume_json }}

Job posting (structured JSON):

{{ job_posting_json }}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_gap_analysis_prompt.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/prompts/gap_analysis/v1.jinja2 backend/tests/test_gap_analysis_prompt.py
git commit -m "feat: add gap_analysis prompt template with strict-match anti-generosity rules"
```

---

### Task 6: Gap Analyzer service

**Files:**
- Create: `backend/app/services/gap_analyzer.py`
- Test: `backend/tests/test_gap_analyzer.py`

**Interfaces:**
- Consumes: `TailoringSession`, `JobPosting`, `ResumeVersion`, `GapAnalysis` (from `app.models.db_models`), `GapAnalysisDocument` (Task 2), `AIOrchestrator`/`TaskConfig`/`OrchestratorError` (existing), `PromptRegistry` (existing), `StageExecutionError` (existing, `app.services.errors`), `clean_missing_skills_pair`/`adjacent_not_matching_pair`/`synonym_matching_pair` (Task 4, test-only).
- Produces: `analyze_gap(db: Session, session: TailoringSession, orchestrator: AIOrchestrator, prompt_registry: PromptRegistry) -> GapAnalysis`, `GapAnalysisError` (exception, inherits `StageExecutionError`). Consumed by Task 7 (`sessions.py`'s `_run_gap_analysis`).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_gap_analyzer.py`:

```python
import pytest
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, Resume, ResumeVersion, JobPosting, TailoringSession
from app.core.llm.orchestrator import OrchestratorResult, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.gap_analysis import GapAnalysisDocument
from app.services.gap_analyzer import analyze_gap, GapAnalysisError
from tests.fixtures.gap_analysis_fixtures import adjacent_not_matching_pair, synonym_matching_pair


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


def _make_session_with_resume_version_and_parsed_job_posting(db, resume_json, job_posting_json):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json=job_posting_json)
    db.add_all([resume, job_posting])
    db.commit()

    resume_version = ResumeVersion(
        resume_id=resume.id, version_number=1, resume_json=resume_json, produced_by_stage="resume_parsing",
    )
    db.add(resume_version)
    db.commit()

    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()
    return session, resume_version, job_posting


def test_analyze_gap_persists_analysis_json_and_links_ids():
    db = _make_db()
    resume_doc, job_posting_doc = adjacent_not_matching_pair()
    session, resume_version, job_posting = _make_session_with_resume_version_and_parsed_job_posting(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(),
    )

    result_document = GapAnalysisDocument(matching_skills=["Python"], missing_skills=["Flask"])
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    analysis = analyze_gap(db, session, orchestrator, prompt_registry)

    assert analysis.session_id == session.id
    assert analysis.resume_version_id == resume_version.id
    assert analysis.job_posting_id == job_posting.id
    assert analysis.analysis_json["missing_skills"] == ["Flask"]


def test_analyze_gap_fails_fast_when_no_resume_version_without_calling_orchestrator():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Developer"})
    db.add_all([resume, job_posting])
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(GapAnalysisError, match="resume_parsing"):
        analyze_gap(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_analyze_gap_fails_fast_when_job_posting_not_extracted_without_calling_orchestrator():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json=None)
    db.add_all([resume, job_posting])
    db.commit()
    resume_version = ResumeVersion(
        resume_id=resume.id, version_number=1,
        resume_json={"schema_version": 1, "contact": {"full_name": "Sam"}},
        produced_by_stage="resume_parsing",
    )
    db.add(resume_version)
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(GapAnalysisError, match="jd_extraction"):
        analyze_gap(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_analyze_gap_adjacent_skill_guard_does_not_count_django_as_flask_match():
    """Strict-match guard (spec §6.1): Django does not satisfy a Flask requirement -
    persisted output must reflect Flask as missing, not matching, byte-for-byte
    against whatever the orchestrator returned."""
    db = _make_db()
    resume_doc, job_posting_doc = adjacent_not_matching_pair()
    session, _, _ = _make_session_with_resume_version_and_parsed_job_posting(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(),
    )

    result_document = GapAnalysisDocument(matching_skills=["Python"], missing_skills=["Flask"])
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    analysis = analyze_gap(db, session, orchestrator, prompt_registry)

    assert analysis.analysis_json["missing_skills"] == ["Flask"]
    assert "Flask" not in analysis.analysis_json["matching_skills"]


def test_analyze_gap_synonym_match_guard_counts_js_as_javascript_match():
    """Reverse of the strict-match guard (this plan's addition to spec §6.1): a
    genuine synonym/abbreviation (JS <-> JavaScript) must be counted as a match,
    not treated as missing - proving the strict-match rule isn't overcorrecting
    into false negatives."""
    db = _make_db()
    resume_doc, job_posting_doc = synonym_matching_pair()
    session, _, _ = _make_session_with_resume_version_and_parsed_job_posting(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(),
    )

    result_document = GapAnalysisDocument(matching_skills=["JavaScript", "React"], missing_skills=[])
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    analysis = analyze_gap(db, session, orchestrator, prompt_registry)

    assert "JavaScript" in analysis.analysis_json["matching_skills"]
    assert analysis.analysis_json["missing_skills"] == []


def test_analyze_gap_wraps_orchestrator_error():
    db = _make_db()
    resume_doc, job_posting_doc = adjacent_not_matching_pair()
    session, _, _ = _make_session_with_resume_version_and_parsed_job_posting(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(),
    )

    orchestrator = FakeOrchestrator(error=OrchestratorError("all providers exhausted"))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(GapAnalysisError):
        analyze_gap(db, session, orchestrator, prompt_registry)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_gap_analyzer.py -v` (from `backend/`)
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.gap_analyzer'`

- [ ] **Step 3: Write the service**

`backend/app/services/gap_analyzer.py`:

```python
import json
from sqlalchemy.orm import Session
from app.core.llm.orchestrator import AIOrchestrator, TaskConfig, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import TailoringSession, JobPosting, ResumeVersion, GapAnalysis
from app.models.gap_analysis import GapAnalysisDocument
from app.services.errors import StageExecutionError

GAP_ANALYSIS_MODEL = "z-ai/glm-5.2"
GAP_ANALYSIS_TEMPERATURE = 0.1


class GapAnalysisError(StageExecutionError):
    """Raised when gap analysis fails, whether due to unmet prerequisite stages or
    LLM-structuring failure."""


def analyze_gap(
    db: Session,
    session: TailoringSession,
    orchestrator: AIOrchestrator,
    prompt_registry: PromptRegistry,
) -> GapAnalysis:
    resume_version = (
        db.query(ResumeVersion)
        .filter_by(resume_id=session.resume_id)
        .order_by(ResumeVersion.id.desc())
        .first()
    )
    if resume_version is None:
        raise GapAnalysisError("resume_parsing has not succeeded for this session yet")

    job_posting = db.get(JobPosting, session.job_posting_id)
    if job_posting is None or job_posting.parsed_json is None:
        raise GapAnalysisError("jd_extraction has not succeeded for this session yet")

    prompt = prompt_registry.render(
        "gap_analysis", "v1",
        resume_json=json.dumps(resume_version.resume_json, indent=2),
        job_posting_json=json.dumps(job_posting.parsed_json, indent=2),
    )
    task = TaskConfig(
        task_type="gap_analysis",
        provider="nvidia",
        model=GAP_ANALYSIS_MODEL,
        temperature=GAP_ANALYSIS_TEMPERATURE,
        response_schema=GapAnalysisDocument,
        fallback_providers=[],
    )

    try:
        result = orchestrator.run(task, prompt=prompt)
    except OrchestratorError as exc:
        raise GapAnalysisError(str(exc)) from exc

    analysis = GapAnalysis(
        session_id=session.id,
        resume_version_id=resume_version.id,
        job_posting_id=job_posting.id,
        analysis_json=result.output.model_dump(),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_gap_analyzer.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/gap_analyzer.py backend/tests/test_gap_analyzer.py
git commit -m "feat: add gap analyzer service with dependency guard and strict-match fabrication guards"
```

---

### Task 7: Wire `gap_analysis` into `run_stage`

**Files:**
- Modify: `backend/app/api/sessions.py`
- Modify: `backend/tests/test_api_sessions.py`

**Interfaces:**
- Consumes: `analyze_gap` (Task 6), `STAGE_RUNNERS`/`STAGE_TIMEOUT_SECONDS`/`run_stage` (existing, `app.api.sessions`).
- Produces: `STAGE_RUNNERS["gap_analysis"]` entry; `POST /sessions/{id}/run-stage/gap_analysis` returns `{"stage_name": "gap_analysis", "status": "succeeded", "gap_analysis_id": <int>}` on success.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_api_sessions.py`:

```python
def test_run_stage_gap_analysis_succeeds(client, db_session, monkeypatch):
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

    class FakeGapAnalysis:
        def __init__(self, id):
            self.id = id

    def fake_analyze_gap(db, session, orchestrator, prompt_registry):
        return FakeGapAnalysis(id=7)

    monkeypatch.setattr(sessions_module, "analyze_gap", fake_analyze_gap)

    response = client.post(f"/sessions/{session_id}/run-stage/gap_analysis")

    assert response.status_code == 200
    assert response.json() == {"stage_name": "gap_analysis", "status": "succeeded", "gap_analysis_id": 7}

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert len(runs) == 1
    assert runs[0]["stage_name"] == "gap_analysis"
    assert runs[0]["status"] == "succeeded"


def test_run_stage_gap_analysis_reports_failure(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module
    from app.services.gap_analyzer import GapAnalysisError

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def failing_analyze_gap(db, session, orchestrator, prompt_registry):
        raise GapAnalysisError("resume_parsing has not succeeded for this session yet")

    monkeypatch.setattr(sessions_module, "analyze_gap", failing_analyze_gap)

    response = client.post(f"/sessions/{session_id}/run-stage/gap_analysis")

    assert response.status_code == 422

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert runs[0]["status"] == "failed"


def test_run_stage_gap_analysis_times_out(client, db_session, monkeypatch):
    import time
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job", parsed_json={"title": "Barista"})
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    class FakeGapAnalysis:
        def __init__(self, id):
            self.id = id

    def slow_analyze_gap(db, session, orchestrator, prompt_registry):
        time.sleep(0.5)
        return FakeGapAnalysis(id=1)

    monkeypatch.setattr(sessions_module, "analyze_gap", slow_analyze_gap)
    monkeypatch.setattr(sessions_module, "STAGE_TIMEOUT_SECONDS", 0.05)

    response = client.post(f"/sessions/{session_id}/run-stage/gap_analysis")

    assert response.status_code == 504

    # See test_run_stage_resume_parsing_times_out_uses_captured_run_id_not_stale_object
    # for why this expire_all() is needed: the `client` fixture hands every request the
    # same `db_session` object, and the timeout branch commits the failure through a
    # separate `fresh_db` session.
    db_session.expire_all()
    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert runs[0]["status"] == "failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_api_sessions.py -v` (from `backend/`)
Expected: the 3 new tests FAIL with 501 responses (`gap_analysis` not yet in `STAGE_RUNNERS`)

- [ ] **Step 3: Wire `gap_analysis` into `sessions.py`**

In `backend/app/api/sessions.py`, add an import alongside the existing service imports:

```python
from app.services.gap_analyzer import analyze_gap
```

Add a new dispatcher function after `_run_jd_extraction` and before the `STAGE_RUNNERS` dict:

```python
def _run_gap_analysis(db: Session, session: TailoringSession, settings) -> dict:
    orchestrator = build_orchestrator(db, session_id=session.id)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)
    analysis = analyze_gap(db, session, orchestrator, prompt_registry)
    return {"gap_analysis_id": analysis.id}
```

Update the `STAGE_RUNNERS` dict:

```python
STAGE_RUNNERS = {
    "resume_parsing": _run_resume_parsing,
    "jd_extraction": _run_jd_extraction,
    "gap_analysis": _run_gap_analysis,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_api_sessions.py -v`
Expected: all tests in this file pass (11 pre-existing + 3 new = 14 passed)

- [ ] **Step 5: Run the full suite**

Run: `py -3 -m pytest -q` (from `backend/`)
Expected: 117 passed, 1 skipped (95 after Task 1, + 4 from Task 2, + 1 net new from Task 3 — `test_db_models.py`'s rewritten file keeps the same 4-test count, plus 1 new migration test — + 3 from Task 4, + 5 from Task 5, + 6 from Task 6, + 3 from Task 7 = 95+4+1+3+5+6+3 = 117).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/sessions.py backend/tests/test_api_sessions.py
git commit -m "feat: wire gap_analysis into run_stage via STAGE_RUNNERS"
```

---

### Task 8: Manual smoke-test script

**Files:**
- Create: `backend/scripts/smoke_test_gap_analysis.py`

**Interfaces:**
- Consumes: everything from Tasks 1-7. Not run by pytest — manual verification only, costs two real NVIDIA API calls. This is the sole place real-model strict-match behavior (spec §6.1, in both the over-generous and over-strict directions) actually gets observed by a human.

- [ ] **Step 1: Write the script**

`backend/scripts/smoke_test_gap_analysis.py`:

```python
"""Manual smoke test: run with `python scripts/smoke_test_gap_analysis.py`
after setting NVIDIA_API_KEY in backend/.env. Costs two real API calls - not
run by pytest.

Runs gap analysis against the real NVIDIA API for two scenarios where the
strict-match rule (spec §6.1) is most likely to go wrong in either direction:
adjacent_not_matching_pair (Django vs. Flask - must NOT be counted as a match)
and synonym_matching_pair (JavaScript vs. JS - MUST be counted as a match).
The automated test suite (which mocks the orchestrator) proves gap_analyzer.py
persists whatever the model returns verbatim; it cannot prove the real model
actually applies the strict-match rule correctly in both directions - that's
what this script is for."""
import json
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.core.llm.orchestrator_factory import build_orchestrator
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import Base, Resume, ResumeVersion, JobPosting, TailoringSession
from app.services.gap_analyzer import analyze_gap
from tests.fixtures.gap_analysis_fixtures import adjacent_not_matching_pair, synonym_matching_pair


def _run_scenario(db, orchestrator, prompt_registry, label, resume_doc, job_posting_doc):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json=job_posting_doc.model_dump())
    db.add_all([resume, job_posting])
    db.commit()

    resume_version = ResumeVersion(
        resume_id=resume.id, version_number=1,
        resume_json=resume_doc.model_dump(), produced_by_stage="resume_parsing",
    )
    db.add(resume_version)
    db.commit()

    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    print(f"--- {label} ---")
    analysis = analyze_gap(db, session, orchestrator, prompt_registry)
    print(json.dumps(analysis.analysis_json, indent=2))


if __name__ == "__main__":
    settings = get_settings()
    if not settings.nvidia_api_key:
        raise SystemExit("Set NVIDIA_API_KEY in backend/.env before running this script.")

    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = make_session_factory(engine)()

    orchestrator = build_orchestrator(db, session_id=None)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)

    adjacent_resume, adjacent_job = adjacent_not_matching_pair()
    _run_scenario(
        db, orchestrator, prompt_registry,
        "adjacent_not_matching_pair (Django vs. Flask)", adjacent_resume, adjacent_job,
    )

    synonym_resume, synonym_job = synonym_matching_pair()
    _run_scenario(
        db, orchestrator, prompt_registry,
        "synonym_matching_pair (JavaScript vs. JS)", synonym_resume, synonym_job,
    )
```

- [ ] **Step 2: Commit**

```bash
git add backend/scripts/smoke_test_gap_analysis.py
git commit -m "feat: add manual smoke-test script for gap_analysis"
```

---

## Self-Review

**Spec coverage:**
- §2 (scope boundary, no numeric score) → Task 2 (schema has no score field), Task 5 (prompt never asks for one).
- §3 (`GapAnalysisDocument` field list) → Task 2.
- §4 (storage, no dedup) → Task 3 (new table, no unique constraint by design).
- §5 (data flow, dependency guard, error naming) → Task 6.
- §6.1 (strict-match rule + worked examples, both directions) → Task 5 (prompt content + tests), Task 6 (persistence-layer guard tests for both Django/Flask and JS/JavaScript), Task 8 (real-model smoke script for both).
- §6.2 (missing-skills strict subset, deliberate tradeoff) → Task 5 (prompt content + test), documented inline in Task 6's `GapAnalysisError` docstring context.
- §7 (API integration, reuse existing timeout mechanism unchanged) → Task 7.
- §8 (fixture pairs, mocked-provider tests, manual smoke script) → Tasks 4, 6, 8.
- §9 (ledger cleanup) → Task 1.
- §10 (out of scope: no score, no tailoring generation, no implied-requirement inference, no dedup, no changes to resume_parsing/jd_extraction/timeout/orchestrator) → confirmed no task introduces any of these; Task 7 reuses `STAGE_TIMEOUT_SECONDS`/`ThreadPoolExecutor` verbatim rather than modifying it.

**Placeholder scan:** no TBD/TODO markers; every step has complete, runnable code.

**Type consistency:** `analyze_gap(db, session, orchestrator, prompt_registry) -> GapAnalysis` signature matches exactly between Task 6 (definition), Task 7 (`_run_gap_analysis` caller), and Task 8 (smoke script caller). `GapAnalysisError` is defined once in Task 6 and imported (not redefined) in Task 7. `GapAnalysisError` inherits `StageExecutionError` (existing base class), so Task 7's `except StageExecutionError` in `run_stage` catches it without modification. `GapAnalysisDocument` (Task 2) field names (`matching_skills`, `missing_skills`, `experience_gap_notes`, `relevant_projects`, `irrelevant_projects`, `recommended_keywords`) are used identically in Task 5's prompt output-shape block, Task 6's fabrication-guard test assertions, and Task 3's `analysis_json` test payloads. `GapAnalysis` ORM class (Task 3: `session_id`, `resume_version_id`, `job_posting_id`, `analysis_json`, `created_at`) fields match exactly what Task 6's `analyze_gap` constructs. `clean_missing_skills_pair`/`adjacent_not_matching_pair`/`synonym_matching_pair` (Task 4) signatures (`() -> tuple[ResumeDocument, JobPostingDocument]`) match how they're called in Task 6 and Task 8.

---

**Plan complete and saved to `docs/superpowers/plans/2026-07-06-phase4-gap-analysis.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
