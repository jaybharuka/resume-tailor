"""prompt_versions unique constraint and llm_calls RESTRICT policy

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-04

"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_prompt_versions_task_type_version", "prompt_versions", ["task_type", "version"]
    )
    op.drop_constraint("llm_calls_prompt_version_id_fkey", "llm_calls", type_="foreignkey")
    op.create_foreign_key(
        "llm_calls_prompt_version_id_fkey", "llm_calls", "prompt_versions",
        ["prompt_version_id"], ["id"], ondelete="RESTRICT",
    )


def downgrade():
    op.drop_constraint("llm_calls_prompt_version_id_fkey", "llm_calls", type_="foreignkey")
    op.create_foreign_key(
        "llm_calls_prompt_version_id_fkey", "llm_calls", "prompt_versions",
        ["prompt_version_id"], ["id"], ondelete="CASCADE",
    )
    op.drop_constraint("uq_prompt_versions_task_type_version", "prompt_versions", type_="unique")
