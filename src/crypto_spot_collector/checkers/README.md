# Trading Signal Checkers

This module contains checker classes for detecting trading signals in market data.

## Overview

The checker system is designed to be extensible, allowing for multiple trading strategies to be implemented without modifying the core trading logic.

## Base Class

All checkers inherit from `SignalChecker` base class which provides a common interface:

```python
from crypto_spot_collector.checkers.base_checker import SignalChecker

class SignalChecker(ABC):
    @abstractmethod
    def check(self, df: pd.DataFrame, **kwargs) -> bool:
        """Check for trading signals in the provided DataFrame."""
        pass
```

## Available Checkers

### SARChecker

The `SARChecker` detects buy signals based on the Parabolic SAR indicator.

**Usage:**

```python
from crypto_spot_collector.checkers.sar_checker import SARChecker

# Initialize checker with desired consecutive count
checker = SARChecker(consecutive_positive_count=3)

# Check for signal in DataFrame with SAR indicators
signal_detected = checker.check(df)
```

**Signal Logic:**

The checker looks for exactly N consecutive positive SAR values that appear after NaN values, where N is the `consecutive_positive_count`. This indicates a potential bullish trend reversal.

**Parameters:**

- `consecutive_positive_count` (int): Number of consecutive positive SAR values required for a buy signal (default: 3)

## Creating a New Checker

To create a new trading strategy, inherit from `SignalChecker`:

```python
from crypto_spot_collector.checkers.base_checker import SignalChecker
import pandas as pd

class MyCustomChecker(SignalChecker):
    def __init__(self, custom_param: int = 10):
        self.custom_param = custom_param
    
    def check(self, df: pd.DataFrame, **kwargs) -> bool:
        # Implement your signal detection logic here
        # Return True if buy signal is detected, False otherwise
        return False
```

Then use it in your trading logic:

```python
checker = MyCustomChecker(custom_param=20)
if checker.check(df):
    # Place order
    pass
```
