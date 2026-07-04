from tests.fixtures.jd_fixtures import (
    complete_jd_text,
    no_requirements_header_jd_text,
    blurred_requirements_qualifications_jd_text,
    terse_jd_text,
    not_a_job_posting_text,
)


def test_complete_jd_text_has_distinct_requirements_and_qualifications_sections():
    text = complete_jd_text()
    assert "Requirements:" in text
    assert "Qualifications:" in text
    assert "Acme Corp" in text


def test_no_requirements_header_jd_text_has_no_requirements_label():
    text = no_requirements_header_jd_text()
    assert "Requirements:" not in text
    assert "Marketing Coordinator" in text


def test_blurred_requirements_qualifications_jd_text_has_no_qualifications_label():
    text = blurred_requirements_qualifications_jd_text()
    assert "Qualifications:" not in text
    assert "Must-haves:" in text


def test_terse_jd_text_is_short():
    text = terse_jd_text()
    assert len(text) < 100
    assert "Barista" in text


def test_not_a_job_posting_text_contains_no_job_posting_markers():
    text = not_a_job_posting_text()
    assert "Requirements" not in text
    assert "Responsibilities" not in text
