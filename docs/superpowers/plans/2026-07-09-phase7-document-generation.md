# Phase 7 — Document Generation (LaTeX → PDF) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the tailored resume into a polished PDF via a LaTeX template compiled by Tectonic — the first phase producing a user-facing deliverable file rather than structured DB data.

**Architecture:** A dedicated LaTeX-safe Jinja2 renderer (`LatexRenderer`) converts the tailored resume's structured JSON into `.tex` source, using an `escape_latex()` filter for every user-supplied string. A `document_generator.py` service guards on a single prerequisite (a session-scoped `tailoring_rewrite` version must exist), compiles the `.tex` via a dependency-injected Tectonic-invoking callable, and persists the resulting PDF via the existing `Storage` protocol into a new `generated_documents.resume_version_id`-linked row. No LLM Orchestrator involvement anywhere in this phase.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Jinja2, Tectonic (new binary dependency) — no new Python package dependencies.

## Global Constraints

- Templates render via a **separate** Jinja2 `Environment` (not `PromptRegistry`), with LaTeX-safe delimiters: `variable_start_string="<<"`, `variable_end_string=">>"`, `block_start_string="<%"`, `block_end_string="%>"`, `comment_start_string="<#"`, `comment_end_string="#>"`, plus `trim_blocks=True, lstrip_blocks=True`.
- `escape_latex(text)` must handle `& % $ # _ { } ~ ^ \` correctly via a **single pass over the original characters** (not sequential `str.replace()` calls) — a multi-pass approach would re-scan and corrupt characters introduced by an earlier replacement (e.g. escaping `\` first as `\textbackslash{}` and then escaping `{`/`}` would also escape the braces just introduced).
- `generated_documents.resume_version_id`: new nullable FK (`ondelete="CASCADE"`) added via a new migration (0005), using `op.batch_alter_table` (per the established SQLite constraint-alteration workaround from migration 0004).
- `generated_documents.version_number` = `max(version_number for this session_id + document_type) + 1` — scoped to `(session_id, document_type)`, deliberately distinct from `resume_versions.version_number`'s global-per-resume counter, since this table has no resume-spanning identity.
- `document_type` for this phase's output is `"resume_pdf"`.
- Storage reuses the existing `Storage` protocol / `LocalDiskStorage` — key pattern `generated_documents/{session_id}/{document_type}_v{version_number}.pdf`.
- The Tectonic compiler is dependency-injected into `generate_document(...)` as a `latex_compiler` callable (`(tex_source: str) -> bytes`), mirroring how other services inject their `orchestrator`/`http_client` — this lets guard/persistence tests use a fake compiler with no real Tectonic needed.
- The one test that exercises the **real** Tectonic binary is gated with `pytest.mark.skipif` based on `shutil.which("tectonic")`, mirroring this project's existing Postgres-gated migration test pattern — it skips cleanly in every subagent's isolated worktree venv (which has no system Tectonic install) and only genuinely runs where Tectonic is actually installed (the Docker image, or a developer's local machine after following the README).
- `backend/Dockerfile` installs Tectonic and **pre-warms its LaTeX package cache at build time** (a throwaway compile during the image build) so the deployed container never needs network access to compile a resume at request time. Local dev/fresh checkouts do **not** pre-warm — the first real local compile needs network access to populate the package cache; this is a documented, accepted tradeoff, not a discovered surprise.
- `DocumentGenerationError` inherits `StageExecutionError`.
- Windows test runner for this repo: `py -3 -m pytest` (or venv-equivalent), run from `backend/`.
- Baseline before Task 1: 166 passed, 1 skipped (Postgres-dependent migration test).
- Expected final state after Task 6 (in an environment without Tectonic installed, i.e. every subagent's worktree): 192 passed, 2 skipped (Postgres-gated test + the new Tectonic-gated test).

---

### Task 1: Ledger cleanup (4 test-strictness fixes + 1 won't-fix documentation + 1 ledger correction)

**Files:**
- Modify: `backend/tests/test_resume_parsing_prompt.py`
- Modify: `backend/tests/test_resume_parser.py`
- Modify: `backend/tests/test_gap_analysis_schema.py`
- Modify: `backend/tests/test_gap_analyzer.py`
- Modify: `backend/app/services/tailoring_engine.py`

**Interfaces:**
- Consumes: nothing new — pure cleanup of existing Phase 2-5 code.
- Produces: nothing new — no later task depends on this task's changes.

This task closes 4 test-strictness gaps flagged by Phase 6's final review, and formally closes 2 by-design items as won't-fix. **Important note on the second won't-fix item**: the "substring-within-token skill matching" item was already fixed by an earlier dedicated bug-fix commit (tokenized word-boundary matching replaced raw substring checks) — this task marks that item CLOSED with a note that it was resolved earlier, not carried forward as a fresh won't-fix, since the current code no longer does substring matching at all. Only the `certifications` count-only-check item is a genuine still-open by-design item needing a documentation comment.

- [ ] **Step 1: Write the JSON-shape test for the resume_parsing prompt**

Add to `backend/tests/test_resume_parsing_prompt.py`, with a new import at the top:

```python
import re
from app.models.resume import ResumeDocument, ContactInfo, WorkExperience, Project, Education
```

```python
def test_resume_parsing_prompt_json_shape_matches_resume_document_fields():
    """Ledger item: previously this prompt's fabrication-guard test only checked
    keyword presence, not that the prompt's declared JSON shape actually matches
    ResumeDocument's real fields (top-level and nested)."""
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render("resume_parsing", "v1", extracted_text="Jane Doe\nEngineer")

    shape_start = rendered.index('{\n  "schema_version"')
    shape_end = rendered.index("\n\nIf the source text has no work experience")
    shape_block = rendered[shape_start:shape_end]

    keys_in_prompt = set(re.findall(r'"(\w+)":', shape_block))

    expected_keys = (
        set(ResumeDocument.model_fields.keys())
        | set(ContactInfo.model_fields.keys())
        | set(WorkExperience.model_fields.keys())
        | set(Project.model_fields.keys())
        | set(Education.model_fields.keys())
    )
    assert keys_in_prompt == expected_keys
