import pytest
from app.models.resume import (
    ResumeDocument,
    ContactInfo,
    CURRENT_RESUME_SCHEMA_VERSION,
    migrate_resume_document,
    UnsupportedResumeSchemaVersion,
)


def test_resume_document_defaults_to_current_schema_version():
    doc = ResumeDocument(contact=ContactInfo(full_name="Jane Doe"))
    assert doc.schema_version == CURRENT_RESUME_SCHEMA_VERSION
    assert doc.work_experience == []


def test_resume_document_roundtrips_through_json():
    doc = ResumeDocument(
        contact=ContactInfo(full_name="Jane Doe", email="jane@example.com"),
        summary="Backend engineer",
        skills=["Python", "FastAPI"],
    )
    restored = ResumeDocument.model_validate_json(doc.model_dump_json())
    assert restored == doc


def test_migrate_resume_document_accepts_current_version():
    raw = {"schema_version": 1, "contact": {"full_name": "Jane Doe"}}
    doc = migrate_resume_document(raw)
    assert doc.contact.full_name == "Jane Doe"


def test_migrate_resume_document_rejects_unknown_future_version():
    raw = {"schema_version": 999, "contact": {"full_name": "Jane Doe"}}
    with pytest.raises(UnsupportedResumeSchemaVersion):
        migrate_resume_document(raw)
