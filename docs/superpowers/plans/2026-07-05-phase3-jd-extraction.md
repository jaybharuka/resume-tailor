# Phase 3 JD Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `jd_extraction` stage real — structure pasted job-description text into the canonical `JobPostingDocument` via the existing `AIOrchestrator`, and wire it into `POST /sessions/{id}/run-stage/jd_extraction` alongside the existing `resume_parsing` stage.

**Architecture:** A new `backend/app/services/jd_extractor.py` module (the JD Extractor logical service) mirrors Phase 2's `resume_parser.py` exactly, minus the PDF-extraction step (the text is already pasted). `run_stage` is generalized from a single hardcoded `resume_parsing` branch into a small stage-dispatch table so both stages share the identical timeout/thread-safety mechanism built in Phase 2.

**Tech Stack:** No new dependencies — reuses the existing FastAPI/SQLAlchemy/AIOrchestrator/PromptRegistry stack from Phases 1-2.

## Global Constraints

- Python 3.11+.
- Pasted-text only in this phase — no URL fetching, no headless-browser rendering, no auth-wall handling (all deferred to a future phase).
- **Hard requirement:** the `jd_extraction` prompt must instruct the model to leave fields null/empty rather than fabricate, with the requirements/qualifications tie-breaking rule demonstrated via 1-2 concrete worked examples embedded directly in the prompt template (not just described abstractly).
- `title` is the schema's only required field and therefore the highest fabrication-risk field — the "not a job posting" fixture's test must assert the persisted title matches an honest, non-fabricated placeholder byte-for-byte, not merely that the response validated.
- No `job_posting_versions` table — `JobPosting.parsed_json` is updated in place, a deliberate choice for this phase (see spec §4), not something to "fix" incidentally while doing other work here.
- `run_stage`'s timeout is `STAGE_TIMEOUT_SECONDS = 330` (renamed from Phase 2's `RESUME_PARSING_TIMEOUT_SECONDS` now that it covers two stages) — the existing Phase 2 tests referencing the old name must be updated, not left broken.
- Follow TDD: write the failing test, confirm it fails, implement, confirm it passes, commit.

---

### Task 1: Canonical `JobPostingDocument` schema

**Files:**
- Create: `backend/app/models/job_posting.py`
- Test: `backend/tests/test_job_posting_schema.py`

**Interfaces:**
- Produces: `CURRENT_JOB_POSTING_SCHEMA_VERSION: int`, `JobPostingDocument` (Pydantic model), `UnsupportedJobPostingSchemaVersion` (Exception), `migrate_job_posting_document(data: dict) -> JobPostingDocument`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_job_posting_schema.py`:
```python
import pytest
from app.models.job_posting import (
    JobPostingDocument,
    CURRENT_JOB_POSTING_SCHEMA_VERSION,
    migrate_job_posting_document,
    UnsupportedJobPostingSchemaVersion,
)


def test_job_posting_document_defaults_to_current_schema_version():
    doc = JobPostingDocument(title="Senior Backend Engineer")
    assert doc.schema_version == CURRENT_JOB_POSTING_SCHEMA_VERSION
    assert doc.requirements == []
    assert doc.company is None


def test_job_posting_document_roundtrips_through_json():
    doc = JobPostingDocument(
        title="Senior Backend Engineer",
        company="Acme Corp",
        location="Remote (US)",
        employment_type="Full-time",
        requirements=["5+ years Python"],
        responsibilities=["Design backend services"],
        qualifications=["B.S. Computer Science"],
        keywords=["Python", "PostgreSQL"],
    )
    restored = JobPostingDocument.model_validate_json(doc.model_dump_json())
    assert restored == doc


def test_migrate_job_posting_document_accepts_current_version():
    raw = {"schema_version": 1, "title": "Barista"}
    doc = migrate_job_posting_document(raw)
    assert doc.title == "Barista"


def test_migrate_job_posting_document_rejects_unknown_future_version():
    raw = {"schema_version": 999, "title": "Barista"}
    with pytest.raises(UnsupportedJobPostingSchemaVersion):
        migrate_job_posting_document(raw)
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `py -3 -m pytest tests/test_job_posting_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.job_posting'`

- [ ] **Step 3: Implement the schema**

`backend/app/models/job_posting.py`:
```python
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field

CURRENT_JOB_POSTING_SCHEMA_VERSION = 1


class JobPostingDocument(BaseModel):
    schema_version: int = CURRENT_JOB_POSTING_SCHEMA_VERSION
    title: str
    company: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    requirements: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class UnsupportedJobPostingSchemaVersion(Exception):
    pass


def migrate_job_posting_document(data: dict) -> JobPostingDocument:
    """Load a raw parsed_json dict of any known schema_version into the current
    JobPostingDocument shape.

    New migrators get registered here (e.g. an `if version == 1: ...` branch
    calling a `_migrate_v1_to_v2` helper) the first time schema_version is
    bumped past 1 — mirrors `app/models/resume.py`'s `migrate_resume_document`.
    """
    version = data.get("schema_version", CURRENT_JOB_POSTING_SCHEMA_VERSION)
    if version == CURRENT_JOB_POSTING_SCHEMA_VERSION:
        return JobPostingDocument.model_validate(data)
    raise UnsupportedJobPostingSchemaVersion(
        f"No migrator registered for job posting schema_version={version}"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `backend/`): `py -3 -m pytest tests/test_job_posting_schema.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/job_posting.py backend/tests/test_job_posting_schema.py
