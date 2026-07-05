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

    response = client.post(f"/sessions/{session_id}/run-stage/document_generation")

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
    monkeypatch.setattr(sessions_module, "STAGE_TIMEOUT_SECONDS", 0.05)

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
    monkeypatch.setattr(sessions_module, "STAGE_TIMEOUT_SECONDS", 0.05)

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


def test_run_stage_gap_analysis_succeeds(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(
        source_url="https://example.com/job", raw_text="Barista at Corner Cafe.",
        parsed_json={"title": "Barista"},
    )
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    class FakeGapAnalysis:
        def __init__(self, id):
            self.id = id

    def fake_analyze_gap(db, session, orchestrator, prompt_registry):
        return FakeGapAnalysis(id=7)

    monkeypatch.setattr(sessions_module, "analyze_gap", fake_analyze_gap)

    response = client.post(f"/sessions/{session_id}/run-stage/gap_analysis")

    assert response.status_code == 200
    assert response.json() == {"stage_name": "gap_analysis", "status": "succeeded", "gap_analysis_id": 7}

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert len(runs) == 1
    assert runs[0]["stage_name"] == "gap_analysis"
    assert runs[0]["status"] == "succeeded"


def test_run_stage_gap_analysis_reports_failure(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module
    from app.services.gap_analyzer import GapAnalysisError

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def failing_analyze_gap(db, session, orchestrator, prompt_registry):
        raise GapAnalysisError("resume_parsing has not succeeded for this session yet")

    monkeypatch.setattr(sessions_module, "analyze_gap", failing_analyze_gap)

    response = client.post(f"/sessions/{session_id}/run-stage/gap_analysis")

    assert response.status_code == 422

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert runs[0]["status"] == "failed"


def test_run_stage_gap_analysis_times_out(client, db_session, monkeypatch):
    import time
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job", parsed_json={"title": "Barista"})
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    class FakeGapAnalysis:
        def __init__(self, id):
            self.id = id

    def slow_analyze_gap(db, session, orchestrator, prompt_registry):
        time.sleep(0.5)
        return FakeGapAnalysis(id=1)

    monkeypatch.setattr(sessions_module, "analyze_gap", slow_analyze_gap)
    monkeypatch.setattr(sessions_module, "STAGE_TIMEOUT_SECONDS", 0.05)

    response = client.post(f"/sessions/{session_id}/run-stage/gap_analysis")

    assert response.status_code == 504

    # See test_run_stage_resume_parsing_times_out_uses_captured_run_id_not_stale_object
    # for why this expire_all() is needed: the `client` fixture hands every request the
    # same `db_session` object, and the timeout branch commits the failure through a
    # separate `fresh_db` session.
    db_session.expire_all()
    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
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


def test_run_stage_jd_extraction_succeeds(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job", raw_text="Barista at Corner Cafe.")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def fake_extract_job_posting(db, job_posting, orchestrator, prompt_registry):
        job_posting.parsed_json = {"title": "Barista"}
        return job_posting

    monkeypatch.setattr(sessions_module, "extract_job_posting", fake_extract_job_posting)

    response = client.post(f"/sessions/{session_id}/run-stage/jd_extraction")

    assert response.status_code == 200
    assert response.json() == {"stage_name": "jd_extraction", "status": "succeeded", "job_posting_id": job.id}

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert len(runs) == 1
    assert runs[0]["stage_name"] == "jd_extraction"
    assert runs[0]["status"] == "succeeded"


def test_run_stage_jd_extraction_reports_failure(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module
    from app.services.jd_extractor import JDExtractionError

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job", raw_text="Barista at Corner Cafe.")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def failing_extract_job_posting(db, job_posting, orchestrator, prompt_registry):
        raise JDExtractionError("no raw_text on this job posting to extract from")

    monkeypatch.setattr(sessions_module, "extract_job_posting", failing_extract_job_posting)

    response = client.post(f"/sessions/{session_id}/run-stage/jd_extraction")

    assert response.status_code == 422

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert runs[0]["status"] == "failed"


def test_run_stage_jd_extraction_times_out(client, db_session, monkeypatch):
    import time
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job", raw_text="Barista at Corner Cafe.")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def slow_extract_job_posting(db, job_posting, orchestrator, prompt_registry):
        time.sleep(0.5)
        job_posting.parsed_json = {"title": "Barista"}
        return job_posting

    monkeypatch.setattr(sessions_module, "extract_job_posting", slow_extract_job_posting)
    monkeypatch.setattr(sessions_module, "STAGE_TIMEOUT_SECONDS", 0.05)

    response = client.post(f"/sessions/{session_id}/run-stage/jd_extraction")

    assert response.status_code == 504

    # See test_run_stage_resume_parsing_times_out_uses_captured_run_id_not_stale_object for
    # why this expire_all() is needed: the `client` fixture hands every request the same
    # `db_session` object, and the timeout branch commits the failure through a separate
    # `fresh_db` session, so `db_session`'s identity map needs to be told its cached
    # `PipelineRun` is stale before re-reading it here.
    db_session.expire_all()
    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert runs[0]["status"] == "failed"


def test_run_stage_tailoring_rewrite_succeeds(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(
        source_url="https://example.com/job", raw_text="Barista at Corner Cafe.",
        parsed_json={"title": "Barista"},
    )
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    class FakeResumeVersion:
        def __init__(self, id):
            self.id = id

    def fake_tailor_resume(db, session, orchestrator, prompt_registry):
        return FakeResumeVersion(id=11)

    monkeypatch.setattr(sessions_module, "tailor_resume", fake_tailor_resume)

    response = client.post(f"/sessions/{session_id}/run-stage/tailoring_rewrite")

    assert response.status_code == 200
    assert response.json() == {"stage_name": "tailoring_rewrite", "status": "succeeded", "resume_version_id": 11}

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert len(runs) == 1
    assert runs[0]["stage_name"] == "tailoring_rewrite"
    assert runs[0]["status"] == "succeeded"


def test_run_stage_tailoring_rewrite_reports_failure(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module
    from app.services.tailoring_engine import TailoringError

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def failing_tailor_resume(db, session, orchestrator, prompt_registry):
        raise TailoringError("resume_parsing has not succeeded for this session yet")

    monkeypatch.setattr(sessions_module, "tailor_resume", failing_tailor_resume)

    response = client.post(f"/sessions/{session_id}/run-stage/tailoring_rewrite")

    assert response.status_code == 422

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert runs[0]["status"] == "failed"


def test_run_stage_tailoring_rewrite_times_out(client, db_session, monkeypatch):
    import time
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job", parsed_json={"title": "Barista"})
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    class FakeResumeVersion:
        def __init__(self, id):
            self.id = id

    def slow_tailor_resume(db, session, orchestrator, prompt_registry):
        time.sleep(0.5)
        return FakeResumeVersion(id=1)

    monkeypatch.setattr(sessions_module, "tailor_resume", slow_tailor_resume)
    monkeypatch.setattr(sessions_module, "STAGE_TIMEOUT_SECONDS", 0.05)

    response = client.post(f"/sessions/{session_id}/run-stage/tailoring_rewrite")

    assert response.status_code == 504

    # See test_run_stage_resume_parsing_times_out_uses_captured_run_id_not_stale_object
    # for why this expire_all() is needed: the `client` fixture hands every request
    # the same `db_session` object, and the timeout branch commits the failure
    # through a separate `fresh_db` session.
    db_session.expire_all()
    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert runs[0]["status"] == "failed"


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
