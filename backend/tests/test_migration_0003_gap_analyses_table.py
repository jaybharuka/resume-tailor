"""Migration test for 0003 (gap_analyses table): confirms upgrade() creates the
table and downgrade() cleanly reverses it. Unlike migration 0002
(test_migration_data_preservation.py), this migration is a plain CREATE TABLE
with foreign keys declared inline - fully supported by SQLite outside batch
mode, so no Postgres/data-preservation concern applies here.

Deviation from the original task brief: the brief's draft of this test also
replayed migration 0002's upgrade() before 0003's, to build a "realistic"
pre-0003 schema. That doesn't work on SQLite: 0002 issues raw
ALTER TABLE ... ADD/DROP CONSTRAINT statements outside of Alembic batch mode,
which SQLite's dialect does not support at all (this is exactly why
test_migration_data_preservation.py is skipped unless a real Postgres is
reachable). Since gap_analyses' foreign keys only reference tables/columns
created by 0001 (tailoring_sessions, resume_versions, job_postings) and are
untouched by 0002's changes (which only affect prompt_versions and
llm_calls), running 0001's upgrade() alone is sufficient to exercise a real
pre-0003 -> post-0003 upgrade/downgrade without requiring Postgres.
"""
import importlib.util
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"
MIGRATION_0001_PATH = VERSIONS_DIR / "0001_initial_schema.py"
MIGRATION_0003_PATH = VERSIONS_DIR / "0003_gap_analyses_table.py"


def _load_migration(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_0003_creates_and_drops_gap_analyses_table():
    migration_0001 = _load_migration(MIGRATION_0001_PATH, "migration_0001_for_0003_test")
    migration_0003 = _load_migration(MIGRATION_0003_PATH, "migration_0003_under_test")

    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))

        migration_context = MigrationContext.configure(connection)
        with Operations.context(migration_context):
            migration_0001.upgrade()
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