git commit -m "feat: add canonical JobPostingDocument schema with schema_version"
```

---

### Task 2: `jd_extraction` prompt template

**Files:**
- Create: `backend/prompts/jd_extraction/v1.jinja2`
- Test: `backend/tests/test_jd_extraction_prompt.py`

**Interfaces:**
- Consumes: `PromptRegistry` (Phase 1).
- Produces: the registered `(task_type="jd_extraction", version="v1")` prompt template.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_jd_extraction_prompt.py`:
```python
from app.core.llm.prompt_registry import PromptRegistry
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, PromptVersion


def test_jd_extraction_prompt_registers_via_sync_to_db():
    registry = PromptRegistry(prompts_root="prompts")
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        registry.sync_to_db(db)
        row = db.query(PromptVersion).filter_by(task_type="jd_extraction", version="v1").one()
        assert row.template_path == "jd_extraction/v1.jinja2"


def test_jd_extraction_prompt_instructs_against_fabrication():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render("jd_extraction", "v1", raw_text="Barista at Corner Cafe.")
    lowered = rendered.lower()
    assert "do not" in lowered or "never" in lowered
    assert "fabricat" in lowered or "invent" in lowered
    assert "null" in lowered


def test_jd_extraction_prompt_embeds_concrete_tie_breaking_examples():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render("jd_extraction", "v1", raw_text="Barista at Corner Cafe.")
    lowered = rendered.lower()
    assert "example 1" in lowered
    assert "example 2" in lowered
    assert "qualifications" in lowered and "requirements" in lowered


def test_jd_extraction_prompt_addresses_title_fabrication_risk():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render("jd_extraction", "v1", raw_text="Barista at Corner Cafe.")
    lowered = rendered.lower()
    assert "untitled" in lowered
    assert "required" in lowered
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `py -3 -m pytest tests/test_jd_extraction_prompt.py -v`
Expected: FAIL with `jinja2.exceptions.TemplateNotFound`

- [ ] **Step 3: Write the template**

`backend/prompts/jd_extraction/v1.jinja2`:
```
You are extracting structured job posting data from raw job description text.
The text below may contain formatting artifacts (inconsistent line breaks,
stray whitespace) - work around that, but do not invent content that is not
present in the text.

CRITICAL RULE: If a piece of information is missing, unclear, or ambiguous in
the source text, leave the corresponding field null (or an empty list, per its
type) rather than guessing or inferring plausible-sounding content. Never
invent a job title, company name, requirement, responsibility, or
qualification that is not directly present in the source text below. It is
always better to leave a field empty than to fabricate a plausible-sounding
value. This applies even to "title", which is a required field: if the source
text truly contains no identifiable job title, use a plain, honest placeholder
such as "Untitled" rather than inventing a plausible-sounding title.

REQUIREMENTS VS QUALIFICATIONS RULE: Job postings frequently blur
"requirements" and "qualifications" into one undifferentiated list, or only
label one of the two. If the source text does not clearly distinguish between
the two, put every relevant item under "requirements" and leave
"qualifications" as an empty list. Never split one undifferentiated list into
two, and never duplicate the same item across both fields. For example:

Example 1 - source text says: "Must-haves: 3+ years in SQL, experience with
Tableau, strong communication skills" (no separate qualifications section) ->
requirements: ["3+ years in SQL", "experience with Tableau", "strong
communication skills"], qualifications: [].

Example 2 - source text says: "Requirements: 5+ years Python experience.
Qualifications: Bachelor's degree in Computer Science." (clearly two separate,
labeled sections) -> requirements: ["5+ years Python experience"],
qualifications: ["Bachelor's degree in Computer Science"].

Output ONLY a single JSON object matching exactly this shape (no markdown code
fences, no explanation, no extra text before or after the JSON):

{
  "schema_version": 1,
  "title": "string, required",
  "company": "string or null",
  "location": "string or null",
  "employment_type": "string or null",
  "requirements": ["array of strings, may be empty"],
  "responsibilities": ["array of strings, may be empty"],
  "qualifications": ["array of strings, may be empty"],
  "keywords": ["array of strings, may be empty"]
}

Source text extracted from the job posting:

