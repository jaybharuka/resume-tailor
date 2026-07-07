from __future__ import annotations
from pydantic import BaseModel, Field

CURRENT_INTERVIEW_QUESTIONS_SCHEMA_VERSION = 1


class InterviewQuestionsDocument(BaseModel):
    schema_version: int = CURRENT_INTERVIEW_QUESTIONS_SCHEMA_VERSION
    questions: list[str] = Field(min_length=5)


class UnsupportedInterviewQuestionsSchemaVersion(Exception):
    pass


def migrate_interview_questions_document(data: dict) -> InterviewQuestionsDocument:
    """Load a raw generated_documents.content dict of any known schema_version
    into the current InterviewQuestionsDocument shape. New migrators get
    registered here the first time schema_version is bumped past 1 - mirrors
    app/models/gap_analysis.py's migrate_gap_analysis_document."""
    version = data.get("schema_version", CURRENT_INTERVIEW_QUESTIONS_SCHEMA_VERSION)
    if version == CURRENT_INTERVIEW_QUESTIONS_SCHEMA_VERSION:
        return InterviewQuestionsDocument.model_validate(data)
    raise UnsupportedInterviewQuestionsSchemaVersion(
        f"No migrator registered for interview questions schema_version={version}"
    )
