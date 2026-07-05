from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, JSON, Boolean, Float, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Resume(Base):
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True)
    original_filename = Column(String, nullable=False)
    storage_path = Column(String, nullable=False)
    raw_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    versions = relationship("ResumeVersion", back_populates="resume", passive_deletes=True)


class ResumeVersion(Base):
    __tablename__ = "resume_versions"

    id = Column(Integer, primary_key=True)
    resume_id = Column(Integer, ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    session_id = Column(Integer, ForeignKey("tailoring_sessions.id", ondelete="CASCADE"), nullable=True)
    version_number = Column(Integer, nullable=False)
    resume_json = Column(JSON, nullable=False)
    produced_by_stage = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    resume = relationship("Resume", back_populates="versions")


class JobPosting(Base):
    __tablename__ = "job_postings"

    id = Column(Integer, primary_key=True)
    source_url = Column(String, nullable=True)
    source_provider = Column(String, nullable=True)
    raw_text = Column(Text, nullable=True)
    parsed_json = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


class TailoringSession(Base):
    __tablename__ = "tailoring_sessions"

    id = Column(Integer, primary_key=True)
    resume_id = Column(Integer, ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    job_posting_id = Column(Integer, ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False, default="created")
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("tailoring_sessions.id", ondelete="CASCADE"), nullable=False)
    stage_name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("tailoring_sessions.id", ondelete="CASCADE"), nullable=False)
    resume_version_id = Column(Integer, ForeignKey("resume_versions.id", ondelete="CASCADE"), nullable=False)
    overall_score = Column(Float, nullable=True)
    open_source_score = Column(Float, nullable=True)
    projects_score = Column(Float, nullable=True)
    production_score = Column(Float, nullable=True)
    technical_skills_score = Column(Float, nullable=True)
    raw_response_json = Column(JSON, nullable=False)
    rubric_version = Column(String, nullable=True)
    hiring_agent_service_version = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


class GeneratedDocument(Base):
    __tablename__ = "generated_documents"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("tailoring_sessions.id", ondelete="CASCADE"), nullable=False)
    document_type = Column(String, nullable=False)
    storage_path = Column(String, nullable=True)
    content = Column(Text, nullable=True)
    version_number = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("task_type", "version", name="uq_prompt_versions_task_type_version"),
    )

    id = Column(Integer, primary_key=True)
    task_type = Column(String, nullable=False)
    name = Column(String, nullable=False)
    version = Column(String, nullable=False)
    template_path = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("tailoring_sessions.id", ondelete="CASCADE"), nullable=True)
    prompt_version_id = Column(Integer, ForeignKey("prompt_versions.id", ondelete="RESTRICT"), nullable=True)
    provider = Column(String, nullable=False)
    model = Column(String, nullable=False)
    task_type = Column(String, nullable=False)
    temperature = Column(Float, nullable=True)
    request_payload = Column(JSON, nullable=True)
    response_payload = Column(JSON, nullable=True)
    validated = Column(Boolean, nullable=False, default=False)
    latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


class GapAnalysis(Base):
    __tablename__ = "gap_analyses"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("tailoring_sessions.id", ondelete="CASCADE"), nullable=False)
    resume_version_id = Column(Integer, ForeignKey("resume_versions.id", ondelete="CASCADE"), nullable=False)
    job_posting_id = Column(Integer, ForeignKey("job_postings.id", ondelete="CASCADE"), nullable=False)
    analysis_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


class TailoringChange(Base):
    __tablename__ = "tailoring_changes"

    id = Column(Integer, primary_key=True)
    resume_version_id = Column(Integer, ForeignKey("resume_versions.id", ondelete="CASCADE"), nullable=False)
    field_changed = Column(String, nullable=False)
    original_text = Column(Text, nullable=True)
    tailored_text = Column(Text, nullable=False)
    rationale = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
