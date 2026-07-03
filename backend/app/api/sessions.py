from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.models.db_models import Resume, JobPosting, TailoringSession, PipelineRun, GeneratedDocument

router = APIRouter(prefix="/sessions", tags=["sessions"])


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
    if db.get(TailoringSession, session_id) is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")
    raise HTTPException(
        status_code=501,
        detail=f"stage '{stage_name}' is not implemented yet (Phase 1 contract only)",
    )


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
