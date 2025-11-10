"""Market data provider with technical indicators."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

import pandas as pd
from ta.trend import PSARIndicator

from crypto_spot_collector.repository.ohlcv_repository import OHLCVRepository


class MarketDataProvider:
    """Provides market data with technical indicators (SMA, SAR, etc.)."""

    def __init__(self) -> None:
        """Initialize the market data provider."""
        pass

    def get_dataframe_with_indicators(
        self,
        symbol: str,
        interval: Literal["1m", "5m", "10m", "1h", "2h", "4h", "6h"],
        from_datetime: datetime,
        to_datetime: datetime,
        sma_windows: Optional[List[int]] = None,
        sar_config: Optional[Dict[str, float]] = None,
    ) -> pd.DataFrame:
        """
        Get OHLCV data as DataFrame with technical indicators.

        Args:
            symbol: Cryptocurrency symbol (e.g., 'BTC')
            interval: Time interval for data aggregation
            from_datetime: Start datetime (inclusive)
            to_datetime: End datetime (inclusive)
            sma_windows: List of SMA window sizes to calculate (e.g., [50, 100])
            sar_config: SAR indicator configuration with 'step' and 'max_step'

        Returns:
            DataFrame with OHLCV data and technical indicators
        """
        # Set default values
        if sma_windows is None:
            sma_windows = [50, 100]
        if sar_config is None:
            sar_config = {"step": 0.02, "max_step": 0.2}

        # Fetch data from repository
        with OHLCVRepository() as repo:
            data = repo.get_ohlcv_data(
                symbol=symbol,
                interval=interval,
                from_datetime=from_datetime,
                to_datetime=to_datetime,
            )

            # Convert to DataFrame
            df = pd.DataFrame(
                [
                    {
                        "timestamp": d.timestamp_utc,
                        "open": float(d.open_price),
                        "high": float(d.high_price),
                        "low": float(d.low_price),
                        "close": float(d.close_price),
                        "volume": float(d.volume),
                    }
                    for d in data
                ]
            )

            if df.empty:
                return df

            # Add SMA indicators
            for window in sma_windows:
                df[f"sma_{window}"] = df["close"].rolling(window=window).mean()

            # Add SAR indicators
            sar_indicator = PSARIndicator(
                high=df["high"],
                low=df["low"],
                close=df["close"],
                step=sar_config["step"],
                max_step=sar_config["max_step"],
            )

            df["sar"] = sar_indicator.psar()
            df["sar_up"] = sar_indicator.psar_up()
            df["sar_down"] = sar_indicator.psar_down()

            return df
