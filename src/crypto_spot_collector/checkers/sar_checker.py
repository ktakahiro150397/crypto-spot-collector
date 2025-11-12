"""SAR (Parabolic SAR) signal checker implementation."""

from typing import Any

import pandas as pd
from loguru import logger

from crypto_spot_collector.checkers.base_checker import SignalChecker


class SARChecker(SignalChecker):
    """Checker for Parabolic SAR buy signals."""

    def __init__(self, consecutive_positive_count: int = 3) -> None:
        """
        Initialize SAR checker.

        Args:
            consecutive_positive_count: Number of consecutive positive SAR values required
        """
        self.consecutive_positive_count = consecutive_positive_count

    def check(self, df: pd.DataFrame, **kwargs: Any) -> bool:
        """
        Check for SAR buy signal.

        NaNから数値に切り替わって、そこから指定数連続で正の値になっている場合のみTrueを返す
        それ以上のプラス連続はFalseを返す

        Args:
            df: DataFrame with OHLCV data and SAR indicators (must have 'sar_up' column)
            **kwargs: Additional parameters (not used)

        Returns:
            True if SAR buy signal is detected, False otherwise
        """
        if "sar_up" not in df.columns:
            logger.error("DataFrame does not contain 'sar_up' column")
            return False

        # 最新10件を逆順で取得(最新 -> 古い順)
        recent_values = df["sar_up"].tail(10)[::-1].values

        consecutive_positive = 0

        # 最初に連続する数値の個数を数える
        for i, value in enumerate(recent_values):
            if pd.isna(value):
                break
            consecutive_positive += 1

        logger.debug(
            f"Consecutive positive SAR values: {consecutive_positive}")

        # 連続する数値が指定数以外の場合はFalse
        if consecutive_positive != self.consecutive_positive_count:
            logger.debug(
                f"Signal check failed: consecutive_positive={consecutive_positive} "
                f"(expected: {self.consecutive_positive_count})"
            )
            return False

        # 指定数の数値の後にNaNがあるかチェック
        if consecutive_positive < len(recent_values) and pd.isna(
            recent_values[consecutive_positive]
        ):
            logger.debug(
                f"SAR signal confirmed: {self.consecutive_positive_count} "
                f"consecutive positive values after NaN"
            )
            return True

        logger.debug(
            f"Signal check failed: no NaN after {self.consecutive_positive_count} "
            f"consecutive positive values"
        )
        return False
