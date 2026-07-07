import pytest
from pydantic import ValidationError
from app.models.interview_questions import (
    InterviewQuestionsDocument,
    CURRENT_INTERVIEW_QUESTIONS_SCHEMA_VERSION,
    migrate_interview_questions_document,
    UnsupportedInterviewQuestionsSchemaVersion,
)


def test_interview_questions_document_defaults_to_current_schema_version():
    doc = InterviewQuestionsDocument(questions=["Q1?", "Q2?", "Q3?", "Q4?", "Q5?"])
    assert doc.schema_version == CURRENT_INTERVIEW_QUESTIONS_SCHEMA_VERSION
    assert len(doc.questions) == 5


def test_interview_questions_document_rejects_fewer_than_five_questions():
    """Structural-validation guard (spec §3, §7): min_length=5 is the entire
    guard for this document type - this proves it's actually enforced by
    Pydantic at construction time, not merely documented."""
    with pytest.raises(ValidationError):
        InterviewQuestionsDocument(questions=["Q1?", "Q2?", "Q3?", "Q4?"])


def test_interview_questions_document_roundtrips_through_json():
    doc = InterviewQuestionsDocument(questions=["Q1?", "Q2?", "Q3?", "Q4?", "Q5?"])
    serialized = doc.model_dump_json()
    assert '"schema_version"' in serialized
    restored = InterviewQuestionsDocument.model_validate_json(serialized)
    assert restored == doc


def test_migrate_interview_questions_document_accepts_current_version():
    raw = {"schema_version": 1, "questions": ["Q1?", "Q2?", "Q3?", "Q4?", "Q5?"]}
    doc = migrate_interview_questions_document(raw)
    assert len(doc.questions) == 5


def test_migrate_interview_questions_document_rejects_unknown_future_version():
    raw = {"schema_version": 999, "questions": ["Q1?", "Q2?", "Q3?", "Q4?", "Q5?"]}
    with pytest.raises(UnsupportedInterviewQuestionsSchemaVersion):
        migrate_interview_questions_document(raw)
