from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field
from app.models.resume import ResumeDocument

CURRENT_TAILORING_RESULT_SCHEMA_VERSION = 1


class TailoringChangeRecord(BaseModel):
    field_changed: str
    original_text: Optional[str] = None
    tailored_text: str
    rationale: str


class TailoringResult(BaseModel):
    schema_version: int = CURRENT_TAILORING_RESULT_SCHEMA_VERSION
    tailored_resume: ResumeDocument
    changes: list[TailoringChangeRecord] = Field(default_factory=list)


class UnsupportedTailoringResultSchemaVersion(Exception):
    pass


def migrate_tailoring_result(data: dict) -> TailoringResult:
    """Load a raw dict of any known schema_version into the current TailoringResult
    shape. New migrators get registered here the first time schema_version is
    bumped past 1 — mirrors app/models/resume.py's migrate_resume_document.
    """
    version = data.get("schema_version", CURRENT_TAILORING_RESULT_SCHEMA_VERSION)
    if version == CURRENT_TAILORING_RESULT_SCHEMA_VERSION:
        return TailoringResult.model_validate(data)
    raise UnsupportedTailoringResultSchemaVersion(
        f"No migrator registered for tailoring result schema_version={version}"
    )
