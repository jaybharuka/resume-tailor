from __future__ import annotations
from pydantic import BaseModel

CURRENT_RECRUITER_SUMMARY_SCHEMA_VERSION = 1


class RecruiterSummaryDocument(BaseModel):
    schema_version: int = CURRENT_RECRUITER_SUMMARY_SCHEMA_VERSION
    body: str


class UnsupportedRecruiterSummarySchemaVersion(Exception):
    pass


def migrate_recruiter_summary_document(data: dict) -> RecruiterSummaryDocument:
    """Load a raw generated_documents.content dict of any known schema_version
    into the current RecruiterSummaryDocument shape. New migrators get
    registered here the first time schema_version is bumped past 1 - mirrors
    app/models/gap_analysis.py's migrate_gap_analysis_document."""
    version = data.get("schema_version", CURRENT_RECRUITER_SUMMARY_SCHEMA_VERSION)
    if version == CURRENT_RECRUITER_SUMMARY_SCHEMA_VERSION:
        return RecruiterSummaryDocument.model_validate(data)
    raise UnsupportedRecruiterSummarySchemaVersion(
        f"No migrator registered for recruiter summary schema_version={version}"
    )
