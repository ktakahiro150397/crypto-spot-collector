"""SAR (Parabolic SAR) signal checker implementation."""

from typing import Any

import pandas as pd
from loguru import logger

from crypto_spot_collector.checkers.base_checker import SignalChecker


class SARChecker(SignalChecker):
    """Checker for Parabolic SAR buy and sell signals."""

    def __init__(
        self,
        consecutive_count: int = 3,
        *,
        consecutive_positive_count: int | None = None,
    ) -> None:
        """
        Initialize SAR checker.

        Args:
            consecutive_count: Number of consecutive SAR values required for signal
        """
        # Preserve the public keyword used by the original tests and scripts
        # while keeping the direction-neutral name used by the perp runtime.
        if consecutive_positive_count is not None:
            consecutive_count = consecutive_positive_count
        if consecutive_count <= 0:
            raise ValueError("consecutive_count must be greater than zero")
        self.consecutive_count = consecutive_count

    def _check_consecutive_values(
        self, values: Any, column_name: str, signal_type: str
    ) -> bool:
        """Return true only on the candle that reaches the configured run length.

        Args:
            values: SAR values ordered oldest to newest
            column_name: チェック対象のカラム名（ログ出力用）
            signal_type: シグナルタイプ（'long' or 'short'）

        Returns:
            True if signal is detected, False otherwise
        """
        series = list(values)
        if len(series) < self.consecutive_count + 1:
            logger.debug(
                f"Signal check failed: {column_name} needs at least "
                f"{self.consecutive_count + 1} rows"
            )
            return False

        latest_run = series[-self.consecutive_count :]
        boundary = series[-self.consecutive_count - 1]
        if all(not pd.isna(value) for value in latest_run) and pd.isna(boundary):
            logger.debug(
                f"SAR {signal_type} signal confirmed on latest closed candle: "
                f"{self.consecutive_count} consecutive values"
            )
            return True

        logger.debug(
            f"Signal check failed: latest {column_name} run did not reach exactly "
            f"{self.consecutive_count} values on the newest candle"
        )
        return False

    def check_long(self, df: pd.DataFrame, **kwargs: Any) -> bool:
        """
        Check for SAR long (buy) signal.

        NaNから数値に切り替わって、そこから指定数連続でsar_upが存在する場合のみTrueを返す
        それ以上の連続はFalseを返す

        Args:
            df: DataFrame with OHLCV data and SAR indicators (must have 'sar_up' column)
            **kwargs: Additional parameters (not used)

        Returns:
            True if SAR long signal is detected, False otherwise
        """
        if "sar_up" not in df.columns:
            logger.error("DataFrame does not contain 'sar_up' column")
            return False

        return self._check_consecutive_values(
            df["sar_up"].tail(self.consecutive_count + 1).values,
            "sar_up",
            "long",
        )

    def check_short(self, df: pd.DataFrame, **kwargs: Any) -> bool:
        """
        Check for SAR short (sell) signal.

        NaNから数値に切り替わって、そこから指定数連続でsar_downが存在する場合のみTrueを返す
        それ以上の連続はFalseを返す

        Args:
            df: DataFrame with OHLCV data and SAR indicators (must have 'sar_down' column)
            **kwargs: Additional parameters (not used)

        Returns:
            True if SAR short signal is detected, False otherwise
        """
        if "sar_down" not in df.columns:
            logger.error("DataFrame does not contain 'sar_down' column")
            return False

        return self._check_consecutive_values(
            df["sar_down"].tail(self.consecutive_count + 1).values,
            "sar_down",
            "short",
        )

    def check(self, df: pd.DataFrame, **kwargs: Any) -> bool:
        """
        Check for SAR buy signal (backward compatibility).

        Args:
            df: DataFrame with OHLCV data and SAR indicators (must have 'sar_up' column)
            **kwargs: Additional parameters (not used)

        Returns:
            True if SAR buy signal is detected, False otherwise
        """
        return self.check_long(df, **kwargs)

    def get_current_sar_direction(self, df: pd.DataFrame) -> str | None:
        """
        Get the current SAR direction (long/short).

        Args:
            df: DataFrame with OHLCV data and SAR indicators

        Returns:
            'long' if SAR is currently in bullish trend (sar_up has value)
            'short' if SAR is currently in bearish trend (sar_down has value)
            None if SAR direction cannot be determined
        """
        if df.empty:
            logger.warning("DataFrame is empty, cannot determine SAR direction")
            return None

        if "sar_up" not in df.columns or "sar_down" not in df.columns:
            logger.error("DataFrame does not contain 'sar_up' or 'sar_down' columns")
            return None

        # Check the most recent SAR value
        latest_sar_up = df["sar_up"].iloc[-1]
        latest_sar_down = df["sar_down"].iloc[-1]

        has_up = not pd.isna(latest_sar_up)
        has_down = not pd.isna(latest_sar_down)
        if has_up == has_down:
            logger.warning("SAR direction is ambiguous")
            return None
        if has_up:
            logger.debug("Current SAR direction: long (bullish)")
            return "long"
        if has_down:
            logger.debug("Current SAR direction: short (bearish)")
            return "short"
        return None

    def check_sar_direction_switch(
        self, df: pd.DataFrame, previous_direction: str | None
    ) -> tuple[bool, str | None]:
        """
        Check if SAR direction has switched from the previous direction.

        Args:
            df: DataFrame with OHLCV data and SAR indicators
            previous_direction: Previous SAR direction ('long', 'short', or None)

        Returns:
            Tuple of (switch_detected, current_direction):
                - switch_detected: True if direction switched, False otherwise
                - current_direction: Current SAR direction ('long', 'short', or None)
        """
        current_direction = self.get_current_sar_direction(df)

        if previous_direction is None or current_direction is None:
            logger.debug(
                f"No switch detected: previous={previous_direction}, "
                f"current={current_direction}"
            )
            return False, current_direction

        if previous_direction != current_direction:
            logger.info(
                f"SAR direction switch detected: {previous_direction} -> {current_direction}"
            )
            return True, current_direction

        logger.debug(f"SAR direction unchanged: {current_direction}")
        return False, current_direction
