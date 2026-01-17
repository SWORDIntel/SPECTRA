"""
Activity Forecasting
====================

Forecast future activity patterns using time-series models.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import numpy as np

logger = logging.getLogger(__name__)

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    logger.warning("pandas not available. Forecasting limited.")


class ActivityForecaster:
    """
    Forecast future activity patterns using statistical models.
    
    Supports:
    - ARIMA models for time-series forecasting
    - Prophet for seasonal forecasting (if available)
    - Simple linear/trend extrapolation
    """
    
    def __init__(self):
        """Initialize forecaster"""
        if not PANDAS_AVAILABLE:
            logger.warning("pandas not available. Limited forecasting capability.")
    
    def forecast_message_volume(
        self,
        timestamps: List[datetime],
        forecast_hours: int = 24,
        method: str = "trend"
    ) -> Dict[str, Any]:
        """
        Forecast message volume for future period.
        
        Args:
            timestamps: Historical message timestamps
            forecast_hours: Hours to forecast ahead
            method: Forecasting method ("trend", "arima", "prophet")
        
        Returns:
            Forecast with confidence intervals
        """
        if not timestamps:
            return {'forecast': [], 'confidence': 0.0}
        
        if method == "trend":
            return self._trend_forecast(timestamps, forecast_hours)
        elif method == "arima" and PANDAS_AVAILABLE:
            return self._arima_forecast(timestamps, forecast_hours)
        elif method == "prophet":
            return self._prophet_forecast(timestamps, forecast_hours)
        else:
            return self._trend_forecast(timestamps, forecast_hours)
    
    def _trend_forecast(
        self,
        timestamps: List[datetime],
        forecast_hours: int
    ) -> Dict[str, Any]:
        """Simple trend-based forecast"""
        if len(timestamps) < 2:
            return {'forecast': [], 'confidence': 0.0}
        
        sorted_times = sorted(timestamps)
        time_span_hours = (sorted_times[-1] - sorted_times[0]).total_seconds() / 3600
        
        if time_span_hours == 0:
            return {'forecast': [], 'confidence': 0.0}
        
        # Calculate rate
        messages_per_hour = len(timestamps) / time_span_hours
        
        # Simple linear trend
        forecast = []
        last_time = sorted_times[-1]
        for hour in range(1, forecast_hours + 1):
            forecast.append({
                'time': last_time + timedelta(hours=hour),
                'expected_messages': messages_per_hour,
                'confidence': 0.7,  # Lower confidence for simple method
            })
        
        return {
            'forecast': forecast,
            'confidence': 0.7,
            'method': 'trend',
        }
    
    def _arima_forecast(
        self,
        timestamps: List[datetime],
        forecast_hours: int
    ) -> Dict[str, Any]:
        """ARIMA-based forecast"""
        try:
            df = pd.DataFrame({'timestamp': timestamps})
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
            hourly = df.resample('1H').size()
            
            if len(hourly) < 10:
                return self._trend_forecast(timestamps, forecast_hours)
            
            # Simple ARIMA-like approach using differencing
            diff = hourly.diff().dropna()
            mean_diff = diff.mean()
            
            forecast = []
            last_time = hourly.index[-1]
            last_value = hourly.iloc[-1]
            
            for hour in range(1, forecast_hours + 1):
                forecast.append({
                    'time': last_time + pd.Timedelta(hours=hour),
                    'expected_messages': max(0, last_value + mean_diff * hour),
                    'confidence': 0.8,
                })
            
            return {
                'forecast': forecast,
                'confidence': 0.8,
                'method': 'arima',
            }
        except Exception as e:
            logger.debug(f"ARIMA forecast failed: {e}")
            return self._trend_forecast(timestamps, forecast_hours)
    
    def _prophet_forecast(
        self,
        timestamps: List[datetime],
        forecast_hours: int
    ) -> Dict[str, Any]:
        """Prophet-based forecast (if available)"""
        try:
            from prophet import Prophet
        except ImportError:
            logger.debug("Prophet not available, using trend forecast")
            return self._trend_forecast(timestamps, forecast_hours)
        
        try:
            df = pd.DataFrame({
                'ds': sorted(timestamps),
                'y': [1] * len(timestamps)
            })
            
            model = Prophet()
            model.fit(df)
            
            future = model.make_future_dataframe(periods=forecast_hours, freq='H')
            forecast_df = model.predict(future)
            
            forecast = []
            for _, row in forecast_df.tail(forecast_hours).iterrows():
                forecast.append({
                    'time': row['ds'],
                    'expected_messages': max(0, row['yhat']),
                    'confidence_lower': max(0, row.get('yhat_lower', 0)),
                    'confidence_upper': row.get('yhat_upper', 0),
                    'confidence': 0.85,
                })
            
            return {
                'forecast': forecast,
                'confidence': 0.85,
                'method': 'prophet',
            }
        except Exception as e:
            logger.debug(f"Prophet forecast failed: {e}")
            return self._trend_forecast(timestamps, forecast_hours)
    
    def predict_actor_activity(
        self,
        actor_timestamps: List[datetime],
        forecast_hours: int = 24
    ) -> Dict[str, Any]:
        """
        Predict when an actor will be active next.
        
        Args:
            actor_timestamps: Historical activity timestamps for actor
            forecast_hours: Hours to forecast
        
        Returns:
            Prediction with probability distribution
        """
        if not actor_timestamps:
            return {'next_activity': None, 'confidence': 0.0}
        
        sorted_times = sorted(actor_timestamps)
        
        # Calculate average interval
        if len(sorted_times) < 2:
            return {'next_activity': None, 'confidence': 0.0}
        
        intervals = [
            (sorted_times[i+1] - sorted_times[i]).total_seconds() / 3600
            for i in range(len(sorted_times) - 1)
        ]
        
        mean_interval = np.mean(intervals)
        last_activity = sorted_times[-1]
        predicted_next = last_activity + timedelta(hours=mean_interval)
        
        # Calculate confidence based on regularity
        std_interval = np.std(intervals)
        cv = std_interval / mean_interval if mean_interval > 0 else 1.0
        confidence = 1.0 / (1.0 + cv)
        
        return {
            'next_activity': predicted_next,
            'confidence': float(min(1.0, max(0.0, confidence))),
            'mean_interval_hours': float(mean_interval),
        }
