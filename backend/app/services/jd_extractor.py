from sqlalchemy.orm import Session
from app.core.llm.orchestrator import AIOrchestrator, TaskConfig, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import JobPosting
from app.models.job_posting import JobPostingDocument
from app.services.errors import StageExecutionError

JD_EXTRACTION_MODEL = "z-ai/glm-5.2"
JD_EXTRACTION_TEMPERATURE = 0.1


class JDExtractionError(StageExecutionError):
    """Raised when JD extraction fails, whether due to missing input or LLM-structuring."""


def extract_job_posting(
    db: Session,
    job_posting: JobPosting,
    orchestrator: AIOrchestrator,
    prompt_registry: PromptRegistry,
) -> JobPosting:
    if not job_posting.raw_text:
        raise JDExtractionError(
            "no raw_text on this job posting to extract from — URL fetching is not yet "
            "supported; provide raw_text directly"
        )

    prompt = prompt_registry.render("jd_extraction", "v1", raw_text=job_posting.raw_text)
    task = TaskConfig(
        task_type="jd_extraction",
        provider="nvidia",
        model=JD_EXTRACTION_MODEL,
        temperature=JD_EXTRACTION_TEMPERATURE,
        response_schema=JobPostingDocument,
        fallback_providers=[],
    )

    try:
        result = orchestrator.run(task, prompt=prompt)
    except OrchestratorError as exc:
        raise JDExtractionError(str(exc)) from exc

    job_posting.parsed_json = result.output.model_dump()
    db.commit()
    db.refresh(job_posting)
    return job_posting
