"""Regression guard for the Task 1 Critical finding: a migration that changes
llm_calls.prompt_version_id's FK constraint must never drop and recreate the
column itself, since that silently discards every existing row's value.

This test requires a reachable Postgres, because the 0002 migration's DDL
(ALTER TABLE ... DROP/ADD CONSTRAINT on a foreign key) is not supported by
SQLite outside Alembic batch mode. Start the docker-compose postgres service
(from infra/: `docker compose up -d postgres`) or set TEST_POSTGRES_URL to
point at a reachable Postgres before running this test; it skips cleanly if
none is available.

Note on scaffolding: the schema this test migrates FROM is built by running the
real 0001 migration's `upgrade()` imperatively (not `Base.metadata.create_all`).
`Base.metadata` reflects the *current* ORM models, which already encode 0002's
changes (the unique constraint on prompt_versions, and RESTRICT instead of
CASCADE on the llm_calls FK) — creating the "before" schema from Base.metadata
would make 0002's `create_unique_constraint` fail immediately (the constraint
would already exist) and wouldn't actually exercise a pre-0002 -> post-0002
upgrade. Running 0001's real upgrade() first gives a true pre-0002 schema.
"""
import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.models.db_models import PromptVersion, LLMCall

TEST_POSTGRES_URL = os.environ.get(
    "TEST_POSTGRES_URL", "postgresql://resume_tailor:resume_tailor@localhost:5442/resume_tailor"
)

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"
MIGRATION_0001_PATH = VERSIONS_DIR / "0001_initial_schema.py"
MIGRATION_0002_PATH = VERSIONS_DIR / "0002_prompt_version_unique_and_llm_calls_restrict.py"


def _postgres_available() -> bool:
    try:
        create_engine(TEST_POSTGRES_URL).connect().close()
        return True
    except OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_available(),
    reason=(
        "requires a reachable Postgres — this migration's DDL is not supported by SQLite "
        "outside Alembic batch mode. Start the docker-compose postgres service or set "
        "TEST_POSTGRES_URL."
    ),
)


def _load_migration(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_0002_preserves_existing_llm_calls_prompt_version_id():
    migration_0001 = _load_migration(MIGRATION_0001_PATH, "migration_0001_under_test")
    migration_0002 = _load_migration(MIGRATION_0002_PATH, "migration_0002_under_test")
    engine = create_engine(TEST_POSTGRES_URL)
    schema_name = f"migration_test_{uuid.uuid4().hex[:8]}"

    with engine.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
        connection.execute(text(f'SET search_path TO "{schema_name}"'))
        connection.commit()

        try:
            # Build the true pre-0002 schema by running the real 0001 migration, not
            # Base.metadata.create_all (see module docstring for why that would be wrong).
            migration_context = MigrationContext.configure(connection)
            with Operations.context(migration_context):
                migration_0001.upgrade()
            connection.commit()

            SessionFactory = sessionmaker(bind=connection)
            session = SessionFactory()
            prompt_version = PromptVersion(
                task_type="resume_parsing", name="resume_parsing", version="v1",
                template_path="resume_parsing/v1.jinja2",
            )
            session.add(prompt_version)
            session.commit()

            llm_call = LLMCall(
                prompt_version_id=prompt_version.id, provider="nvidia", model="m1",
                task_type="resume_parsing", validated=True,
            )
            session.add(llm_call)
            session.commit()

            llm_call_id = llm_call.id
            original_prompt_version_id = prompt_version.id
            session.close()

            # Now run the real migration under test.
            migration_context = MigrationContext.configure(connection)
            with Operations.context(migration_context):
                migration_0002.upgrade()
            connection.commit()

            result = connection.execute(
                text("SELECT prompt_version_id FROM llm_calls WHERE id = :id"),
                {"id": llm_call_id},
            ).scalar_one()
            assert result == original_prompt_version_id
        finally:
            connection.rollback()
            connection.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
            connection.commit()
