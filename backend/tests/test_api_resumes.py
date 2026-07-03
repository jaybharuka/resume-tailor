import io


def test_upload_resume_saves_file_and_creates_row(client, tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))

    response = client.post(
        "/resumes",
        files={"file": ("jane.pdf", io.BytesIO(b"%PDF-1.4 fake content"), "application/pdf")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["original_filename"] == "jane.pdf"
    assert body["storage_path"].endswith("jane.pdf")
    assert (tmp_path / "resumes").exists()
