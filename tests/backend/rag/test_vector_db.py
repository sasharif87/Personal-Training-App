import pytest
from unittest.mock import patch, MagicMock
from backend.rag.vector_db import VectorDB

class TestVectorDB:
    
    @pytest.fixture(scope="class")
    def vector_db():
        return VectorDB()
    
    @pytest.mark.parametrize("block_text, metadata, block_id", [
        ("Sample text 1", {"source": "training"}, "block1"),
        ("Another sample text", {"source": "testing"}, "block2")
    ])
    def test_add_historical_block(self, vector_db, block_text, metadata, block_id):
        vector_db.add_historical_block(block_text, metadata, block_id)
        collection = vector_db.chroma_client.get_or_create_collection("training_history")
        assert len(collection.get().ids) == 1
    
    @pytest.mark.parametrize("query_text, n_results", [
        ("Sample text 1", 2),
        ("Another sample text", 1)
    ])
    def test_retrieve_similar_blocks(self, vector_db, query_text, n_results):
        results = vector_db.retrieve_similar_blocks(query_text, n_results)
        assert len(results['documents']) <= n_results
    
    @pytest.mark.parametrize("query_text", [""])
    def test_retrieve_similar_blocks_empty_input(self, vector_db, query_text):
        with pytest.raises(Exception):
            vector_db.retrieve_similar_blocks(query_text)
    
    @pytest.mark.parametrize("query_text", [None])
    def test_retrieve_similar_blocks_none_input(self, vector_db, query_text):
        with pytest.raises(Exception):
            vector_db.retrieve_similar_blocks(query_text)
    
    @pytest.mark.parametrize("query_text", ["Non-existent text"])
    def test_retrieve_similar_blocks_zero_results(self, vector_db, query_text):
        results = vector_db.retrieve_similar_blocks(query_text)
        assert len(results['documents']) == 0
    
    @pytest.mark.parametrize("query_text", ["Sample text 1"])
    def test_retrieve_similar_blocks_negative_n_results(self, vector_db, query_text):
        with pytest.raises(Exception):
            vector_db.retrieve_similar_blocks(query_text, -1)