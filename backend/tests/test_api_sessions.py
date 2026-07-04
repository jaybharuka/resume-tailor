from app.models.db_models import Resume, JobPosting


def test_create_session_requires_existing_resume_and_job_posting(client):
    response = client.post("/sessions", json={"resume_id": 999, "job_posting_id": 999})
    assert response.status_code == 404


def test_create_session_succeeds_with_valid_ids(client, db_session):
    resume = Resume(original_filename="jane.pdf", storage_path="/tmp/jane.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()

    response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})

    assert response.status_code == 201
    assert response.json()["status"] == "created"


def test_run_stage_returns_501_for_unimplemented_stage(client, db_session):
    resume = Resume(original_filename="jane.pdf", storage_path="/tmp/jane.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    response = client.post(f"/sessions/{session_id}/run-stage/jd_extraction")

    assert response.status_code == 501


class FakeResumeVersion:
    def __init__(self, id):
        self.id = id


def test_run_stage_resume_parsing_succeeds(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def fake_parse_resume(db, resume, storage, orchestrator, prompt_registry):
        return FakeResumeVersion(id=42)

    monkeypatch.setattr(sessions_module, "parse_resume", fake_parse_resume)

    response = client.post(f"/sessions/{session_id}/run-stage/resume_parsing")

    assert response.status_code == 200
    assert response.json() == {"stage_name": "resume_parsing", "status": "succeeded", "resume_version_id": 42}

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert len(runs) == 1
    assert runs[0]["stage_name"] == "resume_parsing"
    assert runs[0]["status"] == "succeeded"


def test_run_stage_resume_parsing_reports_failure(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module
    from app.services.resume_parser import ResumeParsingError

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def failing_parse_resume(db, resume, storage, orchestrator, prompt_registry):
        raise ResumeParsingError("no extractable text — this PDF may be scanned/image-based")

    monkeypatch.setattr(sessions_module, "parse_resume", failing_parse_resume)

    response = client.post(f"/sessions/{session_id}/run-stage/resume_parsing")

    assert response.status_code == 422

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert runs[0]["status"] == "failed"


def test_run_stage_resume_parsing_times_out(client, db_session, monkeypatch):
    import time
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def slow_parse_resume(db, resume, storage, orchestrator, prompt_registry):
        time.sleep(0.5)
        return FakeResumeVersion(id=99)

    monkeypatch.setattr(sessions_module, "parse_resume", slow_parse_resume)
    monkeypatch.setattr(sessions_module, "RESUME_PARSING_TIMEOUT_SECONDS", 0.05)

    response = client.post(f"/sessions/{session_id}/run-stage/resume_parsing")

    assert response.status_code == 504


def test_run_stage_resume_parsing_times_out_uses_captured_run_id_not_stale_object(client, db_session, monkeypatch):
    import time
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def slow_parse_resume_that_touches_shared_session(db, resume, storage, orchestrator, prompt_registry):
        # Simulate the background worker thread still being active against the shared
        # session after the request thread has given up waiting on it.
        time.sleep(0.5)
        return FakeResumeVersion(id=99)

    monkeypatch.setattr(sessions_module, "parse_resume", slow_parse_resume_that_touches_shared_session)
    monkeypatch.setattr(sessions_module, "RESUME_PARSING_TIMEOUT_SECONDS", 0.05)

    response = client.post(f"/sessions/{session_id}/run-stage/resume_parsing")

    assert response.status_code == 504

    # The `client` fixture (see conftest.py) hands every request the SAME `db_session`
    # object via `override_get_db`, purely for test convenience — in production `get_db`
    # opens a brand-new Session per request, so this staleness never occurs there. Here,
    # the fresh-session write in the timeout branch commits through an entirely different
    # Session (`fresh_db`), and SQLAlchemy's identity map means `db_session` won't see that
    # committed change on its already-loaded `PipelineRun` object until it's told to treat
    # its cached attributes as stale, so expire it to read back what was actually persisted
    # (this is exactly what a fresh request-scoped Session would see for free).
    db_session.expire_all()
    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"


def test_get_status_returns_empty_pipeline_runs_in_phase_one(client, db_session):
    resume = Resume(original_filename="jane.pdf", storage_path="/tmp/jane.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    response = client.get(f"/sessions/{session_id}/status")

    assert response.status_code == 200
    assert response.json()["pipeline_runs"] == []
