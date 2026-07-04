from app.services.pdf_extractor import extract_text_from_pdf, has_extractable_text
from tests.fixtures.pdf_fixtures import build_normal_resume_pdf, build_blank_pdf


def test_extract_text_from_pdf_returns_resume_content():
    text = extract_text_from_pdf(build_normal_resume_pdf())
    assert "Jane Doe" in text
    assert "Acme Corp" in text


def test_extract_text_from_pdf_returns_near_empty_for_blank_pdf():
    text = extract_text_from_pdf(build_blank_pdf())
    assert text.strip() == ""


def test_has_extractable_text_true_for_real_content():
    assert has_extractable_text("Jane Doe\nSenior Backend Engineer\n" * 3) is True


def test_has_extractable_text_false_for_near_empty_string():
    assert has_extractable_text("   \n  ") is False
    assert has_extractable_text("") is False


def test_has_extractable_text_boundary_at_min_length():
    """Coverage-only addition (ledger item, not a bug fix) — MIN_EXTRACTED_TEXT_LENGTH
    is 20; confirm the boundary is inclusive on the low side."""
    assert has_extractable_text("a" * 19) is False
    assert has_extractable_text("a" * 20) is True
    assert has_extractable_text("a" * 21) is True
