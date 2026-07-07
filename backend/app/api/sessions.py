from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.core.llm.orchestrator_factory import build_orchestrator
from app.core.llm.prompt_registry import PromptRegistry
from app.core.storage import LocalDiskStorage
from app.models.db_models import Resume, JobPosting, TailoringSession, PipelineRun, GeneratedDocument, EvaluationRun, GapAnalysis
from app.services.errors import StageExecutionError
from app.services.resume_parser import parse_resume
from app.services.jd_extractor import extract_job_posting
from app.services.gap_analyzer import analyze_gap
from app.services.tailoring_engine import tailor_resume
from app.services.evaluator import evaluate_resume
from app.services.latex_renderer import LatexRenderer
from app.services.document_generator import generate_document, _compile_latex_to_pdf
from app.services.cover_letter_generator import generate_cover_letter
from app.services.recruiter_summary_generator import generate_recruiter_summary
from app.services.interview_questions_generator import generate_interview_questions

router = APIRouter(prefix="/sessions", tags=["sessions"])

STAGE_TIMEOUT_SECONDS = 330
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


def _run_resume_parsing(db: Session, session: TailoringSession, settings) -> dict:
    resume = db.get(Resume, session.resume_id)
    storage = LocalDiskStorage(root=settings.storage_root)
    orchestrator = build_orchestrator(db, session_id=session.id)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)
    version = parse_resume(db, resume, storage, orchestrator, prompt_registry)
    return {"resume_version_id": version.id}


def _run_jd_extraction(db: Session, session: TailoringSession, settings) -> dict:
    job_posting = db.get(JobPosting, session.job_posting_id)
    orchestrator = build_orchestrator(db, session_id=session.id)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)
    extract_job_posting(db, job_posting, orchestrator, prompt_registry)
    return {"job_posting_id": job_posting.id}


def _run_gap_analysis(db: Session, session: TailoringSession, settings) -> dict:
    orchestrator = build_orchestrator(db, session_id=session.id)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)
    analysis = analyze_gap(db, session, orchestrator, prompt_registry)
    return {"gap_analysis_id": analysis.id}


def _run_tailoring(db: Session, session: TailoringSession, settings) -> dict:
    orchestrator = build_orchestrator(db, session_id=session.id)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)
    tailored_version = tailor_resume(db, session, orchestrator, prompt_registry)
    return {"resume_version_id": tailored_version.id}


def _run_evaluation(db: Session, session: TailoringSession, settings) -> dict:
    with httpx.Client(timeout=300.0) as http_client:
        evaluation = evaluate_resume(db, session, http_client, settings)
    return {"evaluation_run_id": evaluation.id}


def _run_document_generation(db: Session, session: TailoringSession, settings) -> dict:
    storage = LocalDiskStorage(root=settings.storage_root)
    latex_renderer = LatexRenderer(templates_root=settings.latex_templates_root)
    document = generate_document(db, session, storage, latex_renderer, _compile_latex_to_pdf)
    return {"generated_document_id": document.id}


def _run_cover_letter(db: Session, session: TailoringSession, settings) -> dict:
    orchestrator = build_orchestrator(db, session_id=session.id)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)
    document = generate_cover_letter(db, session, orchestrator, prompt_registry)
    return {"generated_document_id": document.id}


def _run_recruiter_summary(db: Session, session: TailoringSession, settings) -> dict:
    orchestrator = build_orchestrator(db, session_id=session.id)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)
    document = generate_recruiter_summary(db, session, orchestrator, prompt_registry)
    return {"generated_document_id": document.id}


def _run_interview_questions(db: Session, session: TailoringSession, settings) -> dict:
    orchestrator = build_orchestrator(db, session_id=session.id)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)
    document = generate_interview_questions(db, session, orchestrator, prompt_registry)
    return {"generated_document_id": document.id}


STAGE_RUNNERS = {
    "resume_parsing": _run_resume_parsing,
    "jd_extraction": _run_jd_extraction,
    "gap_analysis": _run_gap_analysis,
    "tailoring_rewrite": _run_tailoring,
    "evaluation": _run_evaluation,
    "document_generation": _run_document_generation,
    "cover_letter": _run_cover_letter,
    "recruiter_summary": _run_recruiter_summary,
    "interview_questions": _run_interview_questions,
}


