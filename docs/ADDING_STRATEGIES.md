# Example: Adding a New Trading Strategy

This example demonstrates how to add a new trading strategy using the refactored architecture.

## Step 1: Create a New Checker

Create a new checker class that inherits from `SignalChecker`:

```python
# File: src/crypto_spot_collector/checkers/crossover_checker.py

"""Moving Average Crossover signal checker implementation."""

import pandas as pd
from loguru import logger

from crypto_spot_collector.checkers.base_checker import SignalChecker


class MovingAverageCrossoverChecker(SignalChecker):
    """Checker for Moving Average crossover buy signals."""

    def __init__(self, fast_period: int = 50, slow_period: int = 100) -> None:
        """
        Initialize MA Crossover checker.

        Args:
            fast_period: Period for fast moving average
            slow_period: Period for slow moving average
        """
        self.fast_period = fast_period
        self.slow_period = slow_period

    def check(self, df: pd.DataFrame, **kwargs) -> bool:
        """
        Check for MA crossover buy signal.

        Signal is detected when fast MA crosses above slow MA.

        Args:
            df: DataFrame with OHLCV data and SMA indicators
            **kwargs: Additional parameters (not used)

        Returns:
            True if crossover buy signal is detected, False otherwise
        """
        fast_col = f"sma_{self.fast_period}"
        slow_col = f"sma_{self.slow_period}"
        
        if fast_col not in df.columns or slow_col not in df.columns:
            logger.error(f"DataFrame missing required columns: {fast_col}, {slow_col}")
            return False

        if len(df) < 2:
            return False

        # Check if fast MA crossed above slow MA in the most recent period
        current_fast = df[fast_col].iloc[-1]
        current_slow = df[slow_col].iloc[-1]
        previous_fast = df[fast_col].iloc[-2]
        previous_slow = df[slow_col].iloc[-2]

        # Crossover: fast was below slow, now fast is above slow
        if pd.notna(current_fast) and pd.notna(current_slow):
            if previous_fast <= previous_slow and current_fast > current_slow:
                logger.info("MA Crossover signal: Fast MA crossed above Slow MA")
                return True

        return False
```

## Step 2: Use the New Checker in buy_spot.py

Modify the `check_signal` function to use your new checker:

```python
# In buy_spot.py, you can now easily switch strategies:

from crypto_spot_collector.checkers.sar_checker import SARChecker
from crypto_spot_collector.checkers.crossover_checker import MovingAverageCrossoverChecker

async def check_signal(
    startDate: datetime,
    endDate: datetime,
    symbol: str,
    timeframe: str,
    amountByUSDT: float,
    strategy: str = "sar"  # Add strategy parameter
) -> None:
    """Check for buy signals using specified strategy."""

    # Get data with indicators
    data_provider = MarketDataProvider()
    df = data_provider.get_dataframe_with_indicators(
        symbol=symbol,
        interval=timeframe,
        from_datetime=startDate,
        to_datetime=endDate,
        sma_windows=[50, 100],
        sar_config={"step": 0.02, "max_step": 0.2}
    )

    # Select checker based on strategy
    if strategy == "sar":
        checker = SARChecker(consecutive_positive_count=3)
    elif strategy == "ma_crossover":
        checker = MovingAverageCrossoverChecker(fast_period=50, slow_period=100)
    else:
        logger.error(f"Unknown strategy: {strategy}")
        return

    # Check for signal using the selected strategy
    signal_detected = checker.check(df)
    
    if signal_detected:
        # Place order...
        pass
```

## Step 3: Configure Strategy in Settings

Add strategy configuration to your `secrets.json`:

```json
{
  "settings": {
    "timeframes": [
      {
        "timeframe": "1h",
        "amountBuyUSDT": 10,
        "strategy": "sar",
        "consecutivePositiveCount": 3
      },
      {
        "timeframe": "4h",
        "amountBuyUSDT": 20,
        "strategy": "ma_crossover"
      }
    ]
  }
}
```

## Benefits of This Architecture

1. **Separation of Concerns**: Trading logic is separated from signal detection
2. **Easy Testing**: Each checker can be tested independently
3. **Multiple Strategies**: Run different strategies on different timeframes
4. **No Code Duplication**: Data fetching logic is centralized
5. **Maintainability**: Changes to one strategy don't affect others

## Adding More Indicators

To add more indicators to the DataFrame, modify `MarketDataProvider`:

```python
# In market_data_provider.py

def get_dataframe_with_indicators(
    self,
    ...
    rsi_period: int = 14,  # Add new parameter
) -> pd.DataFrame:
    ...
    # Add RSI indicator
    from ta.momentum import RSIIndicator
    rsi = RSIIndicator(close=df["close"], window=rsi_period)
    df["rsi"] = rsi.rsi()
    
    return df
```

Then use it in your checker:

```python
class RSIChecker(SignalChecker):
    def check(self, df: pd.DataFrame, **kwargs) -> bool:
        if "rsi" not in df.columns:
            return False
        
        latest_rsi = df["rsi"].iloc[-1]
        return latest_rsi < 30  # Oversold condition
```
