from __future__ import annotations
from pydantic import BaseModel

CURRENT_COVER_LETTER_SCHEMA_VERSION = 1


class CoverLetterDocument(BaseModel):
    schema_version: int = CURRENT_COVER_LETTER_SCHEMA_VERSION
    body: str


class UnsupportedCoverLetterSchemaVersion(Exception):
    pass


def migrate_cover_letter_document(data: dict) -> CoverLetterDocument:
    """Load a raw generated_documents.content dict of any known schema_version
    into the current CoverLetterDocument shape. New migrators get registered
    here the first time schema_version is bumped past 1 - mirrors
    app/models/gap_analysis.py's migrate_gap_analysis_document."""
    version = data.get("schema_version", CURRENT_COVER_LETTER_SCHEMA_VERSION)
    if version == CURRENT_COVER_LETTER_SCHEMA_VERSION:
        return CoverLetterDocument.model_validate(data)
    raise UnsupportedCoverLetterSchemaVersion(
        f"No migrator registered for cover letter schema_version={version}"
    )
