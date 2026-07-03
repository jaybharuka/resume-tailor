import httpx
from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health(response: Response, db: Session = Depends(get_db)):
    settings = get_settings()

    database_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        database_ok = False

    hiring_agent_ok = True
    try:
        reply = httpx.get(f"{settings.hiring_agent_service_url}/health", timeout=2.0)
        hiring_agent_ok = reply.status_code == 200
    except httpx.HTTPError:
        hiring_agent_ok = False

    if not (database_ok and hiring_agent_ok):
        response.status_code = 503

    return {
        "database": "ok" if database_ok else "error",
        "hiring_agent_service": "ok" if hiring_agent_ok else "error",
    }
