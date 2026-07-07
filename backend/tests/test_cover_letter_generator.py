import pytest
from app.core.db import make_engine, make_session_factory
from app.core.llm.orchestrator import OrchestratorResult, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import (
    Base, Resume, ResumeVersion, JobPosting, TailoringSession, GapAnalysis, GeneratedDocument,
)
from app.models.cover_letter import CoverLetterDocument
from app.services.cover_letter_generator import generate_cover_letter, CoverLetterError
from tests.fixtures.tailoring_fixtures import base_tailoring_triple


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


def _make_session_with_all_prerequisites(db, resume_json, job_posting_json, gap_analysis_json):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json=job_posting_json)
    db.add_all([resume, job_posting])
    db.commit()

    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    tailored_version = ResumeVersion(
        resume_id=resume.id, session_id=session.id, version_number=2,
        resume_json=resume_json, produced_by_stage="tailoring_rewrite",
    )
    db.add(tailored_version)
    db.commit()

    gap_analysis = GapAnalysis(
        session_id=session.id, resume_version_id=tailored_version.id, job_posting_id=job_posting.id,
        analysis_json=gap_analysis_json,
    )
    db.add(gap_analysis)
    db.commit()

    return session, tailored_version, job_posting, gap_analysis


def test_generate_cover_letter_persists_document_with_content():
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, tailored_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    result_document = CoverLetterDocument(body="Dear Hiring Manager, I have built REST APIs using Python and Django.")
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    document = generate_cover_letter(db, session, orchestrator, prompt_registry)

    assert document.session_id == session.id
    assert document.resume_version_id == tailored_version.id
    assert document.document_type == "cover_letter"
    assert document.storage_path is None
    assert document.content == "Dear Hiring Manager, I have built REST APIs using Python and Django."
    assert document.version_number == 1
    assert db.query(GeneratedDocument).count() == 1


def test_generate_cover_letter_fails_fast_when_no_tailored_version_without_calling_orchestrator():
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

    with pytest.raises(CoverLetterError, match="tailoring_rewrite"):
        generate_cover_letter(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_generate_cover_letter_fails_fast_when_gap_analysis_missing_without_calling_orchestrator():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()
    tailored_version = ResumeVersion(
        resume_id=resume.id, session_id=session.id, version_number=2,
        resume_json={"schema_version": 1, "contact": {"full_name": "Sam"}},
        produced_by_stage="tailoring_rewrite",
    )
    db.add(tailored_version)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(CoverLetterError, match="gap_analysis"):
        generate_cover_letter(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_generate_cover_letter_rejects_unearned_skill_and_persists_nothing():
    """Fabrication guard test (spec §4, §7): a generated cover letter claiming
    'Flask' when only 'Django' was in the original resume and gap analysis
    must be rejected outright - nothing persisted."""
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, tailored_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    result_document = CoverLetterDocument(
        body="Dear Hiring Manager, I have extensive experience with Flask and other frameworks."
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(CoverLetterError, match="Flask"):
        generate_cover_letter(db, session, orchestrator, prompt_registry)

    assert db.query(GeneratedDocument).count() == 0


def test_generate_cover_letter_accepts_earned_skill_mentioned_in_prose():
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, tailored_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    result_document = CoverLetterDocument(
        body="Dear Hiring Manager, I have built production Django applications using PostgreSQL."
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    document = generate_cover_letter(db, session, orchestrator, prompt_registry)

    assert "Django" in document.content


def test_generate_cover_letter_accepts_job_title_reference_in_prose():
    """Regression test: referencing the target job's own title (e.g. "the
    Senior Backend Engineer position") is not a claim about the candidate's
    skills and must not be rejected as an unearned skill - discovered via a
    real live E2E run where a real LLM naturally echoed the JD's title back
    ("Senior") and was incorrectly flagged before this fix."""
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    assert job_posting_doc.title == "Senior Backend Engineer"
    session, tailored_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    result_document = CoverLetterDocument(
        body="Dear Hiring Manager, I am excited to apply for the Senior Backend Engineer position."
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    document = generate_cover_letter(db, session, orchestrator, prompt_registry)

    assert "Senior Backend Engineer" in document.content


def test_generate_cover_letter_version_numbering_increments_within_session():
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, tailored_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    result_document = CoverLetterDocument(body="Dear Hiring Manager, I have built production Django applications.")
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    first_document = generate_cover_letter(db, session, orchestrator, prompt_registry)
    second_document = generate_cover_letter(db, session, orchestrator, prompt_registry)

    assert first_document.version_number == 1
    assert second_document.version_number == 2


def test_generate_cover_letter_wraps_orchestrator_error():
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, tailored_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    orchestrator = FakeOrchestrator(error=OrchestratorError("all providers exhausted"))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(CoverLetterError):
        generate_cover_letter(db, session, orchestrator, prompt_registry)

    assert db.query(GeneratedDocument).count() == 0
