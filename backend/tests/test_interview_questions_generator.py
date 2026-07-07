import pytest
from app.core.db import make_engine, make_session_factory
from app.core.llm.orchestrator import OrchestratorResult, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import Base, JobPosting, TailoringSession, GapAnalysis, Resume, ResumeVersion, GeneratedDocument
from app.models.interview_questions import InterviewQuestionsDocument
from app.services.interview_questions_generator import generate_interview_questions, InterviewQuestionsError


class FakeOrchestrator:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.calls = []

    def run(self, task, prompt):
        self.calls.append((task, prompt))
        if self._error is not None:
            raise self._error
        return self._result


def _make_db():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def _make_session_with_all_prerequisites(db):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()

    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    resume_version = ResumeVersion(
        resume_id=resume.id, session_id=session.id, version_number=1,
        resume_json={"contact": {"full_name": "Test"}}, produced_by_stage="original",
    )
    db.add(resume_version)
    db.commit()

    gap_analysis = GapAnalysis(
        session_id=session.id, resume_version_id=resume_version.id, job_posting_id=job_posting.id,
        analysis_json={"missing_skills": ["Docker"]},
    )
    db.add(gap_analysis)
    db.commit()

    return session, job_posting, gap_analysis


def test_generate_interview_questions_persists_document_with_content():
    db = _make_db()
    session, job_posting, gap_analysis = _make_session_with_all_prerequisites(db)

    result_document = InterviewQuestionsDocument(
        questions=[
            "Can you walk me through your experience with Docker?",
            "How do you approach designing a REST API?",
            "Tell me about a time you debugged a production issue.",
            "How do you handle database migrations safely?",
            "What's your experience with distributed systems?",
        ]
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    document = generate_interview_questions(db, session, orchestrator, prompt_registry)

    assert document.session_id == session.id
    assert document.document_type == "interview_questions"
    assert document.storage_path is None
    assert "Docker" in document.content
    assert document.version_number == 1
    assert db.query(GeneratedDocument).count() == 1


def test_generate_interview_questions_fails_fast_when_no_parsed_jd_without_calling_orchestrator():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json=None)
    db.add_all([resume, job_posting])
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(InterviewQuestionsError, match="jd_extraction"):
        generate_interview_questions(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_generate_interview_questions_fails_fast_when_gap_analysis_missing_without_calling_orchestrator():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(InterviewQuestionsError, match="gap_analysis"):
        generate_interview_questions(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_generate_interview_questions_version_numbering_increments_within_session():
    db = _make_db()
    session, job_posting, gap_analysis = _make_session_with_all_prerequisites(db)

    result_document = InterviewQuestionsDocument(
        questions=["Q1?", "Q2?", "Q3?", "Q4?", "Q5?"]
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    first_document = generate_interview_questions(db, session, orchestrator, prompt_registry)
    second_document = generate_interview_questions(db, session, orchestrator, prompt_registry)

    assert first_document.version_number == 1
    assert second_document.version_number == 2


def test_generate_interview_questions_wraps_orchestrator_error():
    """Structural-validation failures (e.g. fewer than 5 questions) surface as
    an OrchestratorError once every provider attempt has failed Pydantic
    validation - this proves the service wraps that as InterviewQuestionsError,
    the same way every other stage wraps an exhausted orchestrator."""
    db = _make_db()
    session, job_posting, gap_analysis = _make_session_with_all_prerequisites(db)

    orchestrator = FakeOrchestrator(error=OrchestratorError("all providers exhausted"))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(InterviewQuestionsError):
        generate_interview_questions(db, session, orchestrator, prompt_registry)

    assert db.query(GeneratedDocument).count() == 0
