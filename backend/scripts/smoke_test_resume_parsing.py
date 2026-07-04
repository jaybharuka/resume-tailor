"""Manual smoke test: run with `python scripts/smoke_test_resume_parsing.py`
after setting NVIDIA_API_KEY in backend/.env. Costs a real API call — not run by pytest.

Parses a synthetic fixture PDF through the real NVIDIA API and prints the
resulting ResumeDocument JSON, so a human can manually verify the model
respects the "never fabricate, leave absent fields null" prompt instruction —
this fixture has a sparse work-experience bullet and no projects section, so
watch specifically for whether the model invents extra bullets or a projects
entry that isn't in the source text."""
import json
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.core.llm.orchestrator_factory import build_orchestrator
from app.core.llm.prompt_registry import PromptRegistry
from app.core.storage import LocalDiskStorage
from app.models.db_models import Base, Resume
from app.services.resume_parser import parse_resume
from tests.fixtures.pdf_fixtures import build_sparse_bullets_resume_pdf

if __name__ == "__main__":
    settings = get_settings()
    if not settings.nvidia_api_key:
        raise SystemExit("Set NVIDIA_API_KEY in backend/.env before running this script.")

    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = make_session_factory(engine)()

    storage = LocalDiskStorage(root="./storage")
    storage_path = storage.save("smoke_test/resume.pdf", build_sparse_bullets_resume_pdf())

    resume = Resume(original_filename="resume.pdf", storage_path=storage_path)
    db.add(resume)
    db.commit()

    orchestrator = build_orchestrator(db, session_id=None)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)

    version = parse_resume(db, resume, storage, orchestrator, prompt_registry)
    print(json.dumps(version.resume_json, indent=2))