```

- [ ] **Step 2: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_resume_parsing_prompt.py -v` (from `backend/`)
Expected: 3 passed (2 pre-existing + this new one). This should pass immediately without any prompt changes — the prompt's declared shape already matches `ResumeDocument`'s real fields; this test just makes that fact automatically verified going forward instead of only checked manually.

- [ ] **Step 3: Broaden the parse_resume fabrication guard assertions**

In `backend/tests/test_resume_parser.py`, change the end of `test_parse_resume_does_not_fabricate_missing_sections`:

```python
    version = parse_resume(db, resume, storage, orchestrator, prompt_registry)

    assert version.resume_json["projects"] == []
    assert version.resume_json["education"] == []
    assert version.resume_json["certifications"] == []
```

- [ ] **Step 4: Add the serialized-field-presence check to the gap-analysis schema roundtrip test**

In `backend/tests/test_gap_analysis_schema.py`, change `test_gap_analysis_document_roundtrips_through_json`:

```python
def test_gap_analysis_document_roundtrips_through_json():
    doc = GapAnalysisDocument(
        matching_skills=["Python", "PostgreSQL"],
        missing_skills=["Docker", "Kubernetes"],
        experience_gap_notes="JD wants 5+ years; resume shows 3 years.",
        relevant_projects=["Inventory Tracker"],
        irrelevant_projects=["Weekend Recipe App"],
        recommended_keywords=["distributed systems"],
    )
    serialized = doc.model_dump_json()
    # Ledger item: confirm schema_version is genuinely present in the serialized
    # JSON, not silently dropped and merely coincidentally reconstructed via its
    # own default value on the restored side (which would make a naive
    # restored == doc comparison pass even if the field were never serialized).
    assert '"schema_version"' in serialized
    restored = GapAnalysisDocument.model_validate_json(serialized)
    assert restored == doc
```

- [ ] **Step 5: Add the orchestrator-was-called assertion**

In `backend/tests/test_gap_analyzer.py`, change the end of `test_analyze_gap_wraps_orchestrator_error`:

```python
    orchestrator = FakeOrchestrator(error=OrchestratorError("all providers exhausted"))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(GapAnalysisError):
        analyze_gap(db, session, orchestrator, prompt_registry)

    assert len(orchestrator.calls) == 1
```

- [ ] **Step 6: Add the won't-fix documentation comment for certifications' count-only check**

In `backend/app/services/tailoring_engine.py`, in `_validate_entries_preserved`, add a comment right after the count-check loop and before the project-identity check:

```python
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

    # Won't-fix (documented, not a gap): certifications only gets the count check
    # above, no identity-set check like projects/work_experience/education get
    # below. Unlike those, a certification is a bare string with no natural
    # identity key to compare on (no name/company+title/institution) - a
    # same-count swap of one certification string for another wouldn't be
    # caught here. Accepted for this phase; would need a different mechanism
    # (e.g. treating certification order as significant) if this ever matters.
    original_project_names = {project["name"] for project in original_resume_json.get("projects", [])}
```

- [ ] **Step 7: Run the full suite to confirm no regressions**

Run: `py -3 -m pytest -q` (from `backend/`)
Expected: 167 passed, 1 skipped (166 baseline + 1 new test from Step 1; Steps 3-5 only added assertions to existing tests, not new test functions).

- [ ] **Step 8: Commit**

```bash
git add backend/tests/test_resume_parsing_prompt.py backend/tests/test_resume_parser.py backend/tests/test_gap_analysis_schema.py backend/tests/test_gap_analyzer.py backend/app/services/tailoring_engine.py
git commit -m "fix: close 4 test-strictness ledger items, document 1 won't-fix, correct 1 stale ledger label"
```

---

### Task 2: `escape_latex()` module

**Files:**
- Create: `backend/app/services/latex_escape.py`
- Test: `backend/tests/test_latex_escape.py`

**Interfaces:**
- Consumes: nothing new — pure string function.
- Produces: `escape_latex(text: str | None) -> str`. Consumed by Task 4 (`LatexRenderer`, as a Jinja2 filter).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_latex_escape.py`:

```python
import pytest
from app.services.latex_escape import escape_latex


@pytest.mark.parametrize("raw,expected", [
    ("&", r"\&"),
    ("%", r"\%"),
    ("$", r"\$"),
    ("#", r"\#"),
    ("_", r"\_"),
    ("{", r"\{"),
    ("}", r"\}"),
    ("~", r"\textasciitilde{}"),
    ("^", r"\textasciicircum{}"),
    ("\\", r"\textbackslash{}"),
])
def test_escape_latex_handles_each_special_character_individually(raw, expected):
    assert escape_latex(raw) == expected


def test_escape_latex_handles_a_realistic_composite_string():
    raw = "Improved throughput 40% using C++ & Python, cost $50/mo, see file_name.py"
    expected = r"Improved throughput 40\% using C++ \& Python, cost \$50/mo, see file\_name.py"
    assert escape_latex(raw) == expected


def test_escape_latex_does_not_corrupt_backslash_replacement_with_later_brace_escaping():
    """Regression guard for the single-pass design: escaping backslash first as
    \\textbackslash{} must not have its own braces re-escaped by a later pass
    over {/} - a naive sequential str.replace() approach would corrupt this."""
    assert escape_latex("\\") == r"\textbackslash{}"
    assert escape_latex("a\\b") == r"a\textbackslash{}b"


def test_escape_latex_handles_plain_text_unchanged():
    assert escape_latex("Jane Doe") == "Jane Doe"


def test_escape_latex_handles_none_as_empty_string():
    assert escape_latex(None) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_latex_escape.py -v` (from `backend/`)
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.latex_escape'`

- [ ] **Step 3: Write the escaping module**

`backend/app/services/latex_escape.py`:

