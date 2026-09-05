"""add country scope to sources and documents

Adds the feed scope (world / in / us) a source and its documents belong to,
so readers can pick which feed they see.

Existing documents keep a NULL country. That is deliberate: they were ingested
before scopes existed, and the government notices among them should not appear
in any country feed. Feed queries always filter on country, so NULL rows are
excluded without deleting any data.

Revision ID: e7b3f42c8a91
Revises: c4a1e97b2d10
Create Date: 2026-09-06

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7b3f42c8a91"
down_revision: Union[str, None] = "c4a1e97b2d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("country", sa.String(length=10), nullable=True))
    op.execute("UPDATE sources SET country = 'world' WHERE country IS NULL")
    op.create_index("ix_sources_country", "sources", ["country"], unique=False)

    op.add_column("documents", sa.Column("country", sa.String(length=10), nullable=True))
    op.create_index("ix_documents_country", "documents", ["country"], unique=False)

    # Backfill the scope of documents from the three original Indian outlets,
    # so existing history stays readable in the India feed rather than
    # disappearing behind the country filter.
    op.execute(
        """
        UPDATE documents
           SET country = 'in'
         WHERE country IS NULL
           AND source_id IN ('et_top_stories', 'mint_top_stories', 'bs_top_stories')
        """
    )

    # Replace the feed index with one that leads on country, matching the
    # query shape now that every feed request is scoped.
    op.drop_index("idx_documents_feed", table_name="documents")
    op.create_index(
        "idx_documents_feed",
        "documents",
        ["country", "is_duplicate", sa.text("ingested_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_documents_feed", table_name="documents")
    op.create_index(
        "idx_documents_feed",
        "documents",
        ["is_duplicate", sa.text("ingested_at DESC")],
        unique=False,
    )
    op.drop_index("ix_documents_country", table_name="documents")
    op.drop_column("documents", "country")
    op.drop_index("ix_sources_country", table_name="sources")
    op.drop_column("sources", "country")
