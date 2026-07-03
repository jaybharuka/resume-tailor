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


class LeaksSecretProvider:
    name = "gemini"

    def generate(self, prompt, model, temperature):
        return '{"text": "response containing nvapi-test-secret-abc123 somehow"}'


def test_response_payload_redacts_known_api_keys_before_persisting(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-secret-abc123")

    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        logger = make_db_logger(db, session_id=None)
        orchestrator = AIOrchestrator(providers={"gemini": LeaksSecretProvider()}, on_call_logged=logger)
        task = TaskConfig(task_type="echo", provider="gemini", model="m1", temperature=0.5, response_schema=EchoResult)

        orchestrator.run(task, prompt="hi")

        rows = db.query(LLMCall).all()
        assert len(rows) == 1
        assert rows[0].provider == "gemini"
        assert rows[0].validated is True
        assert "nvapi-test-secret-abc123" not in str(rows[0].response_payload)
