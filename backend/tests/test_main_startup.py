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