{{ raw_text }}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `backend/`): `py -3 -m pytest tests/test_jd_extraction_prompt.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/prompts/jd_extraction/v1.jinja2 backend/tests/test_jd_extraction_prompt.py
git commit -m "feat: add jd_extraction prompt template with anti-fabrication and tie-breaking rules"
```

---

### Task 3: Synthetic JD text fixtures

**Files:**
- Create: `backend/tests/fixtures/jd_fixtures.py`
- Test: `backend/tests/test_jd_fixtures.py`

**Interfaces:**
- Produces: `complete_jd_text() -> str`, `no_requirements_header_jd_text() -> str`, `blurred_requirements_qualifications_jd_text() -> str`, `terse_jd_text() -> str`, `not_a_job_posting_text() -> str`.
- All content is fabricated placeholder data — no real job postings, no real company/personal information.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_jd_fixtures.py`:
```python
from tests.fixtures.jd_fixtures import (
    complete_jd_text,
    no_requirements_header_jd_text,
    blurred_requirements_qualifications_jd_text,
    terse_jd_text,
    not_a_job_posting_text,
)


def test_complete_jd_text_has_distinct_requirements_and_qualifications_sections():
    text = complete_jd_text()
    assert "Requirements:" in text
    assert "Qualifications:" in text
    assert "Acme Corp" in text


def test_no_requirements_header_jd_text_has_no_requirements_label():
    text = no_requirements_header_jd_text()
    assert "Requirements:" not in text
    assert "Marketing Coordinator" in text


def test_blurred_requirements_qualifications_jd_text_has_no_qualifications_label():
    text = blurred_requirements_qualifications_jd_text()
    assert "Qualifications:" not in text
    assert "Must-haves:" in text


def test_terse_jd_text_is_short():
    text = terse_jd_text()
    assert len(text) < 100
    assert "Barista" in text


def test_not_a_job_posting_text_contains_no_job_posting_markers():
    text = not_a_job_posting_text()
    assert "Requirements" not in text
    assert "Responsibilities" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `py -3 -m pytest tests/test_jd_fixtures.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.fixtures.jd_fixtures'`

- [ ] **Step 3: Implement the fixtures**

