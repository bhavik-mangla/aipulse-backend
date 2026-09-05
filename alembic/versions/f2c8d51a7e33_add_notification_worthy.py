"""add notification_worthy

Marks the small number of stories that justify interrupting a reader, so the
app can send few, high-quality notifications rather than one per new article.

Revision ID: f2c8d51a7e33
Revises: e7b3f42c8a91
Create Date: 2026-09-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2c8d51a7e33"
down_revision: Union[str, None] = "e7b3f42c8a91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "notification_worthy",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # The digest reads only the worthy rows, which are a small minority, so a
    # partial index keeps it cheap.
    op.create_index(
        "idx_documents_notification_worthy",
        "documents",
        ["country", "ingested_at"],
        unique=False,
        postgresql_where=sa.text("notification_worthy"),
    )


def downgrade() -> None:
    op.drop_index("idx_documents_notification_worthy", table_name="documents")
    op.drop_column("documents", "notification_worthy")
