"""Base checker interface for trading signal detection."""

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class SignalChecker(ABC):
    """Abstract base class for trading signal checkers."""

    @abstractmethod
    def check(self, df: pd.DataFrame, **kwargs: Any) -> bool:
        """
        Check for trading signals in the provided DataFrame.

        Args:
            df: DataFrame with OHLCV data and technical indicators
            **kwargs: Additional parameters specific to the checker

        Returns:
            True if a buy signal is detected, False otherwise
        """
        pass