`backend/tests/fixtures/jd_fixtures.py`:
```python
"""Synthetic job-description text fixtures for tests. All company names,
titles, and content below are fabricated placeholders — not real job
postings, not scrubbed real listings."""


def complete_jd_text() -> str:
    return """Senior Backend Engineer at Acme Corp
Location: Remote (US)
Employment Type: Full-time

About the role:
We're looking for a Senior Backend Engineer to join our platform team.

Requirements:
- 5+ years of experience with Python or Go
- Experience with distributed systems and message queues
- Strong understanding of relational databases

Qualifications:
- Bachelor's degree in Computer Science or equivalent experience
- Experience mentoring junior engineers

Responsibilities:
- Design and implement backend services for our core platform
- Participate in on-call rotation
- Collaborate with product and design teams

Keywords: Python, Go, PostgreSQL, Kafka, distributed systems
"""


def no_requirements_header_jd_text() -> str:
    return """Marketing Coordinator at Widget LLC
Location: Chicago, IL

We're hiring a Marketing Coordinator. The ideal candidate has 2+ years of
experience in digital marketing, is comfortable with social media analytics
tools, and has excellent written communication skills. Responsibilities
include managing our social media calendar and coordinating with the design
team on campaign assets.
"""


def blurred_requirements_qualifications_jd_text() -> str:
    return """Data Analyst at Initech
Location: Austin, TX
Employment Type: Contract

Must-haves:
- Proficiency in SQL and Excel
- Experience with Tableau or similar BI tools
- 3+ years in a data analyst role

Responsibilities:
- Build and maintain dashboards for the sales team
- Perform ad-hoc data analysis requests
"""


def terse_jd_text() -> str:
    return "Barista at Corner Cafe. Part-time, in-person."


def not_a_job_posting_text() -> str:
    return """Dear team,

Just a reminder that the office will be closed next Monday for the holiday.
Please make sure to submit your timesheets before end of day Friday. Thanks
everyone for a great quarter!

Best,
Alex
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `backend/`): `py -3 -m pytest tests/test_jd_fixtures.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/tests/fixtures/jd_fixtures.py backend/tests/test_jd_fixtures.py
git commit -m "feat: add synthetic JD text fixtures for extraction tests"
```

---

### Task 4: JD Extractor service

**Files:**
- Create: `backend/app/services/errors.py`
- Modify: `backend/app/services/resume_parser.py`
- Create: `backend/app/services/jd_extractor.py`
- Test: `backend/tests/test_jd_extractor.py`

**Interfaces:**
- Consumes: `AIOrchestrator`, `TaskConfig`, `OrchestratorError` (Phase 1), `PromptRegistry` (Phase 1), `JobPosting` (Phase 1), `JobPostingDocument` (Task 1).
- Produces: `StageExecutionError` (Exception, new shared base class) in `app.services.errors`; `JDExtractionError(StageExecutionError)`; `extract_job_posting(db: Session, job_posting: JobPosting, orchestrator: AIOrchestrator, prompt_registry: PromptRegistry) -> JobPosting`.
- `ResumeParsingError` (Phase 2) now inherits from `StageExecutionError` — a non-breaking, additive change: every existing `except ResumeParsingError` still catches exactly what it did before.

**Note on scope beyond the spec's literal text:** the spec states no fail-fast guard is needed since `POST /job-postings` requires either `source_url` or `raw_text`. That's true for *creation*, but a row created with only `source_url` (no `raw_text`) has `raw_text = None` — and since URL fetching is out of scope this phase, `extract_job_posting` has nothing to structure in that case. This task adds a small, explicit guard for exactly that case (raise `JDExtractionError` with a clear message) rather than sending `None` into the prompt template or crashing with a confusing Jinja2 error.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_jd_extractor.py`:
```python
import pytest
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, JobPosting
from app.core.llm.orchestrator import OrchestratorResult, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.job_posting import JobPostingDocument
from app.services.jd_extractor import extract_job_posting, JDExtractionError
from tests.fixtures.jd_fixtures import (
    blurred_requirements_qualifications_jd_text, not_a_job_posting_text,
)


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


def test_extract_job_posting_persists_parsed_json():
    db = _make_db()
    job_posting = JobPosting(raw_text=blurred_requirements_qualifications_jd_text())
    db.add(job_posting)
    db.commit()

    parsed_document = JobPostingDocument(
        title="Data Analyst", company="Initech", location="Austin, TX",
        employment_type="Contract",
        requirements=["Proficiency in SQL and Excel", "Experience with Tableau or similar BI tools", "3+ years in a data analyst role"],
        responsibilities=["Build and maintain dashboards for the sales team", "Perform ad-hoc data analysis requests"],
        qualifications=[],
        keywords=[],
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=parsed_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    result = extract_job_posting(db, job_posting, orchestrator, prompt_registry)

    assert result.parsed_json["title"] == "Data Analyst"
    assert db.query(JobPosting).filter_by(id=job_posting.id).one().parsed_json["title"] == "Data Analyst"


def test_extract_job_posting_tie_breaking_guard_puts_everything_in_requirements():
    """Tie-breaking guard (spec §3.1, §6): a blurred requirements/qualifications
    fixture must persist all items under requirements with qualifications empty,
    not just validate as JSON."""
    db = _make_db()
    job_posting = JobPosting(raw_text=blurred_requirements_qualifications_jd_text())
    db.add(job_posting)
    db.commit()

    parsed_document = JobPostingDocument(
        title="Data Analyst",
        requirements=["Proficiency in SQL and Excel", "Experience with Tableau or similar BI tools", "3+ years in a data analyst role"],
        qualifications=[],
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=parsed_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    result = extract_job_posting(db, job_posting, orchestrator, prompt_registry)

    assert result.parsed_json["qualifications"] == []
    assert len(result.parsed_json["requirements"]) == 3


def test_extract_job_posting_title_fabrication_guard(tmp_path):
    """Title-fabrication guard (spec §3.2, §6): for a 'not a job posting'
    fixture, the persisted title must match the mocked orchestrator's honest
    placeholder byte-for-byte, proving jd_extractor.py doesn't substitute or
    embellish a fabricated-looking value on top of whatever the orchestrator
    returns."""
    db = _make_db()
    job_posting = JobPosting(raw_text=not_a_job_posting_text())
    db.add(job_posting)
    db.commit()

    parsed_document = JobPostingDocument(title="Untitled")
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=parsed_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    result = extract_job_posting(db, job_posting, orchestrator, prompt_registry)

    assert result.parsed_json["title"] == "Untitled"


def test_extract_job_posting_wraps_orchestrator_error():
    db = _make_db()
    job_posting = JobPosting(raw_text=blurred_requirements_qualifications_jd_text())
    db.add(job_posting)
    db.commit()

    orchestrator = FakeOrchestrator(error=OrchestratorError("all providers exhausted"))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(JDExtractionError):
        extract_job_posting(db, job_posting, orchestrator, prompt_registry)


def test_extract_job_posting_fails_fast_when_no_raw_text_without_calling_orchestrator():
    db = _make_db()
    job_posting = JobPosting(source_url="https://example.com/job", raw_text=None)
    db.add(job_posting)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(JDExtractionError, match="no raw_text"):
        extract_job_posting(db, job_posting, orchestrator, prompt_registry)

    assert orchestrator.calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `py -3 -m pytest tests/test_jd_extractor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.jd_extractor'`

- [ ] **Step 3: Implement the shared error base and the JD Extractor**

