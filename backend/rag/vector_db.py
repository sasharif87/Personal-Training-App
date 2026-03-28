import chromadb
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Any

class VectorDB:
    def __init__(self, persist_directory="./chroma_db"):
        self.chroma_client = chromadb.PersistentClient(path=persist_directory)
        self.collection = self.chroma_client.get_or_create_collection(name="training_history")
        self.encoder = SentenceTransformer('all-MiniLM-L6-v2')

    def add_historical_block(self, block_text: str, metadata: Dict[str, Any], block_id: str):
        embedding = self.encoder.encode(block_text).tolist()
        self.collection.add(
            documents=[block_text],
            embeddings=[embedding],
            metadatas=[metadata],
            ids=[block_id]
        )

    def retrieve_similar_blocks(self, query_text: str, n_results: int = 3) -> List[Dict[str, Any]]:
        query_embedding = self.encoder.encode(query_text).tolist()
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results
        )
        return results
        
if __name__ == "__main__":
    db = VectorDB()
    print("Vector storage initialized.")
