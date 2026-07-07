import pytest
from app.models.cover_letter import (
    CoverLetterDocument,
    CURRENT_COVER_LETTER_SCHEMA_VERSION,
    migrate_cover_letter_document,
    UnsupportedCoverLetterSchemaVersion,
)


def test_cover_letter_document_defaults_to_current_schema_version():
    doc = CoverLetterDocument(body="Dear Hiring Manager, ...")
    assert doc.schema_version == CURRENT_COVER_LETTER_SCHEMA_VERSION
    assert doc.body == "Dear Hiring Manager, ..."


def test_cover_letter_document_roundtrips_through_json():
    doc = CoverLetterDocument(body="Dear Hiring Manager, I am writing to apply.")
    serialized = doc.model_dump_json()
    assert '"schema_version"' in serialized
    restored = CoverLetterDocument.model_validate_json(serialized)
    assert restored == doc


def test_migrate_cover_letter_document_accepts_current_version():
    raw = {"schema_version": 1, "body": "Dear Hiring Manager, ..."}
    doc = migrate_cover_letter_document(raw)
    assert doc.body == "Dear Hiring Manager, ..."


def test_migrate_cover_letter_document_rejects_unknown_future_version():
    raw = {"schema_version": 999, "body": "..."}
    with pytest.raises(UnsupportedCoverLetterSchemaVersion):
        migrate_cover_letter_document(raw)
