from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.llm.orchestrator import AIOrchestrator
from app.core.llm.llm_call_logger import make_db_logger
from app.core.llm.providers.nvidia_provider import NvidiaProvider
from app.core.llm.providers.stub_providers import GeminiProvider, ClaudeProvider, OpenAIProvider


def build_orchestrator(db: Session, session_id: int | None = None) -> AIOrchestrator:
    settings = get_settings()
    providers = {
        "nvidia": NvidiaProvider(api_key=settings.nvidia_api_key, base_url=settings.nvidia_base_url),
        "gemini": GeminiProvider(api_key=settings.gemini_api_key),
        "claude": ClaudeProvider(),
        "openai": OpenAIProvider(),
    }
    return AIOrchestrator(providers=providers, on_call_logged=make_db_logger(db, session_id=session_id))
