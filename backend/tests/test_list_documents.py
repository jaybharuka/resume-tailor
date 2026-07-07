from app.models.db_models import Resume, JobPosting, GeneratedDocument
from app.core.storage import LocalDiskStorage


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
    assert body[0]["id"] == document.id


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


def test_download_document_returns_pdf_bytes(client, db_session, tmp_path, monkeypatch):
    import app.api.sessions as sessions_module
    from app.core.config import Settings

    monkeypatch.setattr(sessions_module, "get_settings", lambda: Settings(storage_root=str(tmp_path)))

    storage = LocalDiskStorage(root=str(tmp_path))
    pdf_bytes = b"%PDF-1.4 fake pdf bytes"
    storage_path = storage.save("generated_documents/1/resume_pdf_v1.pdf", pdf_bytes)

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    document = GeneratedDocument(
        session_id=session_id, resume_version_id=None, document_type="resume_pdf",
        storage_path=storage_path, content=None, version_number=1,
    )
    db_session.add(document)
    db_session.commit()

    response = client.get(f"/sessions/{session_id}/documents/{document.id}/download")

    assert response.status_code == 200
    assert response.content == pdf_bytes
    assert response.headers["content-type"] == "application/pdf"
    assert "resume_pdf_v1.pdf" in response.headers["content-disposition"]


def test_download_document_returns_404_for_unknown_document(client, db_session):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    response = client.get(f"/sessions/{session_id}/documents/999/download")

    assert response.status_code == 404


def test_download_document_returns_404_when_document_belongs_to_different_session(client, db_session, tmp_path, monkeypatch):
    import app.api.sessions as sessions_module
    from app.core.config import Settings

    monkeypatch.setattr(sessions_module, "get_settings", lambda: Settings(storage_root=str(tmp_path)))
    storage = LocalDiskStorage(root=str(tmp_path))
    storage_path = storage.save("generated_documents/1/resume_pdf_v1.pdf", b"%PDF-1.4 fake pdf bytes")

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_a = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id}).json()["id"]
    session_b = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id}).json()["id"]

    document = GeneratedDocument(
        session_id=session_a, resume_version_id=None, document_type="resume_pdf",
        storage_path=storage_path, content=None, version_number=1,
    )
    db_session.add(document)
    db_session.commit()

    response = client.get(f"/sessions/{session_b}/documents/{document.id}/download")

    assert response.status_code == 404


def test_download_document_returns_404_when_file_missing_from_storage(client, db_session, tmp_path, monkeypatch):
    import app.api.sessions as sessions_module
    from app.core.config import Settings

    monkeypatch.setattr(sessions_module, "get_settings", lambda: Settings(storage_root=str(tmp_path)))

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    # storage_path points to a file that was never actually written to disk -
    # simulates the row surviving after the underlying file was moved/deleted.
    document = GeneratedDocument(
        session_id=session_id, resume_version_id=None, document_type="resume_pdf",
        storage_path=str(tmp_path / "generated_documents" / "1" / "resume_pdf_v1.pdf"),
        content=None, version_number=1,
    )
    db_session.add(document)
    db_session.commit()

    response = client.get(f"/sessions/{session_id}/documents/{document.id}/download")

    assert response.status_code == 404
