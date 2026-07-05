"""Manual smoke test: run with `python scripts/smoke_test_tailoring.py` after
setting NVIDIA_API_KEY in backend/.env. Costs a real API call - not run by
pytest.

Runs the tailoring engine against the real NVIDIA API using the
base_tailoring_triple fixture, and prints both the tailored ResumeDocument and
the reported changes, so a human can manually verify the model (a) doesn't
fabricate metrics or unearned skills, (b) doesn't claim a missing_skill as
possessed, and (c) provides genuinely useful, honest rationale for its
changes - the automated test suite (which mocks the orchestrator) proves
tailor_resume persists the model's output verbatim and rejects unearned
skills/invented entries, but cannot prove real-model prompt compliance for
the vectors that have no code-level guard (see spec sections 4.3 and 8)."""
import json
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.core.llm.orchestrator_factory import build_orchestrator
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import Base, Resume, ResumeVersion, JobPosting, TailoringSession, GapAnalysis, TailoringChange
from app.services.tailoring_engine import tailor_resume
from tests.fixtures.tailoring_fixtures import base_tailoring_triple

if __name__ == "__main__":
    settings = get_settings()
    if not settings.nvidia_api_key:
        raise SystemExit("Set NVIDIA_API_KEY in backend/.env before running this script.")

    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = make_session_factory(engine)()

    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json=job_posting_doc.model_dump())
    db.add_all([resume, job_posting])
    db.commit()

    original_version = ResumeVersion(
        resume_id=resume.id, version_number=1,
        resume_json=resume_doc.model_dump(), produced_by_stage="resume_parsing",
    )
    db.add(original_version)
    db.commit()

    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    gap_analysis = GapAnalysis(
        session_id=session.id, resume_version_id=original_version.id, job_posting_id=job_posting.id,
        analysis_json=gap_analysis_doc.model_dump(),
    )
    db.add(gap_analysis)
    db.commit()

    orchestrator = build_orchestrator(db, session_id=session.id)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)

    tailored_version = tailor_resume(db, session, orchestrator, prompt_registry)

    print("--- Tailored resume ---")
    print(json.dumps(tailored_version.resume_json, indent=2))

    changes = db.query(TailoringChange).filter_by(resume_version_id=tailored_version.id).all()
    print("--- Changes ---")
    for change in changes:
        print(f"{change.field_changed}: {change.rationale}")
        print(f"  original: {change.original_text}")
        print(f"  tailored: {change.tailored_text}")
