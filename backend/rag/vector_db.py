# backend/rag/vector_db.py
"""
ChromaDB wrapper — stores and retrieves historical training blocks
for RAG-augmented LLM context.

Connects to the ChromaDB container (HttpClient) by default.
Falls back to local PersistentClient if the container is unavailable.
"""

import logging
import os
from typing import Any, Dict, List, Optional

import chromadb

logger = logging.getLogger(__name__)


class VectorDB:
    def __init__(self, persist_directory: str = "./chroma_db"):
        chroma_host = os.environ.get("CHROMADB_HOST", "")
        chroma_port = int(os.environ.get("CHROMADB_PORT", "8000"))

        if chroma_host:
            try:
                self._client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
                # Verify connectivity
                self._client.heartbeat()
                logger.info("ChromaDB connected via HTTP: %s:%d", chroma_host, chroma_port)
            except Exception as exc:
                logger.warning(
                    "ChromaDB HTTP connection failed (%s:%d): %s — falling back to local storage",
                    chroma_host, chroma_port, exc,
                )
                self._client = chromadb.PersistentClient(path=persist_directory)
        else:
            self._client = chromadb.PersistentClient(path=persist_directory)
            logger.info("ChromaDB using local storage: %s", persist_directory)

        self._collection = self._client.get_or_create_collection("training_blocks")

    def store_block(self, block_id: str, text: str, metadata: Optional[Dict] = None) -> None:
        self._collection.upsert(
            ids=[block_id],
            documents=[text],
            metadatas=[metadata or {}],
        )

    def retrieve_similar_blocks(self, query: str, n_results: int = 3) -> List[Dict[str, Any]]:
        results = self._collection.query(
            query_texts=[query],
            n_results=n_results,
        )
        blocks = []
        for i, doc in enumerate(results.get("documents", [[]])[0]):
            meta = results.get("metadatas", [[]])[0][i] if results.get("metadatas") else {}
            blocks.append({"document": doc, "metadata": meta})
        return blocks

    def count(self) -> int:
        return self._collection.count()

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    db = VectorDB()
    print("Vector storage initialized.")
