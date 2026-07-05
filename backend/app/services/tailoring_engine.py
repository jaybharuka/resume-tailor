import json
from sqlalchemy.orm import Session
from app.core.llm.orchestrator import AIOrchestrator, TaskConfig, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import TailoringSession, JobPosting, ResumeVersion, GapAnalysis, TailoringChange
from app.models.tailoring_result import TailoringResult
from app.services.errors import StageExecutionError

TAILORING_MODEL = "z-ai/glm-5.2"
TAILORING_TEMPERATURE = 0.1


class TailoringError(StageExecutionError):
    """Raised when resume tailoring fails: unmet prerequisite stages, LLM-
    structuring failure, or a fabrication-guard rejection (unearned skill or an
    entry-identity mismatch)."""


def _collect_earned_skills(resume_json: dict, matching_skills: list[str]) -> tuple[set[str], str]:
    """Return (earned_skill_strings, all_bullet_text): the whitelist the
    code-level skills guard checks tailored skills against, and the concatenated
    bullet prose a skill can also be "earned" by appearing in (e.g. "Django"
    mentioned in a sentence but never listed in a dedicated skills/technologies
    field)."""
    earned = set(resume_json.get("skills", []))
    earned.update(matching_skills)
    bullet_text_parts = [
        bullet
        for entry in resume_json.get("work_experience", [])
        for bullet in entry.get("bullets", [])
    ]
    for project in resume_json.get("projects", []):
        earned.update(project.get("technologies", []))
        bullet_text_parts.extend(project.get("bullets", []))
    return earned, " ".join(bullet_text_parts)


def _find_unearned_skill(tailored_resume_json: dict, earned_skills: set[str], bullet_text: str) -> str | None:
    candidates = list(tailored_resume_json.get("skills", []))
    for project in tailored_resume_json.get("projects", []):
        candidates.extend(project.get("technologies", []))
    for skill in candidates:
        if skill in earned_skills or skill in bullet_text:
            continue
        return skill
    return None


def _validate_entries_preserved(original_resume_json: dict, tailored_resume_json: dict) -> None:
    for key in ("work_experience", "projects", "education", "certifications"):
        original_list = original_resume_json.get(key, [])
        tailored_list = tailored_resume_json.get(key, [])
        if len(original_list) != len(tailored_list):
            raise TailoringError(
                f"tailored resume changed the number of {key} entries "
                f"({len(original_list)} -> {len(tailored_list)}); entries may be reworded/reordered "
                f"but never added or removed"
            )

    original_project_names = {project["name"] for project in original_resume_json.get("projects", [])}
    tailored_project_names = {project["name"] for project in tailored_resume_json.get("projects", [])}
    if tailored_project_names != original_project_names:
        raise TailoringError(
            f"tailored resume's project names do not match the original: "
            f"expected {sorted(original_project_names)}, got {sorted(tailored_project_names)}"
        )

    original_experience_keys = {
        (entry["company"], entry["title"]) for entry in original_resume_json.get("work_experience", [])
    }
    tailored_experience_keys = {
        (entry["company"], entry["title"]) for entry in tailored_resume_json.get("work_experience", [])
    }
    if tailored_experience_keys != original_experience_keys:
        raise TailoringError(
            f"tailored resume's work experience entries do not match the original: "
            f"expected {sorted(original_experience_keys)}, got {sorted(tailored_experience_keys)}"
        )

    original_institutions = {entry["institution"] for entry in original_resume_json.get("education", [])}
    tailored_institutions = {entry["institution"] for entry in tailored_resume_json.get("education", [])}
    if tailored_institutions != original_institutions:
        raise TailoringError(
            f"tailored resume's education entries do not match the original: "
            f"expected {sorted(original_institutions)}, got {sorted(tailored_institutions)}"
        )


def _next_version_number(db: Session, resume_id: int) -> int:
    latest = (
        db.query(ResumeVersion)
        .filter_by(resume_id=resume_id)
        .order_by(ResumeVersion.version_number.desc())
        .first()
    )
    return (latest.version_number if latest else 0) + 1


def tailor_resume(
    db: Session,
    session: TailoringSession,
    orchestrator: AIOrchestrator,
    prompt_registry: PromptRegistry,
) -> ResumeVersion:
    original_version = (
        db.query(ResumeVersion)
        .filter_by(resume_id=session.resume_id, produced_by_stage="resume_parsing")
        .order_by(ResumeVersion.id.desc())
        .first()
    )
    if original_version is None:
        raise TailoringError("resume_parsing has not succeeded for this session yet")

    job_posting = db.get(JobPosting, session.job_posting_id)
    if job_posting is None or job_posting.parsed_json is None:
        raise TailoringError("jd_extraction has not succeeded for this session yet")

    gap_analysis = (
        db.query(GapAnalysis)
        .filter_by(session_id=session.id)
        .order_by(GapAnalysis.id.desc())
        .first()
    )
    if gap_analysis is None:
        raise TailoringError("gap_analysis has not succeeded for this session yet")

    prompt = prompt_registry.render(
        "tailoring_rewrite", "v1",
        resume_json=json.dumps(original_version.resume_json, indent=2),
        job_posting_json=json.dumps(job_posting.parsed_json, indent=2),
        gap_analysis_json=json.dumps(gap_analysis.analysis_json, indent=2),
    )
    task = TaskConfig(
        task_type="tailoring_rewrite",
        provider="nvidia",
        model=TAILORING_MODEL,
        temperature=TAILORING_TEMPERATURE,
        response_schema=TailoringResult,
        fallback_providers=[],
    )

    try:
        result = orchestrator.run(task, prompt=prompt)
    except OrchestratorError as exc:
        raise TailoringError(str(exc)) from exc

    tailored_resume_json = result.output.tailored_resume.model_dump()

    _validate_entries_preserved(original_version.resume_json, tailored_resume_json)

    earned_skills, bullet_text = _collect_earned_skills(
        original_version.resume_json, gap_analysis.analysis_json.get("matching_skills", [])
    )
    unearned_skill = _find_unearned_skill(tailored_resume_json, earned_skills, bullet_text)
    if unearned_skill is not None:
        raise TailoringError(
            f"tailored resume includes an unearned skill not present in the original resume "
            f"or gap analysis matching_skills: {unearned_skill!r}"
        )

    version_number = _next_version_number(db, session.resume_id)
    tailored_version = ResumeVersion(
        resume_id=session.resume_id,
        session_id=session.id,
        version_number=version_number,
        resume_json=tailored_resume_json,
        produced_by_stage="tailoring_rewrite",
    )
    db.add(tailored_version)
    db.flush()

    for change in result.output.changes:
        db.add(TailoringChange(
            resume_version_id=tailored_version.id,
            field_changed=change.field_changed,
            original_text=change.original_text,
            tailored_text=change.tailored_text,
            rationale=change.rationale,
        ))

    db.commit()
    db.refresh(tailored_version)
    return tailored_version
