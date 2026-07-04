from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field

CURRENT_JOB_POSTING_SCHEMA_VERSION = 1


class JobPostingDocument(BaseModel):
    schema_version: int = CURRENT_JOB_POSTING_SCHEMA_VERSION
    title: str
    company: Optional[str] = None
    location: Optional[str] = None
    employment_type: Optional[str] = None
    requirements: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class UnsupportedJobPostingSchemaVersion(Exception):
    pass


def migrate_job_posting_document(data: dict) -> JobPostingDocument:
    """Load a raw parsed_json dict of any known schema_version into the current
    JobPostingDocument shape.

    New migrators get registered here (e.g. an `if version == 1: ...` branch
    calling a `_migrate_v1_to_v2` helper) the first time schema_version is
    bumped past 1 — mirrors `app/models/resume.py`'s `migrate_resume_document`.
    """
    version = data.get("schema_version", CURRENT_JOB_POSTING_SCHEMA_VERSION)
    if version == CURRENT_JOB_POSTING_SCHEMA_VERSION:
        return JobPostingDocument.model_validate(data)
    raise UnsupportedJobPostingSchemaVersion(
        f"No migrator registered for job posting schema_version={version}"
    )
