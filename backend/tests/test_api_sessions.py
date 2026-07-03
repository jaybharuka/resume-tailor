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

    response = client.post(f"/sessions/{session_id}/run-stage/resume_parsing")

    assert response.status_code == 501


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
