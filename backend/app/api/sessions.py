from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.core.llm.orchestrator_factory import build_orchestrator
from app.core.llm.prompt_registry import PromptRegistry
from app.core.storage import LocalDiskStorage
from app.models.db_models import Resume, JobPosting, TailoringSession, PipelineRun, GeneratedDocument
from app.services.resume_parser import parse_resume, ResumeParsingError

router = APIRouter(prefix="/sessions", tags=["sessions"])

RESUME_PARSING_TIMEOUT_SECONDS = 330
_STAGE_EXECUTOR = ThreadPoolExecutor(max_workers=4)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CreateSessionRequest(BaseModel):
    resume_id: int
    job_posting_id: int


@router.post("", status_code=201)
def create_session(request: CreateSessionRequest, db: Session = Depends(get_db)):
    if db.get(Resume, request.resume_id) is None:
        raise HTTPException(status_code=404, detail=f"resume {request.resume_id} not found")
    if db.get(JobPosting, request.job_posting_id) is None:
        raise HTTPException(status_code=404, detail=f"job_posting {request.job_posting_id} not found")

    session = TailoringSession(
        resume_id=request.resume_id, job_posting_id=request.job_posting_id, status="created",
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"id": session.id, "status": session.status}


@router.post("/{session_id}/run-stage/{stage_name}")
def run_stage(session_id: int, stage_name: str, db: Session = Depends(get_db)):
    session = db.get(TailoringSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")

    if stage_name != "resume_parsing":
        raise HTTPException(
            status_code=501,
            detail=f"stage '{stage_name}' is not implemented yet (Phase 1 contract only)",
        )

    resume = db.get(Resume, session.resume_id)
    pipeline_run = PipelineRun(
        session_id=session_id, stage_name=stage_name, status="running", started_at=_utcnow(),
    )
    db.add(pipeline_run)
    db.commit()
    db.refresh(pipeline_run)
    pipeline_run_id = pipeline_run.id  # captured before the background thread starts, so the
    # timeout branch below never needs to read an attribute off the request-thread-bound
    # `pipeline_run` object after the worker thread may have started mutating shared state.

    settings = get_settings()
    storage = LocalDiskStorage(root=settings.storage_root)
    orchestrator = build_orchestrator(db, session_id=session_id)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)

    future = _STAGE_EXECUTOR.submit(parse_resume, db, resume, storage, orchestrator, prompt_registry)

    try:
        version = future.result(timeout=RESUME_PARSING_TIMEOUT_SECONDS)
    except FutureTimeoutError:
        # The worker thread is still running `parse_resume` in the background and cannot be
        # forcibly cancelled — it may still commit against `db` after we give up waiting on it.
        # Touching the same `db` Session from this (the request) thread while that's possible
        # is unsafe (SQLAlchemy Sessions aren't safe for concurrent multi-thread use), so the
        # failure record below is written through a fresh, independent session instead of `db`.
        error_message = f"resume_parsing timed out after {RESUME_PARSING_TIMEOUT_SECONDS} seconds"
        fresh_db = make_session_factory(make_engine(settings.database_url))()
        try:
            fresh_run = fresh_db.get(PipelineRun, pipeline_run_id)
            fresh_run.status = "failed"
            fresh_run.error_message = error_message
            fresh_run.completed_at = _utcnow()
            fresh_db.commit()
        finally:
            fresh_db.close()
        raise HTTPException(status_code=504, detail=error_message)
    except ResumeParsingError as exc:
        pipeline_run.status = "failed"
        pipeline_run.error_message = str(exc)
        pipeline_run.completed_at = _utcnow()
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc))

    pipeline_run.status = "succeeded"
    pipeline_run.completed_at = _utcnow()
    db.commit()

    return {"stage_name": stage_name, "status": "succeeded", "resume_version_id": version.id}


@router.get("/{session_id}/status")
def get_status(session_id: int, db: Session = Depends(get_db)):
    session = db.get(TailoringSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")
    runs = db.query(PipelineRun).filter_by(session_id=session_id).all()
    return {
        "id": session.id,
        "status": session.status,
        "pipeline_runs": [
            {"stage_name": run.stage_name, "status": run.status} for run in runs
        ],
    }


@router.get("/{session_id}/documents")
def list_documents(session_id: int, db: Session = Depends(get_db)):
    session = db.get(TailoringSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")
    documents = db.query(GeneratedDocument).filter_by(session_id=session_id).all()
    return [
        {"document_type": doc.document_type, "storage_path": doc.storage_path, "version_number": doc.version_number}
        for doc in documents
    ]
