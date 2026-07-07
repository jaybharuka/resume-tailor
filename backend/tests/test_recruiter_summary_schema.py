import pytest
from app.models.recruiter_summary import (
    RecruiterSummaryDocument,
    CURRENT_RECRUITER_SUMMARY_SCHEMA_VERSION,
    migrate_recruiter_summary_document,
    UnsupportedRecruiterSummarySchemaVersion,
)


def test_recruiter_summary_document_defaults_to_current_schema_version():
    doc = RecruiterSummaryDocument(body="A strong backend candidate with...")
    assert doc.schema_version == CURRENT_RECRUITER_SUMMARY_SCHEMA_VERSION
    assert doc.body == "A strong backend candidate with..."


def test_recruiter_summary_document_roundtrips_through_json():
    doc = RecruiterSummaryDocument(body="A strong backend candidate.")
    serialized = doc.model_dump_json()
    assert '"schema_version"' in serialized
    restored = RecruiterSummaryDocument.model_validate_json(serialized)
    assert restored == doc


def test_migrate_recruiter_summary_document_accepts_current_version():
    raw = {"schema_version": 1, "body": "A strong backend candidate."}
    doc = migrate_recruiter_summary_document(raw)
    assert doc.body == "A strong backend candidate."


def test_migrate_recruiter_summary_document_rejects_unknown_future_version():
    raw = {"schema_version": 999, "body": "..."}
    with pytest.raises(UnsupportedRecruiterSummarySchemaVersion):
        migrate_recruiter_summary_document(raw)
