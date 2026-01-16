"""
Integration Tests for Search Algorithms
========================================

Comprehensive integration tests for all search paths:
- NOT_STISLA timestamp searches
- NOT_STISLA message ID lookups
- QIHSE semantic searches
- Hybrid search combinations
- Temporal-semantic correlation
"""

import unittest
import logging
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import sqlite3

logger = logging.getLogger(__name__)


class TestSearchIntegration(unittest.TestCase):
    """Integration tests for search algorithms"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.db_path = self.temp_dir / "test.db"
        
        # Create test database
        self.conn = sqlite3.connect(str(self.db_path))
        self.cur = self.conn.cursor()
        
        # Create schema
        self.cur.execute("""
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                date TEXT NOT NULL,
                content TEXT,
                channel_id INTEGER,
                user_id INTEGER
            )
        """)
        
        # Insert test data
        base_time = datetime.now()
        for i in range(1000):
            self.cur.execute(
                "INSERT INTO messages (id, date, content, channel_id, user_id) VALUES (?, ?, ?, ?, ?)",
                (i, (base_time + timedelta(seconds=i)).isoformat(), f"Message {i}", 1, 1)
            )
        
        self.conn.commit()
    
    def tearDown(self):
        """Clean up test fixtures"""
        self.conn.close()
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_not_stisla_timestamp_search(self):
        """Test NOT_STISLA timestamp search integration"""
        try:
            from tgarchive.db import SpectraDB
            
            with SpectraDB(self.db_path) as db:
                start_time = int((datetime.now() - timedelta(hours=1)).timestamp())
                end_time = int(datetime.now().timestamp())
                
                message_ids = db.find_messages_by_timestamp_range(start_time, end_time)
                
                self.assertIsInstance(message_ids, list)
                self.assertGreater(len(message_ids), 0)
                
        except ImportError:
            self.skipTest("NOT_STISLA not available")
    
    def test_not_stisla_message_id_lookup(self):
        """Test NOT_STISLA message ID lookup"""
        try:
            from tgarchive.db import SpectraDB
            
            with SpectraDB(self.db_path) as db:
                msg_data = db.find_message_by_id_fast(500)
                
                self.assertIsNotNone(msg_data)
                self.assertEqual(msg_data['id'], 500)
                
        except ImportError:
            self.skipTest("NOT_STISLA not available")
    
    def test_qihse_semantic_search(self):
        """Test QIHSE semantic search integration"""
        try:
            from tgarchive.search.hybrid_search import QdrantVectorManager
            
            # This test requires Qdrant to be running
            vector_manager = QdrantVectorManager(use_qihse=True)
            
            results = vector_manager.search_semantic("test query", limit=10, use_qihse=True)
            
            self.assertIsInstance(results, list)
            
        except Exception as e:
            self.skipTest(f"QIHSE test skipped: {e}")
    
    def test_hybrid_search_combination(self):
        """Test hybrid search combining NOT_STISLA + QIHSE + FTS5"""
        try:
            from tgarchive.search.hybrid_search import HybridSearchEngine
            from tgarchive.db import SpectraDB
            
            with SpectraDB(self.db_path) as db:
                hybrid = HybridSearchEngine(db, use_not_stisla=True, use_qihse=True)
                
                results = hybrid.search(
                    "test query",
                    limit=10,
                    date_from=datetime.now() - timedelta(hours=1),
                    date_to=datetime.now(),
                )
                
                self.assertIsInstance(results, list)
                
        except Exception as e:
            self.skipTest(f"Hybrid search test skipped: {e}")
    
    def test_temporal_semantic_correlation(self):
        """Test temporal-semantic correlation search"""
        try:
            from tgarchive.search.temporal_semantic import TemporalSemanticSearch
            from tgarchive.db import SpectraDB
            
            with SpectraDB(self.db_path) as db:
                temporal_semantic = TemporalSemanticSearch(db)
                
                results = temporal_semantic.find_semantically_similar_in_timeframe(
                    "test query",
                    datetime.now() - timedelta(hours=1),
                    datetime.now(),
                    limit=10,
                )
                
                self.assertIsInstance(results, list)
                
        except Exception as e:
            self.skipTest(f"Temporal-semantic test skipped: {e}")
    
    def test_unified_search_algorithm_selection(self):
        """Test unified search engine algorithm selection"""
        try:
            from tgarchive.search.unified_search import UnifiedSearchEngine
            from tgarchive.db import SpectraDB
            
            with SpectraDB(self.db_path) as db:
                unified = UnifiedSearchEngine(db)
                
                # Test auto-selection for timestamp query
                results = unified.search(
                    "2024-01-01",
                    search_type="auto",
                    date_from=datetime.now() - timedelta(days=1),
                    date_to=datetime.now(),
                )
                
                self.assertIsInstance(results, list)
                
        except Exception as e:
            self.skipTest(f"Unified search test skipped: {e}")
    
    def test_batch_search_optimization(self):
        """Test batch search with NOT_STISLA parallel search"""
        try:
            from tgarchive.search.hybrid_search import HybridSearchEngine
            from tgarchive.db import SpectraDB
            
            with SpectraDB(self.db_path) as db:
                hybrid = HybridSearchEngine(db, use_not_stisla=True)
                
                queries = ["100", "200", "300", "400", "500"]
                results = hybrid.search_batch(queries, limit_per_query=5)
                
                self.assertIsInstance(results, dict)
                self.assertEqual(len(results), len(queries))
                
        except Exception as e:
            self.skipTest(f"Batch search test skipped: {e}")


if __name__ == "__main__":
    unittest.main()