```python
_LATEX_ESCAPE_MAP = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def escape_latex(text: str | None) -> str:
    """Escape a plain string for safe insertion into LaTeX source.

    Builds the result in a SINGLE pass over the original characters (not
    sequential global str.replace() calls), since a naive multi-pass approach
    would re-scan and corrupt characters introduced by an earlier replacement
    - e.g. escaping "\\" first as "\\textbackslash{}" and THEN escaping "{"/"}"
    in a later pass would also escape the braces just introduced, corrupting
    the output into "\\textbackslash\\{\\}". Iterating once over the original
    characters and mapping each to its replacement (or itself) avoids this
    entirely, since replacement text is never re-scanned.
    """
    if text is None:
        return ""
    return "".join(_LATEX_ESCAPE_MAP.get(char, char) for char in text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_latex_escape.py -v`
Expected: 14 passed (10 parametrized cases + 4 standalone tests)

- [ ] **Step 5: Run the full suite**

Run: `py -3 -m pytest -q` (from `backend/`)
Expected: 181 passed, 1 skipped (167 after Task 1, + 14 from this task).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/latex_escape.py backend/tests/test_latex_escape.py
git commit -m "feat: add escape_latex with single-pass character mapping"
```

---

### Task 3: `generated_documents.resume_version_id` migration

**Files:**
- Modify: `backend/app/models/db_models.py`
- Create: `backend/alembic/versions/0005_generated_document_resume_version.py`
- Modify: `backend/tests/test_db_models.py`
- Create: `backend/tests/test_migration_0005_generated_document_resume_version.py`

**Interfaces:**
- Consumes: `Base` (from `app.models.db_models`, already exists).
- Produces: `GeneratedDocument.resume_version_id` column. Consumed by Task 5 (`document_generator.py` sets this field).

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_db_models.py`, update both `test_all_tables_create_and_accept_a_linked_row` and `test_deleting_a_session_cascades_to_its_dependent_rows_including_tailored_version`: change the `document = GeneratedDocument(...)` construction in **both** functions to:

```python
        document = GeneratedDocument(
            session_id=session.id, resume_version_id=version.id, document_type="ats_report",
            content="report body", version_number=1,
        )
```

And in `test_all_tables_create_and_accept_a_linked_row`, add this assertion right after the existing `assert db.query(TailoringChange)...` line:

```python
        assert db.query(GeneratedDocument).first().resume_version_id == version.id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3 -m pytest tests/test_db_models.py -v` (from `backend/`)
Expected: FAIL with `TypeError: 'resume_version_id' is an invalid keyword argument for GeneratedDocument`

- [ ] **Step 3: Add `resume_version_id` to the ORM class**

In `backend/app/models/db_models.py`, modify `GeneratedDocument`:

