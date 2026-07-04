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
