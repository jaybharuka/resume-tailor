import json
from sqlalchemy.orm import Session
from app.core.llm.orchestrator import AIOrchestrator, TaskConfig, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import TailoringSession, JobPosting, GapAnalysis, GeneratedDocument
from app.models.interview_questions import InterviewQuestionsDocument
from app.services.errors import StageExecutionError

INTERVIEW_QUESTIONS_MODEL = "z-ai/glm-5.2"
INTERVIEW_QUESTIONS_TEMPERATURE = 0.3
DOCUMENT_TYPE = "interview_questions"


class InterviewQuestionsError(StageExecutionError):
    """Raised when interview question generation fails: unmet prerequisite
    stages, or LLM-structuring/validation failure (including fewer than the
    required minimum of 5 questions, enforced by InterviewQuestionsDocument's
    min_length constraint)."""


def _next_version_number(db: Session, session_id: int, document_type: str) -> int:
    latest = (
        db.query(GeneratedDocument)
        .filter_by(session_id=session_id, document_type=document_type)
        .order_by(GeneratedDocument.version_number.desc())
        .first()
    )
    return (latest.version_number if latest else 0) + 1


def generate_interview_questions(
    db: Session,
    session: TailoringSession,
    orchestrator: AIOrchestrator,
    prompt_registry: PromptRegistry,
) -> GeneratedDocument:
    job_posting = db.get(JobPosting, session.job_posting_id)
    if job_posting is None or job_posting.parsed_json is None:
        raise InterviewQuestionsError("jd_extraction has not succeeded for this session yet")

    gap_analysis = (
        db.query(GapAnalysis)
        .filter_by(session_id=session.id)
        .order_by(GapAnalysis.id.desc())
        .first()
    )
    if gap_analysis is None:
        raise InterviewQuestionsError("gap_analysis has not succeeded for this session yet")

    prompt = prompt_registry.render(
        "interview_questions", "v1",
        job_posting_json=json.dumps(job_posting.parsed_json, indent=2),
        gap_analysis_json=json.dumps(gap_analysis.analysis_json, indent=2),
    )
    task = TaskConfig(
        task_type="interview_questions",
        provider="nvidia",
        model=INTERVIEW_QUESTIONS_MODEL,
        temperature=INTERVIEW_QUESTIONS_TEMPERATURE,
        response_schema=InterviewQuestionsDocument,
        fallback_providers=[],
    )

    try:
        result = orchestrator.run(task, prompt=prompt)
    except OrchestratorError as exc:
        raise InterviewQuestionsError(str(exc)) from exc

    content = "\n".join(result.output.questions)

    version_number = _next_version_number(db, session.id, DOCUMENT_TYPE)
    document = GeneratedDocument(
        session_id=session.id,
        resume_version_id=None,
        document_type=DOCUMENT_TYPE,
        storage_path=None,
        content=content,
        version_number=version_number,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document
