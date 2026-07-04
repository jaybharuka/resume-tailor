import pytest
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, Resume, ResumeVersion, JobPosting, TailoringSession
from app.core.llm.orchestrator import OrchestratorResult, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.gap_analysis import GapAnalysisDocument
from app.services.gap_analyzer import analyze_gap, GapAnalysisError
from tests.fixtures.gap_analysis_fixtures import adjacent_not_matching_pair, synonym_matching_pair


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


def _make_session_with_resume_version_and_parsed_job_posting(db, resume_json, job_posting_json):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json=job_posting_json)
    db.add_all([resume, job_posting])
    db.commit()

    resume_version = ResumeVersion(
        resume_id=resume.id, version_number=1, resume_json=resume_json, produced_by_stage="resume_parsing",
    )
    db.add(resume_version)
    db.commit()

    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()
    return session, resume_version, job_posting


def test_analyze_gap_persists_analysis_json_and_links_ids():
    db = _make_db()
    resume_doc, job_posting_doc = adjacent_not_matching_pair()
    session, resume_version, job_posting = _make_session_with_resume_version_and_parsed_job_posting(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(),
    )

    result_document = GapAnalysisDocument(matching_skills=["Python"], missing_skills=["Flask"])
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    analysis = analyze_gap(db, session, orchestrator, prompt_registry)

    assert analysis.session_id == session.id
    assert analysis.resume_version_id == resume_version.id
    assert analysis.job_posting_id == job_posting.id
    assert analysis.analysis_json["missing_skills"] == ["Flask"]


def test_analyze_gap_fails_fast_when_no_resume_version_without_calling_orchestrator():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Developer"})
    db.add_all([resume, job_posting])
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(GapAnalysisError, match="resume_parsing"):
        analyze_gap(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_analyze_gap_fails_fast_when_job_posting_not_extracted_without_calling_orchestrator():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json=None)
    db.add_all([resume, job_posting])
    db.commit()
    resume_version = ResumeVersion(
        resume_id=resume.id, version_number=1,
        resume_json={"schema_version": 1, "contact": {"full_name": "Sam"}},
        produced_by_stage="resume_parsing",
    )
    db.add(resume_version)
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(GapAnalysisError, match="jd_extraction"):
        analyze_gap(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_analyze_gap_adjacent_skill_guard_does_not_count_django_as_flask_match():
    """Strict-match guard (spec §6.1): Django does not satisfy a Flask requirement -
    persisted output must reflect Flask as missing, not matching, byte-for-byte
    against whatever the orchestrator returned."""
    db = _make_db()
    resume_doc, job_posting_doc = adjacent_not_matching_pair()
    session, _, _ = _make_session_with_resume_version_and_parsed_job_posting(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(),
    )

    result_document = GapAnalysisDocument(matching_skills=["Python"], missing_skills=["Flask"])
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    analysis = analyze_gap(db, session, orchestrator, prompt_registry)

    assert analysis.analysis_json["missing_skills"] == ["Flask"]
    assert "Flask" not in analysis.analysis_json["matching_skills"]


def test_analyze_gap_synonym_match_guard_counts_js_as_javascript_match():
    """Reverse of the strict-match guard (this plan's addition to spec §6.1): a
    genuine synonym/abbreviation (JS <-> JavaScript) must be counted as a match,
    not treated as missing - proving the strict-match rule isn't overcorrecting
    into false negatives."""
    db = _make_db()
    resume_doc, job_posting_doc = synonym_matching_pair()
    session, _, _ = _make_session_with_resume_version_and_parsed_job_posting(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(),
    )

    result_document = GapAnalysisDocument(matching_skills=["JavaScript", "React"], missing_skills=[])
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    analysis = analyze_gap(db, session, orchestrator, prompt_registry)

    assert "JavaScript" in analysis.analysis_json["matching_skills"]
    assert analysis.analysis_json["missing_skills"] == []


def test_analyze_gap_wraps_orchestrator_error():
    db = _make_db()
    resume_doc, job_posting_doc = adjacent_not_matching_pair()
    session, _, _ = _make_session_with_resume_version_and_parsed_job_posting(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(),
    )

    orchestrator = FakeOrchestrator(error=OrchestratorError("all providers exhausted"))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(GapAnalysisError):
        analyze_gap(db, session, orchestrator, prompt_registry)
