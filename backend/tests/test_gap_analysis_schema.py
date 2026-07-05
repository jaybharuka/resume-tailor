import pytest
from app.models.gap_analysis import (
    GapAnalysisDocument,
    CURRENT_GAP_ANALYSIS_SCHEMA_VERSION,
    migrate_gap_analysis_document,
    UnsupportedGapAnalysisSchemaVersion,
)


def test_gap_analysis_document_defaults_to_current_schema_version():
    doc = GapAnalysisDocument()
    assert doc.schema_version == CURRENT_GAP_ANALYSIS_SCHEMA_VERSION
    assert doc.matching_skills == []
    assert doc.missing_skills == []
    assert doc.experience_gap_notes is None
    assert doc.relevant_projects == []
    assert doc.irrelevant_projects == []
    assert doc.recommended_keywords == []


def test_gap_analysis_document_roundtrips_through_json():
    doc = GapAnalysisDocument(
        matching_skills=["Python", "PostgreSQL"],
        missing_skills=["Docker", "Kubernetes"],
        experience_gap_notes="JD wants 5+ years; resume shows 3 years.",
        relevant_projects=["Inventory Tracker"],
        irrelevant_projects=["Weekend Recipe App"],
        recommended_keywords=["distributed systems"],
    )
    serialized = doc.model_dump_json()
    # Ledger item: confirm schema_version is genuinely present in the serialized
    # JSON, not silently dropped and merely coincidentally reconstructed via its
    # own default value on the restored side (which would make a naive
    # restored == doc comparison pass even if the field were never serialized).
    assert '"schema_version"' in serialized
    restored = GapAnalysisDocument.model_validate_json(serialized)
    assert restored == doc


def test_migrate_gap_analysis_document_accepts_current_version():
    raw = {"schema_version": 1, "matching_skills": ["Python"]}
    doc = migrate_gap_analysis_document(raw)
    assert doc.matching_skills == ["Python"]


def test_migrate_gap_analysis_document_rejects_unknown_future_version():
    raw = {"schema_version": 999, "matching_skills": ["Python"]}
    with pytest.raises(UnsupportedGapAnalysisSchemaVersion):
        migrate_gap_analysis_document(raw)
