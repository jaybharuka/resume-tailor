import shutil
import pytest
from app.core.db import make_engine, make_session_factory
from app.core.storage import LocalDiskStorage
from app.models.db_models import Base, Resume, ResumeVersion, JobPosting, TailoringSession, GeneratedDocument
from app.services.document_generator import generate_document, _compile_latex_to_pdf, DocumentGenerationError
from app.services.latex_renderer import LatexRenderer

TECTONIC_AVAILABLE = shutil.which("tectonic") is not None


class FakeLatexCompiler:
    def __init__(self, pdf_bytes=None, error=None):
        self._pdf_bytes = pdf_bytes if pdf_bytes is not None else b"%PDF-1.4 fake pdf bytes"
        self._error = error
        self.calls = []

    def __call__(self, tex_source: str) -> bytes:
        self.calls.append(tex_source)
        if self._error is not None:
            raise self._error
        return self._pdf_bytes


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


def test_generate_document_persists_pdf_and_links_ids(tmp_path):
    db = _make_db()
    session, tailored_version = _make_session_with_tailored_version(db)
    storage = LocalDiskStorage(root=str(tmp_path))
    latex_renderer = LatexRenderer(templates_root="latex_templates")
    latex_compiler = FakeLatexCompiler()

    document = generate_document(db, session, storage, latex_renderer, latex_compiler)

    assert document.session_id == session.id
    assert document.resume_version_id == tailored_version.id
    assert document.document_type == "resume_pdf"
    assert document.version_number == 1
    assert document.content is None
    assert db.query(GeneratedDocument).count() == 1

    from pathlib import Path
    assert Path(document.storage_path).read_bytes() == b"%PDF-1.4 fake pdf bytes"


def test_generate_document_fails_fast_when_no_tailored_version_without_compiling(tmp_path):
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    storage = LocalDiskStorage(root=str(tmp_path))
    latex_renderer = LatexRenderer(templates_root="latex_templates")
    latex_compiler = FakeLatexCompiler()

    with pytest.raises(DocumentGenerationError, match="tailoring_rewrite"):
        generate_document(db, session, storage, latex_renderer, latex_compiler)

    assert latex_compiler.calls == []


def test_generate_document_wraps_compiler_error(tmp_path):
    db = _make_db()
    session, tailored_version = _make_session_with_tailored_version(db)
    storage = LocalDiskStorage(root=str(tmp_path))
    latex_renderer = LatexRenderer(templates_root="latex_templates")
    latex_compiler = FakeLatexCompiler(error=DocumentGenerationError("tectonic compile failed: mock error"))

    with pytest.raises(DocumentGenerationError):
        generate_document(db, session, storage, latex_renderer, latex_compiler)

    assert db.query(GeneratedDocument).count() == 0


def test_generate_document_version_numbering_increments_within_session(tmp_path):
    db = _make_db()
    session, tailored_version = _make_session_with_tailored_version(db)
    storage = LocalDiskStorage(root=str(tmp_path))
    latex_renderer = LatexRenderer(templates_root="latex_templates")
    latex_compiler = FakeLatexCompiler()

    first_document = generate_document(db, session, storage, latex_renderer, latex_compiler)
    second_document = generate_document(db, session, storage, latex_renderer, latex_compiler)

    assert first_document.version_number == 1
    assert second_document.version_number == 2


@pytest.mark.skipif(
    not TECTONIC_AVAILABLE,
    reason="requires the tectonic binary on PATH - see README for install instructions",
)
def test_compile_latex_to_pdf_produces_a_valid_pdf():
    tex_source = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "Hello, world.\n"
        "\\end{document}\n"
    )

    pdf_bytes = _compile_latex_to_pdf(tex_source)

    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 500
