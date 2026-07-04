import pytest
from fastapi.testclient import TestClient
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base
from app.api.deps import get_db
from app.main import app
import app.main as main_module
import app.api.sessions as sessions_module


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
def client(db_session, monkeypatch):
    def override_get_db():
        yield db_session

    # `sync_prompt_registry` (run via the app's lifespan on every TestClient startup)
    # builds its own engine/session directly from Settings rather than going through
    # `get_db`, so without this it would silently touch the real default DB file on
    # disk instead of this test's in-memory schema. Point it at the same engine
    # `db_session` is bound to, so the prompt sync runs against the real test schema.
    test_engine = db_session.get_bind()
    monkeypatch.setattr(main_module, "make_engine", lambda database_url: test_engine)
    monkeypatch.setattr(main_module, "make_session_factory", lambda engine: make_session_factory(engine))

    # `run_stage`'s timeout branch (Task 8) similarly builds its own fresh engine/session
    # directly from Settings rather than going through `get_db`, so it needs the same
    # redirection to the in-memory test engine as `sync_prompt_registry` above — otherwise
    # it would look up the pipeline_run row in the real default DB file, where it was never
    # created, instead of this test's in-memory schema.
    monkeypatch.setattr(sessions_module, "make_engine", lambda database_url: test_engine)
    monkeypatch.setattr(sessions_module, "make_session_factory", lambda engine: make_session_factory(engine))

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
