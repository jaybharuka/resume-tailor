# Phase 1 Architecture Skeleton Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `resume-tailor` platform's architecture skeleton — repo layout, canonical resume schema, task-driven AI orchestrator with audit logging, prompt registry, 9-table Postgres schema, a thin HTTP wrapper around the existing `hiring-agent` repo, and session/job-oriented API routes — with no real parsing/tailoring/report logic yet.

**Architecture:** A FastAPI `backend/` app holds all business logic as in-process modules behind narrow interfaces (`Provider`, `Storage`). A separate `hiring-agent-service/` FastAPI shim wraps the existing, untouched `hiring-agent` repo and exposes one HTTP endpoint. Local Postgres + both services run via `docker-compose`. See the approved spec: `docs/superpowers/specs/2026-07-03-phase1-architecture-design.md`.

**Tech Stack:** FastAPI, Pydantic v2, Pydantic-Settings, SQLAlchemy 2.0, Alembic, Jinja2, google-generativeai (Gemini), openai SDK (NVIDIA NIM, OpenAI-compatible), pytest, Docker Compose, Postgres 16.

## Global Constraints

- Python 3.11+ (matches the existing `hiring-agent` repo's pinned version).
- Single-user, local-first: no auth, no multi-tenancy, no cloud accounts required to run Phase 1.
- The existing `hiring-agent` repo (`c:\Reads\hiring-agent-imp\hiring-agent-imp`) is never modified — `hiring-agent-service` only imports and calls it.
- No hardcoded secrets anywhere in committed code. `GEMINI_API_KEY` and `NVIDIA_API_KEY` are read from `.env` files (gitignored) only.
- No real resume parsing, JD extraction, tailoring, LaTeX/PDF generation, report content, n8n workflows, or frontend UI in this phase — those are Phases 2–10.
- Every AI provider call must be logged (success or failure) so `llm_calls` stays a complete audit trail.
- Follow TDD: write the failing test, confirm it fails, implement, confirm it passes, commit.

---

### Task 1: Backend project scaffold + settings

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/requirements-dev.txt`
- Create: `backend/pytest.ini`
- Create: `backend/.env.example`
- Create: `backend/app/__init__.py`
- Create: `backend/app/core/__init__.py`
- Create: `backend/app/core/config.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/__init__.py`
- Test: `backend/tests/test_config.py`
- Create: `.gitignore` (repo root)

**Interfaces:**
- Produces: `Settings` (Pydantic `BaseSettings`) with fields `database_url: str`, `storage_root: str`, `gemini_api_key: str | None`, `nvidia_api_key: str | None`, `nvidia_base_url: str`, `hiring_agent_service_url: str`; and `get_settings() -> Settings`.

- [ ] **Step 1: Create the scaffold files**

`backend/requirements.txt`:
```
fastapi==0.115.6
uvicorn[standard]==0.32.1
pydantic==2.11.7
pydantic-settings==2.6.1
sqlalchemy==2.0.36
alembic==1.14.0
psycopg2-binary==2.9.10
jinja2==3.1.6
google-generativeai==0.4.0
google-api-core==2.24.0
openai==1.57.0
httpx==0.27.2
python-dotenv==1.0.1
python-multipart==0.0.19
```

`backend/requirements-dev.txt`:
```
pytest==8.3.4
```

`backend/pytest.ini`:
```ini
[pytest]
pythonpath = .
```

`backend/.env.example`:
```
DATABASE_URL=sqlite:///./resume_tailor.db
STORAGE_ROOT=./storage
GEMINI_API_KEY=
NVIDIA_API_KEY=
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
HIRING_AGENT_SERVICE_URL=http://localhost:8100
```

`.gitignore` (repo root):
```
.env
__pycache__/
*.pyc
.venv/
storage/
*.db
.pytest_cache/
```

`backend/app/__init__.py`: empty file.
`backend/app/core/__init__.py`: empty file.
`backend/tests/__init__.py`: empty file.

- [ ] **Step 2: Write the failing test**

`backend/tests/test_config.py`:
```python
from app.core.config import Settings


def test_settings_defaults_when_no_env_vars():
    settings = Settings(_env_file=None)
    assert settings.database_url == "sqlite:///./resume_tailor.db"
    assert settings.storage_root == "./storage"
    assert settings.hiring_agent_service_url == "http://localhost:8100"
    assert settings.gemini_api_key is None


def test_settings_reads_env_vars(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql://user:pass@localhost/db"
    assert settings.gemini_api_key == "test-gemini-key"
```

- [ ] **Step 3: Run test to verify it fails**

Run (from `backend/`): `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.config'`

- [ ] **Step 4: Implement Settings and the FastAPI app entrypoint**

`backend/app/core/config.py`:
```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./resume_tailor.db"
    storage_root: str = "./storage"
    gemini_api_key: str | None = None
    nvidia_api_key: str | None = None
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    hiring_agent_service_url: str = "http://localhost:8100"


def get_settings() -> Settings:
    return Settings()
```

`backend/app/main.py`:
```python
from fastapi import FastAPI

app = FastAPI(title="Resume Tailor Backend")


@app.get("/")
def root():
    return {"service": "resume-tailor-backend"}
```

- [ ] **Step 5: Run test to verify it passes**

Run (from `backend/`): `pytest tests/test_config.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/requirements-dev.txt backend/pytest.ini backend/.env.example \
  backend/app/__init__.py backend/app/core/__init__.py backend/app/core/config.py backend/app/main.py \
  backend/tests/__init__.py backend/tests/test_config.py .gitignore
git commit -m "feat: scaffold backend FastAPI app with env-driven settings"
```

---

### Task 2: Storage protocol + LocalDiskStorage

**Files:**
- Create: `backend/app/core/storage.py`
- Test: `backend/tests/test_storage.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `Storage` (Protocol) with `save(key: str, data: bytes) -> str`, `load(key: str) -> bytes`, `delete(key: str) -> None`; `LocalDiskStorage(root: str)` implementing it.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_storage.py`:
```python
import pytest
from app.core.storage import LocalDiskStorage


def test_save_and_load_roundtrip(tmp_path):
    storage = LocalDiskStorage(root=str(tmp_path))
    path = storage.save("sessions/abc/resume.pdf", b"hello world")
    assert path.endswith("resume.pdf")
    assert storage.load("sessions/abc/resume.pdf") == b"hello world"


def test_delete_removes_file(tmp_path):
    storage = LocalDiskStorage(root=str(tmp_path))
    storage.save("file.txt", b"data")
    storage.delete("file.txt")
    with pytest.raises(FileNotFoundError):
        storage.load("file.txt")


def test_save_rejects_path_traversal(tmp_path):
    storage = LocalDiskStorage(root=str(tmp_path))
    with pytest.raises(ValueError):
        storage.save("../escape.txt", b"data")
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `pytest tests/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.storage'`

- [ ] **Step 3: Implement Storage and LocalDiskStorage**

`backend/app/core/storage.py`:
```python
from pathlib import Path
from typing import Protocol


class Storage(Protocol):
    def save(self, key: str, data: bytes) -> str: ...
    def load(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class LocalDiskStorage:
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        path = (self.root / key).resolve()
        root_resolved = self.root.resolve()
        if root_resolved not in path.parents and path != root_resolved:
            raise ValueError(f"key '{key}' escapes storage root")
        return path

    def save(self, key: str, data: bytes) -> str:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    def load(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.exists():
            path.unlink()
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `backend/`): `pytest tests/test_storage.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/storage.py backend/tests/test_storage.py
git commit -m "feat: add Storage protocol and LocalDiskStorage implementation"
```

---

### Task 3: Canonical ResumeDocument schema with versioning

**Files:**
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/resume.py`
- Test: `backend/tests/test_resume_schema.py`

**Interfaces:**
- Produces: `CURRENT_RESUME_SCHEMA_VERSION: int`, `ContactInfo`, `WorkExperience`, `Project`, `Education`, `ResumeDocument` (all Pydantic models), `UnsupportedResumeSchemaVersion` (Exception), `migrate_resume_document(data: dict) -> ResumeDocument`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_resume_schema.py`:
```python
import pytest
from app.models.resume import (
    ResumeDocument,
    ContactInfo,
    CURRENT_RESUME_SCHEMA_VERSION,
    migrate_resume_document,
    UnsupportedResumeSchemaVersion,
)


def test_resume_document_defaults_to_current_schema_version():
    doc = ResumeDocument(contact=ContactInfo(full_name="Jane Doe"))
    assert doc.schema_version == CURRENT_RESUME_SCHEMA_VERSION
    assert doc.work_experience == []


def test_resume_document_roundtrips_through_json():
    doc = ResumeDocument(
        contact=ContactInfo(full_name="Jane Doe", email="jane@example.com"),
        summary="Backend engineer",
        skills=["Python", "FastAPI"],
    )
    restored = ResumeDocument.model_validate_json(doc.model_dump_json())
    assert restored == doc


def test_migrate_resume_document_accepts_current_version():
    raw = {"schema_version": 1, "contact": {"full_name": "Jane Doe"}}
    doc = migrate_resume_document(raw)
    assert doc.contact.full_name == "Jane Doe"


def test_migrate_resume_document_rejects_unknown_future_version():
    raw = {"schema_version": 999, "contact": {"full_name": "Jane Doe"}}
    with pytest.raises(UnsupportedResumeSchemaVersion):
        migrate_resume_document(raw)
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `pytest tests/test_resume_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models'`

- [ ] **Step 3: Implement the schema**

`backend/app/models/__init__.py`: empty file.

`backend/app/models/resume.py`:
```python
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field

CURRENT_RESUME_SCHEMA_VERSION = 1


class ContactInfo(BaseModel):
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    links: list[str] = Field(default_factory=list)


class WorkExperience(BaseModel):
    company: str
    title: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)


class Project(BaseModel):
    name: str
    description: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class Education(BaseModel):
    institution: str
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class ResumeDocument(BaseModel):
    schema_version: int = CURRENT_RESUME_SCHEMA_VERSION
    contact: ContactInfo
    summary: Optional[str] = None
    work_experience: list[WorkExperience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)


class UnsupportedResumeSchemaVersion(Exception):
    pass


def migrate_resume_document(data: dict) -> ResumeDocument:
    """Load a raw resume_json dict of any known schema_version into the current ResumeDocument shape.

    New migrators get registered here (e.g. an `if version == 1: ...` branch calling a
    `_migrate_v1_to_v2` helper) the first time schema_version is bumped past 1.
    """
    version = data.get("schema_version", CURRENT_RESUME_SCHEMA_VERSION)
    if version == CURRENT_RESUME_SCHEMA_VERSION:
        return ResumeDocument.model_validate(data)
    raise UnsupportedResumeSchemaVersion(
        f"No migrator registered for resume schema_version={version}"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `backend/`): `pytest tests/test_resume_schema.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/__init__.py backend/app/models/resume.py backend/tests/test_resume_schema.py
git commit -m "feat: add canonical ResumeDocument schema with schema_version"
```

---

### Task 4: Database models, session factory, and Alembic migration

**Files:**
- Create: `backend/app/core/db.py`
- Create: `backend/app/models/db_models.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/0001_initial_schema.py`
- Test: `backend/tests/test_db_models.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (independent of `ResumeDocument`; `resume_json`/`raw_response_json` columns are untyped `JSON`).
- Produces: `make_engine(database_url: str | None = None)`, `make_session_factory(engine)`; ORM classes `Base`, `Resume`, `ResumeVersion`, `JobPosting`, `TailoringSession`, `PipelineRun`, `EvaluationRun`, `GeneratedDocument`, `PromptVersion`, `LLMCall`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_db_models.py`:
```python
from app.core.db import make_engine, make_session_factory
from app.models.db_models import (
    Base, Resume, ResumeVersion, JobPosting, TailoringSession,
    PipelineRun, EvaluationRun, GeneratedDocument, PromptVersion, LLMCall,
)


def test_all_nine_tables_create_and_accept_a_linked_row():
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
        db.add_all([pipeline_run, evaluation, document, prompt_version])
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
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `pytest tests/test_db_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.db'`

- [ ] **Step 3: Implement the engine/session factory and ORM models**

`backend/app/core/db.py`:
```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings


def make_engine(database_url: str | None = None):
    settings = get_settings()
    url = database_url or settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)
```

`backend/app/models/db_models.py`:
```python
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, JSON, Boolean, Float
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True)
    original_filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    raw_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    versions = relationship("ResumeVersion", back_populates="resume")


class ResumeVersion(Base):
    __tablename__ = "resume_versions"

    id = Column(Integer, primary_key=True)
    resume_id = Column(Integer, ForeignKey("resumes.id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    resume_json = Column(JSON, nullable=False)
    produced_by_stage = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    resume = relationship("Resume", back_populates="versions")


class JobPosting(Base):
    __tablename__ = "job_postings"

    id = Column(Integer, primary_key=True)
    source_url = Column(String, nullable=True)
    source_provider = Column(String, nullable=True)
    raw_text = Column(Text, nullable=True)
    parsed_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


class TailoringSession(Base):
    __tablename__ = "tailoring_sessions"

    id = Column(Integer, primary_key=True)
    resume_id = Column(Integer, ForeignKey("resumes.id"), nullable=False)
    job_posting_id = Column(Integer, ForeignKey("job_postings.id"), nullable=False)
    status = Column(String, nullable=False, default="created")
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("tailoring_sessions.id"), nullable=False)
    stage_name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("tailoring_sessions.id"), nullable=False)
    resume_version_id = Column(Integer, ForeignKey("resume_versions.id"), nullable=False)
    overall_score = Column(Float, nullable=True)
    open_source_score = Column(Float, nullable=True)
    projects_score = Column(Float, nullable=True)
    production_score = Column(Float, nullable=True)
    technical_skills_score = Column(Float, nullable=True)
    raw_response_json = Column(JSON, nullable=False)
    rubric_version = Column(String, nullable=True)
    hiring_agent_service_version = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


class GeneratedDocument(Base):
    __tablename__ = "generated_documents"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("tailoring_sessions.id"), nullable=False)
    document_type = Column(String, nullable=False)
    storage_path = Column(String, nullable=True)
    content = Column(Text, nullable=True)
    version_number = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id = Column(Integer, primary_key=True)
    task_type = Column(String, nullable=False)
    name = Column(String, nullable=False)
    version = Column(String, nullable=False)
    template_path = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("tailoring_sessions.id"), nullable=True)
    prompt_version_id = Column(Integer, ForeignKey("prompt_versions.id"), nullable=True)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    task_type = Column(String, nullable=False)
    temperature = Column(Float, nullable=True)
    request_payload = Column(JSON, nullable=True)
    response_payload = Column(JSON, nullable=True)
    validated = Column(Boolean, nullable=False, default=False)
    latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `backend/`): `pytest tests/test_db_models.py -v`
Expected: 1 passed

- [ ] **Step 5: Add Alembic wiring and the hand-written initial migration**

`backend/alembic.ini`:
```ini
[alembic]
script_location = alembic
sqlalchemy.url =

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

`backend/alembic/script.py.mako`:
```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade():
    ${upgrades if upgrades else "pass"}


def downgrade():
    ${downgrades if downgrades else "pass"}
```

`backend/alembic/env.py`:
```python
import sys
from pathlib import Path
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.models.db_models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

`backend/alembic/versions/0001_initial_schema.py`:
```python
"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-03

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "resumes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("original_filename", sa.String, nullable=False),
        sa.Column("storage_path", sa.String, nullable=False),
        sa.Column("raw_text", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "job_postings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_url", sa.String, nullable=True),
        sa.Column("source_provider", sa.String, nullable=True),
        sa.Column("raw_text", sa.Text, nullable=True),
        sa.Column("parsed_json", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "resume_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("resume_id", sa.Integer, sa.ForeignKey("resumes.id"), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("resume_json", sa.JSON, nullable=False),
        sa.Column("produced_by_stage", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "tailoring_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("resume_id", sa.Integer, sa.ForeignKey("resumes.id"), nullable=False),
        sa.Column("job_posting_id", sa.Integer, sa.ForeignKey("job_postings.id"), nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("tailoring_sessions.id"), nullable=False),
        sa.Column("stage_name", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
    )

    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("tailoring_sessions.id"), nullable=False),
        sa.Column("resume_version_id", sa.Integer, sa.ForeignKey("resume_versions.id"), nullable=False),
        sa.Column("overall_score", sa.Float, nullable=True),
        sa.Column("open_source_score", sa.Float, nullable=True),
        sa.Column("projects_score", sa.Float, nullable=True),
        sa.Column("production_score", sa.Float, nullable=True),
        sa.Column("technical_skills_score", sa.Float, nullable=True),
        sa.Column("raw_response_json", sa.JSON, nullable=False),
        sa.Column("rubric_version", sa.String, nullable=True),
        sa.Column("hiring_agent_service_version", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "generated_documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("tailoring_sessions.id"), nullable=False),
        sa.Column("document_type", sa.String, nullable=False),
        sa.Column("storage_path", sa.String, nullable=True),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("task_type", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("version", sa.String, nullable=False),
        sa.Column("template_path", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("tailoring_sessions.id"), nullable=True),
        sa.Column("prompt_version_id", sa.Integer, sa.ForeignKey("prompt_versions.id"), nullable=True),
        sa.Column("provider", sa.String, nullable=False),
        sa.Column("model", sa.String, nullable=False),
        sa.Column("task_type", sa.String, nullable=False),
        sa.Column("temperature", sa.Float, nullable=True),
        sa.Column("request_payload", sa.JSON, nullable=True),
        sa.Column("response_payload", sa.JSON, nullable=True),
        sa.Column("validated", sa.Boolean, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("llm_calls")
    op.drop_table("prompt_versions")
    op.drop_table("generated_documents")
    op.drop_table("evaluation_runs")
    op.drop_table("pipeline_runs")
    op.drop_table("tailoring_sessions")
    op.drop_table("resume_versions")
    op.drop_table("job_postings")
    op.drop_table("resumes")
```

- [ ] **Step 6: Verify the migration applies cleanly against a scratch database**

Run (from `backend/`):
```bash
DATABASE_URL="sqlite:///./_migration_check.db" alembic upgrade head
```
Expected: log lines ending in `Running upgrade  -> 0001, initial schema`, and `backend/_migration_check.db` now exists.

Then clean up: `rm backend/_migration_check.db`

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/db.py backend/app/models/db_models.py backend/alembic.ini backend/alembic/env.py \
  backend/alembic/script.py.mako backend/alembic/versions/0001_initial_schema.py backend/tests/test_db_models.py
git commit -m "feat: add 9-table SQLAlchemy schema, session factory, and Alembic migration"
```

---

### Task 5: Prompt Registry

**Files:**
- Create: `backend/app/core/llm/__init__.py`
- Create: `backend/app/core/llm/prompt_registry.py`
- Test: `backend/tests/test_prompt_registry.py`

**Interfaces:**
- Consumes: `PromptVersion` from Task 4 (`app.models.db_models`).
- Produces: `PromptRegistry(prompts_root: str)` with `.discover() -> list[tuple[str, str, str]]`, `.sync_to_db(db: Session) -> int`, `.render(task_type: str, version: str, **context) -> str`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_prompt_registry.py`:
```python
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, PromptVersion
from app.core.llm.prompt_registry import PromptRegistry


def _make_db():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def test_sync_to_db_creates_one_row_per_template(tmp_path):
    prompts_dir = tmp_path / "prompts"
    (prompts_dir / "tailoring_rewrite").mkdir(parents=True)
    (prompts_dir / "tailoring_rewrite" / "v1.jinja2").write_text("Rewrite: {{ bullet }}")

    registry = PromptRegistry(prompts_root=str(prompts_dir))
    db = _make_db()

    count = registry.sync_to_db(db)

    assert count == 1
    row = db.query(PromptVersion).one()
    assert row.task_type == "tailoring_rewrite"
    assert row.version == "v1"


def test_sync_to_db_is_idempotent(tmp_path):
    prompts_dir = tmp_path / "prompts"
    (prompts_dir / "tailoring_rewrite").mkdir(parents=True)
    (prompts_dir / "tailoring_rewrite" / "v1.jinja2").write_text("Rewrite: {{ bullet }}")

    registry = PromptRegistry(prompts_root=str(prompts_dir))
    db = _make_db()

    registry.sync_to_db(db)
    second_run_count = registry.sync_to_db(db)

    assert second_run_count == 0
    assert db.query(PromptVersion).count() == 1


def test_render_fills_template_variables(tmp_path):
    prompts_dir = tmp_path / "prompts"
    (prompts_dir / "tailoring_rewrite").mkdir(parents=True)
    (prompts_dir / "tailoring_rewrite" / "v1.jinja2").write_text("Rewrite: {{ bullet }}")
    registry = PromptRegistry(prompts_root=str(prompts_dir))

    rendered = registry.render("tailoring_rewrite", "v1", bullet="Built a thing")

    assert rendered == "Rewrite: Built a thing"
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `pytest tests/test_prompt_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.llm'`

- [ ] **Step 3: Implement PromptRegistry**

`backend/app/core/llm/__init__.py`: empty file.

`backend/app/core/llm/prompt_registry.py`:
```python
from pathlib import Path
import jinja2
from sqlalchemy.orm import Session
from app.models.db_models import PromptVersion


class PromptRegistry:
    def __init__(self, prompts_root: str):
        self.prompts_root = Path(prompts_root)
        self._env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(self.prompts_root)))

    def discover(self) -> list[tuple[str, str, str]]:
        """Return (task_type, version, template_path) for every template on disk."""
        found = []
        if not self.prompts_root.exists():
            return found
        for task_dir in sorted(self.prompts_root.iterdir()):
            if not task_dir.is_dir():
                continue
            for template_file in sorted(task_dir.glob("*.jinja2")):
                version = template_file.stem
                found.append((task_dir.name, version, str(template_file.relative_to(self.prompts_root))))
        return found

    def sync_to_db(self, db: Session) -> int:
        """Upsert a prompt_versions row for every template on disk. Returns rows created or updated."""
        touched = 0
        for task_type, version, template_path in self.discover():
            existing = (
                db.query(PromptVersion)
                .filter_by(task_type=task_type, version=version)
                .one_or_none()
            )
            if existing is None:
                db.add(PromptVersion(
                    task_type=task_type, name=task_type,
                    version=version, template_path=template_path,
                ))
                touched += 1
            elif existing.template_path != template_path:
                existing.template_path = template_path
                touched += 1
        db.commit()
        return touched

    def render(self, task_type: str, version: str, **context) -> str:
        template = self._env.get_template(f"{task_type}/{version}.jinja2")
        return template.render(**context)
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `backend/`): `pytest tests/test_prompt_registry.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/llm/__init__.py backend/app/core/llm/prompt_registry.py backend/tests/test_prompt_registry.py
git commit -m "feat: add PromptRegistry keyed by (task_type, version)"
```

---

### Task 6: AI Orchestrator core (retry, fallback, OrchestratorError)

**Files:**
- Create: `backend/app/core/llm/provider.py`
- Create: `backend/app/core/llm/orchestrator.py`
- Test: `backend/tests/test_orchestrator.py`

**Interfaces:**
- Produces: `ProviderError` (Exception), `Provider` (Protocol: `name: str`, `generate(prompt: str, model: str, temperature: float) -> str`), `OrchestratorError` (Exception), `TaskConfig(task_type, provider, model, temperature, response_schema, fallback_providers=[])`, `OrchestratorResult(output, provider_used, attempts)`, `AIOrchestrator(providers: dict[str, Provider], on_call_logged: Callable[[dict], None] | None)` with `.run(task: TaskConfig, prompt: str) -> OrchestratorResult`.
- Failure policy implemented: same-provider retry once, then each `fallback_providers` entry in order, then raise `OrchestratorError`; every attempt (success or failure) is passed to `on_call_logged`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_orchestrator.py`:
```python
import pytest
from pydantic import BaseModel
from app.core.llm.provider import ProviderError
from app.core.llm.orchestrator import AIOrchestrator, TaskConfig, OrchestratorError


class EchoResult(BaseModel):
    text: str


class FailNTimesProvider:
    def __init__(self, name: str, fail_times: int, output: str = '{"text": "ok"}'):
        self.name = name
        self.fail_times = fail_times
        self.output = output
        self.calls = 0

    def generate(self, prompt: str, model: str, temperature: float) -> str:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ProviderError("simulated failure")
        return self.output


class AlwaysFailsProvider:
    def __init__(self, name: str):
        self.name = name
        self.calls = 0

    def generate(self, prompt: str, model: str, temperature: float) -> str:
        self.calls += 1
        raise ProviderError("simulated failure")


class BadJsonProvider:
    name = "bad_json"

    def generate(self, prompt: str, model: str, temperature: float) -> str:
        return "not json"


def test_succeeds_on_same_provider_retry():
    provider = FailNTimesProvider(name="gemini", fail_times=1)
    orchestrator = AIOrchestrator(providers={"gemini": provider})
    task = TaskConfig(task_type="echo", provider="gemini", model="m1", temperature=0.5, response_schema=EchoResult)

    result = orchestrator.run(task, prompt="hi")

    assert result.output.text == "ok"
    assert result.provider_used == "gemini"
    assert provider.calls == 2


def test_falls_back_to_next_provider_after_same_provider_retry_fails():
    primary = AlwaysFailsProvider(name="nvidia")
    fallback = FailNTimesProvider(name="gemini", fail_times=0)
    orchestrator = AIOrchestrator(providers={"nvidia": primary, "gemini": fallback})
    task = TaskConfig(
        task_type="echo", provider="nvidia", model="m1", temperature=0.5,
        response_schema=EchoResult, fallback_providers=["gemini"],
    )

    result = orchestrator.run(task, prompt="hi")

    assert result.provider_used == "gemini"
    assert primary.calls == 2
    assert fallback.calls == 1


def test_raises_orchestrator_error_when_all_providers_exhausted():
    primary = AlwaysFailsProvider(name="nvidia")
    fallback = AlwaysFailsProvider(name="gemini")
    orchestrator = AIOrchestrator(providers={"nvidia": primary, "gemini": fallback})
    task = TaskConfig(
        task_type="echo", provider="nvidia", model="m1", temperature=0.5,
        response_schema=EchoResult, fallback_providers=["gemini"],
    )

    with pytest.raises(OrchestratorError):
        orchestrator.run(task, prompt="hi")


def test_schema_validation_failure_is_treated_as_a_failed_attempt():
    bad = BadJsonProvider()
    good = FailNTimesProvider(name="gemini", fail_times=0)
    orchestrator = AIOrchestrator(providers={"bad_json": bad, "gemini": good})
    task = TaskConfig(
        task_type="echo", provider="bad_json", model="m1", temperature=0.5,
        response_schema=EchoResult, fallback_providers=["gemini"],
    )

    result = orchestrator.run(task, prompt="hi")

    assert result.provider_used == "gemini"


def test_every_attempt_is_logged_including_failures():
    logged = []
    primary = AlwaysFailsProvider(name="nvidia")
    fallback = FailNTimesProvider(name="gemini", fail_times=0)
    orchestrator = AIOrchestrator(
        providers={"nvidia": primary, "gemini": fallback},
        on_call_logged=logged.append,
    )
    task = TaskConfig(
        task_type="echo", provider="nvidia", model="m1", temperature=0.5,
        response_schema=EchoResult, fallback_providers=["gemini"],
    )

    orchestrator.run(task, prompt="hi")

    assert len(logged) == 3
    assert [entry["validated"] for entry in logged] == [False, False, True]
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `pytest tests/test_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.llm.provider'`

- [ ] **Step 3: Implement Provider protocol and AIOrchestrator**

`backend/app/core/llm/provider.py`:
```python
from typing import Protocol


class ProviderError(Exception):
    """Raised by a Provider when a call fails (timeout, rate limit, API error)."""


class Provider(Protocol):
    name: str

    def generate(self, prompt: str, model: str, temperature: float) -> str: ...
```

`backend/app/core/llm/orchestrator.py`:
```python
import time
from dataclasses import dataclass, field
from typing import Callable, Type
from pydantic import BaseModel, ValidationError
from app.core.llm.provider import ProviderError


class OrchestratorError(Exception):
    """Raised when every provider (primary + fallbacks, with same-provider retry) has failed."""


@dataclass
class TaskConfig:
    task_type: str
    provider: str
    model: str
    temperature: float
    response_schema: Type[BaseModel]
    fallback_providers: list[str] = field(default_factory=list)


@dataclass
class OrchestratorResult:
    output: BaseModel
    provider_used: str
    attempts: int


class AIOrchestrator:
    def __init__(self, providers: dict, on_call_logged: Callable[[dict], None] | None = None):
        self.providers = providers
        self.on_call_logged = on_call_logged or (lambda record: None)

    def _attempt(self, task: TaskConfig, provider_name: str, prompt: str):
        provider = self.providers[provider_name]
        started = time.monotonic()
        try:
            raw_output = provider.generate(prompt, model=task.model, temperature=task.temperature)
        except ProviderError as exc:
            self.on_call_logged({
                "provider": provider_name, "model": task.model, "task_type": task.task_type,
                "temperature": task.temperature, "validated": False,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "response_payload": None, "error": str(exc),
            })
            return None

        latency_ms = int((time.monotonic() - started) * 1000)
        try:
            parsed = task.response_schema.model_validate_json(raw_output)
        except ValidationError as exc:
            self.on_call_logged({
                "provider": provider_name, "model": task.model, "task_type": task.task_type,
                "temperature": task.temperature, "validated": False,
                "latency_ms": latency_ms, "response_payload": raw_output, "error": str(exc),
            })
            return None

        self.on_call_logged({
            "provider": provider_name, "model": task.model, "task_type": task.task_type,
            "temperature": task.temperature, "validated": True,
            "latency_ms": latency_ms, "response_payload": raw_output, "error": None,
        })
        return OrchestratorResult(output=parsed, provider_used=provider_name, attempts=1)

    def run(self, task: TaskConfig, prompt: str) -> OrchestratorResult:
        # task.provider appears twice: same-provider retry (failure policy step 1),
        # then each fallback in order (step 2), then OrchestratorError (step 3).
        provider_order = [task.provider, task.provider] + task.fallback_providers
        for provider_name in provider_order:
            result = self._attempt(task, provider_name, prompt)
            if result is not None:
                return result
        raise OrchestratorError(
            f"All providers exhausted for task_type={task.task_type}: "
            f"tried {task.provider} (x2) then fallbacks {task.fallback_providers}"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `backend/`): `pytest tests/test_orchestrator.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/llm/provider.py backend/app/core/llm/orchestrator.py backend/tests/test_orchestrator.py
git commit -m "feat: add AIOrchestrator with same-provider retry, fallback, and call logging"
```

---

### Task 7: Shared exponential-backoff-with-jitter retry helper

**Files:**
- Create: `backend/app/core/llm/retry.py`
- Test: `backend/tests/test_retry.py`

**Interfaces:**
- Produces: `with_backoff(fn: Callable[[], T], is_retryable: Callable[[Exception], bool], max_retries: int = 5, base_delay: float = 10.0, max_delay: float = 120.0, sleep: Callable[[float], None] = time.sleep) -> T`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_retry.py`:
```python
import pytest
from app.core.llm.retry import with_backoff


class RetryableError(Exception):
    pass


class FatalError(Exception):
    pass


def test_retries_until_success_within_max_retries():
    attempts = {"count": 0}

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RetryableError("try again")
        return "ok"

    result = with_backoff(
        flaky, is_retryable=lambda e: isinstance(e, RetryableError),
        max_retries=5, base_delay=0.01, max_delay=0.05, sleep=lambda s: None,
    )

    assert result == "ok"
    assert attempts["count"] == 3


def test_raises_immediately_on_non_retryable_error():
    def always_fatal():
        raise FatalError("nope")

    with pytest.raises(FatalError):
        with_backoff(
            always_fatal, is_retryable=lambda e: isinstance(e, RetryableError),
            max_retries=5, base_delay=0.01, sleep=lambda s: None,
        )


def test_raises_after_exhausting_max_retries():
    def always_retryable():
        raise RetryableError("still failing")

    with pytest.raises(RetryableError):
        with_backoff(
            always_retryable, is_retryable=lambda e: isinstance(e, RetryableError),
            max_retries=3, base_delay=0.01, sleep=lambda s: None,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `pytest tests/test_retry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.llm.retry'`

- [ ] **Step 3: Implement with_backoff**

`backend/app/core/llm/retry.py`:
```python
import random
import time
from typing import Callable, TypeVar

T = TypeVar("T")


def with_backoff(
    fn: Callable[[], T],
    is_retryable: Callable[[Exception], bool],
    max_retries: int = 5,
    base_delay: float = 10.0,
    max_delay: float = 120.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call fn(), retrying with exponential backoff + jitter on retryable errors."""
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as exc:
            if attempt == max_retries - 1 or not is_retryable(exc):
                raise
            delay = min(base_delay * (2 ** attempt), max_delay)
            delay += random.uniform(0, delay * 0.1)
            sleep(delay)
    raise RuntimeError("unreachable")
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `backend/`): `pytest tests/test_retry.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/llm/retry.py backend/tests/test_retry.py
git commit -m "feat: add generalized exponential-backoff-with-jitter retry helper"
```

---

### Task 8: NVIDIA provider adapter (primary)

> **Plan amendment (post-Task-7):** the project owner decided NVIDIA NIM is the primary provider for Phase 1 (API key already provisioned), not Gemini. Gemini is deferred to a stub alongside Claude/OpenAI (Task 9). Reference model: `z-ai/glm-5.2`.

**Files:**
- Create: `backend/app/core/llm/providers/__init__.py`
- Create: `backend/app/core/llm/providers/nvidia_provider.py`
- Create: `backend/scripts/smoke_test_nvidia.py`
- Test: `backend/tests/test_nvidia_provider.py`

**Interfaces:**
- Consumes: `ProviderError` (Task 6), `with_backoff` (Task 7), `get_settings` (Task 1).
- Produces: `NvidiaProvider(api_key: str, base_url: str = "https://integrate.api.nvidia.com/v1", sleep: Callable[[float], None] = time.sleep)` implementing `Provider` (`name = "nvidia"`).
- Failure classification: retryable = `openai.APIConnectionError`, `openai.APITimeoutError`, or `openai.APIStatusError` with `status_code == 429` or `status_code >= 500`. Not retryable (fails fast, no retry) = everything else, including 4xx auth/bad-request errors (401/403/400/404/422).
- Security: the API key is never hardcoded (read from `Settings.nvidia_api_key`, itself sourced from `.env`), and is stripped out of any `ProviderError` message via `_sanitize` before it can reach a log line or an `llm_calls` row.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_nvidia_provider.py`:
```python
import pytest
from app.core.llm.provider import ProviderError
from app.core.llm.providers import nvidia_provider as nvidia_provider_module
from app.core.llm.providers.nvidia_provider import NvidiaProvider


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeAPIStatusError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class FakeCompletions:
    def create(self, **kwargs):
        return FakeCompletion('{"text": "hello from nvidia"}')


class FakeChat:
    def __init__(self):
        self.completions = FakeCompletions()


class FakeOpenAIClient:
    def __init__(self, base_url, api_key):
        self.base_url = base_url
        self.api_key = api_key
        self.chat = FakeChat()


def test_generate_returns_model_text(monkeypatch):
    monkeypatch.setattr(nvidia_provider_module, "OpenAI", FakeOpenAIClient)

    provider = NvidiaProvider(api_key="fake-key")
    result = provider.generate("say hi", model="z-ai/glm-5.2", temperature=1.0)

    assert result == '{"text": "hello from nvidia"}'


def test_generate_wraps_unexpected_errors_as_provider_error(monkeypatch):
    class BrokenCompletions:
        def create(self, **kwargs):
            raise RuntimeError("connection reset")

    class BrokenChat:
        def __init__(self):
            self.completions = BrokenCompletions()

    class BrokenOpenAIClient:
        def __init__(self, base_url, api_key):
            self.chat = BrokenChat()

    monkeypatch.setattr(nvidia_provider_module, "OpenAI", BrokenOpenAIClient)

    provider = NvidiaProvider(api_key="fake-key")
    with pytest.raises(ProviderError):
        provider.generate("say hi", model="z-ai/glm-5.2", temperature=1.0)


def test_auth_error_fails_fast_without_retrying(monkeypatch):
    monkeypatch.setattr(nvidia_provider_module, "APIStatusError", FakeAPIStatusError)

    call_count = {"n": 0}

    class AuthFailingCompletions:
        def create(self, **kwargs):
            call_count["n"] += 1
            raise FakeAPIStatusError("Invalid API key", status_code=401)

    class AuthFailingChat:
        def __init__(self):
            self.completions = AuthFailingCompletions()

    class AuthFailingOpenAIClient:
        def __init__(self, base_url, api_key):
            self.chat = AuthFailingChat()

    monkeypatch.setattr(nvidia_provider_module, "OpenAI", AuthFailingOpenAIClient)

    provider = NvidiaProvider(api_key="fake-key", sleep=lambda s: None)
    with pytest.raises(ProviderError):
        provider.generate("say hi", model="z-ai/glm-5.2", temperature=1.0)

    assert call_count["n"] == 1


def test_rate_limit_error_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr(nvidia_provider_module, "APIStatusError", FakeAPIStatusError)

    call_count = {"n": 0}

    class FlakyCompletions:
        def create(self, **kwargs):
            call_count["n"] += 1
            if call_count["n"] < 2:
                raise FakeAPIStatusError("Rate limited", status_code=429)
            return FakeCompletion('{"text": "hello from nvidia"}')

    class FlakyChat:
        def __init__(self):
            self.completions = FlakyCompletions()

    class FlakyOpenAIClient:
        def __init__(self, base_url, api_key):
            self.chat = FlakyChat()

    monkeypatch.setattr(nvidia_provider_module, "OpenAI", FlakyOpenAIClient)

    provider = NvidiaProvider(api_key="fake-key", sleep=lambda s: None)
    result = provider.generate("say hi", model="z-ai/glm-5.2", temperature=1.0)

    assert result == '{"text": "hello from nvidia"}'
    assert call_count["n"] == 2


def test_api_key_never_appears_in_provider_error_message(monkeypatch):
    secret_key = "nvapi-super-secret-value-123"

    class LeakyCompletions:
        def create(self, **kwargs):
            raise RuntimeError(f"request failed, Authorization: Bearer {secret_key}")

    class LeakyChat:
        def __init__(self):
            self.completions = LeakyCompletions()

    class LeakyOpenAIClient:
        def __init__(self, base_url, api_key):
            self.chat = LeakyChat()

    monkeypatch.setattr(nvidia_provider_module, "OpenAI", LeakyOpenAIClient)

    provider = NvidiaProvider(api_key=secret_key, sleep=lambda s: None)
    with pytest.raises(ProviderError) as exc_info:
        provider.generate("say hi", model="z-ai/glm-5.2", temperature=1.0)

    assert secret_key not in str(exc_info.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_nvidia_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.llm.providers'`

- [ ] **Step 3: Implement NvidiaProvider**

`backend/app/core/llm/providers/__init__.py`: empty file.

`backend/app/core/llm/providers/nvidia_provider.py`:
```python
import time
from typing import Callable
from openai import OpenAI
from openai import APIStatusError, APIConnectionError, APITimeoutError
from app.core.llm.provider import ProviderError
from app.core.llm.retry import with_backoff


def _is_retryable_nvidia_error(exc: Exception) -> bool:
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


def _sanitize(message: str, api_key: str) -> str:
    if api_key and api_key in message:
        return message.replace(api_key, "***REDACTED***")
    return message


class NvidiaProvider:
    name = "nvidia"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://integrate.api.nvidia.com/v1",
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._api_key = api_key
        self._client = OpenAI(base_url=base_url, api_key=api_key)
        self._sleep = sleep

    def generate(self, prompt: str, model: str, temperature: float) -> str:
        def call():
            completion = self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                top_p=1,
                max_tokens=16384,
                seed=42,
            )
            return completion.choices[0].message.content

        try:
            return with_backoff(
                call, is_retryable=_is_retryable_nvidia_error,
                max_retries=5, base_delay=10.0, max_delay=120.0,
                sleep=self._sleep,
            )
        except Exception as exc:
            raise ProviderError(f"NVIDIA call failed: {_sanitize(str(exc), self._api_key)}") from exc
```

`backend/scripts/smoke_test_nvidia.py` (manual verification only, not run by pytest — costs a real API call):
```python
"""Manual smoke test. Run with `python scripts/smoke_test_nvidia.py` after
setting NVIDIA_API_KEY in backend/.env."""
from app.core.config import get_settings
from app.core.llm.providers.nvidia_provider import NvidiaProvider

if __name__ == "__main__":
    settings = get_settings()
    if not settings.nvidia_api_key:
        raise SystemExit("Set NVIDIA_API_KEY in backend/.env before running this script.")
    provider = NvidiaProvider(api_key=settings.nvidia_api_key, base_url=settings.nvidia_base_url)
    result = provider.generate("Say hello in exactly three words.", model="z-ai/glm-5.2", temperature=1.0)
    print(result)
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `backend/`): `pytest tests/test_nvidia_provider.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/llm/providers/__init__.py backend/app/core/llm/providers/nvidia_provider.py \
  backend/scripts/smoke_test_nvidia.py backend/tests/test_nvidia_provider.py
git commit -m "feat: add NvidiaProvider adapter as primary LLM provider (retry classification + key sanitization)"
```

---

### Task 9: Gemini/Claude/OpenAI stub adapters

> **Plan amendment:** Gemini moves here from its original Task 8 slot — it is now a stub alongside Claude and OpenAI, matching the pattern already planned for those two, since NVIDIA (Task 8) is the primary provider instead.

**Files:**
- Create: `backend/app/core/llm/providers/stub_providers.py`
- Test: `backend/tests/test_stub_providers.py`

**Interfaces:**
- Produces: `GeminiProvider(api_key: str | None = None)`, `ClaudeProvider(api_key: str | None = None)`, `OpenAIProvider(api_key: str | None = None)`, all implementing `Provider` and all raising `NotImplementedError` from `.generate(...)`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_stub_providers.py`:
```python
import pytest
from app.core.llm.providers.stub_providers import GeminiProvider, ClaudeProvider, OpenAIProvider


def test_gemini_provider_raises_not_implemented():
    provider = GeminiProvider(api_key="unused")
    with pytest.raises(NotImplementedError):
        provider.generate("hi", model="gemini-x", temperature=0.5)


def test_claude_provider_raises_not_implemented():
    provider = ClaudeProvider(api_key="unused")
    with pytest.raises(NotImplementedError):
        provider.generate("hi", model="claude-x", temperature=0.5)


def test_openai_provider_raises_not_implemented():
    provider = OpenAIProvider(api_key="unused")
    with pytest.raises(NotImplementedError):
        provider.generate("hi", model="gpt-x", temperature=0.5)
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `pytest tests/test_stub_providers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.llm.providers.stub_providers'`

- [ ] **Step 3: Implement the stubs**

`backend/app/core/llm/providers/stub_providers.py`:
```python
class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def generate(self, prompt: str, model: str, temperature: float) -> str:
        raise NotImplementedError("GeminiProvider is a Phase 1 stub; wired in a later phase.")


class ClaudeProvider:
    name = "claude"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def generate(self, prompt: str, model: str, temperature: float) -> str:
        raise NotImplementedError("ClaudeProvider is a Phase 1 stub; wired in a later phase.")


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def generate(self, prompt: str, model: str, temperature: float) -> str:
        raise NotImplementedError("OpenAIProvider is a Phase 1 stub; wired in a later phase.")
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `backend/`): `pytest tests/test_stub_providers.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/llm/providers/stub_providers.py backend/tests/test_stub_providers.py
git commit -m "feat: add Gemini/Claude/OpenAI stub provider adapters"
```

---

### Task 10: LLM call audit logger

**Files:**
- Create: `backend/app/core/llm/llm_call_logger.py`
- Test: `backend/tests/test_llm_call_logger.py`

**Interfaces:**
- Consumes: `LLMCall` (Task 4), `AIOrchestrator`/`TaskConfig` (Task 6).
- Produces: `make_db_logger(db: Session, session_id: int | None = None) -> Callable[[dict], None]` — an `on_call_logged` callback that persists every orchestrator attempt as an `LLMCall` row.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_llm_call_logger.py`:
```python
from pydantic import BaseModel
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, LLMCall
from app.core.llm.llm_call_logger import make_db_logger
from app.core.llm.orchestrator import AIOrchestrator, TaskConfig


class EchoResult(BaseModel):
    text: str


class AlwaysSucceedsProvider:
    name = "gemini"

    def generate(self, prompt, model, temperature):
        return '{"text": "hi"}'


def test_orchestrator_run_persists_llm_call_rows():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        logger = make_db_logger(db, session_id=None)
        orchestrator = AIOrchestrator(providers={"gemini": AlwaysSucceedsProvider()}, on_call_logged=logger)
        task = TaskConfig(task_type="echo", provider="gemini", model="m1", temperature=0.5, response_schema=EchoResult)

        orchestrator.run(task, prompt="hi")

        rows = db.query(LLMCall).all()
        assert len(rows) == 1
        assert rows[0].provider == "gemini"
        assert rows[0].validated is True
        assert rows[0].response_payload == {"text": '{"text": "hi"}'}
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `backend/`): `pytest tests/test_llm_call_logger.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.llm.llm_call_logger'`

- [ ] **Step 3: Implement the logger**

`backend/app/core/llm/llm_call_logger.py`:
```python
from sqlalchemy.orm import Session
from app.models.db_models import LLMCall


def make_db_logger(db: Session, session_id: int | None = None):
    def log(record: dict) -> None:
        db.add(LLMCall(
            session_id=session_id,
            prompt_version_id=record.get("prompt_version_id"),
            provider=record["provider"],
            model=record["model"],
            task_type=record["task_type"],
            temperature=record.get("temperature"),
            request_payload=record.get("request_payload"),
            response_payload={"text": record["response_payload"]} if record.get("response_payload") else None,
            validated=record["validated"],
            latency_ms=record.get("latency_ms"),
        ))
        db.commit()

    return log
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `backend/`): `pytest tests/test_llm_call_logger.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/llm/llm_call_logger.py backend/tests/test_llm_call_logger.py
git commit -m "feat: persist every orchestrator attempt to the llm_calls audit table"
```

---

### Task 11: `hiring-agent-service` HTTP wrapper around the existing hiring-agent repo

**Files:**
- Create: `hiring-agent-service/app.py`
- Create: `hiring-agent-service/requirements.txt`
- Create: `hiring-agent-service/requirements-dev.txt`
- Create: `hiring-agent-service/pytest.ini`
- Create: `hiring-agent-service/README.md`
- Create: `hiring-agent-service/Dockerfile`
- Test: `hiring-agent-service/tests/test_evaluate.py`

**Interfaces:**
- Consumes: `ResumeEvaluator`, `DEFAULT_MODEL`, `MODEL_PARAMETERS` from the existing `hiring-agent` repo (imported via `HIRING_AGENT_REPO_PATH`, default resolves to the sibling `hiring-agent-imp` checkout).
- Produces: `POST /evaluate` (body `{resume_text: str, github_username: str | None}` → JSON with `overall_score`, 4 category scores, `evidence`, `bonus_points`, `deductions`, `rubric_version`, `hiring_agent_service_version`, `raw`), `GET /health`.
- This wrapper never modifies files in the `hiring-agent` repo — it only imports from it.

- [ ] **Step 1: Write the failing test**

`hiring-agent-service/pytest.ini`:
```ini
[pytest]
pythonpath = .
```

`hiring-agent-service/requirements-dev.txt`:
```
pytest==8.3.4
httpx==0.27.2
```

`hiring-agent-service/tests/test_evaluate.py`:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
import app as app_module
from models import EvaluationData


class FakeEvaluator:
    def __init__(self, model_name, model_params):
        pass

    def evaluate_resume(self, resume_text: str) -> EvaluationData:
        return EvaluationData.model_validate({
            "scores": {
                "open_source": {"score": 30, "max": 35, "evidence": "3 popular repos"},
                "self_projects": {"score": 25, "max": 30, "evidence": "2 solid projects"},
                "production": {"score": 20, "max": 25, "evidence": "2 years production"},
                "technical_skills": {"score": 8, "max": 10, "evidence": "Python, FastAPI"},
            },
            "bonus_points": {"total": 5, "breakdown": "Active OSS contributor"},
            "deductions": {"total": 0, "reasons": "No deductions"},
            "key_strengths": ["Strong OSS presence"],
            "areas_for_improvement": ["More production depth"],
        })


def test_evaluate_returns_structured_score(monkeypatch):
    monkeypatch.setattr(app_module, "ResumeEvaluator", FakeEvaluator)
    client = TestClient(app_module.app)

    response = client.post("/evaluate", json={
        "resume_text": "Jane Doe, Senior Backend Engineer...",
        "github_username": None,
    })

    assert response.status_code == 200
    body = response.json()
    assert body["overall_score"] == 88.0
    assert body["open_source_score"] == 30
    assert body["rubric_version"] == "hiring-agent-v1"
    assert body["raw"]["bonus_points"]["total"] == 5


def test_health_endpoint():
    client = TestClient(app_module.app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

Note on the expected score: category scores 30+25+20+8=83, +5 bonus=88, -0 deductions=88; `max_total`=35+30+25+10=100, `max_possible`=120; `min(88, 120)` = 88.0.

- [ ] **Step 2: Run test to verify it fails**

Run (from `hiring-agent-service/`, with the `hiring-agent-imp` sibling repo present at `../hiring-agent-imp` relative to `resume-tailor/`, i.e. `../../hiring-agent-imp` relative to `hiring-agent-service/`):
`pytest tests/test_evaluate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'` (app.py doesn't exist yet)

- [ ] **Step 3: Implement the wrapper**

`hiring-agent-service/requirements.txt`:
```
PyMuPDF==1.26.3
ollama==0.5.1
pydantic==2.11.7
requests==2.32.4
pymupdf4llm==0.0.27
Jinja2==3.1.6
google-generativeai==0.4.0
python-dotenv==1.0.1
fastapi==0.115.6
uvicorn[standard]==0.32.1
```

`hiring-agent-service/app.py`:
```python
import os
import sys
from pathlib import Path

HIRING_AGENT_REPO_PATH = os.environ.get(
    "HIRING_AGENT_REPO_PATH",
    str(Path(__file__).resolve().parent.parent / "hiring-agent-imp"),
)
sys.path.insert(0, HIRING_AGENT_REPO_PATH)

from fastapi import FastAPI
from pydantic import BaseModel
from evaluator import ResumeEvaluator
from prompt import DEFAULT_MODEL, MODEL_PARAMETERS

RUBRIC_VERSION = "hiring-agent-v1"
HIRING_AGENT_SERVICE_VERSION = "0.1.0"

CATEGORY_MAXES = {
    "open_source": 35,
    "self_projects": 30,
    "production": 25,
    "technical_skills": 10,
}

app = FastAPI(title="Hiring Agent Service")


class EvaluateRequest(BaseModel):
    resume_text: str
    github_username: str | None = None


def compute_overall_score(evaluation) -> float:
    total = 0.0
    max_total = 0
    for category_name, category_data in evaluation.scores.model_dump().items():
        capped = min(category_data["score"], CATEGORY_MAXES.get(category_name, category_data["max"]))
        total += capped
        max_total += category_data["max"]
    total += evaluation.bonus_points.total
    total -= evaluation.deductions.total
    max_possible = max_total + 20
    return min(total, max_possible)


@app.post("/evaluate")
def evaluate(request: EvaluateRequest):
    model_params = MODEL_PARAMETERS.get(DEFAULT_MODEL)
    evaluator = ResumeEvaluator(model_name=DEFAULT_MODEL, model_params=model_params)
    evaluation = evaluator.evaluate_resume(request.resume_text)

    scores = evaluation.scores.model_dump()
    return {
        "overall_score": compute_overall_score(evaluation),
        "open_source_score": scores["open_source"]["score"],
        "projects_score": scores["self_projects"]["score"],
        "production_score": scores["production"]["score"],
        "technical_skills_score": scores["technical_skills"]["score"],
        "evidence": {name: data["evidence"] for name, data in scores.items()},
        "bonus_points": evaluation.bonus_points.model_dump(),
        "deductions": evaluation.deductions.model_dump(),
        "rubric_version": RUBRIC_VERSION,
        "hiring_agent_service_version": HIRING_AGENT_SERVICE_VERSION,
        "raw": evaluation.model_dump(),
    }


@app.get("/health")
def health():
    return {"status": "ok"}
```

`hiring-agent-service/README.md`:
```markdown
# hiring-agent-service

Thin HTTP wrapper around the existing `hiring-agent` repo. Never modifies that
repo — only imports from it.

## Running locally

Requires the `hiring-agent` repo checked out as a sibling directory (default:
`../hiring-agent-imp` relative to this service), or set `HIRING_AGENT_REPO_PATH`
to point elsewhere. Also requires `GEMINI_API_KEY` in the environment for real
evaluations (not needed to run the test suite, which mocks `ResumeEvaluator`).

    pip install -r requirements.txt -r requirements-dev.txt
    pytest
    uvicorn app:app --host 0.0.0.0 --port 8100
```

`hiring-agent-service/Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /service
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV HIRING_AGENT_REPO_PATH=/hiring-agent

EXPOSE 8100
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `hiring-agent-service/`):
```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/test_evaluate.py -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add hiring-agent-service/app.py hiring-agent-service/requirements.txt hiring-agent-service/requirements-dev.txt \
  hiring-agent-service/pytest.ini hiring-agent-service/README.md hiring-agent-service/Dockerfile \
  hiring-agent-service/tests/test_evaluate.py
git commit -m "feat: add hiring-agent-service HTTP wrapper with /evaluate and /health"
```

---

### Task 12: Backend API routes (resumes, job-postings, sessions, run-stage stub, health)

**Files:**
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/deps.py`
- Create: `backend/app/api/resumes.py`
- Create: `backend/app/api/job_postings.py`
- Create: `backend/app/api/sessions.py`
- Create: `backend/app/api/health.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/test_api_resumes.py`
- Test: `backend/tests/test_api_sessions.py`
- Test: `backend/tests/test_api_health.py`

**Interfaces:**
- Consumes: `Resume`, `JobPosting`, `TailoringSession`, `PipelineRun`, `GeneratedDocument` (Task 4), `LocalDiskStorage` (Task 2), `get_settings` (Task 1).
- Produces: `get_db()` FastAPI dependency; routes `POST /resumes`, `POST /job-postings`, `POST /sessions`, `POST /sessions/{id}/run-stage/{stage_name}` (always 501), `GET /sessions/{id}/status`, `GET /sessions/{id}/documents`, `GET /health`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/conftest.py`:
```python
import pytest
from fastapi.testclient import TestClient
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base
from app.api.deps import get_db
from app.main import app


@pytest.fixture
def db_session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
```

`backend/tests/test_api_resumes.py`:
```python
import io


def test_upload_resume_saves_file_and_creates_row(client, tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))

    response = client.post(
        "/resumes",
        files={"file": ("jane.pdf", io.BytesIO(b"%PDF-1.4 fake content"), "application/pdf")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["original_filename"] == "jane.pdf"
    assert body["storage_path"].endswith("jane.pdf")
    assert (tmp_path / "resumes").exists()
```

`backend/tests/test_api_sessions.py`:
```python
from app.models.db_models import Resume, JobPosting


def test_create_session_requires_existing_resume_and_job_posting(client):
    response = client.post("/sessions", json={"resume_id": 999, "job_posting_id": 999})
    assert response.status_code == 404


def test_create_session_succeeds_with_valid_ids(client, db_session):
    resume = Resume(original_filename="jane.pdf", storage_path="/tmp/jane.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()

    response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})

    assert response.status_code == 201
    assert response.json()["status"] == "created"


def test_run_stage_returns_501_for_unimplemented_stage(client, db_session):
    resume = Resume(original_filename="jane.pdf", storage_path="/tmp/jane.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    response = client.post(f"/sessions/{session_id}/run-stage/resume_parsing")

    assert response.status_code == 501


def test_get_status_returns_empty_pipeline_runs_in_phase_one(client, db_session):
    resume = Resume(original_filename="jane.pdf", storage_path="/tmp/jane.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    response = client.get(f"/sessions/{session_id}/status")

    assert response.status_code == 200
    assert response.json()["pipeline_runs"] == []
```

`backend/tests/test_api_health.py`:
```python
import httpx
from app.api import health as health_module


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


def test_health_reports_ok_when_db_and_hiring_agent_are_up(client, monkeypatch):
    monkeypatch.setattr(health_module.httpx, "get", lambda url, timeout: FakeResponse(200))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"database": "ok", "hiring_agent_service": "ok"}


def test_health_reports_503_when_hiring_agent_is_down(client, monkeypatch):
    def raise_connect_error(url, timeout):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(health_module.httpx, "get", raise_connect_error)

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["hiring_agent_service"] == "error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `backend/`): `pytest tests/test_api_resumes.py tests/test_api_sessions.py tests/test_api_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.api'`

- [ ] **Step 3: Implement the routes**

`backend/app/api/__init__.py`: empty file.

`backend/app/api/deps.py`:
```python
from functools import lru_cache
from typing import Generator
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory


@lru_cache
def _get_session_factory():
    engine = make_engine(get_settings().database_url)
    return make_session_factory(engine)


def get_db() -> Generator[Session, None, None]:
    db = _get_session_factory()()
    try:
        yield db
    finally:
        db.close()
```

`backend/app/api/resumes.py`:
```python
import uuid
from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.core.storage import LocalDiskStorage
from app.core.config import get_settings
from app.models.db_models import Resume

router = APIRouter(prefix="/resumes", tags=["resumes"])


@router.post("", status_code=201)
async def upload_resume(file: UploadFile = File(...), db: Session = Depends(get_db)):
    settings = get_settings()
    storage = LocalDiskStorage(root=settings.storage_root)
    contents = await file.read()
    key = f"resumes/{uuid.uuid4()}/{file.filename}"
    storage_path = storage.save(key, contents)

    resume = Resume(original_filename=file.filename, storage_path=storage_path)
    db.add(resume)
    db.commit()
    db.refresh(resume)

    return {"id": resume.id, "original_filename": resume.original_filename, "storage_path": resume.storage_path}
```

`backend/app/api/job_postings.py`:
```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.models.db_models import JobPosting

router = APIRouter(prefix="/job-postings", tags=["job-postings"])


class CreateJobPostingRequest(BaseModel):
    source_url: str | None = None
    source_provider: str | None = None
    raw_text: str | None = None

    @model_validator(mode="after")
    def require_url_or_text(self):
        if not self.source_url and not self.raw_text:
            raise ValueError("either source_url or raw_text must be provided")
        return self


@router.post("", status_code=201)
def create_job_posting(request: CreateJobPostingRequest, db: Session = Depends(get_db)):
    posting = JobPosting(
        source_url=request.source_url,
        source_provider=request.source_provider,
        raw_text=request.raw_text,
    )
    db.add(posting)
    db.commit()
    db.refresh(posting)
    return {"id": posting.id, "source_url": posting.source_url}
```

`backend/app/api/sessions.py`:
```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.models.db_models import Resume, JobPosting, TailoringSession, PipelineRun, GeneratedDocument

router = APIRouter(prefix="/sessions", tags=["sessions"])


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
    if db.get(TailoringSession, session_id) is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")
    raise HTTPException(
        status_code=501,
        detail=f"stage '{stage_name}' is not implemented yet (Phase 1 contract only)",
    )


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

`backend/app/api/health.py`:
```python
import httpx
from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health(response: Response, db: Session = Depends(get_db)):
    settings = get_settings()

    database_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        database_ok = False

    hiring_agent_ok = True
    try:
        reply = httpx.get(f"{settings.hiring_agent_service_url}/health", timeout=2.0)
        hiring_agent_ok = reply.status_code == 200
    except httpx.HTTPError:
        hiring_agent_ok = False

    if not (database_ok and hiring_agent_ok):
        response.status_code = 503

    return {
        "database": "ok" if database_ok else "error",
        "hiring_agent_service": "ok" if hiring_agent_ok else "error",
    }
```

`backend/app/main.py` (modify):
```python
from fastapi import FastAPI
from app.api import resumes, job_postings, sessions, health

app = FastAPI(title="Resume Tailor Backend")
app.include_router(resumes.router)
app.include_router(job_postings.router)
app.include_router(sessions.router)
app.include_router(health.router)


@app.get("/")
def root():
    return {"service": "resume-tailor-backend"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `backend/`): `pytest tests/test_api_resumes.py tests/test_api_sessions.py tests/test_api_health.py -v`
Expected: 8 passed

- [ ] **Step 5: Run the full backend test suite**

Run (from `backend/`): `pytest -v`
Expected: all tests from Tasks 1–12 pass (exact count depends on the final task-by-task test tallies, including any review-driven fixes)

- [ ] **Step 6: Commit**

```bash
git add backend/app/api backend/app/main.py backend/tests/conftest.py backend/tests/test_api_resumes.py \
  backend/tests/test_api_sessions.py backend/tests/test_api_health.py
git commit -m "feat: add session/job-oriented API routes with 501 run-stage contract"
```

---

### Task 13: Docker Compose wiring and end-to-end local verification

**Files:**
- Create: `backend/Dockerfile`
- Create: `infra/docker-compose.yml`
- Create: `infra/.env.example`
- Create: `README.md` (repo root)

**Interfaces:**
- Consumes: `backend/Dockerfile`, `hiring-agent-service/Dockerfile` (Task 11), the sibling `hiring-agent-imp` checkout (bind-mounted read-only).

- [ ] **Step 1: Write the Dockerfiles and compose file**

`backend/Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`infra/docker-compose.yml`:
```yaml
version: "3.9"

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: resume_tailor
      POSTGRES_PASSWORD: resume_tailor
      POSTGRES_DB: resume_tailor
    ports:
      - "5442:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U resume_tailor"]
      interval: 5s
      timeout: 5s
      retries: 5

  hiring-agent-service:
    build:
      context: ../hiring-agent-service
    volumes:
      - ../../hiring-agent-imp:/hiring-agent:ro
    environment:
      HIRING_AGENT_REPO_PATH: /hiring-agent
      GEMINI_API_KEY: ${GEMINI_API_KEY}
    ports:
      - "8100:8100"

  backend:
    build:
      context: ../backend
    depends_on:
      postgres:
        condition: service_healthy
      hiring-agent-service:
        condition: service_started
    environment:
      DATABASE_URL: postgresql://resume_tailor:resume_tailor@postgres:5432/resume_tailor
      STORAGE_ROOT: /app/storage
      HIRING_AGENT_SERVICE_URL: http://hiring-agent-service:8100
      GEMINI_API_KEY: ${GEMINI_API_KEY}
      NVIDIA_API_KEY: ${NVIDIA_API_KEY}
    volumes:
      - backend_storage:/app/storage
    ports:
      - "8020:8000"

volumes:
  postgres_data:
  backend_storage:
```

`infra/.env.example`:
```
GEMINI_API_KEY=
NVIDIA_API_KEY=
```

`README.md` (repo root):
```markdown
# resume-tailor

AI resume tailoring platform. Phase 1 delivers the architecture skeleton only —
see `docs/superpowers/specs/2026-07-03-phase1-architecture-design.md` for the
full design and `docs/superpowers/plans/2026-07-03-phase1-architecture.md` for
what was built.

## Local development

1. Copy `infra/.env.example` to `infra/.env` and fill in `GEMINI_API_KEY`
   (and `NVIDIA_API_KEY` once you have one).
2. This repo expects the existing `hiring-agent` repo checked out as a sibling
   directory (`../hiring-agent-imp` relative to this repo's parent).
3. From `infra/`: `docker compose up -d --build`
4. Check `curl http://localhost:8020/health`

## Running backend tests without Docker

    cd backend
    pip install -r requirements.txt -r requirements-dev.txt
    pytest
```

- [ ] **Step 2: Bring the stack up and verify end-to-end**

Run (from `infra/`, after creating `infra/.env` with a real `GEMINI_API_KEY`):
```bash
docker compose up -d --build
```
Expected: three containers (`postgres`, `hiring-agent-service`, `backend`) report `running`/`healthy`.

Apply the migration against the real Postgres container:
```bash
docker compose exec backend alembic upgrade head
```
Expected: log ending in `Running upgrade  -> 0001, initial schema`

Check health:
```bash
curl http://localhost:8020/health
```
Expected: `{"database":"ok","hiring_agent_service":"ok"}`

Tear down:
```bash
docker compose down
```

- [ ] **Step 3: Commit**

```bash
git add backend/Dockerfile infra/docker-compose.yml infra/.env.example README.md
git commit -m "feat: add Docker Compose stack (postgres, hiring-agent-service, backend) and dev README"
```

---

## Self-Review

**Spec coverage:**
- §2 Hiring Agent Integration → Task 11 (thin wrapper, never modifies the source repo).
- §3 Canonical Resume JSON + schema versioning → Task 3.
- §4 Service Boundaries → reflected in the `backend/app/` module layout across all tasks; no extra network hops introduced beyond `hiring-agent-service`.
- §5 AI Orchestrator + failure policy → Tasks 6, 7 (retry helper, reused by NVIDIA and, later, Gemini), 8 (NVIDIA, primary), 9 (Gemini/Claude/OpenAI stubs).
- §6 Prompt Registry keyed by `(task_type, version)` → Task 5.
- §7 Data model (9 tables) → Task 4.
- §8 API shape (session/job-oriented, 501 stubs) → Task 12.
- §9 n8n mapping → documentation-only, already captured in the spec; no code task needed.
- §10 Storage → Task 2.
- §11 Extensibility notes → satisfied by design (open-ended `document_type`/`stage_name` strings, `fallback_providers` list, `schema_version` field) rather than a discrete task.
- §12 Repo layout → matches the file paths used across all tasks.
- §13 Deliverables → each of the 9 bullet points maps to a task above.
- §14 Security note → NVIDIA/Gemini keys only ever referenced via `Settings`/env vars in every task; never hardcoded.

**Placeholder scan:** no TBD/TODO markers; every step has complete, runnable code.

**Type consistency:** `Provider.generate(prompt, model, temperature) -> str` signature matches across `provider.py`, `gemini_provider.py`, `nvidia_provider.py`, `stub_providers.py`, and the fakes in `test_orchestrator.py`. `TaskConfig`/`OrchestratorResult` field names match between `orchestrator.py` and `llm_call_logger.py`'s consumption of `on_call_logged` records. `Storage` protocol method names (`save`/`load`/`delete`) match `LocalDiskStorage` and its only caller (`resumes.py`). `ResumeDocument`/`db_models.py` are intentionally decoupled (`resume_json`/`raw_response_json` are untyped `JSON` columns) per §3/§7 of the spec.

---

**Plan complete and saved to `docs/superpowers/plans/2026-07-03-phase1-architecture.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
