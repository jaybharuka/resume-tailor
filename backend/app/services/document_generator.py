import subprocess
import tempfile
from pathlib import Path
from sqlalchemy.orm import Session
from app.core.storage import Storage
from app.models.db_models import TailoringSession, ResumeVersion, GeneratedDocument
from app.services.latex_renderer import LatexRenderer
from app.services.errors import StageExecutionError

DOCUMENT_TYPE = "resume_pdf"
TECTONIC_TIMEOUT_SECONDS = 120


class DocumentGenerationError(StageExecutionError):
    """Raised when PDF generation fails: unmet tailoring_rewrite prerequisite,
    or a Tectonic compilation failure (malformed LaTeX, missing binary, or
    timeout)."""


def _compile_latex_to_pdf(tex_source: str) -> bytes:
    temp_dir = tempfile.mkdtemp()
    try:
        temp_path = Path(temp_dir)
        tex_path = temp_path / "resume.tex"
        tex_path.write_text(tex_source, encoding="utf-8")

        try:
            result = subprocess.run(
                ["tectonic", "resume.tex"],
                cwd=temp_dir, capture_output=True, timeout=TECTONIC_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            raise DocumentGenerationError(f"tectonic binary not found: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise DocumentGenerationError(
                f"tectonic compile timed out after {TECTONIC_TIMEOUT_SECONDS} seconds"
            ) from exc

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            raise DocumentGenerationError(f"tectonic compile failed: {stderr}")

        pdf_path = temp_path / "resume.pdf"
        return pdf_path.read_bytes()
    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


def _next_version_number(db: Session, session_id: int, document_type: str) -> int:
    latest = (
        db.query(GeneratedDocument)
        .filter_by(session_id=session_id, document_type=document_type)
        .order_by(GeneratedDocument.version_number.desc())
        .first()
    )
    return (latest.version_number if latest else 0) + 1


def generate_document(
    db: Session,
    session: TailoringSession,
    storage: Storage,
    latex_renderer: LatexRenderer,
    latex_compiler,
) -> GeneratedDocument:
    tailored_version = (
        db.query(ResumeVersion)
        .filter_by(session_id=session.id, produced_by_stage="tailoring_rewrite")
        .order_by(ResumeVersion.id.desc())
        .first()
    )
    if tailored_version is None:
        raise DocumentGenerationError("tailoring_rewrite has not succeeded for this session yet")

    tex_source = latex_renderer.render(tailored_version.resume_json)
    pdf_bytes = latex_compiler(tex_source)

    version_number = _next_version_number(db, session.id, DOCUMENT_TYPE)
    storage_key = f"generated_documents/{session.id}/{DOCUMENT_TYPE}_v{version_number}.pdf"
    storage_path = storage.save(storage_key, pdf_bytes)

    document = GeneratedDocument(
        session_id=session.id,
        resume_version_id=tailored_version.id,
        document_type=DOCUMENT_TYPE,
        storage_path=storage_path,
        content=None,
        version_number=version_number,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document
