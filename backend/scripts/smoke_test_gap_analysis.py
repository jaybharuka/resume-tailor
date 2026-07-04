"""Manual smoke test: run with `python scripts/smoke_test_gap_analysis.py`
after setting NVIDIA_API_KEY in backend/.env. Costs two real API calls - not
run by pytest.

Runs gap analysis against the real NVIDIA API for two scenarios where the
strict-match rule (spec §6.1) is most likely to go wrong in either direction:
adjacent_not_matching_pair (Django vs. Flask - must NOT be counted as a match)
and synonym_matching_pair (JavaScript vs. JS - MUST be counted as a match).
The automated test suite (which mocks the orchestrator) proves gap_analyzer.py
persists whatever the model returns verbatim; it cannot prove the real model
actually applies the strict-match rule correctly in both directions - that's
what this script is for."""
import json
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.core.llm.orchestrator_factory import build_orchestrator
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import Base, Resume, ResumeVersion, JobPosting, TailoringSession
from app.services.gap_analyzer import analyze_gap
from tests.fixtures.gap_analysis_fixtures import adjacent_not_matching_pair, synonym_matching_pair


def _run_scenario(db, orchestrator, prompt_registry, label, resume_doc, job_posting_doc):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json=job_posting_doc.model_dump())
    db.add_all([resume, job_posting])
    db.commit()

    resume_version = ResumeVersion(
        resume_id=resume.id, version_number=1,
        resume_json=resume_doc.model_dump(), produced_by_stage="resume_parsing",
    )
    db.add(resume_version)
    db.commit()

    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    print(f"--- {label} ---")
    analysis = analyze_gap(db, session, orchestrator, prompt_registry)
    print(json.dumps(analysis.analysis_json, indent=2))


if __name__ == "__main__":
    settings = get_settings()
    if not settings.nvidia_api_key:
        raise SystemExit("Set NVIDIA_API_KEY in backend/.env before running this script.")

    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = make_session_factory(engine)()

    orchestrator = build_orchestrator(db, session_id=None)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)

    adjacent_resume, adjacent_job = adjacent_not_matching_pair()
    _run_scenario(
        db, orchestrator, prompt_registry,
        "adjacent_not_matching_pair (Django vs. Flask)", adjacent_resume, adjacent_job,
    )

    synonym_resume, synonym_job = synonym_matching_pair()
    _run_scenario(
        db, orchestrator, prompt_registry,
        "synonym_matching_pair (JavaScript vs. JS)", synonym_resume, synonym_job,
    )
