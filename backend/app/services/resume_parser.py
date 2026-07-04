from sqlalchemy.orm import Session
from app.core.llm.orchestrator import AIOrchestrator, TaskConfig, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.core.storage import LocalDiskStorage
from app.models.db_models import Resume, ResumeVersion
from app.models.resume import ResumeDocument
from app.services.pdf_extractor import extract_text_from_pdf, has_extractable_text

RESUME_PARSING_MODEL = "z-ai/glm-5.2"
RESUME_PARSING_TEMPERATURE = 0.1


class ResumeParsingError(Exception):
    """Raised when resume parsing fails, whether at extraction or LLM-structuring."""


def parse_resume(
    db: Session,
    resume: Resume,
    storage: LocalDiskStorage,
    orchestrator: AIOrchestrator,
    prompt_registry: PromptRegistry,
) -> ResumeVersion:
    pdf_bytes = storage.load(resume.storage_path)
    extracted_text = extract_text_from_pdf(pdf_bytes)

    if not has_extractable_text(extracted_text):
        raise ResumeParsingError("no extractable text — this PDF may be scanned/image-based")

    prompt = prompt_registry.render("resume_parsing", "v1", extracted_text=extracted_text)
    task = TaskConfig(
        task_type="resume_parsing",
        provider="nvidia",
        model=RESUME_PARSING_MODEL,
        temperature=RESUME_PARSING_TEMPERATURE,
        response_schema=ResumeDocument,
        fallback_providers=[],
    )

    try:
        result = orchestrator.run(task, prompt=prompt)
    except OrchestratorError as exc:
        raise ResumeParsingError(str(exc)) from exc

    resume.raw_text = extracted_text

    version = ResumeVersion(
        resume_id=resume.id,
        version_number=1,
        resume_json=result.output.model_dump(),
        produced_by_stage="resume_parsing",
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version
