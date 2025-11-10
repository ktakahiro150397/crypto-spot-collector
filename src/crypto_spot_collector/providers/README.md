# Market Data Provider

This module provides a unified interface for retrieving market data with technical indicators.

## Overview

The `MarketDataProvider` class encapsulates the logic for fetching OHLCV (Open, High, Low, Close, Volume) data from the database and enriching it with commonly used technical indicators like SMA (Simple Moving Average) and SAR (Parabolic SAR).

## Usage

```python
from datetime import datetime, timedelta
from crypto_spot_collector.providers.market_data_provider import MarketDataProvider

# Initialize the provider
provider = MarketDataProvider()

# Get data with indicators
df = provider.get_dataframe_with_indicators(
    symbol="BTC",
    interval="1h",
    from_datetime=datetime.now() - timedelta(days=14),
    to_datetime=datetime.now(),
    sma_windows=[50, 100],  # Optional, defaults to [50, 100]
    sar_config={"step": 0.02, "max_step": 0.2}  # Optional
)
```

## DataFrame Columns

The returned DataFrame contains the following columns:

- `timestamp`: Timestamp in UTC
- `open`: Opening price
- `high`: Highest price
- `low`: Lowest price
- `close`: Closing price
- `volume`: Trading volume
- `sma_{window}`: Simple Moving Average for each window size (e.g., `sma_50`, `sma_100`)
- `sar`: Parabolic SAR value
- `sar_up`: SAR value during bullish trend (NaN during bearish)
- `sar_down`: SAR value during bearish trend (NaN during bullish)

## Parameters

### get_dataframe_with_indicators

- `symbol` (str): Cryptocurrency symbol (e.g., 'BTC', 'ETH')
- `interval` (Literal): Time interval - one of "1m", "5m", "10m", "1h", "2h", "4h", "6h"
- `from_datetime` (datetime): Start datetime (inclusive)
- `to_datetime` (datetime): End datetime (inclusive)
- `sma_windows` (Optional[List[int]]): List of SMA window sizes to calculate (default: [50, 100])
- `sar_config` (Optional[Dict[str, float]]): SAR configuration with 'step' and 'max_step' keys (default: {"step": 0.02, "max_step": 0.2})

## Example: Custom Indicators

To use different SMA windows or SAR configuration:

```python
# Custom SMA windows
df = provider.get_dataframe_with_indicators(
    symbol="ETH",
    interval="4h",
    from_datetime=start,
    to_datetime=end,
    sma_windows=[20, 50, 200]  # 20, 50, and 200-period SMAs
)

# Custom SAR parameters
df = provider.get_dataframe_with_indicators(
    symbol="SOL",
    interval="1h",
    from_datetime=start,
    to_datetime=end,
    sar_config={"step": 0.01, "max_step": 0.15}  # Less aggressive SAR
)
```

## Benefits

1. **Consistency**: Ensures all trading strategies use the same data processing logic
2. **Maintainability**: Changes to indicator calculations only need to be made in one place
3. **Extensibility**: Easy to add new indicators without modifying trading logic
4. **Testability**: Data retrieval and processing can be tested independently
