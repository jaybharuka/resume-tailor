"""prompt_versions unique constraint and llm_calls RESTRICT policy

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-04

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("prompt_versions", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            "uq_prompt_versions_task_type_version", ["task_type", "version"]
        )

    with op.batch_alter_table("llm_calls", schema=None) as batch_op:
        batch_op.drop_column("prompt_version_id")
        batch_op.add_column(
            sa.Column("prompt_version_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "llm_calls_prompt_version_id_fkey", "prompt_versions",
            ["prompt_version_id"], ["id"], ondelete="RESTRICT",
        )


def downgrade():
    with op.batch_alter_table("llm_calls", schema=None) as batch_op:
        batch_op.drop_column("prompt_version_id")
        batch_op.add_column(
            sa.Column("prompt_version_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "llm_calls_prompt_version_id_fkey", "prompt_versions",
            ["prompt_version_id"], ["id"], ondelete="CASCADE",
        )

    with op.batch_alter_table("prompt_versions", schema=None) as batch_op:
        batch_op.drop_constraint("uq_prompt_versions_task_type_version", type_="unique")