@router.post("/{session_id}/run-stage/{stage_name}")
def run_stage(session_id: int, stage_name: str, db: Session = Depends(get_db)):
    session = db.get(TailoringSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")

    stage_runner = STAGE_RUNNERS.get(stage_name)
    if stage_runner is None:
        raise HTTPException(
            status_code=501,
            detail=f"stage '{stage_name}' is not implemented yet (Phase 1 contract only)",
        )

    settings = get_settings()
    pipeline_run = PipelineRun(
        session_id=session_id, stage_name=stage_name, status="running", started_at=_utcnow(),
    )
    db.add(pipeline_run)
    db.commit()
    db.refresh(pipeline_run)
    pipeline_run_id = pipeline_run.id  # captured before the background thread starts, so the
    # timeout branch below never needs to read an attribute off the request-thread-bound
    # `pipeline_run` object after the worker thread may have started mutating shared state.

    future = _STAGE_EXECUTOR.submit(stage_runner, db, session, settings)

    try:
        result = future.result(timeout=STAGE_TIMEOUT_SECONDS)
    except FutureTimeoutError:
        # The worker thread is still running the stage in the background and cannot be
        # forcibly cancelled — it may still commit against `db` after we give up waiting on it.
        # Touching the same `db` Session from this (the request) thread while that's possible
        # is unsafe (SQLAlchemy Sessions aren't safe for concurrent multi-thread use), so the
        # failure record below is written through a fresh, independent session instead of `db`.
        error_message = f"{stage_name} timed out after {STAGE_TIMEOUT_SECONDS} seconds"
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
    except StageExecutionError as exc:
        pipeline_run.status = "failed"
        pipeline_run.error_message = str(exc)
        pipeline_run.completed_at = _utcnow()
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc))

    pipeline_run.status = "succeeded"
    pipeline_run.completed_at = _utcnow()
    db.commit()

    return {"stage_name": stage_name, "status": "succeeded", **result}


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


@router.get("/{session_id}/reports/ats")
def get_ats_report(session_id: int, db: Session = Depends(get_db)):
    session = db.get(TailoringSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")

    evaluation = (
        db.query(EvaluationRun)
        .filter_by(session_id=session_id)
        .order_by(EvaluationRun.id.desc())
        .first()
    )
    if evaluation is None:
        raise HTTPException(status_code=404, detail="evaluation has not succeeded for this session yet")

    raw = evaluation.raw_response_json or {}
    return {
        "session_id": session_id,
        "evaluation_run_id": evaluation.id,
        "overall_score": evaluation.overall_score,
        "open_source_score": evaluation.open_source_score,
        "projects_score": evaluation.projects_score,
        "production_score": evaluation.production_score,
        "technical_skills_score": evaluation.technical_skills_score,
        "rubric_version": evaluation.rubric_version,
        "hiring_agent_service_version": evaluation.hiring_agent_service_version,
        "evidence": raw.get("evidence"),
        "bonus_points": raw.get("bonus_points"),
        "deductions": raw.get("deductions"),
    }


@router.get("/{session_id}/reports/skill-gap")
def get_skill_gap_report(session_id: int, db: Session = Depends(get_db)):
    session = db.get(TailoringSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")

    gap_analysis = (
        db.query(GapAnalysis)
        .filter_by(session_id=session_id)
        .order_by(GapAnalysis.id.desc())
        .first()
    )
    if gap_analysis is None:
        raise HTTPException(status_code=404, detail="gap_analysis has not succeeded for this session yet")

    analysis = gap_analysis.analysis_json or {}
    return {
        "session_id": session_id,
        "gap_analysis_id": gap_analysis.id,
        "matching_skills": analysis.get("matching_skills", []),
        "missing_skills": analysis.get("missing_skills", []),
        "experience_gap_notes": analysis.get("experience_gap_notes"),
        "relevant_projects": analysis.get("relevant_projects", []),
        "irrelevant_projects": analysis.get("irrelevant_projects", []),
        "recommended_keywords": analysis.get("recommended_keywords", []),
    }
