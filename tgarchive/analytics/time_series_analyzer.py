"""
Time-Series Analysis
====================

Advanced time-series analysis for temporal pattern detection in SPECTRA data.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import numpy as np

logger = logging.getLogger(__name__)

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    logger.warning("pandas not available. Time-series analysis limited.")


class TimeSeriesAnalyzer:
    """
    Time-series analysis for message volumes, user activity, and channel growth.
    
    Features:
    - Message volume time-series
    - User activity patterns
    - Channel growth trends
    - Correlation analysis
    - Seasonal pattern detection
    - Trend decomposition
    """
    
    def __init__(self):
        """Initialize time-series analyzer"""
        if not PANDAS_AVAILABLE:
            logger.warning("pandas not available. Limited functionality.")
    
    def analyze_message_volume(
        self,
        timestamps: List[datetime],
        window: str = "1H"
    ) -> Dict[str, Any]:
        """
        Analyze message volume over time.
        
        Args:
            timestamps: List of message timestamps
            window: Time window for aggregation (e.g., "1H", "1D", "1W")
        
        Returns:
            Dictionary with volume statistics and patterns
        """
        if not PANDAS_AVAILABLE:
            return self._simple_volume_analysis(timestamps, window)
        
        try:
            df = pd.DataFrame({'timestamp': timestamps})
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
            
            # Resample by window
            volume_series = df.resample(window).size()
            
            return {
                'volume_series': volume_series.to_dict(),
                'mean_volume': float(volume_series.mean()),
                'std_volume': float(volume_series.std()),
                'max_volume': int(volume_series.max()),
                'min_volume': int(volume_series.min()),
                'trend': self._detect_trend(volume_series),
                'seasonality': self._detect_seasonality(volume_series),
            }
        except Exception as e:
            logger.error(f"Time-series analysis failed: {e}")
            return self._simple_volume_analysis(timestamps, window)
    
    def _simple_volume_analysis(
        self,
        timestamps: List[datetime],
        window: str
    ) -> Dict[str, Any]:
        """Simple volume analysis without pandas"""
        # Basic statistics
        if not timestamps:
            return {}
        
        sorted_times = sorted(timestamps)
        time_span = (sorted_times[-1] - sorted_times[0]).total_seconds()
        
        return {
            'total_messages': len(timestamps),
            'time_span_hours': time_span / 3600,
            'messages_per_hour': len(timestamps) / (time_span / 3600) if time_span > 0 else 0,
        }
    
    def analyze_user_activity(
        self,
        user_messages: Dict[int, List[datetime]]
    ) -> Dict[int, Dict[str, Any]]:
        """
        Analyze activity patterns for multiple users.
        
        Args:
            user_messages: Dict mapping user_id -> list of timestamps
        
        Returns:
            Dict mapping user_id -> activity statistics
        """
        results = {}
        
        for user_id, timestamps in user_messages.items():
            if not timestamps:
                continue
            
            sorted_times = sorted(timestamps)
            time_span = (sorted_times[-1] - sorted_times[0]).total_seconds() / 3600
            
            # Calculate activity metrics
            results[user_id] = {
                'message_count': len(timestamps),
                'time_span_hours': time_span,
                'messages_per_hour': len(timestamps) / time_span if time_span > 0 else 0,
                'peak_hours': self._find_peak_hours(timestamps),
                'activity_regularity': self._calculate_regularity(timestamps),
            }
        
        return results
    
    def analyze_channel_growth(
        self,
        channel_messages: List[datetime]
    ) -> Dict[str, Any]:
        """
        Analyze channel growth trends.
        
        Args:
            channel_messages: List of message timestamps for channel
        
        Returns:
            Growth statistics and trends
        """
        if not channel_messages:
            return {}
        
        sorted_times = sorted(channel_messages)
        
        # Calculate growth rate
        if len(sorted_times) < 2:
            return {'total_messages': len(channel_messages)}
        
        time_span_days = (sorted_times[-1] - sorted_times[0]).days
        if time_span_days == 0:
            time_span_days = 1
        
        messages_per_day = len(channel_messages) / time_span_days
        
        # Detect growth acceleration
        if PANDAS_AVAILABLE and len(sorted_times) > 10:
            try:
                df = pd.DataFrame({'timestamp': sorted_times})
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)
                daily = df.resample('1D').size()
                
                if len(daily) > 1:
                    growth_rate = (daily.iloc[-1] - daily.iloc[0]) / max(1, daily.iloc[0])
                    acceleration = self._calculate_acceleration(daily)
                else:
                    growth_rate = 0.0
                    acceleration = 0.0
            except Exception:
                growth_rate = 0.0
                acceleration = 0.0
        else:
            growth_rate = 0.0
            acceleration = 0.0
        
        return {
            'total_messages': len(channel_messages),
            'time_span_days': time_span_days,
            'messages_per_day': messages_per_day,
            'growth_rate': growth_rate,
            'acceleration': acceleration,
        }
    
    def detect_correlations(
        self,
        series1: List[float],
        series2: List[float],
        lag_max: int = 10
    ) -> Dict[str, Any]:
        """
        Detect temporal correlations between two time series.
        
        Args:
            series1: First time series
            series2: Second time series
            lag_max: Maximum lag to test
        
        Returns:
            Correlation statistics
        """
        if len(series1) != len(series2) or len(series1) < 2:
            return {}
        
        # Calculate correlation at different lags
        correlations = {}
        for lag in range(-lag_max, lag_max + 1):
            if lag == 0:
                shifted_series2 = series2
            elif lag > 0:
                shifted_series2 = series2[lag:] + [0] * lag
            else:
                shifted_series2 = [0] * abs(lag) + series2[:lag]
            
            if len(shifted_series2) == len(series1):
                corr = np.corrcoef(series1, shifted_series2[:len(series1)])[0, 1]
                if not np.isnan(corr):
                    correlations[lag] = float(corr)
        
        # Find best correlation
        best_lag = max(correlations.items(), key=lambda x: abs(x[1])) if correlations else (0, 0.0)
        
        return {
            'correlations': correlations,
            'best_lag': best_lag[0],
            'best_correlation': best_lag[1],
        }
    
    def _detect_trend(self, series) -> str:
        """Detect trend direction (increasing, decreasing, stable)"""
        if len(series) < 2:
            return "stable"
        
        first_half = series[:len(series)//2].mean()
        second_half = series[len(series)//2:].mean()
        
        if second_half > first_half * 1.1:
            return "increasing"
        elif second_half < first_half * 0.9:
            return "decreasing"
        else:
            return "stable"
    
    def _detect_seasonality(self, series) -> Optional[Dict[str, Any]]:
        """Detect seasonal patterns"""
        if len(series) < 24:  # Need at least 24 data points
            return None
        
        try:
            # Simple seasonality detection using autocorrelation
            autocorr = [series.autocorr(lag=i) for i in range(1, min(24, len(series)//2))]
            if autocorr:
                max_autocorr = max(enumerate(autocorr, 1), key=lambda x: abs(x[1]))
                return {
                    'period': max_autocorr[0],
                    'strength': float(max_autocorr[1]),
                }
        except Exception:
            pass
        
        return None
    
    def _find_peak_hours(self, timestamps: List[datetime]) -> List[int]:
        """Find peak activity hours"""
        hours = [ts.hour for ts in timestamps]
        hour_counts = {}
        for hour in hours:
            hour_counts[hour] = hour_counts.get(hour, 0) + 1
        
        # Return top 3 peak hours
        sorted_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)
        return [h[0] for h in sorted_hours[:3]]
    
    def _calculate_regularity(self, timestamps: List[datetime]) -> float:
        """Calculate activity regularity (0-1, higher = more regular)"""
        if len(timestamps) < 2:
            return 0.0
        
        sorted_times = sorted(timestamps)
        intervals = [
            (sorted_times[i+1] - sorted_times[i]).total_seconds()
            for i in range(len(sorted_times) - 1)
        ]
        
        if not intervals:
            return 0.0
        
        mean_interval = np.mean(intervals)
        std_interval = np.std(intervals)
        
        # Regularity = 1 / (1 + coefficient of variation)
        cv = std_interval / mean_interval if mean_interval > 0 else 1.0
        regularity = 1.0 / (1.0 + cv)
        
        return float(min(1.0, max(0.0, regularity)))
    
    def _calculate_acceleration(self, daily_series) -> float:
        """Calculate growth acceleration"""
        if len(daily_series) < 3:
            return 0.0
        
        first_third = daily_series[:len(daily_series)//3].mean()
        middle_third = daily_series[len(daily_series)//3:2*len(daily_series)//3].mean()
        last_third = daily_series[2*len(daily_series)//3:].mean()
        
        first_growth = (middle_third - first_third) / max(1, first_third)
        second_growth = (last_third - middle_third) / max(1, middle_third)
        
        acceleration = second_growth - first_growth
        return float(acceleration)
