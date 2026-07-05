import httpx
import pytest
from app.core.config import Settings
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, Resume, ResumeVersion, JobPosting, TailoringSession, EvaluationRun
from app.services.evaluator import evaluate_resume, EvaluationError


class FakeHttpClient:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.calls = []

    def post(self, url, json):
        self.calls.append((url, json))
        if self._error is not None:
            raise self._error
        return self._response


def _make_response(status_code: int, json_body: dict | None = None) -> httpx.Response:
    request = httpx.Request("POST", "http://hiring-agent-service:8100/evaluate")
    return httpx.Response(status_code, json=json_body, request=request)


def _make_db():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def _make_session_with_tailored_version(db):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()

    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    tailored_version = ResumeVersion(
        resume_id=resume.id, session_id=session.id, version_number=2,
        resume_json={"contact": {"full_name": "Jane Doe"}, "skills": ["Python"]},
        produced_by_stage="tailoring_rewrite",
    )
    db.add(tailored_version)
    db.commit()

    return session, tailored_version


def _settings() -> Settings:
    return Settings(hiring_agent_service_url="http://hiring-agent-service:8100")


def test_evaluate_resume_persists_all_score_fields():
    db = _make_db()
    session, tailored_version = _make_session_with_tailored_version(db)

    response_body = {
        "overall_score": 88.0,
        "open_source_score": 30,
        "projects_score": 25,
        "production_score": 20,
        "technical_skills_score": 8,
        "evidence": {"open_source": "3 popular repos"},
        "bonus_points": {"total": 5, "breakdown": "Active OSS contributor"},
        "deductions": {"total": 0, "reasons": "No deductions"},
        "rubric_version": "hiring-agent-v1",
        "hiring_agent_service_version": "0.1.0",
        "raw": {"key_strengths": ["Strong OSS presence"]},
    }
    http_client = FakeHttpClient(response=_make_response(200, response_body))

    evaluation = evaluate_resume(db, session, http_client, _settings())

    assert evaluation.session_id == session.id
    assert evaluation.resume_version_id == tailored_version.id
    assert evaluation.overall_score == 88.0
    assert evaluation.open_source_score == 30
    assert evaluation.projects_score == 25
    assert evaluation.production_score == 20
    assert evaluation.technical_skills_score == 8
    assert evaluation.rubric_version == "hiring-agent-v1"
    assert evaluation.hiring_agent_service_version == "0.1.0"
    assert evaluation.raw_response_json == response_body
    assert db.query(EvaluationRun).count() == 1


def test_evaluate_resume_sends_rendered_text_and_null_github_username():
    db = _make_db()
    session, tailored_version = _make_session_with_tailored_version(db)

    response_body = {
        "overall_score": 50.0, "open_source_score": 10, "projects_score": 10,
        "production_score": 10, "technical_skills_score": 5,
        "rubric_version": "hiring-agent-v1", "hiring_agent_service_version": "0.1.0",
    }
    http_client = FakeHttpClient(response=_make_response(200, response_body))

    evaluate_resume(db, session, http_client, _settings())

    assert len(http_client.calls) == 1
    url, payload = http_client.calls[0]
    assert url == "http://hiring-agent-service:8100/evaluate"
    assert payload["github_username"] is None
    assert "Jane Doe" in payload["resume_text"]


def test_evaluate_resume_fails_fast_when_no_tailored_version_without_calling_http_client():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    http_client = FakeHttpClient()

    with pytest.raises(EvaluationError, match="tailoring_rewrite"):
        evaluate_resume(db, session, http_client, _settings())

    assert http_client.calls == []


def test_evaluate_resume_wraps_connection_error():
    db = _make_db()
    session, tailored_version = _make_session_with_tailored_version(db)

    http_client = FakeHttpClient(error=httpx.ConnectError("connection refused"))

    with pytest.raises(EvaluationError):
        evaluate_resume(db, session, http_client, _settings())

    assert db.query(EvaluationRun).count() == 0


def test_evaluate_resume_wraps_non_200_response():
    db = _make_db()
    session, tailored_version = _make_session_with_tailored_version(db)

    http_client = FakeHttpClient(response=_make_response(500))

    with pytest.raises(EvaluationError):
        evaluate_resume(db, session, http_client, _settings())

    assert db.query(EvaluationRun).count() == 0
