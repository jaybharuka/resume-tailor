"""resume_versions.session_id and tailoring_changes table

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-07

Note: adding a column with an inline ForeignKey via a plain `op.add_column` makes
Alembic try to issue a separate ALTER-ADD-CONSTRAINT statement on the new FK,
which SQLite does not support outside of Alembic's "batch mode" (copy-and-move)
strategy — it raises `NotImplementedError` even though SQLite's own
`ALTER TABLE ... ADD COLUMN ... REFERENCES ...` is otherwise fine. `PromptVersion`/
`LLMCall` (migration 0002) hit the same constraint-alteration limitation and that
migration test is Postgres-gated. To keep this migration test running against
SQLite as a plain, ungated test, `resume_versions.session_id` is added and the
FK is named + created via `op.batch_alter_table`, which Alembic can satisfy with
its copy-and-move strategy on SQLite (and executes as normal ALTER statements on
Postgres/other backends).
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("resume_versions") as batch_op:
        batch_op.add_column(sa.Column("session_id", sa.Integer, nullable=True))
        batch_op.create_foreign_key(
            "fk_resume_versions_session_id", "tailoring_sessions", ["session_id"], ["id"],
            ondelete="CASCADE",
        )
    op.create_table(
        "tailoring_changes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("resume_version_id", sa.Integer, sa.ForeignKey("resume_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_changed", sa.String, nullable=False),
        sa.Column("original_text", sa.Text, nullable=True),
        sa.Column("tailored_text", sa.Text, nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("tailoring_changes")
    with op.batch_alter_table("resume_versions") as batch_op:
        batch_op.drop_constraint("fk_resume_versions_session_id", type_="foreignkey")
        batch_op.drop_column("session_id")
