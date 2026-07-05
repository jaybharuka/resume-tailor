import json
import re
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


# Matches word-like chunks, keeping symbols that are part of common technology
# names attached to their letters (e.g. "C++", "C#", "Node.js") so a bare "C"
# or "Node" never matches as a substring of a different, more specific name.
_SKILL_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+#]*(?:\.[A-Za-z0-9+#]+)*")


def _tokenize_for_skill_matching(text: str) -> list[str]:
    """Tokenize prose into word-like chunks for skill-matching purposes (see
    _SKILL_TOKEN_PATTERN)."""
    return _SKILL_TOKEN_PATTERN.findall(text)


def _skill_mentioned_in_token_groups(skill: str, token_groups: list[list[str]]) -> bool:
    """True if `skill` is genuinely mentioned in `token_groups` - either as a
    standalone single-word technology name, or (for multi-word skills like
    "React Native") as the exact word sequence. Each group is the tokens of one
    bullet, kept separate so a skill at the end of one bullet is never treated
    as adjacent to the first (often-capitalized, sentence-initial) word of the
    next bullet.

    A single-word skill is NOT considered mentioned merely because it's the
    first word of an adjacent, differently-named two-word compound within the
    SAME bullet (e.g. "React" inside "React Native") unless it also appears on
    its own elsewhere - this is what prevents "Java" from matching inside
    "JavaScript" or "React" from matching inside "React Native" while still
    allowing genuine standalone mentions."""
    skill_tokens = skill.split()
    if not skill_tokens:
        return False

    if len(skill_tokens) == 1:
        skill_lower = skill_tokens[0].lower()
        for tokens in token_groups:
            for i, token in enumerate(tokens):
                if token.lower() != skill_lower:
                    continue
                next_token = tokens[i + 1] if i + 1 < len(tokens) else None
                if next_token is not None and next_token[:1].isupper():
                    # Immediately followed by another capitalized word within
                    # the SAME bullet - this occurrence could be the first
                    # half of a distinct two-word compound (e.g. "React" +
                    # "Native"); don't count it as a standalone mention, but
                    # keep looking for another occurrence.
                    continue
                return True
        return False

    skill_lower_tokens = [t.lower() for t in skill_tokens]
    n = len(skill_lower_tokens)
    for tokens in token_groups:
        for i in range(len(tokens) - n + 1):
            if [t.lower() for t in tokens[i:i + n]] == skill_lower_tokens:
                return True
    return False


def _collect_earned_skills(resume_json: dict, matching_skills: list[str]) -> tuple[set[str], list[list[str]]]:
    """Return (earned_skill_strings, bullet_token_groups): the whitelist the
    code-level skills guard checks tailored skills against, and the tokenized
    bullet prose (one token list per bullet) a skill can also be "earned" by
    appearing in (e.g. "Django" mentioned in a sentence but never listed in a
    dedicated skills/technologies field)."""
    earned = set(resume_json.get("skills", []))
    earned.update(matching_skills)
    bullet_texts = [
        bullet
        for entry in resume_json.get("work_experience", [])
        for bullet in entry.get("bullets", [])
    ]
    for project in resume_json.get("projects", []):
        earned.update(project.get("technologies", []))
        bullet_texts.extend(project.get("bullets", []))
    bullet_token_groups = [_tokenize_for_skill_matching(bullet) for bullet in bullet_texts]
    return earned, bullet_token_groups


def _find_unearned_skill(
    tailored_resume_json: dict, earned_skills: set[str], bullet_token_groups: list[list[str]]
) -> str | None:
    candidates = list(tailored_resume_json.get("skills", []))
    for project in tailored_resume_json.get("projects", []):
        candidates.extend(project.get("technologies", []))
    for skill in candidates:
        if skill in earned_skills or _skill_mentioned_in_token_groups(skill, bullet_token_groups):
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

    earned_skills, bullet_token_groups = _collect_earned_skills(
        original_version.resume_json, gap_analysis.analysis_json.get("matching_skills", [])
    )
    unearned_skill = _find_unearned_skill(tailored_resume_json, earned_skills, bullet_token_groups)
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
