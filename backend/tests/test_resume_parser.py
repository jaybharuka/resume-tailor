import pytest
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, Resume, ResumeVersion
from app.core.llm.orchestrator import OrchestratorResult, OrchestratorError
from app.core.storage import LocalDiskStorage
from app.core.llm.prompt_registry import PromptRegistry
from app.models.resume import ResumeDocument, ContactInfo, WorkExperience
from app.services.resume_parser import parse_resume, ResumeParsingError
from tests.fixtures.pdf_fixtures import (
    build_sparse_bullets_resume_pdf, build_missing_section_resume_pdf, build_blank_pdf,
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


def test_parse_resume_persists_resume_version_and_raw_text(tmp_path):
    db = _make_db()
    storage = LocalDiskStorage(root=str(tmp_path))
    storage_path = storage.save("resumes/1/resume.pdf", build_sparse_bullets_resume_pdf())

    resume = Resume(original_filename="resume.pdf", storage_path=storage_path)
    db.add(resume)
    db.commit()

    parsed_document = ResumeDocument(
        contact=ContactInfo(full_name="Alex Lee", email=None, phone=None, location=None),
        summary=None,
        work_experience=[
            WorkExperience(
                company="Startup Co", title="Engineer", start_date="2022", end_date="2024",
                bullets=["Worked on backend"],
            ),
        ],
        projects=[], skills=[], education=[], certifications=[],
    )
    orchestrator = FakeOrchestrator(
        result=OrchestratorResult(output=parsed_document, provider_used="nvidia", attempts=1)
    )
    prompt_registry = PromptRegistry(prompts_root="prompts")

    version = parse_resume(db, resume, storage, orchestrator, prompt_registry)

    assert version.produced_by_stage == "resume_parsing"
    assert version.version_number == 1
    assert version.resume_json["contact"]["full_name"] == "Alex Lee"
    assert resume.raw_text is not None
    assert "Alex Lee" in resume.raw_text
    assert db.query(ResumeVersion).count() == 1


def test_parse_resume_does_not_fabricate_missing_sections(tmp_path):
    """Fabrication guard: fields absent from the source resume must come back
    null/empty in the persisted ResumeDocument, not filled in with invented content."""
    db = _make_db()
    storage = LocalDiskStorage(root=str(tmp_path))
    storage_path = storage.save("resumes/2/resume.pdf", build_missing_section_resume_pdf())

    resume = Resume(original_filename="resume.pdf", storage_path=storage_path)
    db.add(resume)
    db.commit()

    parsed_document = ResumeDocument(
        contact=ContactInfo(full_name="Sam Rivera"),
        summary="Full-stack developer.",
        work_experience=[
            WorkExperience(
                company="Widget LLC", title="Full-Stack Developer", start_date="2019", end_date="2024",
                bullets=["Built customer-facing dashboards using React and FastAPI"],
            ),
        ],
        projects=[],  # no projects section in source -> must stay empty, not invented
        skills=["JavaScript", "React", "FastAPI", "PostgreSQL"],
        education=[], certifications=[],
    )
    orchestrator = FakeOrchestrator(
        result=OrchestratorResult(output=parsed_document, provider_used="nvidia", attempts=1)
    )
    prompt_registry = PromptRegistry(prompts_root="prompts")

    version = parse_resume(db, resume, storage, orchestrator, prompt_registry)

    assert version.resume_json["projects"] == []
    assert version.resume_json["education"] == []
    assert version.resume_json["certifications"] == []


def test_parse_resume_fails_fast_on_blank_pdf_without_calling_orchestrator(tmp_path):
    db = _make_db()
    storage = LocalDiskStorage(root=str(tmp_path))
    storage_path = storage.save("resumes/3/resume.pdf", build_blank_pdf())

    resume = Resume(original_filename="resume.pdf", storage_path=storage_path)
    db.add(resume)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(ResumeParsingError, match="no extractable text"):
        parse_resume(db, resume, storage, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_parse_resume_wraps_orchestrator_error(tmp_path):
    db = _make_db()
    storage = LocalDiskStorage(root=str(tmp_path))
    storage_path = storage.save("resumes/4/resume.pdf", build_sparse_bullets_resume_pdf())

    resume = Resume(original_filename="resume.pdf", storage_path=storage_path)
    db.add(resume)
    db.commit()

    orchestrator = FakeOrchestrator(error=OrchestratorError("all providers exhausted"))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(ResumeParsingError):
        parse_resume(db, resume, storage, orchestrator, prompt_registry)
