# Phase 6 — Hiring-Agent Integration (Evaluation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the tailored `ResumeDocument` through the existing `hiring-agent-service` HTTP wrapper to get real evaluation scores, persisted into the existing `evaluation_runs` table.

**Architecture:** A new `render_resume_to_text()` rendering function converts the tailored resume's structured JSON into the plain prose `hiring-agent-service` expects. A new `evaluator.py` service (parallel to `tailoring_engine.py`/`gap_analyzer.py`) guards on a single prerequisite (a `tailoring_rewrite` version must exist for the session), calls `hiring-agent-service` over HTTP via an injected client, and persists the response into `evaluation_runs`. No LLM Orchestrator, no prompt template — the only external call is a synchronous HTTP POST.

**Tech Stack:** FastAPI, SQLAlchemy, `httpx` (existing dependency, already used in `app/api/health.py`) — no new dependencies.

## Global Constraints

- `hiring-agent-service`'s real contract (verified against `hiring-agent-service/app.py`): `POST /evaluate` takes `{"resume_text": str, "github_username": str | None}`, returns `overall_score`, `open_source_score`, `projects_score`, `production_score`, `technical_skills_score`, `evidence`, `bonus_points`, `deductions`, `rubric_version`, `hiring_agent_service_version`, `raw`.
- `github_username` is passed as `None` always — confirmed dead code in the wrapper's call chain (`evaluator.evaluate_resume(request.resume_text)` never forwards it, and `ResumeEvaluator.evaluate_resume` doesn't even accept the parameter).
- `evaluation_runs` (existing table, verified against `backend/alembic/versions/0001_initial_schema.py`) already has every column needed — **no new migration in this phase**.
- Each evaluation run inserts a new `evaluation_runs` row — no dedup, no update-in-place (matches the `gap_analyses`/tailored-`resume_versions` precedent).
- The dependency guard requires a `resume_versions` row with `produced_by_stage="tailoring_rewrite"` **for this specific session** (`session_id` match), not just any tailored version for the resume.
- `EvaluationError` inherits `StageExecutionError`.
- The HTTP client is dependency-injected into the service function (matching how other services inject the `AIOrchestrator`), not called via a bare module-level `httpx.post` — this keeps the service layer's DI convention consistent (routers like `health.py` use direct calls + monkeypatch; services use constructor injection).
- Reuses `STAGE_TIMEOUT_SECONDS`/`ThreadPoolExecutor`/fresh-session-on-timeout unchanged.
- `test_run_stage_returns_501_for_unimplemented_stage` must move to a new placeholder stage name (`document_generation`) since `evaluation` is implemented for real by this phase.
- Windows test runner for this repo: `py -3 -m pytest` (or venv-equivalent), run from `backend/`.
- Baseline before Task 1: 156 passed, 1 skipped (Postgres-dependent migration test).

---

### Task 1: `render_resume_to_text()` rendering function

**Files:**
- Create: `backend/app/services/resume_renderer.py`
- Test: `backend/tests/test_resume_renderer.py`

**Interfaces:**
- Consumes: nothing new — operates on a plain `dict` (a `resume_versions.resume_json` value).
- Produces: `render_resume_to_text(resume_json: dict) -> str`. Consumed by Task 2 (`evaluator.py`).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_resume_renderer.py`:

```python
from app.services.resume_renderer import render_resume_to_text