```python
class GeneratedDocument(Base):
    __tablename__ = "generated_documents"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("tailoring_sessions.id", ondelete="CASCADE"), nullable=False)
    resume_version_id = Column(Integer, ForeignKey("resume_versions.id", ondelete="CASCADE"), nullable=True)
    document_type = Column(String, nullable=False)
    storage_path = Column(String, nullable=True)
    content = Column(Text, nullable=True)
    version_number = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `py -3 -m pytest tests/test_db_models.py -v`
Expected: 4 passed

- [ ] **Step 5: Write the Alembic migration**

`backend/alembic/versions/0005_generated_document_resume_version.py`:

```python
"""generated_documents.resume_version_id

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-09

Note: see migration 0004's docstring for why a plain op.add_column with an
inline ForeignKey fails on SQLite outside batch mode - the same reasoning
applies here, so this column and its FK are added via op.batch_alter_table.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("generated_documents") as batch_op:
        batch_op.add_column(sa.Column("resume_version_id", sa.Integer, nullable=True))
        batch_op.create_foreign_key(
            "fk_generated_documents_resume_version_id", "resume_versions", ["resume_version_id"], ["id"],
            ondelete="CASCADE",
        )


def downgrade():
    with op.batch_alter_table("generated_documents") as batch_op:
        batch_op.drop_constraint("fk_generated_documents_resume_version_id", type_="foreignkey")
        batch_op.drop_column("resume_version_id")
```

- [ ] **Step 6: Write the migration test**

`backend/tests/test_migration_0005_generated_document_resume_version.py`:

```python
"""Migration test for 0005 (generated_documents.resume_version_id): confirms
upgrade() adds the column+FK and downgrade() cleanly reverses it. Uses
op.batch_alter_table for the same SQLite reason documented in migration 0004."""
import importlib.util
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"
MIGRATION_0001_PATH = VERSIONS_DIR / "0001_initial_schema.py"
MIGRATION_0005_PATH = VERSIONS_DIR / "0005_generated_document_resume_version.py"


def _load_migration(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_0005_adds_and_drops_resume_version_id():
    migration_0001 = _load_migration(MIGRATION_0001_PATH, "migration_0001_for_0005_test")
    migration_0005 = _load_migration(MIGRATION_0005_PATH, "migration_0005_under_test")

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))

        migration_context = MigrationContext.configure(connection)
        with Operations.context(migration_context):
            migration_0001.upgrade()
        connection.commit()

        inspector = inspect(engine)
        assert "resume_version_id" not in [col["name"] for col in inspector.get_columns("generated_documents")]

        migration_context = MigrationContext.configure(connection)
        with Operations.context(migration_context):
            migration_0005.upgrade()
        connection.commit()

        inspector = inspect(engine)
        assert "resume_version_id" in [col["name"] for col in inspector.get_columns("generated_documents")]

        migration_context = MigrationContext.configure(connection)
        with Operations.context(migration_context):
            migration_0005.downgrade()
        connection.commit()

        inspector = inspect(engine)
        assert "resume_version_id" not in [col["name"] for col in inspector.get_columns("generated_documents")]
```

- [ ] **Step 7: Run the new migration test**

Run: `py -3 -m pytest tests/test_migration_0005_generated_document_resume_version.py -v`
Expected: 1 passed

- [ ] **Step 8: Run the full suite**

Run: `py -3 -m pytest -q` (from `backend/`)
Expected: 182 passed, 1 skipped (181 after Task 2, + 1 net new here — `test_db_models.py`'s existing tests are modified, not added, plus 1 new migration test).

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/db_models.py backend/alembic/versions/0005_generated_document_resume_version.py backend/tests/test_db_models.py backend/tests/test_migration_0005_generated_document_resume_version.py
git commit -m "feat: add generated_documents.resume_version_id"
```

---

### Task 4: LaTeX-safe Jinja2 renderer and default resume template

**Files:**
- Create: `backend/latex_templates/resume/default.tex`
- Create: `backend/app/services/latex_renderer.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_latex_renderer.py`

**Interfaces:**
- Consumes: `escape_latex` (Task 2).
- Produces: `LatexRenderer(templates_root: str)` with `.render(resume_json: dict, template_name: str = "default") -> str`. Consumed by Task 5 (`document_generator.py`).

- [ ] **Step 1: Add the `latex_templates_root` setting**

In `backend/app/core/config.py`, add a new field to `Settings`:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./resume_tailor.db"
    storage_root: str = "./storage"
    prompts_root: str = "./prompts"
    latex_templates_root: str = "./latex_templates"
    gemini_api_key: str | None = None
    nvidia_api_key: str | None = None
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    hiring_agent_service_url: str = "http://localhost:8100"
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_latex_renderer.py`:

```python
from app.services.latex_renderer import LatexRenderer


def _fully_populated_resume() -> dict:
    return {
        "contact": {
            "full_name": "Jane Doe", "email": "jane@example.com", "phone": "555-1234",
            "location": "Springfield", "links": ["https://github.com/janedoe"],
        },
        "summary": "Backend engineer with 5 years of experience.",
        "work_experience": [
            {
                "company": "Acme Corp", "title": "Senior Backend Engineer",
                "start_date": "2021", "end_date": "2024",
                "bullets": ["Built payment systems"],
            },
        ],
        "projects": [
            {
                "name": "Task Queue", "description": "A distributed task queue",
                "bullets": ["400+ GitHub stars"], "technologies": ["Python", "Redis"],
            },
        ],
        "skills": ["Python", "PostgreSQL"],
        "education": [
            {
                "institution": "State University", "degree": "B.S.",
                "field_of_study": "Computer Science", "start_date": "2014", "end_date": "2018",
            },
        ],
        "certifications": ["AWS Certified Solutions Architect"],
    }


def test_latex_renderer_produces_valid_tex_for_fully_populated_resume():
    renderer = LatexRenderer(templates_root="latex_templates")

    tex_source = renderer.render(_fully_populated_resume())

    assert r"\documentclass" in tex_source
    assert r"\begin{document}" in tex_source
    assert r"\end{document}" in tex_source
    assert "Jane Doe" in tex_source
    assert "Springfield" in tex_source
    assert "Senior Backend Engineer" in tex_source
    assert "Task Queue" in tex_source
    assert "State University" in tex_source
    assert "AWS Certified Solutions Architect" in tex_source
    # No unresolved LaTeX-safe Jinja2 delimiters should remain in the output -
    # this would indicate a missing variable or a template typo.
    assert "<<" not in tex_source
    assert "%>" not in tex_source


def test_latex_renderer_handles_optional_fields_gracefully_for_sparse_resume():
    """Per this phase's spec: the first phase rendering the full breadth of
    ResumeDocument's optional fields into a document a real user sees, so
    missing/empty optional fields must degrade gracefully, not error or emit
    stray empty section headers."""
    sparse_resume = {
        "contact": {
            "full_name": "Alex Lee", "email": "alex@example.com", "phone": None,
            "location": None, "links": [],
        },
        "summary": None,
        "work_experience": [
            {
                "company": "Startup Co", "title": "Engineer",
                "start_date": "2022", "end_date": "2024", "bullets": [],
            },
        ],
        "projects": [],
        "skills": [],
        "education": [],
        "certifications": [],
    }

    tex_source = LatexRenderer(templates_root="latex_templates").render(sparse_resume)

    assert "Alex Lee" in tex_source
    assert "Startup Co" in tex_source
    assert r"\section*{Summary}" not in tex_source
    assert r"\section*{Projects}" not in tex_source
    assert r"\section*{Education}" not in tex_source
    assert r"\section*{Certifications}" not in tex_source
    assert "<<" not in tex_source
    assert "%>" not in tex_source


def test_latex_renderer_escapes_special_characters_in_resume_fields():
    resume = _fully_populated_resume()
    resume["work_experience"][0]["bullets"] = ["Improved throughput 40% using C++ & Python"]

    tex_source = LatexRenderer(templates_root="latex_templates").render(resume)

    assert r"40\%" in tex_source
    assert r"\&" in tex_source
    # The raw, unescaped characters must not appear in the rendered bullet text.
    assert "40% using" not in tex_source
    assert "C++ & Python" not in tex_source
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_latex_renderer.py -v` (from `backend/`)
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.latex_renderer'`

- [ ] **Step 4: Write the LaTeX template**

`backend/latex_templates/resume/default.tex`:

```
\documentclass[11pt]{article}
\usepackage[margin=0.75in]{geometry}
\usepackage{enumitem}
\usepackage{hyperref}
\pagestyle{empty}

\begin{document}

\begin{center}
{\LARGE \textbf{<< resume.contact.full_name | latex_escape >>}}
<% if contact_line_parts %>\\[4pt]
<< contact_line_parts | join(" | ") | latex_escape >>
<% endif %>
<% if resume.contact.links %>\\[2pt]
<< resume.contact.links | join(" | ") | latex_escape >>
<% endif %>
\end{center}

<% if resume.summary %>
\section*{Summary}
<< resume.summary | latex_escape >>
<% endif %>

<% if resume.work_experience %>
\section*{Experience}
<% for entry in resume.work_experience %>
\textbf{<< entry.title | latex_escape >>} at \textbf{<< entry.company | latex_escape >>} \hfill << entry.start_date | latex_escape >> -- << entry.end_date | latex_escape >>
<% if entry.bullets %>
\begin{itemize}[leftmargin=*, noitemsep]
<% for bullet in entry.bullets %>\item << bullet | latex_escape >>
<% endfor %>
\end{itemize}
<% endif %>
<% endfor %>
<% endif %>

<% if resume.projects %>
\section*{Projects}
<% for project in resume.projects %>
\textbf{<< project.name | latex_escape >>}<% if project.description %> -- << project.description | latex_escape >><% endif %>
<% if project.bullets %>
\begin{itemize}[leftmargin=*, noitemsep]
<% for bullet in project.bullets %>\item << bullet | latex_escape >>
<% endfor %>
\end{itemize}
<% endif %>
<% if project.technologies %>
\textit{Technologies: << project.technologies | join(", ") | latex_escape >>}
<% endif %>
<% endfor %>
<% endif %>

<% if resume.skills %>
\section*{Skills}
<< resume.skills | join(", ") | latex_escape >>
<% endif %>

<% if resume.education %>
\section*{Education}
<% for entry in resume.education %>
\textbf{<< entry.institution | latex_escape >>}<% if entry.degree %>, << entry.degree | latex_escape >><% endif %><% if entry.field_of_study %>, << entry.field_of_study | latex_escape >><% endif %> \hfill << entry.start_date | latex_escape >> -- << entry.end_date | latex_escape >>
<% endfor %>
<% endif %>

<% if resume.certifications %>
\section*{Certifications}
\begin{itemize}[leftmargin=*, noitemsep]
<% for cert in resume.certifications %>\item << cert | latex_escape >>
<% endfor %>
\end{itemize}
<% endif %>

\end{document}
```

- [ ] **Step 5: Write the renderer**

`backend/app/services/latex_renderer.py`:

```python
import jinja2
from app.services.latex_escape import escape_latex


class LatexRenderer:
    def __init__(self, templates_root: str):
        self.templates_root = templates_root
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(templates_root),
            variable_start_string="<<", variable_end_string=">>",
            block_start_string="<%", block_end_string="%>",
            comment_start_string="<#", comment_end_string="#>",
            trim_blocks=True, lstrip_blocks=True,
        )
        self._env.filters["latex_escape"] = escape_latex

    def render(self, resume_json: dict, template_name: str = "default") -> str:
        template = self._env.get_template(f"resume/{template_name}.tex")
        contact = resume_json.get("contact", {})
        contact_line_parts = [
            part for part in (contact.get("email"), contact.get("phone"), contact.get("location")) if part
        ]
        return template.render(resume=resume_json, contact_line_parts=contact_line_parts)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_latex_renderer.py -v`
Expected: 3 passed

- [ ] **Step 7: Run the full suite**

Run: `py -3 -m pytest -q` (from `backend/`)
Expected: 185 passed, 1 skipped (182 after Task 3, + 3 from this task).

- [ ] **Step 8: Commit**

```bash
git add backend/latex_templates/resume/default.tex backend/app/services/latex_renderer.py backend/app/core/config.py backend/tests/test_latex_renderer.py
git commit -m "feat: add LatexRenderer with LaTeX-safe Jinja2 delimiters and default resume template"
```

---

### Task 5: Document Generator service

**Files:**
- Create: `backend/app/services/document_generator.py`
- Test: `backend/tests/test_document_generator.py`

**Interfaces:**
- Consumes: `LatexRenderer` (Task 4), `Storage` protocol / `LocalDiskStorage` (existing, `app.core.storage`), `TailoringSession`/`ResumeVersion`/`GeneratedDocument` (`app.models.db_models`), `StageExecutionError` (`app.services.errors`).
- Produces: `generate_document(db, session, storage, latex_renderer, latex_compiler) -> GeneratedDocument`, `_compile_latex_to_pdf(tex_source: str) -> bytes` (the real Tectonic-invoking implementation), `DocumentGenerationError` (exception, inherits `StageExecutionError`). Consumed by Task 6 (`sessions.py`'s `_run_document_generation`).

`latex_compiler` is any callable `(tex_source: str) -> bytes` — `_compile_latex_to_pdf` in production, a fake in most tests (the guard/persistence tests don't need a real compile).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_document_generator.py`:

```python
import shutil
import pytest
from app.core.db import make_engine, make_session_factory
from app.core.storage import LocalDiskStorage
from app.models.db_models import Base, Resume, ResumeVersion, JobPosting, TailoringSession, GeneratedDocument
from app.services.document_generator import generate_document, _compile_latex_to_pdf, DocumentGenerationError
from app.services.latex_renderer import LatexRenderer

TECTONIC_AVAILABLE = shutil.which("tectonic") is not None


class FakeLatexCompiler:
    def __init__(self, pdf_bytes=None, error=None):
        self._pdf_bytes = pdf_bytes if pdf_bytes is not None else b"%PDF-1.4 fake pdf bytes"
        self._error = error
        self.calls = []

    def __call__(self, tex_source: str) -> bytes:
        self.calls.append(tex_source)
        if self._error is not None:
            raise self._error
        return self._pdf_bytes


def _make_db():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def _make_session_with_tailored_version(db):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()

    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    tailored_version = ResumeVersion(
        resume_id=resume.id, session_id=session.id, version_number=2,
        resume_json={"contact": {"full_name": "Jane Doe"}, "skills": ["Python"]},
        produced_by_stage="tailoring_rewrite",
    )
    db.add(tailored_version)
    db.commit()

    return session, tailored_version


def test_generate_document_persists_pdf_and_links_ids(tmp_path):
    db = _make_db()
    session, tailored_version = _make_session_with_tailored_version(db)
    storage = LocalDiskStorage(root=str(tmp_path))
    latex_renderer = LatexRenderer(templates_root="latex_templates")
    latex_compiler = FakeLatexCompiler()

    document = generate_document(db, session, storage, latex_renderer, latex_compiler)

    assert document.session_id == session.id
    assert document.resume_version_id == tailored_version.id
    assert document.document_type == "resume_pdf"
    assert document.version_number == 1
    assert document.content is None
    assert db.query(GeneratedDocument).count() == 1

    from pathlib import Path
    assert Path(document.storage_path).read_bytes() == b"%PDF-1.4 fake pdf bytes"


def test_generate_document_fails_fast_when_no_tailored_version_without_compiling(tmp_path):
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    storage = LocalDiskStorage(root=str(tmp_path))
    latex_renderer = LatexRenderer(templates_root="latex_templates")
    latex_compiler = FakeLatexCompiler()

    with pytest.raises(DocumentGenerationError, match="tailoring_rewrite"):
        generate_document(db, session, storage, latex_renderer, latex_compiler)

    assert latex_compiler.calls == []


def test_generate_document_wraps_compiler_error(tmp_path):
    db = _make_db()
    session, tailored_version = _make_session_with_tailored_version(db)
    storage = LocalDiskStorage(root=str(tmp_path))
    latex_renderer = LatexRenderer(templates_root="latex_templates")
    latex_compiler = FakeLatexCompiler(error=DocumentGenerationError("tectonic compile failed: mock error"))

    with pytest.raises(DocumentGenerationError):
        generate_document(db, session, storage, latex_renderer, latex_compiler)

    assert db.query(GeneratedDocument).count() == 0


def test_generate_document_version_numbering_increments_within_session(tmp_path):
    db = _make_db()
    session, tailored_version = _make_session_with_tailored_version(db)
    storage = LocalDiskStorage(root=str(tmp_path))
    latex_renderer = LatexRenderer(templates_root="latex_templates")
    latex_compiler = FakeLatexCompiler()

    first_document = generate_document(db, session, storage, latex_renderer, latex_compiler)
    second_document = generate_document(db, session, storage, latex_renderer, latex_compiler)

    assert first_document.version_number == 1
    assert second_document.version_number == 2


@pytest.mark.skipif(
    not TECTONIC_AVAILABLE,
    reason="requires the tectonic binary on PATH - see README for install instructions",
)
def test_compile_latex_to_pdf_produces_a_valid_pdf():
    tex_source = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "Hello, world.\n"
        "\\end{document}\n"
    )

    pdf_bytes = _compile_latex_to_pdf(tex_source)

    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 500
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_document_generator.py -v` (from `backend/`)
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.document_generator'`

- [ ] **Step 3: Write the service**

`backend/app/services/document_generator.py`:

```python
import subprocess
import tempfile
from pathlib import Path
from sqlalchemy.orm import Session
from app.core.storage import Storage
from app.models.db_models import TailoringSession, ResumeVersion, GeneratedDocument
from app.services.latex_renderer import LatexRenderer
from app.services.errors import StageExecutionError

DOCUMENT_TYPE = "resume_pdf"
TECTONIC_TIMEOUT_SECONDS = 120


class DocumentGenerationError(StageExecutionError):
    """Raised when PDF generation fails: unmet tailoring_rewrite prerequisite,
    or a Tectonic compilation failure (malformed LaTeX, missing binary, or
    timeout)."""


def _compile_latex_to_pdf(tex_source: str) -> bytes:
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        tex_path = temp_path / "resume.tex"
        tex_path.write_text(tex_source, encoding="utf-8")

        try:
            result = subprocess.run(
                ["tectonic", "resume.tex"],
                cwd=temp_dir, capture_output=True, timeout=TECTONIC_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            raise DocumentGenerationError(f"tectonic binary not found: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise DocumentGenerationError(
                f"tectonic compile timed out after {TECTONIC_TIMEOUT_SECONDS} seconds"
            ) from exc

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            raise DocumentGenerationError(f"tectonic compile failed: {stderr}")

        pdf_path = temp_path / "resume.pdf"
        return pdf_path.read_bytes()


def _next_version_number(db: Session, session_id: int, document_type: str) -> int:
    latest = (
        db.query(GeneratedDocument)
        .filter_by(session_id=session_id, document_type=document_type)
        .order_by(GeneratedDocument.version_number.desc())
        .first()
    )
    return (latest.version_number if latest else 0) + 1


def generate_document(
    db: Session,
    session: TailoringSession,
    storage: Storage,
    latex_renderer: LatexRenderer,
    latex_compiler,
) -> GeneratedDocument:
    tailored_version = (
        db.query(ResumeVersion)
        .filter_by(session_id=session.id, produced_by_stage="tailoring_rewrite")
        .order_by(ResumeVersion.id.desc())
        .first()
    )
    if tailored_version is None:
        raise DocumentGenerationError("tailoring_rewrite has not succeeded for this session yet")

    tex_source = latex_renderer.render(tailored_version.resume_json)
    pdf_bytes = latex_compiler(tex_source)

    version_number = _next_version_number(db, session.id, DOCUMENT_TYPE)
    storage_key = f"generated_documents/{session.id}/{DOCUMENT_TYPE}_v{version_number}.pdf"
    storage_path = storage.save(storage_key, pdf_bytes)

    document = GeneratedDocument(
        session_id=session.id,
        resume_version_id=tailored_version.id,
        document_type=DOCUMENT_TYPE,
        storage_path=storage_path,
        content=None,
        version_number=version_number,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_document_generator.py -v`
Expected: 4 passed, 1 skipped (the Tectonic-gated test skips unless `tectonic` is on `PATH` in this environment).

- [ ] **Step 5: Run the full suite**

Run: `py -3 -m pytest -q` (from `backend/`)
Expected: 189 passed, 2 skipped (185 after Task 4, + 4 new passing tests; the 5th new test adds a 2nd skip in an environment without Tectonic).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/document_generator.py backend/tests/test_document_generator.py
git commit -m "feat: add document generator service with Tectonic compilation and injectable compiler"
```

---

### Task 6: Wire `document_generation` into `run_stage`

**Files:**
- Modify: `backend/app/api/sessions.py`
- Modify: `backend/tests/test_api_sessions.py`

**Interfaces:**
- Consumes: `generate_document`, `_compile_latex_to_pdf` (Task 5), `LatexRenderer` (Task 4), `STAGE_RUNNERS`/`STAGE_TIMEOUT_SECONDS`/`run_stage` (existing, `app.api.sessions`).
- Produces: `STAGE_RUNNERS["document_generation"]` entry; `POST /sessions/{id}/run-stage/document_generation` returns `{"stage_name": "document_generation", "status": "succeeded", "generated_document_id": <int>}` on success.

- [ ] **Step 1: Update the stale 501 test and add the new document_generation tests**

In `backend/tests/test_api_sessions.py`, change `test_run_stage_returns_501_for_unimplemented_stage` (which currently posts to `document_generation`, now implemented for real) to target a genuinely-still-unimplemented stage name:

```python
def test_run_stage_returns_501_for_unimplemented_stage(client, db_session):
    resume = Resume(original_filename="jane.pdf", storage_path="/tmp/jane.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    response = client.post(f"/sessions/{session_id}/run-stage/cover_letter_generation")

    assert response.status_code == 501
```

Add these new tests to the same file:

```python
def test_run_stage_document_generation_succeeds(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job", raw_text="Barista at Corner Cafe.")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    class FakeGeneratedDocument:
        def __init__(self, id):
            self.id = id

    def fake_generate_document(db, session, storage, latex_renderer, latex_compiler):
        return FakeGeneratedDocument(id=7)

    monkeypatch.setattr(sessions_module, "generate_document", fake_generate_document)

    response = client.post(f"/sessions/{session_id}/run-stage/document_generation")

    assert response.status_code == 200
    assert response.json() == {"stage_name": "document_generation", "status": "succeeded", "generated_document_id": 7}

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert len(runs) == 1
    assert runs[0]["stage_name"] == "document_generation"
    assert runs[0]["status"] == "succeeded"


def test_run_stage_document_generation_reports_failure(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module
    from app.services.document_generator import DocumentGenerationError

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def failing_generate_document(db, session, storage, latex_renderer, latex_compiler):
        raise DocumentGenerationError("tailoring_rewrite has not succeeded for this session yet")

    monkeypatch.setattr(sessions_module, "generate_document", failing_generate_document)

    response = client.post(f"/sessions/{session_id}/run-stage/document_generation")

    assert response.status_code == 422

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert runs[0]["status"] == "failed"


def test_run_stage_document_generation_times_out(client, db_session, monkeypatch):
    import time
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    class FakeGeneratedDocument:
        def __init__(self, id):
            self.id = id

    def slow_generate_document(db, session, storage, latex_renderer, latex_compiler):
        time.sleep(0.5)
        return FakeGeneratedDocument(id=1)

    monkeypatch.setattr(sessions_module, "generate_document", slow_generate_document)
    monkeypatch.setattr(sessions_module, "STAGE_TIMEOUT_SECONDS", 0.05)

    response = client.post(f"/sessions/{session_id}/run-stage/document_generation")

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
Expected: the 3 new tests FAIL with 501 responses (`document_generation` not yet in `STAGE_RUNNERS`); the updated 501 test already passes (it doesn't depend on new code).

- [ ] **Step 3: Wire `document_generation` into `sessions.py`**

In `backend/app/api/sessions.py`, add imports alongside the existing ones:

```python
from app.services.latex_renderer import LatexRenderer
from app.services.document_generator import generate_document, _compile_latex_to_pdf
```

Add a new dispatcher function after `_run_evaluation` and before the `STAGE_RUNNERS` dict:

```python
def _run_document_generation(db: Session, session: TailoringSession, settings) -> dict:
    storage = LocalDiskStorage(root=settings.storage_root)
    latex_renderer = LatexRenderer(templates_root=settings.latex_templates_root)
    document = generate_document(db, session, storage, latex_renderer, _compile_latex_to_pdf)
    return {"generated_document_id": document.id}
```

Update the `STAGE_RUNNERS` dict:

```python
STAGE_RUNNERS = {
    "resume_parsing": _run_resume_parsing,
    "jd_extraction": _run_jd_extraction,
    "gap_analysis": _run_gap_analysis,
    "tailoring_rewrite": _run_tailoring,
    "evaluation": _run_evaluation,
    "document_generation": _run_document_generation,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_api_sessions.py -v`
Expected: all tests in this file pass (20 pre-existing + 3 new = 23 passed)

- [ ] **Step 5: Run the full suite**

Run: `py -3 -m pytest -q` (from `backend/`)
Expected: 192 passed, 2 skipped (189 after Task 5, + 3 from this task).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/sessions.py backend/tests/test_api_sessions.py
git commit -m "feat: wire document_generation into run_stage via STAGE_RUNNERS"
```

---

### Task 7: Add Tectonic to the Docker image and document local setup

**Files:**
- Modify: `backend/Dockerfile`
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing new.
- Produces: a `tectonic` binary available on `PATH` inside the built Docker image, with its LaTeX package cache pre-warmed at build time.

- [ ] **Step 1: Add Tectonic install + cache pre-warm to the Dockerfile**

Replace the entire contents of `backend/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl --proto '=https' --tlsv1.2 -fsSL https://drop-sh.fullyjustified.net | sh \
    && mv tectonic /usr/local/bin/tectonic \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Pre-warm Tectonic's LaTeX package cache at build time with a throwaway
# compile, so the deployed container never needs network access to fetch
# packages when compiling a real resume at request time (see the Phase 7
# spec, section 4, for the full tradeoff rationale - local dev/fresh
# checkouts deliberately do NOT do this, and pay a one-time network cost on
# first local compile instead).
RUN mkdir -p /tmp/tectonic-warmup \
    && printf '\\documentclass{article}\n\\begin{document}\nwarmup\n\\end{document}\n' > /tmp/tectonic-warmup/warmup.tex \
    && tectonic /tmp/tectonic-warmup/warmup.tex --outdir /tmp/tectonic-warmup \
    && rm -rf /tmp/tectonic-warmup

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
```

- [ ] **Step 2: Document local Tectonic setup and the cache tradeoff in the README**

Add a new section to `README.md`, after the existing "Running backend tests without Docker" section:

```markdown

## Document generation (Phase 7) — Tectonic setup

Document generation compiles LaTeX to PDF using
[Tectonic](https://tectonic-typesetting.github.io/). To run the document
generation tests/smoke script locally (outside Docker), install Tectonic and
make sure it's on your `PATH`:

    # macOS (Homebrew)
    brew install tectonic

    # Linux/Windows: download a release binary from
    # https://github.com/tectonic-typesetting/tectonic/releases
    # or install via cargo: cargo install tectonic

**Package cache tradeoff (deliberate, not a bug):** Tectonic fetches needed
LaTeX packages from a bundle on first use and caches them locally
(`~/.cache/Tectonic` by default) for every compile after that. The Docker
image pre-warms this cache at build time, so the deployed container never
needs network access to compile a resume. Local dev does **not** pre-warm —
the first time you run the document-generation tests or smoke script after
installing Tectonic, that first compile will need network access to
populate your local cache; every compile after that is offline and fast.
If your `pytest` run doesn't have network access the very first time, the
Tectonic-dependent test will report a real failure (not a skip) rather than
silently passing — that's expected on a first run without connectivity, and
resolves itself on any subsequent run once the cache is populated.
```

- [ ] **Step 3: Commit**

```bash
git add backend/Dockerfile README.md
git commit -m "feat: install Tectonic in the Docker image, pre-warm package cache at build time, document local setup"
```

---

### Task 8: Manual smoke-test script

**Files:**
- Create: `backend/scripts/smoke_test_document_generation.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6. Requires a real local Tectonic install (per Task 7's README section) — not run by pytest.

- [ ] **Step 1: Write the script**

`backend/scripts/smoke_test_document_generation.py`:

```python
"""Manual smoke test: run with `python scripts/smoke_test_document_generation.py`
after installing Tectonic locally (see README's "Document generation" section
for setup and the package-cache network tradeoff). Not run by pytest.

