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
