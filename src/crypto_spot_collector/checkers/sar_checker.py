"""SAR (Parabolic SAR) signal checker implementation."""

from typing import Any

import pandas as pd
from loguru import logger

from crypto_spot_collector.checkers.base_checker import SignalChecker


class SARChecker(SignalChecker):
    """Checker for Parabolic SAR buy and sell signals."""

    def __init__(self, consecutive_count: int = 3) -> None:
        """
        Initialize SAR checker.

        Args:
            consecutive_count: Number of consecutive SAR values required for signal
        """
        self.consecutive_count = consecutive_count

    def _check_consecutive_values(
        self,
        values: Any,
        column_name: str,
        signal_type: str
    ) -> bool:
        """
        共通処理: NaNから数値に切り替わって、指定数連続で値が存在するかチェック。

        Args:
            values: 逆順のSAR値配列 (最新 -> 古い順)
            column_name: チェック対象のカラム名（ログ出力用）
            signal_type: シグナルタイプ（'long' or 'short'）

        Returns:
            True if signal is detected, False otherwise
        """
        consecutive = 0

        # 最初に連続する数値の個数を数える
        for value in values:
            if pd.isna(value):
                break
            consecutive += 1

        logger.debug(
            f"Consecutive {signal_type} SAR values ({column_name}): {consecutive}")

        # 連続する数値が指定数以外の場合はFalse
        if consecutive != self.consecutive_count:
            logger.debug(
                f"Signal check failed: consecutive={consecutive} "
                f"(expected: {self.consecutive_count})"
            )
            return False

        # 指定数の数値の後にNaNがあるかチェック
        if consecutive < len(values) and pd.isna(values[consecutive]):
            logger.debug(
                f"SAR {signal_type} signal confirmed: {self.consecutive_count} "
                f"consecutive values after NaN"
            )
            return True

        logger.debug(
            f"Signal check failed: no NaN after {self.consecutive_count} "
            f"consecutive values"
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

        # より多くのデータを確認（最大100件）
        check_count = min(100, len(df))
        recent_values = df["sar_up"].tail(check_count).values[::-1]

        # デバッグ用: df最新・最古の10件を表示
        logger.debug(
            f"DataFrame head (oldest 10 rows):\n{df.head(10)}")
        logger.debug(
            f"DataFrame tail (newest 10 rows):\n{df.tail(10)}")
        # デバッグ用: tail(10) の sar_up 値を直接表示
        tail_sar_up = df["sar_up"].tail(10).values
        logger.debug(
            f"df['sar_up'].tail(10).values (oldest -> newest): {tail_sar_up}")
        # デバッグ用: 最新10件の値を表示
        logger.debug(
            f"Latest 10 sar_up values (newest -> oldest): {recent_values[:10]}")
        logger.debug(f"Total data points checked: {check_count}")

        return self._check_consecutive_values(recent_values, "sar_up", "long")

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

        # より多くのデータを確認（最大100件）
        check_count = min(100, len(df))
        recent_values = df["sar_down"].tail(check_count).values[::-1]

        # デバッグ用: 最新10件の値を表示
        logger.debug(
            f"Latest 10 sar_down values (newest -> oldest): {recent_values[:10]}")
        logger.debug(f"Total data points checked: {check_count}")

        return self._check_consecutive_values(recent_values, "sar_down", "short")

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
