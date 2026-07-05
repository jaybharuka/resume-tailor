"""Manual smoke test: run with `python scripts/smoke_test_document_generation.py`
from the `backend/` directory, after installing Tectonic locally (see README's
"Document generation" section for setup and the package-cache network
tradeoff). Not run by pytest.

Builds a fixture tailored resume, generates a real PDF via the real Tectonic
binary, and prints the resulting file's path and size so a human can open it
and eyeball the rendering quality - this is the one place a human actually
looks at the rendered output, not just asserts it compiled without error."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.core.storage import LocalDiskStorage
from app.models.db_models import Base, Resume, ResumeVersion, JobPosting, TailoringSession
from app.services.document_generator import generate_document, _compile_latex_to_pdf
from app.services.latex_renderer import LatexRenderer

if __name__ == "__main__":
    settings = get_settings()

    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = make_session_factory(engine)()

    resume_json = {
        "schema_version": 1,
        "contact": {
            "full_name": "Morgan Lee", "email": "morgan.lee@example.com", "phone": "555-0100",
            "location": "Remote", "links": ["https://github.com/morganlee-oss"],
        },
        "summary": "Backend engineer focused on distributed systems and open-source tooling.",
        "work_experience": [
            {
                "company": "Acme Corp", "title": "Senior Backend Engineer",
                "start_date": "2021", "end_date": "2024",
                "bullets": [
                    "Operated a production payments service handling 2M requests/day",
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

    storage = LocalDiskStorage(root=settings.storage_root)
    latex_renderer = LatexRenderer(templates_root=settings.latex_templates_root)

    document = generate_document(db, session, storage, latex_renderer, _compile_latex_to_pdf)

    pdf_path = Path(document.storage_path)
    print(json.dumps({
        "generated_document_id": document.id,
        "storage_path": str(pdf_path),
        "file_size_bytes": pdf_path.stat().st_size,
        "version_number": document.version_number,
    }, indent=2))
    print(f"\nOpen the file to eyeball the rendering: {pdf_path.resolve()}")
