"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-03

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "resumes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("original_filename", sa.String, nullable=False),
        sa.Column("storage_path", sa.String, nullable=False),
        sa.Column("raw_text", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "job_postings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("source_url", sa.String, nullable=True),
        sa.Column("source_provider", sa.String, nullable=True),
        sa.Column("raw_text", sa.Text, nullable=True),
        sa.Column("parsed_json", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "resume_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("resume_id", sa.Integer, sa.ForeignKey("resumes.id"), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("resume_json", sa.JSON, nullable=False),
        sa.Column("produced_by_stage", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "tailoring_sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("resume_id", sa.Integer, sa.ForeignKey("resumes.id"), nullable=False),
        sa.Column("job_posting_id", sa.Integer, sa.ForeignKey("job_postings.id"), nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("tailoring_sessions.id"), nullable=False),
        sa.Column("stage_name", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
    )

    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("tailoring_sessions.id"), nullable=False),
        sa.Column("resume_version_id", sa.Integer, sa.ForeignKey("resume_versions.id"), nullable=False),
        sa.Column("overall_score", sa.Float, nullable=True),
        sa.Column("open_source_score", sa.Float, nullable=True),
        sa.Column("projects_score", sa.Float, nullable=True),
        sa.Column("production_score", sa.Float, nullable=True),
        sa.Column("technical_skills_score", sa.Float, nullable=True),
        sa.Column("raw_response_json", sa.JSON, nullable=False),
        sa.Column("rubric_version", sa.String, nullable=True),
        sa.Column("hiring_agent_service_version", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "generated_documents",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("tailoring_sessions.id"), nullable=False),
        sa.Column("document_type", sa.String, nullable=False),
        sa.Column("storage_path", sa.String, nullable=True),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("task_type", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("version", sa.String, nullable=False),
        sa.Column("template_path", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.Integer, sa.ForeignKey("tailoring_sessions.id"), nullable=True),
        sa.Column("prompt_version_id", sa.Integer, sa.ForeignKey("prompt_versions.id"), nullable=True),
        sa.Column("provider", sa.String, nullable=False),
        sa.Column("model", sa.String, nullable=False),
        sa.Column("task_type", sa.String, nullable=False),
        sa.Column("temperature", sa.Float, nullable=True),
        sa.Column("request_payload", sa.JSON, nullable=True),
        sa.Column("response_payload", sa.JSON, nullable=True),
        sa.Column("validated", sa.Boolean, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("llm_calls")
    op.drop_table("prompt_versions")
    op.drop_table("generated_documents")
    op.drop_table("evaluation_runs")
    op.drop_table("pipeline_runs")
    op.drop_table("tailoring_sessions")
    op.drop_table("resume_versions")
    op.drop_table("job_postings")
    op.drop_table("resumes")
