import json
import re
from sqlalchemy.orm import Session
from app.core.llm.orchestrator import AIOrchestrator, TaskConfig, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import TailoringSession, JobPosting, ResumeVersion, GapAnalysis, GeneratedDocument
from app.models.recruiter_summary import RecruiterSummaryDocument
from app.services.errors import StageExecutionError
from app.services.skill_matching import (
    collect_earned_skills, skill_mentioned_in_token_groups, tokenize_for_skill_matching,
)

RECRUITER_SUMMARY_MODEL = "z-ai/glm-5.2"
RECRUITER_SUMMARY_TEMPERATURE = 0.1
DOCUMENT_TYPE = "recruiter_summary"

# A capitalized token that is NOT part of the leading capitalized run of its
# sentence is treated as a candidate skill/technology mention (e.g. "Django"
# mid-sentence) - this excludes ordinary sentence/clause-initial
# capitalization from being checked against the earned-skills whitelist.
#
# NOTE: excluding only the single first token (index 0) of each sentence is
# NOT sufficient in practice: a recruiter summary body like "The candidate
# has built REST APIs using Python and Django, with strong communication
# skills." is one sentence (no period until the end), so "The" being the
# only leading capital isn't the whole story either - "REST" and "APIs" are
# acronym-shaped mid-sentence capitalized tokens that are NOT actual skill
# claims and must not be checked against the whitelist. We skip the whole
# leading run of consecutive capitalized tokens at the start of each
# sentence, not just the first one, and separately exclude acronym-shaped
# tokens via `_is_acronym_like` (see below) - mirrors the fix applied to
# app/services/cover_letter_generator.py.
_SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?])\s+")


def _is_acronym_like(token: str) -> bool:
    """True for acronym-shaped tokens (e.g. "REST", "APIs") that are
    capitalized but are not plausible skill/technology proper nouns in the
    sense this guard cares about - they're all-uppercase, optionally with a
    trailing lowercase "s" for pluralization. Real skill names fabricated by
    an LLM overwhelmingly appear as Title Case words (Django, Flask,
    Kubernetes), so acronyms are excluded to avoid false positives on
    ordinary prose (e.g. "The candidate has built REST APIs")."""
    core = token[:-1] if token.endswith("s") else token
    return len(core) >= 2 and core.isupper()


class RecruiterSummaryError(StageExecutionError):
    """Raised when recruiter summary generation fails: unmet prerequisite
    stages, LLM-structuring failure, or a fabrication-guard rejection (an
    unearned skill mentioned in the generated prose)."""


def _next_version_number(db: Session, session_id: int, document_type: str) -> int:
    latest = (
        db.query(GeneratedDocument)
        .filter_by(session_id=session_id, document_type=document_type)
        .order_by(GeneratedDocument.version_number.desc())
        .first()
    )
    return (latest.version_number if latest else 0) + 1


def _candidate_skill_tokens(body: str) -> list[str]:
    """Return capitalized tokens that are candidates the guard checks against
    the earned-skills set: tokens that are not part of the leading
    capitalized run of their sentence (see module-level note above) and are
    not acronym-shaped (see `_is_acronym_like`)."""
    sentences = _SENTENCE_BOUNDARY_PATTERN.split(body)
    candidates: list[str] = []
    for sentence in sentences:
        tokens = tokenize_for_skill_matching(sentence)
        index = 0
        while index < len(tokens) and tokens[index][:1].isupper():
            index += 1
        for token in tokens[index:]:
            if len(token) < 2 or not token[:1].isupper():
                continue
            if _is_acronym_like(token):
                continue
            candidates.append(token)
    return candidates


def _find_unearned_skill_in_prose(
    body: str, earned_skills: set[str], bullet_token_groups: list[list[str]]
) -> str | None:
    earned_lower = {skill.lower() for skill in earned_skills}
    for candidate in _candidate_skill_tokens(body):
        if candidate.lower() in earned_lower:
            continue
        if skill_mentioned_in_token_groups(candidate, bullet_token_groups):
            continue
        return candidate
    return None


def generate_recruiter_summary(
    db: Session,
    session: TailoringSession,
    orchestrator: AIOrchestrator,
    prompt_registry: PromptRegistry,
) -> GeneratedDocument:
    tailored_version = (
        db.query(ResumeVersion)
        .filter_by(session_id=session.id, produced_by_stage="tailoring_rewrite")
        .order_by(ResumeVersion.id.desc())
        .first()
    )
    if tailored_version is None:
        raise RecruiterSummaryError("tailoring_rewrite has not succeeded for this session yet")

    gap_analysis = (
        db.query(GapAnalysis)
        .filter_by(session_id=session.id)
        .order_by(GapAnalysis.id.desc())
        .first()
    )
    if gap_analysis is None:
        raise RecruiterSummaryError("gap_analysis has not succeeded for this session yet")

    job_posting = db.get(JobPosting, session.job_posting_id)

    prompt = prompt_registry.render(
        "recruiter_summary", "v1",
        resume_json=json.dumps(tailored_version.resume_json, indent=2),
        job_posting_json=json.dumps(job_posting.parsed_json, indent=2),
        gap_analysis_json=json.dumps(gap_analysis.analysis_json, indent=2),
    )
    task = TaskConfig(
        task_type="recruiter_summary",
        provider="nvidia",
        model=RECRUITER_SUMMARY_MODEL,
        temperature=RECRUITER_SUMMARY_TEMPERATURE,
        response_schema=RecruiterSummaryDocument,
        fallback_providers=[],
    )

    try:
        result = orchestrator.run(task, prompt=prompt)
    except OrchestratorError as exc:
        raise RecruiterSummaryError(str(exc)) from exc

    body = result.output.body

    earned_skills, bullet_token_groups = collect_earned_skills(
        tailored_version.resume_json, gap_analysis.analysis_json.get("matching_skills", [])
    )
    # A recruiter summary legitimately needs to name the role being considered
    # (e.g. "for the Senior Backend Engineer position") - referencing the target
    # job's own title is not a claim about the candidate's skills, so title
    # tokens are earned too. Deliberately scoped to `title` only, not the job
    # posting's requirements/keywords - allowlisting those would defeat the
    # guard's purpose, since missing_skills are themselves often drawn straight
    # from requirements.
    job_title = (job_posting.parsed_json or {}).get("title") or ""
    earned_skills = earned_skills | set(tokenize_for_skill_matching(job_title))
    unearned_skill = _find_unearned_skill_in_prose(body, earned_skills, bullet_token_groups)
    if unearned_skill is not None:
        raise RecruiterSummaryError(
            f"generated recruiter summary mentions an unearned skill not present in the tailored "
            f"resume or gap analysis matching_skills: {unearned_skill!r}"
        )

    version_number = _next_version_number(db, session.id, DOCUMENT_TYPE)
    document = GeneratedDocument(
        session_id=session.id,
        resume_version_id=tailored_version.id,
        document_type=DOCUMENT_TYPE,
        storage_path=None,
        content=body,
        version_number=version_number,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document
