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
