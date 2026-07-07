from app.models.db_models import Resume, JobPosting, GeneratedDocument


def test_list_documents_returns_404_for_unknown_session(client):
    response = client.get("/sessions/999/documents")
    assert response.status_code == 404


def test_list_documents_returns_empty_list_when_none_generated(client, db_session):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    response = client.get(f"/sessions/{session_id}/documents")

    assert response.status_code == 200
    assert response.json() == []


def test_list_documents_returns_null_content_for_pdf_type_document(client, db_session):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    document = GeneratedDocument(
        session_id=session_id, resume_version_id=None, document_type="resume_pdf",
        storage_path="/tmp/resume.pdf", content=None, version_number=1,
    )
    db_session.add(document)
    db_session.commit()

    response = client.get(f"/sessions/{session_id}/documents")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["document_type"] == "resume_pdf"
    assert body[0]["storage_path"] == "/tmp/resume.pdf"
    assert body[0]["content"] is None
    assert body[0]["version_number"] == 1


def test_list_documents_returns_populated_content_for_text_type_document(client, db_session):
    """This phase's addition (spec §5): text-based document types (cover_letter,
    recruiter_summary, interview_questions) populate content and leave
    storage_path None - the reverse of the PDF row above. Before this task,
    content was never returned by this endpoint at all, making these three
    document types unreachable through the API despite being persisted."""
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    document = GeneratedDocument(
        session_id=session_id, resume_version_id=None, document_type="cover_letter",
        storage_path=None, content="Dear Hiring Manager, ...", version_number=1,
    )
    db_session.add(document)
    db_session.commit()

    response = client.get(f"/sessions/{session_id}/documents")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["document_type"] == "cover_letter"
    assert body[0]["storage_path"] is None
    assert body[0]["content"] == "Dear Hiring Manager, ..."
