import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError
from app.api import resumes, job_postings, sessions, health
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.core.llm.prompt_registry import PromptRegistry

logger = logging.getLogger(__name__)


def sync_prompt_registry() -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    registry = PromptRegistry(prompts_root=settings.prompts_root)

    db = session_factory()
    try:
        registry.sync_to_db(db)
    except OperationalError:
        logger.warning(
            "Could not sync PromptRegistry at startup — database not reachable yet. "
            "Prompt templates will be out of sync with prompt_versions until the next successful sync."
        )
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    sync_prompt_registry()
    yield


app = FastAPI(title="Resume Tailor Backend", lifespan=lifespan)
app.include_router(resumes.router)
app.include_router(job_postings.router)
app.include_router(sessions.router)
app.include_router(health.router)


@app.get("/")
def root():
    return {"service": "resume-tailor-backend"}
