"""add published_at and feed/simhash indexes

Adds the publication timestamp reported by the source feed, so readers see when
a story was published rather than when it was ingested, plus the indexes that
back the feed listing and the near-duplicate lookup window.

Revision ID: c4a1e97b2d10
Revises: fd8bf26a231a
Create Date: 2026-09-05

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4a1e97b2d10"
down_revision: Union[str, None] = "fd8bf26a231a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_documents_published_at", "documents", ["published_at"], unique=False
    )

    # Every feed request filters on is_duplicate and orders by ingested_at
    # descending. A composite index covers that access path directly.
    op.create_index(
        "idx_documents_feed",
        "documents",
        ["is_duplicate", sa.text("ingested_at DESC")],
        unique=False,
    )

    # The deduplication engine loads a recent window keyed on simhash.
    op.create_index("idx_documents_simhash", "documents", ["simhash"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_documents_simhash", table_name="documents")
    op.drop_index("idx_documents_feed", table_name="documents")
    op.drop_index("ix_documents_published_at", table_name="documents")
    op.drop_column("documents", "published_at")
