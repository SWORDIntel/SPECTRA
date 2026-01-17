"""
Learning Store
==============

Persistent storage for learned patterns and correlations.
"""

import logging
import sqlite3
import json
from typing import Dict, Any, List, Optional
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)


class LearningStore:
    """
    Persistent storage for continuous learning results.
    
    Stores:
    - Learned patterns
    - Correlations
    - Model states
    - Vector embeddings
    """
    
    def __init__(self, db_path: Path):
        """Initialize learning store"""
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
    
    def _init_schema(self):
        """Initialize database schema"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_type TEXT NOT NULL,
                pattern_data TEXT NOT NULL,
                confidence REAL,
                discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS correlations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity1_type TEXT NOT NULL,
                entity1_id TEXT NOT NULL,
                entity2_type TEXT NOT NULL,
                entity2_id TEXT NOT NULL,
                correlation_strength REAL,
                discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                embedding BLOB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
    
    def save_pattern(self, pattern_type: str, pattern_data: Dict[str, Any], confidence: float):
        """Save learned pattern"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO patterns (pattern_type, pattern_data, confidence)
            VALUES (?, ?, ?)
        """, (pattern_type, json.dumps(pattern_data), confidence))
        
        conn.commit()
        conn.close()
    
    def get_patterns(self, pattern_type: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get learned patterns"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        if pattern_type:
            cursor.execute("""
                SELECT pattern_type, pattern_data, confidence, discovered_at
                FROM patterns WHERE pattern_type = ? ORDER BY discovered_at DESC LIMIT ?
            """, (pattern_type, limit))
        else:
            cursor.execute("""
                SELECT pattern_type, pattern_data, confidence, discovered_at
                FROM patterns ORDER BY discovered_at DESC LIMIT ?
            """, (limit,))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'pattern_type': row[0],
                'pattern_data': json.loads(row[1]),
                'confidence': row[2],
                'discovered_at': row[3],
            })
        
        conn.close()
        return results
    
    def save_correlation(
        self,
        entity1_type: str, entity1_id: str,
        entity2_type: str, entity2_id: str,
        strength: float
    ):
        """Save correlation"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO correlations (entity1_type, entity1_id, entity2_type, entity2_id, correlation_strength)
            VALUES (?, ?, ?, ?, ?)
        """, (entity1_type, str(entity1_id), entity2_type, str(entity2_id), strength))
        
        conn.commit()
        conn.close()
    
    def get_correlations(self, entity_type: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get correlations"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        if entity_type:
            cursor.execute("""
                SELECT entity1_type, entity1_id, entity2_type, entity2_id, correlation_strength, discovered_at
                FROM correlations
                WHERE entity1_type = ? OR entity2_type = ?
                ORDER BY correlation_strength DESC LIMIT ?
            """, (entity_type, entity_type, limit))
        else:
            cursor.execute("""
                SELECT entity1_type, entity1_id, entity2_type, entity2_id, correlation_strength, discovered_at
                FROM correlations ORDER BY correlation_strength DESC LIMIT ?
            """, (limit,))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'entity1': {'type': row[0], 'id': row[1]},
                'entity2': {'type': row[2], 'id': row[3]},
                'strength': row[4],
                'discovered_at': row[5],
            })
        
        conn.close()
        return results
    
    def save_embedding(self, entity_type: str, entity_id: str, embedding: np.ndarray):
        """Save vector embedding"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        embedding_blob = embedding.tobytes()
        
        cursor.execute("""
            INSERT INTO embeddings (entity_type, entity_id, embedding)
            VALUES (?, ?, ?)
        """, (entity_type, str(entity_id), embedding_blob))
        
        conn.commit()
        conn.close()
    
    def get_embedding(self, entity_type: str, entity_id: str) -> Optional[np.ndarray]:
        """Get vector embedding"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT embedding FROM embeddings
            WHERE entity_type = ? AND entity_id = ?
            ORDER BY created_at DESC LIMIT 1
        """, (entity_type, str(entity_id)))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return np.frombuffer(row[0], dtype=np.float32)
        return None
