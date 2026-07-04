"""Manual smoke test: run with `python scripts/smoke_test_jd_extraction.py`
after setting NVIDIA_API_KEY in backend/.env. Costs a real API call — not run
by pytest.

Extracts a synthetic 'not a job posting' fixture through the real NVIDIA API
and prints the resulting JobPostingDocument JSON, so a human can manually
verify the model does NOT fabricate a plausible-looking title to satisfy the
schema's one required field when the source text isn't a job posting at all —
this is the highest fabrication-risk case in this phase (see spec §3.2), and
the automated test suite (which mocks the orchestrator) cannot itself prove
real-model behavior for it."""
import json
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.core.llm.orchestrator_factory import build_orchestrator
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import Base, JobPosting
from app.services.jd_extractor import extract_job_posting
from tests.fixtures.jd_fixtures import not_a_job_posting_text

if __name__ == "__main__":
    settings = get_settings()
    if not settings.nvidia_api_key:
        raise SystemExit("Set NVIDIA_API_KEY in backend/.env before running this script.")

    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = make_session_factory(engine)()

    job_posting = JobPosting(raw_text=not_a_job_posting_text())
    db.add(job_posting)
    db.commit()

    orchestrator = build_orchestrator(db, session_id=None)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)

    result = extract_job_posting(db, job_posting, orchestrator, prompt_registry)
    print(json.dumps(result.parsed_json, indent=2))