def test_render_resume_to_text_includes_all_populated_sections():
    resume_json = {
        "contact": {
            "full_name": "Jane Doe", "email": "jane@example.com", "phone": "555-1234",
            "location": "Springfield", "links": ["https://github.com/janedoe"],
        },
        "summary": "Backend engineer with 5 years of experience.",
        "work_experience": [
            {
                "company": "Acme Corp", "title": "Senior Backend Engineer",
                "start_date": "2021", "end_date": "2024",
                "bullets": ["Built payment systems"],
            },
        ],
        "projects": [
            {
                "name": "Task Queue", "description": "A distributed task queue",
                "bullets": ["400+ GitHub stars"], "technologies": ["Python", "Redis"],
            },
        ],
        "skills": ["Python", "PostgreSQL"],
        "education": [
            {
                "institution": "State University", "degree": "B.S.",
                "field_of_study": "Computer Science", "start_date": "2014", "end_date": "2018",
            },
        ],
        "certifications": ["AWS Certified Solutions Architect"],
    }

    text = render_resume_to_text(resume_json)

    assert "Jane Doe" in text
    assert "jane@example.com" in text
    assert "https://github.com/janedoe" in text
    assert "Backend engineer with 5 years of experience." in text
    assert "Senior Backend Engineer" in text
    assert "Acme Corp" in text
    assert "Built payment systems" in text
    assert "Task Queue" in text
    assert "A distributed task queue" in text
    assert "400+ GitHub stars" in text
    assert "Python, Redis" in text
    assert "Python, PostgreSQL" in text
    assert "State University" in text
    assert "B.S." in text
    assert "Computer Science" in text
    assert "AWS Certified Solutions Architect" in text


def test_render_resume_to_text_omits_empty_sections_for_sparse_resume():
    resume_json = {
        "contact": {"full_name": "Alex Lee", "email": None, "phone": None, "location": None, "links": []},
        "summary": None,
        "work_experience": [
            {
                "company": "Startup Co", "title": "Engineer",
                "start_date": "2022", "end_date": "2024", "bullets": ["Worked on backend"],
            },
        ],
        "projects": [],
        "skills": [],
        "education": [],
        "certifications": [],
    }

    text = render_resume_to_text(resume_json)

    assert "Alex Lee" in text
    assert "Startup Co" in text
    assert "Summary" not in text
    assert "Projects" not in text
    assert "Skills" not in text
    assert "Education" not in text
    assert "Certifications" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_resume_renderer.py -v` (from `backend/`)
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.resume_renderer'`

- [ ] **Step 3: Write the renderer**

`backend/app/services/resume_renderer.py`:

```python
def render_resume_to_text(resume_json: dict) -> str:
    """Render a structured resume (a resume_versions.resume_json value) into
    plain prose, since hiring-agent-service's /evaluate expects raw resume
    text (matching what ResumeEvaluator was built and tuned against), not
    structured JSON."""
    lines: list[str] = []

    contact = resume_json.get("contact", {})
    if contact.get("full_name"):
        lines.append(contact["full_name"])
    contact_line_parts = [
        part for part in (contact.get("email"), contact.get("phone"), contact.get("location")) if part
    ]
    if contact_line_parts:
        lines.append(" | ".join(contact_line_parts))
    for link in contact.get("links", []):
        lines.append(link)
    lines.append("")

    if resume_json.get("summary"):
        lines.append("Summary")
        lines.append(resume_json["summary"])
        lines.append("")

    work_experience = resume_json.get("work_experience", [])
    if work_experience:
        lines.append("Experience")
        for entry in work_experience:
            header = f"{entry.get('title', '')} at {entry.get('company', '')}"
            if entry.get("start_date") or entry.get("end_date"):
                header += f" ({entry.get('start_date', '')} - {entry.get('end_date', '')})"
            lines.append(header)
            for bullet in entry.get("bullets", []):
                lines.append(f"- {bullet}")
            lines.append("")

    projects = resume_json.get("projects", [])
    if projects:
        lines.append("Projects")
        for project in projects:
            lines.append(project.get("name", ""))
            if project.get("description"):
                lines.append(project["description"])
            for bullet in project.get("bullets", []):
                lines.append(f"- {bullet}")
            technologies = project.get("technologies", [])
            if technologies:
                lines.append(f"Technologies: {', '.join(technologies)}")
            lines.append("")

    skills = resume_json.get("skills", [])
    if skills:
        lines.append("Skills")
        lines.append(", ".join(skills))
        lines.append("")

    education = resume_json.get("education", [])
    if education:
        lines.append("Education")
        for entry in education:
            line = entry.get("institution", "")
            if entry.get("degree"):
                line += f" - {entry['degree']}"
            if entry.get("field_of_study"):
                line += f", {entry['field_of_study']}"
            if entry.get("start_date") or entry.get("end_date"):
                line += f" ({entry.get('start_date', '')} - {entry.get('end_date', '')})"
            lines.append(line)
        lines.append("")

    certifications = resume_json.get("certifications", [])
    if certifications:
        lines.append("Certifications")
        for cert in certifications:
            lines.append(f"- {cert}")
        lines.append("")

    return "\n".join(lines).strip()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_resume_renderer.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/resume_renderer.py backend/tests/test_resume_renderer.py
git commit -m "feat: add render_resume_to_text for hiring-agent-service input"
```

