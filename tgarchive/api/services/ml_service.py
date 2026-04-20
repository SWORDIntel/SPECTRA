"""
ML/AI Service
=============

Service layer for ML/AI operations.
"""

import logging
from typing import Dict, Any, Optional, List

try:
    from ...ml.pattern_detector import PatternDetector
    from ...ml.correlation_engine import CorrelationEngine
    from ...ml.continuous_learner import ContinuousLearner
    from ...ai.entity_extraction import EntityExtractor
    from ...ai.semantic_search import SemanticSearcher
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("ML/AI modules not available")

logger = logging.getLogger(__name__)


class MLService:
    """Service for ML/AI operations."""
    
    def __init__(self):
        if ML_AVAILABLE:
            self.pattern_detector = PatternDetector()
            self.correlation_engine = CorrelationEngine()
            self.continuous_learner = ContinuousLearner()
            self.entity_extractor = EntityExtractor()
            self.semantic_searcher = SemanticSearcher()
        else:
            self.pattern_detector = None
            self.correlation_engine = None
            self.continuous_learner = None
            self.entity_extractor = None
            self.semantic_searcher = None
    
    async def detect_patterns(
        self,
        data: List[Dict[str, Any]],
        pattern_type: str = "all",
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Detect patterns in data.
        
        Args:
            data: Input data
            pattern_type: Type of patterns to detect
            options: Detection options
            
        Returns:
            Detected patterns
        """
        if not self.pattern_detector:
            return {"error": "Pattern detector not available"}
        
        try:
            patterns = self.pattern_detector.detect(
                data,
                pattern_type=pattern_type,
                **options or {}
            )
            
            return {
                "patterns": patterns.get("patterns", []),
                "confidence": patterns.get("confidence", {}),
                "metadata": patterns.get("metadata", {})
            }
        except Exception as e:
            logger.error(f"Pattern detection failed: {e}", exc_info=True)
            raise
    
    async def analyze_correlation(
        self,
        entities: List[Dict[str, Any]],
        correlation_type: str = "behavioral",
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Analyze correlations between entities.
        
        Args:
            entities: List of entity dictionaries
            correlation_type: Type of correlation
            options: Analysis options
            
        Returns:
            Correlation analysis results
        """
        if not self.correlation_engine:
            return {"error": "Correlation engine not available"}
        
        try:
            correlations = self.correlation_engine.analyze(
                entities,
                correlation_type=correlation_type,
                **options or {}
            )
            
            return {
                "correlations": correlations.get("correlations", []),
                "strength": correlations.get("strength", {}),
                "graph": correlations.get("graph", {})
            }
        except Exception as e:
            logger.error(f"Correlation analysis failed: {e}", exc_info=True)
            raise
    
    async def extract_entities(
        self,
        text: str,
        entity_types: Optional[List[str]] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Extract entities from text.
        
        Args:
            text: Input text
            entity_types: Types of entities to extract
            options: Extraction options
            
        Returns:
            Extracted entities
        """
        if not self.entity_extractor:
            return {"error": "Entity extractor not available"}
        
        try:
            entities = self.entity_extractor.extract(
                text,
                entity_types=entity_types,
                **options or {}
            )
            
            return {
                "entities": entities.get("entities", []),
                "confidence": entities.get("confidence", {}),
                "metadata": entities.get("metadata", {})
            }
        except Exception as e:
            logger.error(f"Entity extraction failed: {e}", exc_info=True)
            raise
    
    async def semantic_search(
        self,
        query: str,
        limit: int = 10,
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Perform semantic search.
        
        Args:
            query: Search query
            limit: Maximum results
            options: Search options
            
        Returns:
            Search results
        """
        if not self.semantic_searcher:
            return {"error": "Semantic searcher not available"}
        
        try:
            results = self.semantic_searcher.search(
                query,
                limit=limit,
                **options or {}
            )
            
            return {
                "results": results.get("results", []),
                "total": results.get("total", 0),
                "query": query
            }
        except Exception as e:
            logger.error(f"Semantic search failed: {e}", exc_info=True)
            raise
    
    async def list_models(self) -> Dict[str, Any]:
        """
        List available ML models.
        
        Returns:
            List of models
        """
        return {
            "models": [
                {
                    "name": "pattern_detector",
                    "available": self.pattern_detector is not None
                },
                {
                    "name": "correlation_engine",
                    "available": self.correlation_engine is not None
                },
                {
                    "name": "entity_extractor",
                    "available": self.entity_extractor is not None
                },
                {
                    "name": "semantic_searcher",
                    "available": self.semantic_searcher is not None
                }
            ]
        }
    
    async def train_model(
        self,
        model_name: str,
        training_data: List[Dict[str, Any]],
        options: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Train an ML model.
        
        Args:
            model_name: Name of model to train
            training_data: Training data
            options: Training options
            
        Returns:
            Training results
        """
        if not self.continuous_learner:
            return {"error": "Continuous learner not available"}
        
        try:
            result = self.continuous_learner.train(
                model_name,
                training_data,
                **options or {}
            )
            
            return {
                "model_name": model_name,
                "status": "completed",
                "metrics": result.get("metrics", {}),
                "message": "Model training completed"
            }
        except Exception as e:
            logger.error(f"Model training failed: {e}", exc_info=True)
            raise