Builds a fixture tailored resume, generates a real PDF via the real Tectonic
binary, and prints the resulting file's path and size so a human can open it
and eyeball the rendering quality - this is the one place a human actually
looks at the rendered output, not just asserts it compiled without error."""
import json
from pathlib import Path
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.core.storage import LocalDiskStorage
from app.models.db_models import Base, Resume, ResumeVersion, JobPosting, TailoringSession
from app.services.document_generator import generate_document, _compile_latex_to_pdf
from app.services.latex_renderer import LatexRenderer

if __name__ == "__main__":
    settings = get_settings()

    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = make_session_factory(engine)()

    resume_json = {
        "schema_version": 1,
        "contact": {
            "full_name": "Morgan Lee", "email": "morgan.lee@example.com", "phone": "555-0100",
            "location": "Remote", "links": ["https://github.com/morganlee-oss"],
        },
        "summary": "Backend engineer focused on distributed systems and open-source tooling.",
        "work_experience": [
            {
                "company": "Acme Corp", "title": "Senior Backend Engineer",
                "start_date": "2021", "end_date": "2024",
                "bullets": [
                    "Operated a production payments service handling 2M requests/day",
                    "Led migration from monolith to microservices, cutting deploy time by 60%",
                ],
            },
        ],
        "projects": [
            {
                "name": "Open Source Task Queue",
                "description": "A lightweight distributed task queue in Python",
                "bullets": ["400+ GitHub stars, used in production by three startups"],
                "technologies": ["Python", "Redis"],
            },
        ],
        "skills": ["Python", "PostgreSQL", "Docker", "Kubernetes", "AWS"],
        "education": [],
        "certifications": [],
    }

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()

    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    tailored_version = ResumeVersion(
        resume_id=resume.id, session_id=session.id, version_number=2,
        resume_json=resume_json, produced_by_stage="tailoring_rewrite",
    )
    db.add(tailored_version)
    db.commit()

    storage = LocalDiskStorage(root=settings.storage_root)
    latex_renderer = LatexRenderer(templates_root=settings.latex_templates_root)

    document = generate_document(db, session, storage, latex_renderer, _compile_latex_to_pdf)

    pdf_path = Path(document.storage_path)
    print(json.dumps({
        "generated_document_id": document.id,
        "storage_path": str(pdf_path),
        "file_size_bytes": pdf_path.stat().st_size,
        "version_number": document.version_number,
    }, indent=2))
    print(f"\nOpen the file to eyeball the rendering: {pdf_path.resolve()}")
```

- [ ] **Step 2: Commit**

```bash
git add backend/scripts/smoke_test_document_generation.py
git commit -m "feat: add manual smoke-test script for document_generation"
```

---

## Self-Review

**Spec coverage:**
- §1 (context, two verified gaps: no Tectonic, no resume_version_id) → Task 3 (migration), Task 7 (Dockerfile).
- §2 (separate Jinja2 Environment, LaTeX-safe delimiters, single default template) → Task 4.
- §3 (escape_latex, single-pass, order-matters) → Task 2.
- §4 (compilation via subprocess, failure wrapping, Tectonic caching tradeoff) → Task 5, Task 7.
- §5 (resume_version_id migration, version_number scoping distinct from resume_versions) → Task 3.
- §6 (Storage reuse, key pattern) → Task 5.
- §7 (dependency guard, data flow) → Task 5.
- §8 (API integration, stale 501 test) → Task 6.
- §9 (testing: escaping fixture, template-rendering + optional-field test, real compile test, dependency-guard test, API tests, smoke script) → Tasks 2, 4, 5, 6, 8 respectively.
- §10 (ledger cleanup) → Task 1.
- §11 (out of scope: multiple templates, cover letters, CI cache pre-warming, changes to prior services) → confirmed no task introduces any of these.

**Placeholder scan:** no TBD/TODO markers; every step has complete, runnable code.

**Type consistency:** `generate_document(db, session, storage, latex_renderer, latex_compiler) -> GeneratedDocument` matches exactly between Task 5 (definition) and Task 6 (`_run_document_generation` caller) and Task 8 (smoke script caller). `DocumentGenerationError` is defined once in Task 5 and imported (not redefined) in Task 6; it inherits `StageExecutionError` so Task 6's existing `except StageExecutionError` clause in `run_stage` catches it without modification. `LatexRenderer(templates_root: str).render(resume_json: dict, template_name: str = "default") -> str` (Task 4) signature matches how it's constructed and called in Task 5, Task 6, and Task 8. `escape_latex(text: str | None) -> str` (Task 2) matches how it's registered as a Jinja2 filter in Task 4. `GeneratedDocument.resume_version_id` (Task 3) matches exactly what Task 5's `generate_document` constructs.

---

**Plan complete and saved to `docs/superpowers/plans/2026-07-09-phase7-document-generation.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
