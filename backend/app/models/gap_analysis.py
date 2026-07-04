from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field

CURRENT_GAP_ANALYSIS_SCHEMA_VERSION = 1


class GapAnalysisDocument(BaseModel):
    schema_version: int = CURRENT_GAP_ANALYSIS_SCHEMA_VERSION
    matching_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    experience_gap_notes: Optional[str] = None
    relevant_projects: list[str] = Field(default_factory=list)
    irrelevant_projects: list[str] = Field(default_factory=list)
    recommended_keywords: list[str] = Field(default_factory=list)


class UnsupportedGapAnalysisSchemaVersion(Exception):
    pass


def migrate_gap_analysis_document(data: dict) -> GapAnalysisDocument:
    """Load a raw analysis_json dict of any known schema_version into the current
    GapAnalysisDocument shape.

    New migrators get registered here the first time schema_version is bumped
    past 1 — mirrors `app/models/resume.py`'s `migrate_resume_document` and
    `app/models/job_posting.py`'s `migrate_job_posting_document`.
    """
    version = data.get("schema_version", CURRENT_GAP_ANALYSIS_SCHEMA_VERSION)
    if version == CURRENT_GAP_ANALYSIS_SCHEMA_VERSION:
        return GapAnalysisDocument.model_validate(data)
    raise UnsupportedGapAnalysisSchemaVersion(
        f"No migrator registered for gap analysis schema_version={version}"
    )
