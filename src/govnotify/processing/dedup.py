"""
Deduplication engine - multi-layer duplicate detection.
"""
import hashlib
import structlog
from datasketch import MinHash, MinHashLSH
from govnotify.models.source import RawDocument

logger = structlog.get_logger(__name__)


class DeduplicationEngine:
    """
    Handles exact and near-duplicate detection.
    Layer 1: Exact SHA-256 hash
    Layer 1.5: Title + Source match (catches OCR variations)
    Layer 2: MinHash LSH (near-duplicate)
    """

    def __init__(self, threshold: float = 0.85, num_perm: int = 128) -> None:
        self.threshold = threshold
        self.num_perm = num_perm
        self.lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        self.hash_to_id: dict[str, str] = {}

    def register_hash(self, content_hash: str, document_id: str) -> None:
        self.hash_to_id[content_hash] = document_id

    def compute_exact_hash(self, text: str) -> str:
        normalized = " ".join(text.lower().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def compute_minhash(self, text: str) -> MinHash:
        m = MinHash(num_perm=self.num_perm)
        words = text.lower().split()
        for i in range(len(words) - 2):
            shingle = " ".join(words[i : i + 3])
            m.update(shingle.encode("utf-8"))
        return m

    def register_minhash(self, document_id: str, text: str) -> None:
        minhash = self.compute_minhash(text)
        try:
            self.lsh.insert(document_id, minhash)
        except ValueError:
            pass

    async def is_duplicate(self, doc: RawDocument, session=None) -> tuple[bool, str | None]:
        """Check Layer 1 (Hash), Layer 1.5 (Title), and Layer 2 (MinHash)."""
        # Layer 0: Memory Hash
        if doc.content_hash in self.hash_to_id:
            return True, self.hash_to_id[doc.content_hash]

        if session:
            from sqlalchemy import select
            from govnotify.storage.postgres import DocumentORM
            
            # Layer 1: DB Hash
            stmt = select(DocumentORM.id).where(DocumentORM.content_hash == doc.content_hash).limit(1)
            res = await session.execute(stmt)
            existing_id = res.scalar_one_or_none()
            if existing_id:
                return True, str(existing_id)

            # Layer 1.5: Title + Source (catches OCR variations)
            if doc.title and len(doc.title) > 10:
                stmt = select(DocumentORM.id).where(
                    DocumentORM.title == doc.title,
                    DocumentORM.source_id == doc.source_id
                ).limit(1)
                res = await session.execute(stmt)
                existing_id = res.scalar_one_or_none()
                if existing_id:
                    return True, str(existing_id)

        # Layer 2: MinHash LSH
        minhash = self.compute_minhash(doc.raw_content)
        similar_ids = self.lsh.query(minhash)
        if similar_ids:
            return True, similar_ids[0]

        return False, None

    def clear(self) -> None:
        self.lsh = MinHashLSH(threshold=self.threshold, num_perm=self.num_perm)
        self.hash_to_id = {}
