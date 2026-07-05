import httpx
from sqlalchemy.orm import Session
from app.models.db_models import TailoringSession, ResumeVersion, EvaluationRun
from app.services.resume_renderer import render_resume_to_text
from app.services.errors import StageExecutionError


class EvaluationError(StageExecutionError):
    """Raised when hiring-agent evaluation fails: the tailoring_rewrite
    prerequisite hasn't succeeded yet, or the HTTP call to hiring-agent-service
    failed (connection error or non-2xx response)."""


def evaluate_resume(
    db: Session,
    session: TailoringSession,
    http_client,
    settings,
) -> EvaluationRun:
    tailored_version = (
        db.query(ResumeVersion)
        .filter_by(session_id=session.id, produced_by_stage="tailoring_rewrite")
        .order_by(ResumeVersion.id.desc())
        .first()
    )
    if tailored_version is None:
        raise EvaluationError("tailoring_rewrite has not succeeded for this session yet")

    resume_text = render_resume_to_text(tailored_version.resume_json)

    try:
        response = http_client.post(
            f"{settings.hiring_agent_service_url}/evaluate",
            json={"resume_text": resume_text, "github_username": None},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise EvaluationError(str(exc)) from exc

    body = response.json()

    evaluation = EvaluationRun(
        session_id=session.id,
        resume_version_id=tailored_version.id,
        overall_score=body.get("overall_score"),
        open_source_score=body.get("open_source_score"),
        projects_score=body.get("projects_score"),
        production_score=body.get("production_score"),
        technical_skills_score=body.get("technical_skills_score"),
        raw_response_json=body,
        rubric_version=body.get("rubric_version"),
        hiring_agent_service_version=body.get("hiring_agent_service_version"),
    )
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)
    return evaluation
