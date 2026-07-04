import pytest
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, JobPosting
from app.core.llm.orchestrator import OrchestratorResult, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.job_posting import JobPostingDocument
from app.services.jd_extractor import extract_job_posting, JDExtractionError
from tests.fixtures.jd_fixtures import (
    blurred_requirements_qualifications_jd_text, not_a_job_posting_text,
)


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


def test_extract_job_posting_persists_parsed_json():
    db = _make_db()
    job_posting = JobPosting(raw_text=blurred_requirements_qualifications_jd_text())
    db.add(job_posting)
    db.commit()

    parsed_document = JobPostingDocument(
        title="Data Analyst", company="Initech", location="Austin, TX",
        employment_type="Contract",
        requirements=["Proficiency in SQL and Excel", "Experience with Tableau or similar BI tools", "3+ years in a data analyst role"],
        responsibilities=["Build and maintain dashboards for the sales team", "Perform ad-hoc data analysis requests"],
        qualifications=[],
        keywords=[],
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=parsed_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    result = extract_job_posting(db, job_posting, orchestrator, prompt_registry)

    assert result.parsed_json["title"] == "Data Analyst"
    assert db.query(JobPosting).filter_by(id=job_posting.id).one().parsed_json["title"] == "Data Analyst"


def test_extract_job_posting_tie_breaking_guard_puts_everything_in_requirements():
    """Tie-breaking guard (spec §3.1, §6): a blurred requirements/qualifications
    fixture must persist all items under requirements with qualifications empty,
    not just validate as JSON."""
    db = _make_db()
    job_posting = JobPosting(raw_text=blurred_requirements_qualifications_jd_text())
    db.add(job_posting)
    db.commit()

    parsed_document = JobPostingDocument(
        title="Data Analyst",
        requirements=["Proficiency in SQL and Excel", "Experience with Tableau or similar BI tools", "3+ years in a data analyst role"],
        qualifications=[],
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=parsed_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    result = extract_job_posting(db, job_posting, orchestrator, prompt_registry)

    assert result.parsed_json["qualifications"] == []
    assert len(result.parsed_json["requirements"]) == 3


def test_extract_job_posting_title_fabrication_guard(tmp_path):
    """Title-fabrication guard (spec §3.2, §6): for a 'not a job posting'
    fixture, the persisted title must match the mocked orchestrator's honest
    placeholder byte-for-byte, proving jd_extractor.py doesn't substitute or
    embellish a fabricated-looking value on top of whatever the orchestrator
    returns."""
    db = _make_db()
    job_posting = JobPosting(raw_text=not_a_job_posting_text())
    db.add(job_posting)
    db.commit()

    parsed_document = JobPostingDocument(title="Untitled")
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=parsed_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    result = extract_job_posting(db, job_posting, orchestrator, prompt_registry)

    assert result.parsed_json["title"] == "Untitled"


def test_extract_job_posting_wraps_orchestrator_error():
    db = _make_db()
    job_posting = JobPosting(raw_text=blurred_requirements_qualifications_jd_text())
    db.add(job_posting)
    db.commit()

    orchestrator = FakeOrchestrator(error=OrchestratorError("all providers exhausted"))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(JDExtractionError):
        extract_job_posting(db, job_posting, orchestrator, prompt_registry)


def test_extract_job_posting_fails_fast_when_no_raw_text_without_calling_orchestrator():
    db = _make_db()
    job_posting = JobPosting(source_url="https://example.com/job", raw_text=None)
    db.add(job_posting)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(JDExtractionError, match="no raw_text"):
        extract_job_posting(db, job_posting, orchestrator, prompt_registry)

    assert orchestrator.calls == []