`backend/app/services/errors.py`:
```python
class StageExecutionError(Exception):
    """Base class for errors raised by a run_stage service function (extraction
    or LLM-structuring failure). run_stage catches this base class so any
    current or future stage's service function can signal a stage failure
    without run_stage needing to know about each stage's specific exception
    type."""
```

In `backend/app/services/resume_parser.py`, change:
```python
class ResumeParsingError(Exception):
    """Raised when resume parsing fails, whether at extraction or LLM-structuring."""
```
to:
```python
from app.services.errors import StageExecutionError


class ResumeParsingError(StageExecutionError):
    """Raised when resume parsing fails, whether at extraction or LLM-structuring."""
```
(add the new import line near the top of the file alongside the existing imports; this is the only change to this file — every existing `except ResumeParsingError` clause anywhere in the codebase still catches exactly what it did before, since `ResumeParsingError` itself is unchanged, only its parent class is new.)

`backend/app/services/jd_extractor.py`:
```python
from sqlalchemy.orm import Session
from app.core.llm.orchestrator import AIOrchestrator, TaskConfig, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import JobPosting
from app.models.job_posting import JobPostingDocument
from app.services.errors import StageExecutionError

JD_EXTRACTION_MODEL = "z-ai/glm-5.2"
JD_EXTRACTION_TEMPERATURE = 0.1


class JDExtractionError(StageExecutionError):
    """Raised when JD extraction fails, whether due to missing input or LLM-structuring."""


def extract_job_posting(
    db: Session,
    job_posting: JobPosting,
    orchestrator: AIOrchestrator,
    prompt_registry: PromptRegistry,
) -> JobPosting:
    if not job_posting.raw_text:
        raise JDExtractionError(
            "no raw_text on this job posting to extract from — URL fetching is not yet "
            "supported; provide raw_text directly"
        )

    prompt = prompt_registry.render("jd_extraction", "v1", raw_text=job_posting.raw_text)
    task = TaskConfig(
        task_type="jd_extraction",
        provider="nvidia",
        model=JD_EXTRACTION_MODEL,
        temperature=JD_EXTRACTION_TEMPERATURE,
        response_schema=JobPostingDocument,
        fallback_providers=[],
    )

    try:
        result = orchestrator.run(task, prompt=prompt)
    except OrchestratorError as exc:
        raise JDExtractionError(str(exc)) from exc

    job_posting.parsed_json = result.output.model_dump()
    db.commit()
    db.refresh(job_posting)
    return job_posting
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `backend/`): `py -3 -m pytest tests/test_jd_extractor.py tests/test_resume_parser.py -v`
Expected: all pass (5 new in `test_jd_extractor.py`; the existing `test_resume_parser.py` tests still pass unmodified, confirming the `StageExecutionError` base-class change didn't break anything).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/errors.py backend/app/services/resume_parser.py backend/app/services/jd_extractor.py \
  backend/tests/test_jd_extractor.py
git commit -m "feat: add JD Extractor service and shared StageExecutionError base class"
```

---

### Task 5: Generalize `run_stage` to dispatch both stages

**Files:**
- Modify: `backend/app/api/sessions.py`
- Modify: `backend/tests/test_api_sessions.py`

**Interfaces:**
- Consumes: `extract_job_posting`/`JDExtractionError` (Task 4), `StageExecutionError` (Task 4), `parse_resume` (Phase 2, unchanged).
- Produces: `run_stage` now dispatches to either `resume_parsing` or `jd_extraction` via a `STAGE_RUNNERS` dict; every other `stage_name` still `501`s. `RESUME_PARSING_TIMEOUT_SECONDS` is renamed to `STAGE_TIMEOUT_SECONDS`.

**Why this rename is safe and necessary:** the 330-second timeout was always a property of the synchronous-execution mechanism, not of `resume_parsing` specifically — now that a second stage shares the same mechanism, the old name would be actively misleading. Phase 2's existing timeout tests reference the old name via `monkeypatch.setattr(sessions_module, "RESUME_PARSING_TIMEOUT_SECONDS", 0.05)`; this task updates those two references to the new name (not left broken) as part of the same commit.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_api_sessions.py`, first make these two **surgical edits** to existing tests (rename only, no other changes):
- In `test_run_stage_resume_parsing_times_out`, change `monkeypatch.setattr(sessions_module, "RESUME_PARSING_TIMEOUT_SECONDS", 0.05)` to `monkeypatch.setattr(sessions_module, "STAGE_TIMEOUT_SECONDS", 0.05)`.
- In `test_run_stage_resume_parsing_times_out_uses_captured_run_id_not_stale_object`, make the identical change.

Then add these new tests to the same file:

