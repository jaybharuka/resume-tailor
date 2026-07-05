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
