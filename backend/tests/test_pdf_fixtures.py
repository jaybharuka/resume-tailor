import pymupdf
from tests.fixtures.pdf_fixtures import (
    build_normal_resume_pdf,
    build_no_summary_resume_pdf,
    build_sparse_bullets_resume_pdf,
    build_missing_section_resume_pdf,
    build_blank_pdf,
)


def _extract_raw_text(pdf_bytes: bytes) -> str:
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        return "".join(page.get_text() for page in doc)


def test_build_normal_resume_pdf_contains_expected_content():
    text = _extract_raw_text(build_normal_resume_pdf())
    assert "Jane Doe" in text
    assert "Acme Corp" in text
    assert "Summary" in text


def test_build_no_summary_resume_pdf_has_no_summary_heading():
    text = _extract_raw_text(build_no_summary_resume_pdf())
    assert "John Smith" in text
    assert "Summary" not in text


def test_build_sparse_bullets_resume_pdf_has_minimal_bullets():
    text = _extract_raw_text(build_sparse_bullets_resume_pdf())
    assert "Alex Lee" in text
    assert "Worked on backend" in text


def test_build_missing_section_resume_pdf_has_no_projects_heading():
    text = _extract_raw_text(build_missing_section_resume_pdf())
    assert "Sam Rivera" in text
    assert "Projects" not in text


def test_build_blank_pdf_has_no_extractable_text():
    text = _extract_raw_text(build_blank_pdf())
    assert text.strip() == ""