```python
def test_run_stage_jd_extraction_succeeds(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job", raw_text="Barista at Corner Cafe.")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def fake_extract_job_posting(db, job_posting, orchestrator, prompt_registry):
        job_posting.parsed_json = {"title": "Barista"}
        return job_posting

    monkeypatch.setattr(sessions_module, "extract_job_posting", fake_extract_job_posting)

    response = client.post(f"/sessions/{session_id}/run-stage/jd_extraction")

    assert response.status_code == 200
    assert response.json() == {"stage_name": "jd_extraction", "status": "succeeded", "job_posting_id": job.id}

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert len(runs) == 1
    assert runs[0]["stage_name"] == "jd_extraction"
    assert runs[0]["status"] == "succeeded"


def test_run_stage_jd_extraction_reports_failure(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module
    from app.services.jd_extractor import JDExtractionError

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job", raw_text="Barista at Corner Cafe.")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def failing_extract_job_posting(db, job_posting, orchestrator, prompt_registry):
        raise JDExtractionError("no raw_text on this job posting to extract from")

    monkeypatch.setattr(sessions_module, "extract_job_posting", failing_extract_job_posting)

    response = client.post(f"/sessions/{session_id}/run-stage/jd_extraction")

    assert response.status_code == 422

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert runs[0]["status"] == "failed"


def test_run_stage_jd_extraction_times_out(client, db_session, monkeypatch):
    import time
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job", raw_text="Barista at Corner Cafe.")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def slow_extract_job_posting(db, job_posting, orchestrator, prompt_registry):
        time.sleep(0.5)
        job_posting.parsed_json = {"title": "Barista"}
        return job_posting

    monkeypatch.setattr(sessions_module, "extract_job_posting", slow_extract_job_posting)
    monkeypatch.setattr(sessions_module, "STAGE_TIMEOUT_SECONDS", 0.05)

    response = client.post(f"/sessions/{session_id}/run-stage/jd_extraction")

    assert response.status_code == 504

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert runs[0]["status"] == "failed"


def test_run_stage_still_501s_for_a_genuinely_unimplemented_stage(client, db_session):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    response = client.post(f"/sessions/{session_id}/run-stage/tailoring_rewrite")

    assert response.status_code == 501
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `py -3 -m pytest tests/test_api_sessions.py -v`
Expected: the renamed-constant tests and the pre-existing `jd_extraction` 501 test (`test_run_stage_returns_501_for_unimplemented_stage`, which uses `jd_extraction` as its example per Phase 2's Task 8) now conflict with the new behavior being added — this is expected; the 4 new tests FAIL (jd_extraction still 501s unconditionally); the two renamed-constant tests FAIL with `AttributeError` (no `STAGE_TIMEOUT_SECONDS` yet).

Note: `test_run_stage_returns_501_for_unimplemented_stage` currently uses `jd_extraction` as its "still unimplemented" example stage name (set that way in Phase 2's Task 8, since `resume_parsing` had just become real then). Now that `jd_extraction` is about to become real too, this test must be updated the same way Phase 2 updated it: change its stage name to another still-unimplemented one. Update it to use `"tailoring_rewrite"` instead of `"jd_extraction"` — this is the same edit as adding `test_run_stage_still_501s_for_a_genuinely_unimplemented_stage` above, so simply rename/replace the body of the existing `test_run_stage_returns_501_for_unimplemented_stage` test to use `tailoring_rewrite`, rather than keeping both as separate tests with the same content.

- [ ] **Step 3: Generalize `run_stage`**

`backend/app/api/sessions.py` (full replacement):
```python
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.core.llm.orchestrator_factory import build_orchestrator
from app.core.llm.prompt_registry import PromptRegistry
from app.core.storage import LocalDiskStorage
from app.models.db_models import Resume, JobPosting, TailoringSession, PipelineRun, GeneratedDocument
from app.services.errors import StageExecutionError
from app.services.resume_parser import parse_resume
from app.services.jd_extractor import extract_job_posting

router = APIRouter(prefix="/sessions", tags=["sessions"])

STAGE_TIMEOUT_SECONDS = 330
_STAGE_EXECUTOR = ThreadPoolExecutor(max_workers=4)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CreateSessionRequest(BaseModel):
    resume_id: int
    job_posting_id: int


@router.post("", status_code=201)
def create_session(request: CreateSessionRequest, db: Session = Depends(get_db)):
    if db.get(Resume, request.resume_id) is None:
        raise HTTPException(status_code=404, detail=f"resume {request.resume_id} not found")
    if db.get(JobPosting, request.job_posting_id) is None:
        raise HTTPException(status_code=404, detail=f"job_posting {request.job_posting_id} not found")

    session = TailoringSession(
        resume_id=request.resume_id, job_posting_id=request.job_posting_id, status="created",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"id": session.id, "status": session.status}


def _run_resume_parsing(db: Session, session: TailoringSession, settings) -> dict:
    resume = db.get(Resume, session.resume_id)
    storage = LocalDiskStorage(root=settings.storage_root)
    orchestrator = build_orchestrator(db, session_id=session.id)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)
    version = parse_resume(db, resume, storage, orchestrator, prompt_registry)
    return {"resume_version_id": version.id}


