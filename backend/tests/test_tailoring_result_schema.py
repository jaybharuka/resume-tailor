import pytest
from app.models.resume import ResumeDocument, ContactInfo
from app.models.tailoring_result import (
    TailoringResult,
    TailoringChangeRecord,
    CURRENT_TAILORING_RESULT_SCHEMA_VERSION,
    migrate_tailoring_result,
    UnsupportedTailoringResultSchemaVersion,
)


def _minimal_resume() -> ResumeDocument:
    return ResumeDocument(contact=ContactInfo(full_name="Jane Doe"))


def test_tailoring_result_defaults_to_current_schema_version():
    result = TailoringResult(tailored_resume=_minimal_resume())
    assert result.schema_version == CURRENT_TAILORING_RESULT_SCHEMA_VERSION
    assert result.changes == []


def test_tailoring_change_record_allows_null_original_text():
    record = TailoringChangeRecord(
        field_changed="summary", tailored_text="Rewritten summary.",
        rationale="Emphasized backend experience.",
    )
    assert record.original_text is None


def test_tailoring_result_roundtrips_through_json():
    result = TailoringResult(
        tailored_resume=_minimal_resume(),
        changes=[
            TailoringChangeRecord(
                field_changed='projects["Inventory Tracker"].bullets[0]',
                original_text="Worked on a project.",
                tailored_text="Built an inventory tracking system used by 3 teams.",
                rationale="Incorporated recommended keyword 'inventory' and strengthened the verb.",
            ),
        ],
    )
    restored = TailoringResult.model_validate_json(result.model_dump_json())
    assert restored == result


def test_migrate_tailoring_result_accepts_current_version():
    raw = {"schema_version": 1, "tailored_resume": _minimal_resume().model_dump(), "changes": []}
    result = migrate_tailoring_result(raw)
    assert result.changes == []


def test_migrate_tailoring_result_rejects_unknown_future_version():
    raw = {"schema_version": 999, "tailored_resume": _minimal_resume().model_dump(), "changes": []}
    with pytest.raises(UnsupportedTailoringResultSchemaVersion):
        migrate_tailoring_result(raw)
