import pytest
from app.models.job_posting import (
    JobPostingDocument,
    CURRENT_JOB_POSTING_SCHEMA_VERSION,
    migrate_job_posting_document,
    UnsupportedJobPostingSchemaVersion,
)


def test_job_posting_document_defaults_to_current_schema_version():
    doc = JobPostingDocument(title="Senior Backend Engineer")
    assert doc.schema_version == CURRENT_JOB_POSTING_SCHEMA_VERSION
    assert doc.requirements == []
    assert doc.company is None


def test_job_posting_document_roundtrips_through_json():
    doc = JobPostingDocument(
        title="Senior Backend Engineer",
        company="Acme Corp",
        location="Remote (US)",
        employment_type="Full-time",
        requirements=["5+ years Python"],
        responsibilities=["Design backend services"],
        qualifications=["B.S. Computer Science"],
        keywords=["Python", "PostgreSQL"],
    )
    restored = JobPostingDocument.model_validate_json(doc.model_dump_json())
    assert restored == doc


def test_migrate_job_posting_document_accepts_current_version():
    raw = {"schema_version": 1, "title": "Barista"}
    doc = migrate_job_posting_document(raw)
    assert doc.title == "Barista"


def test_migrate_job_posting_document_rejects_unknown_future_version():
    raw = {"schema_version": 999, "title": "Barista"}
    with pytest.raises(UnsupportedJobPostingSchemaVersion):
        migrate_job_posting_document(raw)