def _run_jd_extraction(db: Session, session: TailoringSession, settings) -> dict:
    job_posting = db.get(JobPosting, session.job_posting_id)
    orchestrator = build_orchestrator(db, session_id=session.id)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)
    extract_job_posting(db, job_posting, orchestrator, prompt_registry)
    return {"job_posting_id": job_posting.id}


STAGE_RUNNERS = {
    "resume_parsing": _run_resume_parsing,
    "jd_extraction": _run_jd_extraction,
}


@router.post("/{session_id}/run-stage/{stage_name}")
def run_stage(session_id: int, stage_name: str, db: Session = Depends(get_db)):
    session = db.get(TailoringSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")

    stage_runner = STAGE_RUNNERS.get(stage_name)
    if stage_runner is None:
        raise HTTPException(
            status_code=501,
            detail=f"stage '{stage_name}' is not implemented yet (Phase 1 contract only)",
        )

    settings = get_settings()
    pipeline_run = PipelineRun(
        session_id=session_id, stage_name=stage_name, status="running", started_at=_utcnow(),
    )
    db.add(pipeline_run)
    db.commit()
    db.refresh(pipeline_run)
    pipeline_run_id = pipeline_run.id  # captured before the background thread starts, so the
    # timeout branch below never needs to read an attribute off the request-thread-bound
    # `pipeline_run` object after the worker thread may have started mutating shared state.

    future = _STAGE_EXECUTOR.submit(stage_runner, db, session, settings)

    try:
        result = future.result(timeout=STAGE_TIMEOUT_SECONDS)
    except FutureTimeoutError:
        # The worker thread is still running the stage in the background and cannot be
        # forcibly cancelled — it may still commit against `db` after we give up waiting on it.
        # Touching the same `db` Session from this (the request) thread while that's possible
        # is unsafe (SQLAlchemy Sessions aren't safe for concurrent multi-thread use), so the
        # failure record below is written through a fresh, independent session instead of `db`.
        error_message = f"{stage_name} timed out after {STAGE_TIMEOUT_SECONDS} seconds"
        fresh_db = make_session_factory(make_engine(settings.database_url))()
        try:
            fresh_run = fresh_db.get(PipelineRun, pipeline_run_id)
            fresh_run.status = "failed"
            fresh_run.error_message = error_message
            fresh_run.completed_at = _utcnow()
            fresh_db.commit()
        finally:
            fresh_db.close()
        raise HTTPException(status_code=504, detail=error_message)
    except StageExecutionError as exc:
        pipeline_run.status = "failed"
        pipeline_run.error_message = str(exc)
        pipeline_run.completed_at = _utcnow()
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc))

    pipeline_run.status = "succeeded"
    pipeline_run.completed_at = _utcnow()
    db.commit()

    return {"stage_name": stage_name, "status": "succeeded", **result}


