import json
from sqlalchemy.orm import Session
from app.core.llm.orchestrator import AIOrchestrator, TaskConfig, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import TailoringSession, JobPosting, ResumeVersion, GapAnalysis
from app.models.gap_analysis import GapAnalysisDocument
from app.services.errors import StageExecutionError

GAP_ANALYSIS_MODEL = "z-ai/glm-5.2"
GAP_ANALYSIS_TEMPERATURE = 0.1


class GapAnalysisError(StageExecutionError):
    """Raised when gap analysis fails, whether due to unmet prerequisite stages or
    LLM-structuring failure."""


def analyze_gap(
    db: Session,
    session: TailoringSession,
    orchestrator: AIOrchestrator,
    prompt_registry: PromptRegistry,
) -> GapAnalysis:
    resume_version = (
        db.query(ResumeVersion)
        .filter_by(resume_id=session.resume_id)
        .order_by(ResumeVersion.id.desc())
        .first()
    )
    if resume_version is None:
        raise GapAnalysisError("resume_parsing has not succeeded for this session yet")

    job_posting = db.get(JobPosting, session.job_posting_id)
    if job_posting is None or job_posting.parsed_json is None:
        raise GapAnalysisError("jd_extraction has not succeeded for this session yet")

    prompt = prompt_registry.render(
        "gap_analysis", "v1",
        resume_json=json.dumps(resume_version.resume_json, indent=2),
        job_posting_json=json.dumps(job_posting.parsed_json, indent=2),
    )
    task = TaskConfig(
        task_type="gap_analysis",
        provider="nvidia",
        model=GAP_ANALYSIS_MODEL,
        temperature=GAP_ANALYSIS_TEMPERATURE,
        response_schema=GapAnalysisDocument,
        fallback_providers=[],
    )

    try:
        result = orchestrator.run(task, prompt=prompt)
    except OrchestratorError as exc:
        raise GapAnalysisError(str(exc)) from exc

    analysis = GapAnalysis(
        session_id=session.id,
        resume_version_id=resume_version.id,
        job_posting_id=job_posting.id,
        analysis_json=result.output.model_dump(),
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis
