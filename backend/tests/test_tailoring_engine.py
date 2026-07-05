import pytest
from app.core.db import make_engine, make_session_factory
from app.models.db_models import (
    Base, Resume, ResumeVersion, JobPosting, TailoringSession, GapAnalysis, TailoringChange,
)
from app.core.llm.orchestrator import OrchestratorResult, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.resume import ResumeDocument
from app.models.tailoring_result import TailoringResult, TailoringChangeRecord
from app.services.tailoring_engine import tailor_resume, TailoringError
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

    original_version = ResumeVersion(
        resume_id=resume.id, version_number=1, resume_json=resume_json, produced_by_stage="resume_parsing",
    )
    db.add(original_version)
    db.commit()

    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    gap_analysis = GapAnalysis(
        session_id=session.id, resume_version_id=original_version.id, job_posting_id=job_posting.id,
        analysis_json=gap_analysis_json,
    )
    db.add(gap_analysis)
    db.commit()

    return session, original_version, job_posting, gap_analysis


def _passing_tailoring_result(resume: ResumeDocument) -> TailoringResult:
    """A tailored result that reorders and rewords nothing - a safe, always-
    passing baseline for tests that aren't specifically exercising a guard."""
    return TailoringResult(
        tailored_resume=resume,
        changes=[
            TailoringChangeRecord(
                field_changed="summary", original_text=resume.summary, tailored_text=resume.summary or "",
                rationale="No change needed for this test scenario.",
            ),
        ],
    )


def test_tailor_resume_persists_tailored_version_and_changes():
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, original_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    result_document = _passing_tailoring_result(resume_doc)
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    tailored_version = tailor_resume(db, session, orchestrator, prompt_registry)

    assert tailored_version.resume_id == session.resume_id
    assert tailored_version.session_id == session.id
    assert tailored_version.produced_by_stage == "tailoring_rewrite"
    assert tailored_version.version_number == 2
    assert db.query(TailoringChange).filter_by(resume_version_id=tailored_version.id).count() == 1


