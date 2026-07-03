from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field

CURRENT_RESUME_SCHEMA_VERSION = 1


class ContactInfo(BaseModel):
    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    links: list[str] = Field(default_factory=list)


class WorkExperience(BaseModel):
    company: str
    title: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)


class Project(BaseModel):
    name: str
    description: Optional[str] = None
    bullets: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class Education(BaseModel):
    institution: str
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class ResumeDocument(BaseModel):
    schema_version: int = CURRENT_RESUME_SCHEMA_VERSION
    contact: ContactInfo
    summary: Optional[str] = None
    work_experience: list[WorkExperience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)


class UnsupportedResumeSchemaVersion(Exception):
    pass


def migrate_resume_document(data: dict) -> ResumeDocument:
    """Load a raw resume_json dict of any known schema_version into the current ResumeDocument shape.

    New migrators get registered here (e.g. an `if version == 1: ...` branch calling a
    `_migrate_v1_to_v2` helper) the first time schema_version is bumped past 1.
    """
    version = data.get("schema_version", CURRENT_RESUME_SCHEMA_VERSION)
    if version == CURRENT_RESUME_SCHEMA_VERSION:
        return ResumeDocument.model_validate(data)
    raise UnsupportedResumeSchemaVersion(
        f"No migrator registered for resume schema_version={version}"
    )
