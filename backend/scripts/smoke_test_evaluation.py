"""Manual smoke test: run with `python scripts/smoke_test_evaluation.py` after
starting the hiring-agent-service container locally (it requires
GEMINI_API_KEY - see hiring-agent-service/README.md). Makes a real HTTP call -
not run by pytest.

Builds a fixture resume with clear, known production/open-source/technical-
skills indicators (a popular open-source project, a production deployment
metric, named technologies), runs it through render_resume_to_text() and the
real hiring-agent-service, and prints the resulting scores/evidence.

This is the one place the information-loss risk documented in the Phase 6
spec (section 3) actually gets checked by a human: does the rendered prose
surface this fixture's known signal strongly enough for the real evaluator's
scores/evidence to plausibly reflect it? The automated test suite (which
mocks the HTTP client) only proves the pipeline persists whatever
hiring-agent-service returns - it cannot prove the rendering doesn't quietly
under-represent real, scoring-relevant content."""
import json
import httpx
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, Resume, ResumeVersion, JobPosting, TailoringSession
from app.services.evaluator import evaluate_resume

if __name__ == "__main__":
    settings = get_settings()

    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = make_session_factory(engine)()

    resume_json = {
        "schema_version": 1,
        "contact": {
            "full_name": "Morgan Lee", "email": "morgan.lee@example.com", "phone": None,
            "location": "Remote", "links": ["https://github.com/morganlee-oss"],
        },
        "summary": "Backend engineer focused on distributed systems and open-source tooling.",
        "work_experience": [
            {
                "company": "Acme Corp", "title": "Senior Backend Engineer",
                "start_date": "2021", "end_date": "2024",
                "bullets": [
                    "Operated a production payments service handling 2M requests/day with 99.99% uptime",
                    "Led migration from monolith to microservices, cutting deploy time by 60%",
                ],
            },
        ],
        "projects": [
            {
                "name": "Open Source Task Queue",
                "description": "A lightweight distributed task queue in Python",
                "bullets": ["400+ GitHub stars, used in production by three startups"],
                "technologies": ["Python", "Redis"],
            },
        ],
        "skills": ["Python", "PostgreSQL", "Docker", "Kubernetes", "AWS"],
        "education": [],
        "certifications": [],
    }

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
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

    with httpx.Client(timeout=300.0) as http_client:
        evaluation = evaluate_resume(db, session, http_client, settings)

    print("--- Scores ---")
    print(json.dumps({
        "overall_score": evaluation.overall_score,
        "open_source_score": evaluation.open_source_score,
        "projects_score": evaluation.projects_score,
        "production_score": evaluation.production_score,
        "technical_skills_score": evaluation.technical_skills_score,
    }, indent=2))
    print("--- Full raw response (evidence, bonus_points, deductions) ---")
    print(json.dumps(evaluation.raw_response_json, indent=2))