def test_tailor_resume_fails_fast_when_no_original_resume_version_without_calling_orchestrator():
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

    with pytest.raises(TailoringError, match="resume_parsing"):
        tailor_resume(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_tailor_resume_fails_fast_when_job_posting_not_extracted_without_calling_orchestrator():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json=None)
    db.add_all([resume, job_posting])
    db.commit()
    original_version = ResumeVersion(
        resume_id=resume.id, version_number=1,
        resume_json={"schema_version": 1, "contact": {"full_name": "Sam"}},
        produced_by_stage="resume_parsing",
    )
    db.add(original_version)
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(TailoringError, match="jd_extraction"):
        tailor_resume(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_tailor_resume_fails_fast_when_gap_analysis_missing_without_calling_orchestrator():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()
    original_version = ResumeVersion(
        resume_id=resume.id, version_number=1,
        resume_json={"schema_version": 1, "contact": {"full_name": "Sam"}},
        produced_by_stage="resume_parsing",
    )
    db.add(original_version)
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(TailoringError, match="gap_analysis"):
        tailor_resume(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_tailor_resume_rejects_unearned_adjacent_skill_and_persists_nothing():
    """Service-layer guard test (spec §4.2, §8): a tailored skill claiming 'Flask'
    when only 'Django' was in the original resume and gap analysis must be
    rejected outright - nothing persisted, not silently filtered."""
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, original_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    tailored_resume = resume_doc.model_copy(deep=True)
    tailored_resume.skills = tailored_resume.skills + ["Flask"]
    result_document = TailoringResult(
        tailored_resume=tailored_resume,
        changes=[
            TailoringChangeRecord(
                field_changed="skills", original_text=None, tailored_text="Flask", rationale="Added Flask.",
            ),
        ],
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(TailoringError, match="Flask"):
        tailor_resume(db, session, orchestrator, prompt_registry)

    assert db.query(ResumeVersion).filter_by(produced_by_stage="tailoring_rewrite").count() == 0
    assert db.query(TailoringChange).count() == 0


def test_tailor_resume_rejects_invented_project_and_persists_nothing():
    """Service-layer guard test (spec §8): a tailored project whose name doesn't
    match any original project is a fabricated entry - the entry-identity
    invariant catches this without needing semantic judgment."""
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, original_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    tailored_resume = resume_doc.model_copy(deep=True)
    tailored_resume.projects[1].name = "Completely Invented Project"
    result_document = TailoringResult(
        tailored_resume=tailored_resume,
        changes=[
            TailoringChangeRecord(
                field_changed='projects["Completely Invented Project"]', original_text=None,
                tailored_text="Completely Invented Project", rationale="Renamed.",
            ),
        ],
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(TailoringError, match="project names"):
        tailor_resume(db, session, orchestrator, prompt_registry)

    assert db.query(ResumeVersion).filter_by(produced_by_stage="tailoring_rewrite").count() == 0
    assert db.query(TailoringChange).count() == 0


def test_tailor_resume_preserves_entry_count_on_passing_run():
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, original_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    result_document = _passing_tailoring_result(resume_doc)
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    tailored_version = tailor_resume(db, session, orchestrator, prompt_registry)

    assert len(tailored_version.resume_json["projects"]) == len(resume_doc.projects)
    assert len(tailored_version.resume_json["work_experience"]) == len(resume_doc.work_experience)


def test_tailor_resume_version_numbering_increments_across_sessions_for_same_resume():
    """Version numbering test (spec §3.2, §8): two sessions tailoring the same
    resume must produce sequential version_numbers (2, then 3), each session_id
    correctly distinguishing which session produced which row."""
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    db.add(resume)
    db.commit()
    original_version = ResumeVersion(
        resume_id=resume.id, version_number=1, resume_json=resume_doc.model_dump(), produced_by_stage="resume_parsing",
    )
    db.add(original_version)
    db.commit()

    job_posting_a = JobPosting(raw_text="placeholder", parsed_json=job_posting_doc.model_dump())
    job_posting_b = JobPosting(raw_text="placeholder", parsed_json=job_posting_doc.model_dump())
    db.add_all([job_posting_a, job_posting_b])
    db.commit()

    session_a = TailoringSession(resume_id=resume.id, job_posting_id=job_posting_a.id, status="created")
    session_b = TailoringSession(resume_id=resume.id, job_posting_id=job_posting_b.id, status="created")
    db.add_all([session_a, session_b])
    db.commit()

    gap_analysis_a = GapAnalysis(
        session_id=session_a.id, resume_version_id=original_version.id, job_posting_id=job_posting_a.id,
        analysis_json=gap_analysis_doc.model_dump(),
    )
    gap_analysis_b = GapAnalysis(
        session_id=session_b.id, resume_version_id=original_version.id, job_posting_id=job_posting_b.id,
        analysis_json=gap_analysis_doc.model_dump(),
    )
    db.add_all([gap_analysis_a, gap_analysis_b])
    db.commit()

    result_document = _passing_tailoring_result(resume_doc)
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    tailored_a = tailor_resume(db, session_a, orchestrator, prompt_registry)
    tailored_b = tailor_resume(db, session_b, orchestrator, prompt_registry)

    assert tailored_a.version_number == 2
    assert tailored_b.version_number == 3
    assert tailored_a.session_id == session_a.id
    assert tailored_b.session_id == session_b.id


def test_tailor_resume_reorder_does_not_misattribute_change_paths():
    """Reorder-misattribution guard test (spec §3.4, §8): reordering the two
    projects in the tailored output must not cause a TailoringChange row to be
    attributed to the wrong project, since field_changed paths are identity-
    anchored (project name), not positional."""
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, original_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    # tailored_resume is an independent deep copy of resume_doc - reordering and
    # mutating ITS OWN project list never touches resume_doc's original objects.
    tailored_resume = resume_doc.model_copy(deep=True)
    tailored_resume.projects = [tailored_resume.projects[1], tailored_resume.projects[0]]
    tailored_resume.projects[0].bullets = ["Rewritten Recipe Finder bullet"]
    tailored_resume.projects[1].bullets = ["Rewritten Inventory Tracker bullet"]

    result_document = TailoringResult(
        tailored_resume=tailored_resume,
        changes=[
            TailoringChangeRecord(
                field_changed='projects["Recipe Finder"].bullets[0]',
                original_text=resume_doc.projects[1].bullets[0],
                tailored_text="Rewritten Recipe Finder bullet",
                rationale="Reworded.",
            ),
            TailoringChangeRecord(
                field_changed='projects["Inventory Tracker"].bullets[0]',
                original_text=resume_doc.projects[0].bullets[0],
                tailored_text="Rewritten Inventory Tracker bullet",
                rationale="Reworded and reordered second since Recipe Finder is more relevant.",
            ),
        ],
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    tailored_version = tailor_resume(db, session, orchestrator, prompt_registry)

    changes = {
        change.field_changed: change.tailored_text
        for change in db.query(TailoringChange).filter_by(resume_version_id=tailored_version.id).all()
    }
    assert changes['projects["Recipe Finder"].bullets[0]'] == "Rewritten Recipe Finder bullet"
    assert changes['projects["Inventory Tracker"].bullets[0]'] == "Rewritten Inventory Tracker bullet"


def test_tailor_resume_re_tailoring_is_independent_fresh_attempt():
    """Re-tailoring-is-independent test (spec §7, §8): running tailor_resume twice
    for the same session must both read from the ORIGINAL resume_parsing version,
    not chain off each other, and get distinct sequential version_numbers."""
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, original_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    result_document = _passing_tailoring_result(resume_doc)
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    first_run = tailor_resume(db, session, orchestrator, prompt_registry)
    second_run = tailor_resume(db, session, orchestrator, prompt_registry)

    assert first_run.version_number == 2
    assert second_run.version_number == 3
    # Both calls rendered a prompt built from the same original resume_json (not
    # from each other's output) - since the source document never changed
    # between calls, both prompts are byte-identical.
    assert orchestrator.calls[0][1] == orchestrator.calls[1][1]


def test_tailor_resume_wraps_orchestrator_error():
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, original_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    orchestrator = FakeOrchestrator(error=OrchestratorError("all providers exhausted"))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(TailoringError):
        tailor_resume(db, session, orchestrator, prompt_registry)