---

### Task 2: Evaluator service

**Files:**
- Create: `backend/app/services/evaluator.py`
- Test: `backend/tests/test_evaluator.py`

**Interfaces:**
- Consumes: `render_resume_to_text` (Task 1); `TailoringSession`, `ResumeVersion`, `EvaluationRun` (`app.models.db_models`, already exist); `StageExecutionError` (`app.services.errors`, already exists); `Settings` (`app.core.config`, already exists, has `hiring_agent_service_url`).
- Produces: `evaluate_resume(db: Session, session: TailoringSession, http_client, settings) -> EvaluationRun`, `EvaluationError` (exception, inherits `StageExecutionError`). Consumed by Task 3 (`sessions.py`'s `_run_evaluation`).

`http_client` is any object with a `.post(url, json=dict) -> response` method where `response` has `.raise_for_status()` and `.json()` — a real `httpx.Client` in production, a fake in tests. This mirrors how other services accept an `orchestrator` parameter rather than importing/constructing one internally.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_evaluator.py`:

```python
import httpx
import pytest
from app.core.config import Settings
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, Resume, ResumeVersion, JobPosting, TailoringSession, EvaluationRun
from app.services.evaluator import evaluate_resume, EvaluationError


class FakeHttpClient:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.calls = []

    def post(self, url, json):
        self.calls.append((url, json))
        if self._error is not None:
            raise self._error
        return self._response


def _make_response(status_code: int, json_body: dict | None = None) -> httpx.Response:
    request = httpx.Request("POST", "http://hiring-agent-service:8100/evaluate")
    return httpx.Response(status_code, json=json_body, request=request)


def _make_db():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def _make_session_with_tailored_version(db):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()

    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    tailored_version = ResumeVersion(
        resume_id=resume.id, session_id=session.id, version_number=2,
        resume_json={"contact": {"full_name": "Jane Doe"}, "skills": ["Python"]},
        produced_by_stage="tailoring_rewrite",
    )
    db.add(tailored_version)
    db.commit()

    return session, tailored_version


def _settings() -> Settings:
    return Settings(hiring_agent_service_url="http://hiring-agent-service:8100")


def test_evaluate_resume_persists_all_score_fields():
    db = _make_db()
    session, tailored_version = _make_session_with_tailored_version(db)

    response_body = {
        "overall_score": 88.0,
        "open_source_score": 30,
        "projects_score": 25,
        "production_score": 20,
        "technical_skills_score": 8,
        "evidence": {"open_source": "3 popular repos"},
        "bonus_points": {"total": 5, "breakdown": "Active OSS contributor"},
        "deductions": {"total": 0, "reasons": "No deductions"},
        "rubric_version": "hiring-agent-v1",
        "hiring_agent_service_version": "0.1.0",
        "raw": {"key_strengths": ["Strong OSS presence"]},
    }
    http_client = FakeHttpClient(response=_make_response(200, response_body))

    evaluation = evaluate_resume(db, session, http_client, _settings())

    assert evaluation.session_id == session.id
    assert evaluation.resume_version_id == tailored_version.id
    assert evaluation.overall_score == 88.0
    assert evaluation.open_source_score == 30
    assert evaluation.projects_score == 25
    assert evaluation.production_score == 20
    assert evaluation.technical_skills_score == 8
    assert evaluation.rubric_version == "hiring-agent-v1"
    assert evaluation.hiring_agent_service_version == "0.1.0"
    assert evaluation.raw_response_json == response_body
    assert db.query(EvaluationRun).count() == 1


def test_evaluate_resume_sends_rendered_text_and_null_github_username():
    db = _make_db()
    session, tailored_version = _make_session_with_tailored_version(db)

    response_body = {
        "overall_score": 50.0, "open_source_score": 10, "projects_score": 10,
        "production_score": 10, "technical_skills_score": 5,
        "rubric_version": "hiring-agent-v1", "hiring_agent_service_version": "0.1.0",
    }
    http_client = FakeHttpClient(response=_make_response(200, response_body))

    evaluate_resume(db, session, http_client, _settings())

    assert len(http_client.calls) == 1
    url, payload = http_client.calls[0]
    assert url == "http://hiring-agent-service:8100/evaluate"
    assert payload["github_username"] is None
    assert "Jane Doe" in payload["resume_text"]


def test_evaluate_resume_fails_fast_when_no_tailored_version_without_calling_http_client():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    http_client = FakeHttpClient()

    with pytest.raises(EvaluationError, match="tailoring_rewrite"):
        evaluate_resume(db, session, http_client, _settings())

    assert http_client.calls == []


def test_evaluate_resume_wraps_connection_error():
    db = _make_db()
    session, tailored_version = _make_session_with_tailored_version(db)

    http_client = FakeHttpClient(error=httpx.ConnectError("connection refused"))

    with pytest.raises(EvaluationError):
        evaluate_resume(db, session, http_client, _settings())

    assert db.query(EvaluationRun).count() == 0


def test_evaluate_resume_wraps_non_200_response():
    db = _make_db()
    session, tailored_version = _make_session_with_tailored_version(db)

    http_client = FakeHttpClient(response=_make_response(500))

    with pytest.raises(EvaluationError):
        evaluate_resume(db, session, http_client, _settings())

    assert db.query(EvaluationRun).count() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_evaluator.py -v` (from `backend/`)
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.evaluator'`

- [ ] **Step 3: Write the service**

`backend/app/services/evaluator.py`:

```python
import httpx
from sqlalchemy.orm import Session
from app.models.db_models import TailoringSession, ResumeVersion, EvaluationRun
from app.services.resume_renderer import render_resume_to_text
from app.services.errors import StageExecutionError


class EvaluationError(StageExecutionError):
    """Raised when hiring-agent evaluation fails: the tailoring_rewrite
    prerequisite hasn't succeeded yet, or the HTTP call to hiring-agent-service
    failed (connection error or non-2xx response)."""


def evaluate_resume(
    db: Session,
    session: TailoringSession,
    http_client,
    settings,
) -> EvaluationRun:
    tailored_version = (
        db.query(ResumeVersion)
        .filter_by(session_id=session.id, produced_by_stage="tailoring_rewrite")
        .order_by(ResumeVersion.id.desc())
        .first()
    )
    if tailored_version is None:
        raise EvaluationError("tailoring_rewrite has not succeeded for this session yet")

    resume_text = render_resume_to_text(tailored_version.resume_json)

    try:
        response = http_client.post(
            f"{settings.hiring_agent_service_url}/evaluate",
            json={"resume_text": resume_text, "github_username": None},
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise EvaluationError(str(exc)) from exc

    body = response.json()

    evaluation = EvaluationRun(
        session_id=session.id,
        resume_version_id=tailored_version.id,
        overall_score=body.get("overall_score"),
        open_source_score=body.get("open_source_score"),
        projects_score=body.get("projects_score"),
        production_score=body.get("production_score"),
        technical_skills_score=body.get("technical_skills_score"),
        raw_response_json=body,
        rubric_version=body.get("rubric_version"),
        hiring_agent_service_version=body.get("hiring_agent_service_version"),
    )
    db.add(evaluation)
    db.commit()
    db.refresh(evaluation)
    return evaluation
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_evaluator.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/evaluator.py backend/tests/test_evaluator.py
git commit -m "feat: add evaluator service with tailoring_rewrite dependency guard"
```

---

### Task 3: Wire `evaluation` into `run_stage`

**Files:**
- Modify: `backend/app/api/sessions.py`
- Modify: `backend/tests/test_api_sessions.py`

**Interfaces:**
- Consumes: `evaluate_resume` (Task 2), `STAGE_RUNNERS`/`STAGE_TIMEOUT_SECONDS`/`run_stage` (existing, `app.api.sessions`).
- Produces: `STAGE_RUNNERS["evaluation"]` entry; `POST /sessions/{id}/run-stage/evaluation` returns `{"stage_name": "evaluation", "status": "succeeded", "evaluation_run_id": <int>}` on success.

- [ ] **Step 1: Update the stale 501 test and add the new evaluation tests**

In `backend/tests/test_api_sessions.py`, change `test_run_stage_returns_501_for_unimplemented_stage` (which currently posts to `evaluation`, now implemented for real) to target a genuinely-still-unimplemented stage name:

```python
def test_run_stage_returns_501_for_unimplemented_stage(client, db_session):
    resume = Resume(original_filename="jane.pdf", storage_path="/tmp/jane.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    response = client.post(f"/sessions/{session_id}/run-stage/document_generation")

    assert response.status_code == 501
```

Add these new tests to the same file:

```python
def test_run_stage_evaluation_succeeds(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job", raw_text="Barista at Corner Cafe.")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    class FakeEvaluationRun:
        def __init__(self, id):
            self.id = id

    def fake_evaluate_resume(db, session, http_client, settings):
        return FakeEvaluationRun(id=5)

    monkeypatch.setattr(sessions_module, "evaluate_resume", fake_evaluate_resume)

    response = client.post(f"/sessions/{session_id}/run-stage/evaluation")

    assert response.status_code == 200
    assert response.json() == {"stage_name": "evaluation", "status": "succeeded", "evaluation_run_id": 5}

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert len(runs) == 1
    assert runs[0]["stage_name"] == "evaluation"
    assert runs[0]["status"] == "succeeded"


def test_run_stage_evaluation_reports_failure(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module
    from app.services.evaluator import EvaluationError

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def failing_evaluate_resume(db, session, http_client, settings):
        raise EvaluationError("tailoring_rewrite has not succeeded for this session yet")

    monkeypatch.setattr(sessions_module, "evaluate_resume", failing_evaluate_resume)

    response = client.post(f"/sessions/{session_id}/run-stage/evaluation")

    assert response.status_code == 422

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert runs[0]["status"] == "failed"


def test_run_stage_evaluation_times_out(client, db_session, monkeypatch):
    import time
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    class FakeEvaluationRun:
        def __init__(self, id):
            self.id = id

    def slow_evaluate_resume(db, session, http_client, settings):
        time.sleep(0.5)
        return FakeEvaluationRun(id=1)

    monkeypatch.setattr(sessions_module, "evaluate_resume", slow_evaluate_resume)
    monkeypatch.setattr(sessions_module, "STAGE_TIMEOUT_SECONDS", 0.05)

    response = client.post(f"/sessions/{session_id}/run-stage/evaluation")

    assert response.status_code == 504

    # See test_run_stage_resume_parsing_times_out_uses_captured_run_id_not_stale_object
    # for why this expire_all() is needed: the `client` fixture hands every request
    # the same `db_session` object, and the timeout branch commits the failure
    # through a separate `fresh_db` session.
    db_session.expire_all()
    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert runs[0]["status"] == "failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3 -m pytest tests/test_api_sessions.py -v` (from `backend/`)
Expected: the 3 new tests FAIL with 501 responses (`evaluation` not yet in `STAGE_RUNNERS`); the updated 501 test already passes (it doesn't depend on new code).

- [ ] **Step 3: Wire `evaluation` into `sessions.py`**

In `backend/app/api/sessions.py`, add imports alongside the existing ones:

```python
import httpx
from app.services.evaluator import evaluate_resume
```

Add a new dispatcher function after `_run_tailoring` and before the `STAGE_RUNNERS` dict:

```python
def _run_evaluation(db: Session, session: TailoringSession, settings) -> dict:
    with httpx.Client(timeout=300.0) as http_client:
        evaluation = evaluate_resume(db, session, http_client, settings)
    return {"evaluation_run_id": evaluation.id}
```

Update the `STAGE_RUNNERS` dict:

```python
STAGE_RUNNERS = {
    "resume_parsing": _run_resume_parsing,
    "jd_extraction": _run_jd_extraction,
    "gap_analysis": _run_gap_analysis,
    "tailoring_rewrite": _run_tailoring,
    "evaluation": _run_evaluation,
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -3 -m pytest tests/test_api_sessions.py -v`
Expected: all tests in this file pass (17 pre-existing + 3 new = 20 passed)

- [ ] **Step 5: Run the full suite**

Run: `py -3 -m pytest -q` (from `backend/`)
Expected: 166 passed, 1 skipped (156 baseline + 2 from Task 1 + 5 from Task 2 + 3 from Task 3).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/sessions.py backend/tests/test_api_sessions.py
git commit -m "feat: wire evaluation into run_stage via STAGE_RUNNERS"
```

---

### Task 4: Manual smoke-test script

**Files:**
- Create: `backend/scripts/smoke_test_evaluation.py`

**Interfaces:**
- Consumes: everything from Tasks 1-3. Not run by pytest — manual verification only, requires the real `hiring-agent-service` container running locally (which itself requires `GEMINI_API_KEY`, per that service's README). This is the sole place the spec §3 information-loss risk actually gets checked: does `render_resume_to_text()`'s output surface a fixture's known production/open-source/technical-skills signal strongly enough for the real evaluator to reflect it in scores?

- [ ] **Step 1: Write the script**

`backend/scripts/smoke_test_evaluation.py`:

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add backend/scripts/smoke_test_evaluation.py
git commit -m "feat: add manual smoke-test script for evaluation"
```

---

## Self-Review

**Spec coverage:**
- §2 (real contract, `github_username` confirmed dead) → Task 2 (`evaluate_resume` always passes `github_username=None`, matching the verified-safe finding).
- §3 (rendering, information-loss risk) → Task 1 (`render_resume_to_text`), Task 4 (smoke script explicitly checks information-loss with a fixture carrying known signal).
- §4 (reuses existing `evaluation_runs`, no migration) → Task 2 (`EvaluationRun` construction maps every field, no schema changes anywhere in this plan).
- §5 (single dependency guard, session-scoped `tailoring_rewrite` lookup) → Task 2 (`filter_by(session_id=session.id, produced_by_stage="tailoring_rewrite")`).
- §6 (HTTP client dependency injection) → Task 2 (`http_client` parameter, mirrors `orchestrator` injection pattern).
- §7 (API integration, reused timeout mechanism, stale 501 test fix) → Task 3.
- §8 (testing: renderer unit tests, mocked-client service tests, API tests, manual smoke script) → Tasks 1, 2, 3, 4 respectively.
- §9 (out of scope: no retry loop, no `github_username` extraction, no changes to `hiring-agent-service`/`evaluation_runs`/timeout design) → confirmed no task introduces any of these.

**Placeholder scan:** no TBD/TODO markers; every step has complete, runnable code.

**Type consistency:** `evaluate_resume(db, session, http_client, settings) -> EvaluationRun` matches exactly between Task 2 (definition), Task 3 (`_run_evaluation` caller), and Task 4 (smoke script caller). `EvaluationError` is defined once in Task 2 and imported (not redefined) in Task 3; it inherits `StageExecutionError` so Task 3's existing `except StageExecutionError` clause in `run_stage` catches it without modification. `render_resume_to_text(resume_json: dict) -> str` (Task 1) signature matches exactly how it's called in Task 2. `EvaluationRun` field names (`session_id`, `resume_version_id`, `overall_score`, `open_source_score`, `projects_score`, `production_score`, `technical_skills_score`, `raw_response_json`, `rubric_version`, `hiring_agent_service_version`) match the existing ORM class exactly — no new fields introduced, none omitted.

---

**Plan complete and saved to `docs/superpowers/plans/2026-07-08-phase6-hiring-agent-evaluation.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
