"""Smart defaults and suggestions using ML and operation history"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from ..ai.continuous_learning import ContinuousLearner
    from ..ai.pattern_detector import PatternDetector
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    logger.debug("ML components not available for smart defaults")


class SmartDefaults:
    """Smart defaults using ML and operation history"""
    
    def __init__(self, command_history=None, continuous_learner=None, pattern_detector=None):
        self.command_history = command_history
        self.continuous_learner = continuous_learner
        self.pattern_detector = pattern_detector
    
    def suggest_defaults(self, operation_type: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """Suggest default values for an operation"""
        defaults = {}
        
        # Get from command history
        if self.command_history:
            recent = self.command_history.search_by_operation_type(operation_type, limit=5)
            if recent:
                # Use most common parameters
                param_counts = {}
                for entry in recent:
                    for key, value in entry.parameters.items():
                        if key not in param_counts:
                            param_counts[key] = {}
                        param_counts[key][value] = param_counts[key].get(value, 0) + 1
                
                for key, counts in param_counts.items():
                    if counts:
                        defaults[key] = max(counts.items(), key=lambda x: x[1])[0]
        
        # Get ML suggestions if available
        if self.continuous_learner and context:
            try:
                ml_suggestions = self.continuous_learner.predict(context)
                defaults.update(ml_suggestions)
            except Exception as e:
                logger.debug(f"ML suggestions not available: {e}")
        
        return defaults
    
    def suggest_next_action(self, current_context: Dict[str, Any] = None) -> Optional[str]:
        """Suggest next action based on patterns"""
        if self.pattern_detector and current_context:
            try:
                patterns = self.pattern_detector.detect_patterns(current_context)
                if patterns:
                    # Return most likely next action
                    return patterns[0].get("predicted_action")
            except Exception as e:
                logger.debug(f"Pattern detection not available: {e}")
        return None
