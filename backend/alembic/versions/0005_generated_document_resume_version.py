"""generated_documents.resume_version_id

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-09

Note: see migration 0004's docstring for why a plain op.add_column with an
inline ForeignKey fails on SQLite outside batch mode - the same reasoning
applies here, so this column and its FK are added via op.batch_alter_table.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("generated_documents") as batch_op:
        batch_op.add_column(sa.Column("resume_version_id", sa.Integer, nullable=True))
        batch_op.create_foreign_key(
            "fk_generated_documents_resume_version_id", "resume_versions", ["resume_version_id"], ["id"],
            ondelete="CASCADE",
        )


def downgrade():
    with op.batch_alter_table("generated_documents") as batch_op:
        batch_op.drop_constraint("fk_generated_documents_resume_version_id", type_="foreignkey")
        batch_op.drop_column("resume_version_id")
