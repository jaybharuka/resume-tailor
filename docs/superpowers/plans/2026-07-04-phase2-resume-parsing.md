# Phase 2 Resume Parsing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `resume_parsing` stage real — extract text from an uploaded PDF, structure it into the canonical `ResumeDocument` via the Phase 1 `AIOrchestrator` (NVIDIA primary), and persist the result — wired into `POST /sessions/{id}/run-stage/resume_parsing`.

**Architecture:** A new `backend/app/services/resume_parser.py` module (the Resume Parser logical service) extracts PDF text via `pymupdf4llm`, fails fast on empty text, calls the orchestrator with a `resume_parsing` task whose prompt explicitly forbids fabrication, and persists a `resume_versions` row on success. `run_stage` executes this synchronously with an explicit, thread-based timeout (no queue/worker infrastructure yet, matching Phase 1's async-ready-but-not-yet-async design).

**Tech Stack:** PyMuPDF, pymupdf4llm, the existing FastAPI/SQLAlchemy/Alembic/AIOrchestrator stack from Phase 1.

## Global Constraints

- Python 3.11+.
- PDF-only in this phase — no DOCX, no OCR for scanned/image-based PDFs (both explicitly deferred).
- **Hard requirement, not a style preference:** the `resume_parsing` prompt must instruct the model to leave `ResumeDocument` fields null/empty when information is absent or ambiguous, never to infer or fabricate plausible-sounding content. This must be tested against sparse/incomplete fixtures specifically, not just a complete one.
- Synchronous execution only in this phase — `run_stage` blocks on a single LLM call; no background workers/queues.
- The synchronous timeout is **330 seconds**, sized against the orchestrator's real worst case: the primary provider is tried twice (`provider_order = [primary, primary, *fallbacks]`, Phase 1 Task 6), and each entry can itself take ~150s to exhaust `with_backoff`'s internal retries (Phase 1 Task 7) — so ~300s worst-case with no fallback configured, plus headroom.
- `resume_parsing`'s `TaskConfig` uses `fallback_providers=[]` — Gemini/Claude/OpenAI remain non-functional Phase 1 stubs, so listing one as a fallback would add no real redundancy.
- The prompt-registry startup hook must tolerate `sqlalchemy.exc.OperationalError` (DB not reachable yet) but must NOT swallow other exceptions (e.g. a genuine schema mismatch) — those must propagate and fail app startup loudly.
- `resume_versions.version_number` is hardcoded to `1` in this phase (parsing only happens once per resume today) — Phase 6 (Resume Optimizer) must generalize this when it starts creating additional versions.
- Synthetic PDF test fixtures contain fabricated placeholder identities only — not real personal data, not scrubbed real resumes.
- Follow TDD: write the failing test, confirm it fails, implement, confirm it passes, commit.

---

### Task 1: `prompt_versions` unique constraint and `llm_calls` RESTRICT policy

**Files:**
- Modify: `backend/app/models/db_models.py`
- Create: `backend/alembic/versions/0002_prompt_version_unique_and_llm_calls_restrict.py`
- Modify: `backend/tests/test_db_models.py`

**Interfaces:**
- Consumes: `Base`, `PromptVersion`, `LLMCall`, `make_engine`, `make_session_factory` (Phase 1).
- Produces: `PromptVersion` now has a `(task_type, version)` unique constraint; `LLMCall.prompt_version_id`'s FK is `ondelete="RESTRICT"` instead of `ondelete="CASCADE"`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_db_models.py` (add this import near the top alongside the existing ones, and add these two test functions at the end of the file):

```python
from sqlalchemy.exc import IntegrityError
```

```python
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

(`pytest` is already imported in this file from Phase 1's Task 4 — if not, add `import pytest` at the top.)

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_db_models.py -v`
Expected: FAIL — no `IntegrityError` raised (the constraint/policy don't exist yet), or a `NameError`/`ImportError` if `IntegrityError` isn't imported yet.

- [ ] **Step 3: Add the constraint and change the FK policy**

In `backend/app/models/db_models.py`, add `UniqueConstraint` to the existing `sqlalchemy` import line:

```python
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, JSON, Boolean, Float, UniqueConstraint
)
```

Change the `PromptVersion` class to add `__table_args__`:

```python
class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("task_type", "version", name="uq_prompt_versions_task_type_version"),
    )

    id = Column(Integer, primary_key=True)
    task_type = Column(String, nullable=False)
    name = Column(String, nullable=False)
    version = Column(String, nullable=False)
    template_path = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
```

Change `LLMCall.prompt_version_id`'s `ondelete` from `"CASCADE"` to `"RESTRICT"`:

```python
    prompt_version_id = Column(Integer, ForeignKey("prompt_versions.id", ondelete="RESTRICT"), nullable=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `backend/`): `pytest tests/test_db_models.py -v`
Expected: all pass, including the 2 new tests.

- [ ] **Step 5: Write the Alembic migration**

`backend/alembic/versions/0002_prompt_version_unique_and_llm_calls_restrict.py`:

```python
"""prompt_versions unique constraint and llm_calls RESTRICT policy

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-04

"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_prompt_versions_task_type_version", "prompt_versions", ["task_type", "version"]
    )
    op.drop_constraint("llm_calls_prompt_version_id_fkey", "llm_calls", type_="foreignkey")
    op.create_foreign_key(
        "llm_calls_prompt_version_id_fkey", "llm_calls", "prompt_versions",
        ["prompt_version_id"], ["id"], ondelete="RESTRICT",
    )


def downgrade():
    op.drop_constraint("llm_calls_prompt_version_id_fkey", "llm_calls", type_="foreignkey")
    op.create_foreign_key(
        "llm_calls_prompt_version_id_fkey", "llm_calls", "prompt_versions",
        ["prompt_version_id"], ["id"], ondelete="CASCADE",
    )
    op.drop_constraint("uq_prompt_versions_task_type_version", "prompt_versions", type_="unique")
```

Note: `llm_calls_prompt_version_id_fkey` is Postgres/SQLAlchemy's default auto-generated constraint name (`<table>_<column>_fkey`), matching how the FK was originally created inline in `0001_initial_schema.py`.

- [ ] **Step 6: Verify the migration applies cleanly against a scratch database**

Run (from `backend/`):
```bash
DATABASE_URL="sqlite:///./_migration_check.db" alembic upgrade head
```
Expected: log ending in `Running upgrade 0001 -> 0002, prompt_versions unique constraint and llm_calls RESTRICT policy`

Then clean up: `rm backend/_migration_check.db`

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/db_models.py backend/alembic/versions/0002_prompt_version_unique_and_llm_calls_restrict.py \
  backend/tests/test_db_models.py
git commit -m "fix: add prompt_versions unique constraint and change llm_calls FK to RESTRICT"
```

---

### Task 2: JSON code-fence stripping helper, wired into NvidiaProvider

**Files:**
- Modify: `backend/app/core/llm/provider.py`
- Modify: `backend/app/core/llm/providers/nvidia_provider.py`
- Create: `backend/tests/test_provider.py`
- Modify: `backend/tests/test_nvidia_provider.py`

**Interfaces:**
- Produces: `strip_json_code_fence(text: str) -> str` in `app.core.llm.provider`.

**Why this task exists:** `AIOrchestrator._attempt` calls `task.response_schema.model_validate_json(raw_output)` directly on whatever a provider's `generate()` returns — no fence-stripping happens anywhere today. Real LLMs commonly wrap JSON output in ` ```json ... ``` ` fences despite prompt instructions not to. Since Phase 2 is the first real (non-test) consumer of `response_schema`-validated orchestrator output, this gap would otherwise cause spurious validation failures (burning retries/fallback, or failing entirely) on a semantically-correct response that just needed the fence stripped. `hiring-agent-imp`'s own `llm_utils.extract_json_from_response` does the same kind of stripping — this closes the equivalent gap here.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_provider.py`:
```python
from app.core.llm.provider import strip_json_code_fence


def test_strip_json_code_fence_removes_json_labeled_fence():
    text = '```json\n{"a": 1}\n```'
    assert strip_json_code_fence(text) == '{"a": 1}'


def test_strip_json_code_fence_removes_bare_fence():
    text = '```\n{"a": 1}\n```'
    assert strip_json_code_fence(text) == '{"a": 1}'


def test_strip_json_code_fence_leaves_unfenced_text_unchanged():
    text = '{"a": 1}'
    assert strip_json_code_fence(text) == '{"a": 1}'


def test_strip_json_code_fence_handles_surrounding_whitespace():
    text = '  \n```json\n{"a": 1}\n```\n  '
    assert strip_json_code_fence(text) == '{"a": 1}'
```

Add to `backend/tests/test_nvidia_provider.py` (new test, alongside the existing 5 — do not remove any):
```python
def test_generate_strips_markdown_json_code_fence(monkeypatch):
    class FencedCompletions:
        def create(self, **kwargs):
            return FakeCompletion('```json\n{"text": "hello from nvidia"}\n```')

    class FencedChat:
        def __init__(self):
            self.completions = FencedCompletions()

    class FencedOpenAIClient:
        def __init__(self, base_url, api_key):
            self.chat = FencedChat()

    monkeypatch.setattr(nvidia_provider_module, "OpenAI", FencedOpenAIClient)

    provider = NvidiaProvider(api_key="fake-key")
    result = provider.generate("say hi", model="z-ai/glm-5.2", temperature=1.0)

    assert result == '{"text": "hello from nvidia"}'
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_provider.py tests/test_nvidia_provider.py -v`
Expected: `test_provider.py` tests FAIL with `ModuleNotFoundError`/`ImportError` (`strip_json_code_fence` doesn't exist); the new nvidia test FAILS with an assertion mismatch (raw output still has the fence).

- [ ] **Step 3: Implement the helper and wire it in**

Add to `backend/app/core/llm/provider.py` (append below the existing `Provider` protocol):

```python
def strip_json_code_fence(text: str) -> str:
    """Strip a leading/trailing markdown code fence (```json ... ``` or ``` ... ```), if present."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped
```

In `backend/app/core/llm/providers/nvidia_provider.py`, add the import and use it in `call()`:

```python
from app.core.llm.provider import ProviderError, strip_json_code_fence
```

Change the `call()` function's return line from:
```python
            return completion.choices[0].message.content
```
to:
```python
            return strip_json_code_fence(completion.choices[0].message.content)
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `backend/`): `pytest tests/test_provider.py tests/test_nvidia_provider.py -v`
Expected: `test_provider.py` 4 passed; `test_nvidia_provider.py` 6 passed (5 original + 1 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/llm/provider.py backend/app/core/llm/providers/nvidia_provider.py \
  backend/tests/test_provider.py backend/tests/test_nvidia_provider.py
git commit -m "feat: strip markdown JSON code fences from NVIDIA provider output"
```

---

### Task 3: Synthetic PDF fixture builder

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/tests/fixtures/__init__.py`
- Create: `backend/tests/fixtures/pdf_fixtures.py`
- Test: `backend/tests/test_pdf_fixtures.py`

**Interfaces:**
- Produces: `build_normal_resume_pdf() -> bytes`, `build_no_summary_resume_pdf() -> bytes`, `build_sparse_bullets_resume_pdf() -> bytes`, `build_missing_section_resume_pdf() -> bytes`, `build_blank_pdf() -> bytes`.
- All content is fabricated placeholder data — no real personal information.

- [ ] **Step 1: Add PDF dependencies**

Add to `backend/requirements.txt`:
```
PyMuPDF==1.26.3
pymupdf4llm==0.0.27
```

Run (from `backend/`): `pip install -r requirements.txt`

- [ ] **Step 2: Write the failing tests**

`backend/tests/fixtures/__init__.py`: empty file.

`backend/tests/test_pdf_fixtures.py`:
```python
import pymupdf
from tests.fixtures.pdf_fixtures import (
    build_normal_resume_pdf,
    build_no_summary_resume_pdf,
    build_sparse_bullets_resume_pdf,
    build_missing_section_resume_pdf,
    build_blank_pdf,
)


def _extract_raw_text(pdf_bytes: bytes) -> str:
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        return "".join(page.get_text() for page in doc)


def test_build_normal_resume_pdf_contains_expected_content():
    text = _extract_raw_text(build_normal_resume_pdf())
    assert "Jane Doe" in text
    assert "Acme Corp" in text
    assert "Summary" in text


def test_build_no_summary_resume_pdf_has_no_summary_heading():
    text = _extract_raw_text(build_no_summary_resume_pdf())
    assert "John Smith" in text
    assert "Summary" not in text


def test_build_sparse_bullets_resume_pdf_has_minimal_bullets():
    text = _extract_raw_text(build_sparse_bullets_resume_pdf())
    assert "Alex Lee" in text
    assert "Worked on backend" in text


def test_build_missing_section_resume_pdf_has_no_projects_heading():
    text = _extract_raw_text(build_missing_section_resume_pdf())
    assert "Sam Rivera" in text
    assert "Projects" not in text


def test_build_blank_pdf_has_no_extractable_text():
    text = _extract_raw_text(build_blank_pdf())
    assert text.strip() == ""
```

- [ ] **Step 3: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_pdf_fixtures.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.fixtures.pdf_fixtures'`

- [ ] **Step 4: Implement the fixture builders**

`backend/tests/fixtures/pdf_fixtures.py`:
```python
"""Synthetic PDF resume fixtures for tests. All names, companies, and content
below are fabricated placeholders — not real people, not scrubbed real resumes."""
import pymupdf


def _build_pdf(lines: list[str]) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    y = 50
    for line in lines:
        page.insert_text((50, y), line, fontsize=11)
        y += 18
        if y > 780:
            page = doc.new_page()
            y = 50
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


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


def build_blank_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page()
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes
```

- [ ] **Step 5: Run tests to verify they pass**

Run (from `backend/`): `pytest tests/test_pdf_fixtures.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/tests/fixtures/__init__.py backend/tests/fixtures/pdf_fixtures.py \
  backend/tests/test_pdf_fixtures.py
git commit -m "feat: add synthetic PDF resume fixtures for parsing tests"
```

---

### Task 4: PDF text extractor

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/pdf_extractor.py`
- Test: `backend/tests/test_pdf_extractor.py`

**Interfaces:**
- Consumes: `build_normal_resume_pdf`, `build_blank_pdf` (Task 3).
- Produces: `extract_text_from_pdf(pdf_bytes: bytes) -> str`, `has_extractable_text(text: str) -> bool`, `MIN_EXTRACTED_TEXT_LENGTH: int` in `app.services.pdf_extractor`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_pdf_extractor.py`:
```python
from app.services.pdf_extractor import extract_text_from_pdf, has_extractable_text
from tests.fixtures.pdf_fixtures import build_normal_resume_pdf, build_blank_pdf


def test_extract_text_from_pdf_returns_resume_content():
    text = extract_text_from_pdf(build_normal_resume_pdf())
    assert "Jane Doe" in text
    assert "Acme Corp" in text


def test_extract_text_from_pdf_returns_near_empty_for_blank_pdf():
    text = extract_text_from_pdf(build_blank_pdf())
    assert text.strip() == ""


def test_has_extractable_text_true_for_real_content():
    assert has_extractable_text("Jane Doe\nSenior Backend Engineer\n" * 3) is True


def test_has_extractable_text_false_for_near_empty_string():
    assert has_extractable_text("   \n  ") is False
    assert has_extractable_text("") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `pytest tests/test_pdf_extractor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services'`

- [ ] **Step 3: Implement the extractor**

`backend/app/services/__init__.py`: empty file.

`backend/app/services/pdf_extractor.py`:
```python
import pymupdf
import pymupdf4llm

MIN_EXTRACTED_TEXT_LENGTH = 20


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """Extract markdown-ish text from PDF bytes using pymupdf4llm."""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        return pymupdf4llm.to_markdown(doc)


def has_extractable_text(text: str) -> bool:
    return len(text.strip()) >= MIN_EXTRACTED_TEXT_LENGTH
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `backend/`): `pytest tests/test_pdf_extractor.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/__init__.py backend/app/services/pdf_extractor.py backend/tests/test_pdf_extractor.py
git commit -m "feat: add PDF text extractor using pymupdf4llm"
```

---

### Task 5: `resume_parsing` prompt template

**Files:**
- Modify: `backend/app/core/config.py`
- Create: `backend/prompts/resume_parsing/v1.jinja2`
- Test: `backend/tests/test_resume_parsing_prompt.py`

**Interfaces:**
- Consumes: `PromptRegistry` (Phase 1).
- Produces: `Settings.prompts_root: str` (default `"./prompts"`); the registered `(task_type="resume_parsing", version="v1")` prompt template.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_resume_parsing_prompt.py`:
```python
from app.core.config import Settings
from app.core.llm.prompt_registry import PromptRegistry
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, PromptVersion


def test_settings_default_prompts_root():
    settings = Settings(_env_file=None)
    assert settings.prompts_root == "./prompts"


def test_resume_parsing_prompt_registers_via_sync_to_db():
    registry = PromptRegistry(prompts_root="prompts")
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        registry.sync_to_db(db)
        row = db.query(PromptVersion).filter_by(task_type="resume_parsing", version="v1").one()
        assert row.template_path == "resume_parsing/v1.jinja2"


def test_resume_parsing_prompt_instructs_against_fabrication():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render("resume_parsing", "v1", extracted_text="Jane Doe\nEngineer")
    lowered = rendered.lower()
    assert "do not" in lowered or "never" in lowered
    assert "fabricat" in lowered or "invent" in lowered
    assert "null" in lowered
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_resume_parsing_prompt.py -v`
Expected: FAIL — `test_settings_default_prompts_root` with `AttributeError` (no `prompts_root` field); the other two with `jinja2.exceptions.TemplateNotFound` (template doesn't exist yet).

- [ ] **Step 3: Add the setting and the template**

In `backend/app/core/config.py`, add `prompts_root` to `Settings`:
```python
    prompts_root: str = "./prompts"
```
(add this line alongside the other fields, e.g. right after `storage_root: str = "./storage"`)

`backend/prompts/resume_parsing/v1.jinja2`:
```
You are extracting structured resume data from raw text extracted from a PDF.
The text below may contain extraction artifacts (broken line breaks, stray
whitespace, table fragments) - work around that, but do not invent content
that is not present in the text.

CRITICAL RULE: If a piece of information is missing, unclear, or ambiguous in
the source text, leave the corresponding field null (or an empty list/string,
per its type) rather than guessing or inferring plausible-sounding content.
Never invent a company name, job title, date, degree, or bullet point that is
not directly present in the source text below. It is always better to leave a
field empty than to fabricate a plausible-sounding value.

Output ONLY a single JSON object matching exactly this shape (no markdown code
fences, no explanation, no extra text before or after the JSON):

{
  "schema_version": 1,
  "contact": {
    "full_name": "string, required",
    "email": "string or null",
    "phone": "string or null",
    "location": "string or null",
    "links": ["array of strings, may be empty"]
  },
  "summary": "string or null",
  "work_experience": [
    {
      "company": "string, required",
      "title": "string, required",
      "start_date": "string or null",
      "end_date": "string or null",
      "bullets": ["array of strings, may be empty"]
    }
  ],
  "projects": [
    {
      "name": "string, required",
      "description": "string or null",
      "bullets": ["array of strings, may be empty"],
      "technologies": ["array of strings, may be empty"]
    }
  ],
  "skills": ["array of strings, may be empty"],
  "education": [
    {
      "institution": "string, required",
      "degree": "string or null",
      "field_of_study": "string or null",
      "start_date": "string or null",
      "end_date": "string or null"
    }
  ],
  "certifications": ["array of strings, may be empty"]
}

If the source text has no work experience section at all, "work_experience"
must be an empty array []. If there is no projects section, "projects" must be
an empty array []. Do not fabricate entries to fill sections that are absent
from the source text.

Source text extracted from the resume PDF:

{{ extracted_text }}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `backend/`): `pytest tests/test_resume_parsing_prompt.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/prompts/resume_parsing/v1.jinja2 backend/tests/test_resume_parsing_prompt.py
git commit -m "feat: add resume_parsing prompt template with anti-fabrication instructions"
```

---

### Task 6: Orchestrator factory and Resume Parser service

**Files:**
- Create: `backend/app/core/llm/orchestrator_factory.py`
- Create: `backend/app/services/resume_parser.py`
- Test: `backend/tests/test_orchestrator_factory.py`
- Test: `backend/tests/test_resume_parser.py`

**Interfaces:**
- Consumes: `AIOrchestrator`, `TaskConfig`, `OrchestratorError` (Phase 1 Task 6), `make_db_logger` (Phase 1 Task 10), `NvidiaProvider` (Phase 1 Task 8, Task 2 fence-stripping), `GeminiProvider`/`ClaudeProvider`/`OpenAIProvider` (Phase 1 Task 9), `get_settings` (Phase 1 Task 1), `extract_text_from_pdf`/`has_extractable_text` (Task 4), `PromptRegistry` (Phase 1 Task 5), `LocalDiskStorage` (Phase 1 Task 2), `Resume`/`ResumeVersion` (Phase 1 Task 4), `ResumeDocument` (Phase 1 Task 3).
- Produces: `build_orchestrator(db: Session, session_id: int | None = None) -> AIOrchestrator`; `ResumeParsingError` (Exception); `parse_resume(db: Session, resume: Resume, storage: LocalDiskStorage, orchestrator: AIOrchestrator, prompt_registry: PromptRegistry) -> ResumeVersion`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_orchestrator_factory.py`:
```python
from app.core.llm.orchestrator_factory import build_orchestrator
from app.core.llm.orchestrator import AIOrchestrator
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base


def test_build_orchestrator_returns_configured_orchestrator():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = make_session_factory(engine)()

    orchestrator = build_orchestrator(db, session_id=None)

    assert isinstance(orchestrator, AIOrchestrator)
    assert set(orchestrator.providers.keys()) == {"nvidia", "gemini", "claude", "openai"}
```

`backend/tests/test_resume_parser.py`:
```python
import pytest
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, Resume, ResumeVersion
from app.core.llm.orchestrator import OrchestratorResult, OrchestratorError
from app.core.storage import LocalDiskStorage
from app.core.llm.prompt_registry import PromptRegistry
from app.models.resume import ResumeDocument, ContactInfo, WorkExperience
from app.services.resume_parser import parse_resume, ResumeParsingError
from tests.fixtures.pdf_fixtures import (
    build_sparse_bullets_resume_pdf, build_missing_section_resume_pdf, build_blank_pdf,
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


def test_parse_resume_persists_resume_version_and_raw_text(tmp_path):
    db = _make_db()
    storage = LocalDiskStorage(root=str(tmp_path))
    storage_path = storage.save("resumes/1/resume.pdf", build_sparse_bullets_resume_pdf())

    resume = Resume(original_filename="resume.pdf", storage_path=storage_path)
    db.add(resume)
    db.commit()

    parsed_document = ResumeDocument(
        contact=ContactInfo(full_name="Alex Lee", email=None, phone=None, location=None),
        summary=None,
        work_experience=[
            WorkExperience(
                company="Startup Co", title="Engineer", start_date="2022", end_date="2024",
                bullets=["Worked on backend"],
            ),
        ],
        projects=[], skills=[], education=[], certifications=[],
    )
    orchestrator = FakeOrchestrator(
        result=OrchestratorResult(output=parsed_document, provider_used="nvidia", attempts=1)
    )
    prompt_registry = PromptRegistry(prompts_root="prompts")

    version = parse_resume(db, resume, storage, orchestrator, prompt_registry)

    assert version.produced_by_stage == "resume_parsing"
    assert version.version_number == 1
    assert version.resume_json["contact"]["full_name"] == "Alex Lee"
    assert resume.raw_text is not None
    assert "Alex Lee" in resume.raw_text
    assert db.query(ResumeVersion).count() == 1


def test_parse_resume_does_not_fabricate_missing_sections(tmp_path):
    """Fabrication guard: fields absent from the source resume must come back
    null/empty in the persisted ResumeDocument, not filled in with invented content."""
    db = _make_db()
    storage = LocalDiskStorage(root=str(tmp_path))
    storage_path = storage.save("resumes/2/resume.pdf", build_missing_section_resume_pdf())

    resume = Resume(original_filename="resume.pdf", storage_path=storage_path)
    db.add(resume)
    db.commit()

    parsed_document = ResumeDocument(
        contact=ContactInfo(full_name="Sam Rivera"),
        summary="Full-stack developer.",
        work_experience=[
            WorkExperience(
                company="Widget LLC", title="Full-Stack Developer", start_date="2019", end_date="2024",
                bullets=["Built customer-facing dashboards using React and FastAPI"],
            ),
        ],
        projects=[],  # no projects section in source -> must stay empty, not invented
        skills=["JavaScript", "React", "FastAPI", "PostgreSQL"],
        education=[], certifications=[],
    )
    orchestrator = FakeOrchestrator(
        result=OrchestratorResult(output=parsed_document, provider_used="nvidia", attempts=1)
    )
    prompt_registry = PromptRegistry(prompts_root="prompts")

    version = parse_resume(db, resume, storage, orchestrator, prompt_registry)

    assert version.resume_json["projects"] == []


def test_parse_resume_fails_fast_on_blank_pdf_without_calling_orchestrator(tmp_path):
    db = _make_db()
    storage = LocalDiskStorage(root=str(tmp_path))
    storage_path = storage.save("resumes/3/resume.pdf", build_blank_pdf())

    resume = Resume(original_filename="resume.pdf", storage_path=storage_path)
    db.add(resume)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(ResumeParsingError, match="no extractable text"):
        parse_resume(db, resume, storage, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_parse_resume_wraps_orchestrator_error(tmp_path):
    db = _make_db()
    storage = LocalDiskStorage(root=str(tmp_path))
    storage_path = storage.save("resumes/4/resume.pdf", build_sparse_bullets_resume_pdf())

    resume = Resume(original_filename="resume.pdf", storage_path=storage_path)
    db.add(resume)
    db.commit()

    orchestrator = FakeOrchestrator(error=OrchestratorError("all providers exhausted"))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(ResumeParsingError):
        parse_resume(db, resume, storage, orchestrator, prompt_registry)
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_orchestrator_factory.py tests/test_resume_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.llm.orchestrator_factory'` (and `app.services.resume_parser`).

- [ ] **Step 3: Implement the factory and the service**

`backend/app/core/llm/orchestrator_factory.py`:
```python
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.llm.orchestrator import AIOrchestrator
from app.core.llm.llm_call_logger import make_db_logger
from app.core.llm.providers.nvidia_provider import NvidiaProvider
from app.core.llm.providers.stub_providers import GeminiProvider, ClaudeProvider, OpenAIProvider


def build_orchestrator(db: Session, session_id: int | None = None) -> AIOrchestrator:
    settings = get_settings()
    providers = {
        "nvidia": NvidiaProvider(api_key=settings.nvidia_api_key, base_url=settings.nvidia_base_url),
        "gemini": GeminiProvider(api_key=settings.gemini_api_key),
        "claude": ClaudeProvider(),
        "openai": OpenAIProvider(),
    }
    return AIOrchestrator(providers=providers, on_call_logged=make_db_logger(db, session_id=session_id))
```

`backend/app/services/resume_parser.py`:
```python
from sqlalchemy.orm import Session
from app.core.llm.orchestrator import AIOrchestrator, TaskConfig, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.core.storage import LocalDiskStorage
from app.models.db_models import Resume, ResumeVersion
from app.models.resume import ResumeDocument
from app.services.pdf_extractor import extract_text_from_pdf, has_extractable_text

RESUME_PARSING_MODEL = "z-ai/glm-5.2"
RESUME_PARSING_TEMPERATURE = 0.1


class ResumeParsingError(Exception):
    """Raised when resume parsing fails, whether at extraction or LLM-structuring."""


def parse_resume(
    db: Session,
    resume: Resume,
    storage: LocalDiskStorage,
    orchestrator: AIOrchestrator,
    prompt_registry: PromptRegistry,
) -> ResumeVersion:
    pdf_bytes = storage.load(resume.storage_path)
    extracted_text = extract_text_from_pdf(pdf_bytes)

    if not has_extractable_text(extracted_text):
        raise ResumeParsingError("no extractable text — this PDF may be scanned/image-based")

    prompt = prompt_registry.render("resume_parsing", "v1", extracted_text=extracted_text)
    task = TaskConfig(
        task_type="resume_parsing",
        provider="nvidia",
        model=RESUME_PARSING_MODEL,
        temperature=RESUME_PARSING_TEMPERATURE,
        response_schema=ResumeDocument,
        fallback_providers=[],
    )

    try:
        result = orchestrator.run(task, prompt=prompt)
    except OrchestratorError as exc:
        raise ResumeParsingError(str(exc)) from exc

    resume.raw_text = extracted_text

    version = ResumeVersion(
        resume_id=resume.id,
        version_number=1,
        resume_json=result.output.model_dump(),
        produced_by_stage="resume_parsing",
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `backend/`): `pytest tests/test_orchestrator_factory.py tests/test_resume_parser.py -v`
Expected: 5 passed (1 + 4)

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/llm/orchestrator_factory.py backend/app/services/resume_parser.py \
  backend/tests/test_orchestrator_factory.py backend/tests/test_resume_parser.py
git commit -m "feat: add orchestrator factory and Resume Parser service"
```

---

### Task 7: Prompt-registry startup wiring

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_main_startup.py`

**Interfaces:**
- Consumes: `PromptRegistry` (Phase 1 Task 5), `make_engine`/`make_session_factory` (Phase 1 Task 4), `get_settings` (Phase 1 Task 1).
- Produces: `sync_prompt_registry() -> None` in `app.main`, called from the app's `lifespan`.

**Known limitation (documented, not a bug):** SQLite and Postgres raise different exception classes for "table doesn't exist" — Postgres raises `sqlalchemy.exc.ProgrammingError` (propagates, fails startup loudly, as required), but SQLite's DBAPI raises `sqlite3.OperationalError`, which surfaces through SQLAlchemy as `sqlalchemy.exc.OperationalError` — the same class this hook tolerates for "DB not reachable yet." This means the "fail loudly on schema mismatch" guarantee is only exact for the Postgres/Docker path (the primary supported path per the spec); a local SQLite-based dev run with a genuinely missing table would be misclassified as "not reachable yet" and tolerated instead. This is called out explicitly rather than left as a silent gap.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_main_startup.py`:
```python
import pytest
from sqlalchemy.exc import OperationalError
from app.core.db import make_engine as real_make_engine, make_session_factory as real_make_session_factory
from app.models.db_models import Base, PromptVersion
import app.main as main_module


def test_sync_prompt_registry_tolerates_operational_error(monkeypatch):
    class BrokenRegistry:
        def sync_to_db(self, db):
            raise OperationalError("statement", {}, Exception("connection refused"))

    monkeypatch.setattr(main_module, "PromptRegistry", lambda prompts_root: BrokenRegistry())

    # Should not raise.
    main_module.sync_prompt_registry()


def test_sync_prompt_registry_propagates_non_operational_errors(monkeypatch):
    class BrokenRegistry:
        def sync_to_db(self, db):
            raise RuntimeError("schema mismatch: no such table prompt_versions")

    monkeypatch.setattr(main_module, "PromptRegistry", lambda prompts_root: BrokenRegistry())

    with pytest.raises(RuntimeError):
        main_module.sync_prompt_registry()


def test_sync_prompt_registry_succeeds_when_db_is_ready(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    test_engine = real_make_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(test_engine)

    monkeypatch.setattr(main_module, "make_engine", lambda database_url: test_engine)
    monkeypatch.setattr(main_module, "make_session_factory", lambda engine: real_make_session_factory(engine))

    # Should not raise, and should actually sync the resume_parsing template.
    main_module.sync_prompt_registry()

    with real_make_session_factory(test_engine)() as db:
        assert db.query(PromptVersion).filter_by(task_type="resume_parsing").count() >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_main_startup.py -v`
Expected: FAIL with `AttributeError: module 'app.main' has no attribute 'sync_prompt_registry'`

- [ ] **Step 3: Implement the startup hook**

`backend/app/main.py` (full replacement):
```python
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError
from app.api import resumes, job_postings, sessions, health
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.core.llm.prompt_registry import PromptRegistry

logger = logging.getLogger(__name__)


def sync_prompt_registry() -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    registry = PromptRegistry(prompts_root=settings.prompts_root)

    db = session_factory()
    try:
        registry.sync_to_db(db)
    except OperationalError:
        logger.warning(
            "Could not sync PromptRegistry at startup — database not reachable yet. "
            "Prompt templates will be out of sync with prompt_versions until the next successful sync."
        )
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    sync_prompt_registry()
    yield


app = FastAPI(title="Resume Tailor Backend", lifespan=lifespan)
app.include_router(resumes.router)
app.include_router(job_postings.router)
app.include_router(sessions.router)
app.include_router(health.router)


@app.get("/")
def root():
    return {"service": "resume-tailor-backend"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `backend/`): `pytest tests/test_main_startup.py -v`
Expected: 3 passed

- [ ] **Step 5: Run the full backend test suite**

Run (from `backend/`): `pytest -v`
Expected: all tests pass (existing Phase 1 suite + everything added in Tasks 1-7 of this plan) — the app's `lifespan` now runs on every `TestClient` startup used by `conftest.py`'s `client` fixture, so confirm no existing test broke from this change (the `client` fixture's DB is a fresh in-memory SQLite with `Base.metadata.create_all` already run before the app starts serving, so `sync_prompt_registry`'s real DB access during those tests' `lifespan` will succeed cleanly against that schema — verify this by checking for any new failures here specifically).

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/tests/test_main_startup.py
git commit -m "feat: sync PromptRegistry to DB on app startup, tolerating only connection errors"
```

---

### Task 8: Wire `resume_parsing` into `run_stage`

**Files:**
- Modify: `backend/app/api/sessions.py`
- Modify: `backend/tests/test_api_sessions.py`

**Interfaces:**
- Consumes: `build_orchestrator` (Task 6), `parse_resume`/`ResumeParsingError` (Task 6), `PromptRegistry` (Phase 1), `LocalDiskStorage`/`get_settings` (Phase 1), `make_engine`/`make_session_factory` (Phase 1).
- Produces: `run_stage` now executes `resume_parsing` for real; all other `stage_name` values still `501`.

**Timeout design note:** on timeout, the request thread stops waiting on the background thread running `parse_resume` — but that thread cannot be forcibly cancelled and may still be using the same `db: Session` object. Since SQLAlchemy `Session`s aren't safe for concurrent multi-thread use, the timeout branch below updates the `pipeline_runs` failure record through a **fresh, independent session** rather than reusing `db`. This is an accepted, documented limitation of the synchronous approach — real async/worker execution (a later phase) wouldn't have this problem.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_api_sessions.py`, first **replace** the existing `test_run_stage_returns_501_for_unimplemented_stage` test (its `resume_parsing` stage name is about to become real) with this renamed/adjusted version using a still-unimplemented stage name:

```python
def test_run_stage_returns_501_for_unimplemented_stage(client, db_session):
    resume = Resume(original_filename="jane.pdf", storage_path="/tmp/jane.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    response = client.post(f"/sessions/{session_id}/run-stage/jd_extraction")

    assert response.status_code == 501
```

Then add these new tests to the same file:

```python
class FakeResumeVersion:
    def __init__(self, id):
        self.id = id


def test_run_stage_resume_parsing_succeeds(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def fake_parse_resume(db, resume, storage, orchestrator, prompt_registry):
        return FakeResumeVersion(id=42)

    monkeypatch.setattr(sessions_module, "parse_resume", fake_parse_resume)

    response = client.post(f"/sessions/{session_id}/run-stage/resume_parsing")

    assert response.status_code == 200
    assert response.json() == {"stage_name": "resume_parsing", "status": "succeeded", "resume_version_id": 42}

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert len(runs) == 1
    assert runs[0]["stage_name"] == "resume_parsing"
    assert runs[0]["status"] == "succeeded"


def test_run_stage_resume_parsing_reports_failure(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module
    from app.services.resume_parser import ResumeParsingError

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def failing_parse_resume(db, resume, storage, orchestrator, prompt_registry):
        raise ResumeParsingError("no extractable text — this PDF may be scanned/image-based")

    monkeypatch.setattr(sessions_module, "parse_resume", failing_parse_resume)

    response = client.post(f"/sessions/{session_id}/run-stage/resume_parsing")

    assert response.status_code == 422

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert runs[0]["status"] == "failed"


def test_run_stage_resume_parsing_times_out(client, db_session, monkeypatch):
    import time
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def slow_parse_resume(db, resume, storage, orchestrator, prompt_registry):
        time.sleep(0.5)
        return FakeResumeVersion(id=99)

    monkeypatch.setattr(sessions_module, "parse_resume", slow_parse_resume)
    monkeypatch.setattr(sessions_module, "RESUME_PARSING_TIMEOUT_SECONDS", 0.05)

    response = client.post(f"/sessions/{session_id}/run-stage/resume_parsing")

    assert response.status_code == 504
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_api_sessions.py -v`
Expected: the renamed 501 test passes unchanged; the 3 new tests FAIL (resume_parsing still unconditionally 501s).

- [ ] **Step 3: Implement the real `resume_parsing` branch**

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
from app.services.resume_parser import parse_resume, ResumeParsingError

router = APIRouter(prefix="/sessions", tags=["sessions"])

RESUME_PARSING_TIMEOUT_SECONDS = 330
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


@router.post("/{session_id}/run-stage/{stage_name}")
def run_stage(session_id: int, stage_name: str, db: Session = Depends(get_db)):
    session = db.get(TailoringSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")

    if stage_name != "resume_parsing":
        raise HTTPException(
            status_code=501,
            detail=f"stage '{stage_name}' is not implemented yet (Phase 1 contract only)",
        )

    resume = db.get(Resume, session.resume_id)
    pipeline_run = PipelineRun(
        session_id=session_id, stage_name=stage_name, status="running", started_at=_utcnow(),
    )
    db.add(pipeline_run)
    db.commit()
    db.refresh(pipeline_run)

    settings = get_settings()
    storage = LocalDiskStorage(root=settings.storage_root)
    orchestrator = build_orchestrator(db, session_id=session_id)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)

    future = _STAGE_EXECUTOR.submit(parse_resume, db, resume, storage, orchestrator, prompt_registry)

    try:
        version = future.result(timeout=RESUME_PARSING_TIMEOUT_SECONDS)
    except FutureTimeoutError:
        # The worker thread is still running `parse_resume` in the background and cannot be
        # forcibly cancelled — it may still commit against `db` after we give up waiting on it.
        # Touching the same `db` Session from this (the request) thread while that's possible
        # is unsafe (SQLAlchemy Sessions aren't safe for concurrent multi-thread use), so the
        # failure record below is written through a fresh, independent session instead of `db`.
        error_message = f"resume_parsing timed out after {RESUME_PARSING_TIMEOUT_SECONDS} seconds"
        fresh_db = make_session_factory(make_engine(settings.database_url))()
        try:
            fresh_run = fresh_db.get(PipelineRun, pipeline_run.id)
            fresh_run.status = "failed"
            fresh_run.error_message = error_message
            fresh_run.completed_at = _utcnow()
            fresh_db.commit()
        finally:
            fresh_db.close()
        raise HTTPException(status_code=504, detail=error_message)
    except ResumeParsingError as exc:
        pipeline_run.status = "failed"
        pipeline_run.error_message = str(exc)
        pipeline_run.completed_at = _utcnow()
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc))

    pipeline_run.status = "succeeded"
    pipeline_run.completed_at = _utcnow()
    db.commit()

    return {"stage_name": stage_name, "status": "succeeded", "resume_version_id": version.id}


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

- [ ] **Step 4: Run tests to verify they pass**

Run (from `backend/`): `pytest tests/test_api_sessions.py -v`
Expected: all pass (the renamed 501 test + 3 new resume_parsing tests + all pre-existing session tests).

- [ ] **Step 5: Run the full backend test suite**

Run (from `backend/`): `pytest -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/sessions.py backend/tests/test_api_sessions.py
git commit -m "feat: wire real resume_parsing execution into run_stage with a thread-based timeout"
```

---

### Task 9: Manual smoke-test script

**Files:**
- Create: `backend/scripts/smoke_test_resume_parsing.py`

**Interfaces:**
- Consumes: everything from Tasks 1-8. Not run by pytest — manual verification only, costs a real NVIDIA API call.

- [ ] **Step 1: Write the script**

`backend/scripts/smoke_test_resume_parsing.py`:
```python
"""Manual smoke test: run with `python scripts/smoke_test_resume_parsing.py`
after setting NVIDIA_API_KEY in backend/.env. Costs a real API call — not run by pytest.

Parses a synthetic fixture PDF through the real NVIDIA API and prints the
resulting ResumeDocument JSON, so a human can manually verify the model
respects the "never fabricate, leave absent fields null" prompt instruction —
this fixture has a sparse work-experience bullet and no projects section, so
watch specifically for whether the model invents extra bullets or a projects
entry that isn't in the source text."""
import json
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.core.llm.orchestrator_factory import build_orchestrator
from app.core.llm.prompt_registry import PromptRegistry
from app.core.storage import LocalDiskStorage
from app.models.db_models import Base, Resume
from app.services.resume_parser import parse_resume
from tests.fixtures.pdf_fixtures import build_sparse_bullets_resume_pdf

if __name__ == "__main__":
    settings = get_settings()
    if not settings.nvidia_api_key:
        raise SystemExit("Set NVIDIA_API_KEY in backend/.env before running this script.")

    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = make_session_factory(engine)()

    storage = LocalDiskStorage(root="./storage")
    storage_path = storage.save("smoke_test/resume.pdf", build_sparse_bullets_resume_pdf())

    resume = Resume(original_filename="resume.pdf", storage_path=storage_path)
    db.add(resume)
    db.commit()

    orchestrator = build_orchestrator(db, session_id=None)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)

    version = parse_resume(db, resume, storage, orchestrator, prompt_registry)
    print(json.dumps(version.resume_json, indent=2))
```

- [ ] **Step 2: Commit**

```bash
git add backend/scripts/smoke_test_resume_parsing.py
git commit -m "feat: add manual smoke-test script for resume_parsing"
```

---

## Self-Review

**Spec coverage:**
- §1 (unique constraint + RESTRICT policy) → Task 1.
- §2 (extraction, structuring, persistence, version_number note) → Tasks 4, 6.
- §3 (anti-fabrication prompt requirement, tested against sparse/missing fixtures) → Tasks 3 (fixtures), 5 (prompt + content test), 6 (fabrication-guard persistence test).
- §4 (synchronous execution, 330s timeout math) → Task 8.
- §5 (startup wiring, OperationalError-only tolerance, documented SQLite/Postgres caveat) → Task 7.
- §6 (fixtures, mocked-provider unit tests, manual smoke script) → Tasks 3, 6, 9.
- §7 (out of scope: DOCX/OCR/GitHub-linkage/async/version-number-generalization) → not built anywhere in this plan; confirmed no task introduces any of them.
- The JSON code-fence gap (found while designing Task 6, not originally in the spec) is closed by Task 2, since it would otherwise silently undermine §2's "call the orchestrator" step the first time a real LLM wraps its output in markdown fences.

**Placeholder scan:** no TBD/TODO markers; every step has complete, runnable code.

**Type consistency:** `parse_resume(db, resume, storage, orchestrator, prompt_registry) -> ResumeVersion` signature matches exactly between Task 6 (definition), Task 8 (caller in `sessions.py`), and Task 9 (smoke script). `ResumeParsingError` is defined once in Task 6 and imported (not redefined) in Tasks 8/9. `build_orchestrator(db, session_id=None) -> AIOrchestrator` signature matches between Task 6 (definition) and Tasks 8/9 (callers). `RESUME_PARSING_TIMEOUT_SECONDS` is a module-level constant in `sessions.py` (Task 8), referenced by name (not hardcoded) in its own tests so the timeout test can monkeypatch it directly.

---

**Plan complete and saved to `docs/superpowers/plans/2026-07-04-phase2-resume-parsing.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