@router.get("/{session_id}/status")
def get_status(session_id: int, db: Session = Depends(get_db)):
    session = db.get(TailoringSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")
    runs = db.query(PipelineRun).filter_by(session_id=session_id).all()
    return {
        "id": session.id,
        "status": session.status,
        "pipeline_runs": [
            {"stage_name": run.stage_name, "status": run.status} for run in runs
        ],
    }


@router.get("/{session_id}/documents")
def list_documents(session_id: int, db: Session = Depends(get_db)):
    session = db.get(TailoringSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")
    documents = db.query(GeneratedDocument).filter_by(session_id=session_id).all()
    return [
        {"document_type": doc.document_type, "storage_path": doc.storage_path, "version_number": doc.version_number}
        for doc in documents
    ]
```

Note on backward compatibility: `_run_resume_parsing` still calls the module-level name `parse_resume` (imported at the top of this file), so every existing Phase 2 test that does `monkeypatch.setattr(sessions_module, "parse_resume", fake_parse_resume)` continues to work unchanged — Python resolves `parse_resume` from `sessions.py`'s module namespace at call time, regardless of which function (`run_stage` directly, or now `_run_resume_parsing`) does the calling. The response shape for `resume_parsing` (`{"stage_name", "status": "succeeded", "resume_version_id": ...}`) is unchanged for exactly the same reason: `_run_resume_parsing` returns `{"resume_version_id": version.id}`, which `run_stage` splices into the same response dict as before via `**result`.

- [ ] **Step 4: Run tests to verify they pass**

Run (from `backend/`): `py -3 -m pytest tests/test_api_sessions.py -v`
Expected: all pass — every pre-existing Phase 2 `resume_parsing` test, the renamed-constant timeout tests, the updated 501 test, and the 4 new `jd_extraction` tests.

- [ ] **Step 5: Run the full backend test suite**

Run (from `backend/`): `py -3 -m pytest -v`
Expected: all tests pass (Phases 1-2's existing suite plus everything added in this plan's Tasks 1-5).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/sessions.py backend/tests/test_api_sessions.py
git commit -m "feat: generalize run_stage to dispatch resume_parsing and jd_extraction via a stage-runner table"
```

---

### Task 6: Manual smoke-test script

**Files:**
- Create: `backend/scripts/smoke_test_jd_extraction.py`

**Interfaces:**
- Consumes: everything from Tasks 1-5. Not run by pytest — manual verification only, costs a real NVIDIA API call. This is the sole place real-model title-fabrication behavior (spec §3.2, §6) actually gets observed by a human.

- [ ] **Step 1: Write the script**

`backend/scripts/smoke_test_jd_extraction.py`:
```python
"""Manual smoke test: run with `python scripts/smoke_test_jd_extraction.py`
after setting NVIDIA_API_KEY in backend/.env. Costs a real API call — not run
by pytest.

Extracts a synthetic 'not a job posting' fixture through the real NVIDIA API
and prints the resulting JobPostingDocument JSON, so a human can manually
verify the model does NOT fabricate a plausible-looking title to satisfy the
schema's one required field when the source text isn't a job posting at all —
this is the highest fabrication-risk case in this phase (see spec §3.2), and
the automated test suite (which mocks the orchestrator) cannot itself prove
real-model behavior for it."""
import json
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.core.llm.orchestrator_factory import build_orchestrator
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import Base, JobPosting
from app.services.jd_extractor import extract_job_posting
from tests.fixtures.jd_fixtures import not_a_job_posting_text

if __name__ == "__main__":
    settings = get_settings()
    if not settings.nvidia_api_key:
        raise SystemExit("Set NVIDIA_API_KEY in backend/.env before running this script.")

    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = make_session_factory(engine)()

    job_posting = JobPosting(raw_text=not_a_job_posting_text())
    db.add(job_posting)
    db.commit()

    orchestrator = build_orchestrator(db, session_id=None)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)

    result = extract_job_posting(db, job_posting, orchestrator, prompt_registry)
    print(json.dumps(result.parsed_json, indent=2))
```

- [ ] **Step 2: Commit**

```bash
git add backend/scripts/smoke_test_jd_extraction.py
git commit -m "feat: add manual smoke-test script for jd_extraction"
```

---

## Self-Review

**Spec coverage:**
- §2 (canonical `JobPostingDocument` schema, `schema_version`) → Task 1.
- §3.1 (tie-breaking rule with concrete worked examples) → Task 2 (prompt content + test), Task 4 (persistence-layer guard test).
- §3.2 (title as highest-fabrication-risk field, byte-for-byte guard) → Task 2 (prompt content + test), Task 4 (persistence-layer guard test), Task 6 (real-model smoke script).
- §4 (architecture, no fail-fast guard needed at creation time, deliberate no-`job_posting_versions`-table choice) → Task 4. The plan additionally closes a gap the spec's reasoning didn't fully cover (a `JobPosting` row created with only `source_url` has `raw_text = None`) with an explicit guard and test in Task 4 — flagged inline in that task rather than silently deviating from the spec.
- §5 (API integration, same timeout/thread-safety mechanism, no new timeout math) → Task 5.
- §6 (fixtures, mocked-provider tests, manual smoke script) → Tasks 3, 4, 6.
- §7 (out of scope: URL fetching, headless browser, auth walls, `job_posting_versions` table, changes to `resume_parsing`/timeout design/orchestrator layer) → confirmed no task introduces any of these; Task 5 reuses the existing timeout/thread-safety mechanism verbatim rather than modifying it.
- §8 (Phase 2 backlog carried forward) → not re-addressed by any task in this plan (correctly out of scope here); restated in the spec so it isn't lost, and remains available for a future phase's task list.

**Placeholder scan:** no TBD/TODO markers; every step has complete, runnable code.

**Type consistency:** `extract_job_posting(db, job_posting, orchestrator, prompt_registry) -> JobPosting` signature matches exactly between Task 4 (definition), Task 5 (`_run_jd_extraction` caller), and Task 6 (smoke script caller). `JDExtractionError` is defined once in Task 4 and imported (not redefined) in Task 5. `StageExecutionError` is defined once in Task 4 (`app/services/errors.py`) and both `ResumeParsingError` and `JDExtractionError` inherit from it; Task 5's `except StageExecutionError` catches both without needing to know either subclass by name. `STAGE_TIMEOUT_SECONDS`/`STAGE_RUNNERS` are module-level constants in `sessions.py` (Task 5), referenced by name (not hardcoded) in the task's own tests so they can be monkeypatched directly, exactly matching the pattern Phase 2 established for `RESUME_PARSING_TIMEOUT_SECONDS`.

---

**Plan complete and saved to `docs/superpowers/plans/2026-07-05-phase3-jd-extraction.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
