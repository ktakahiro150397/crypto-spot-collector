"""Tests for SARChecker."""
import pandas as pd
import pytest

from crypto_spot_collector.checkers.sar_checker import SARChecker


class TestSARChecker:
    """Test suite for SARChecker."""

    def test_check_valid_signal_3_consecutive(self) -> None:
        """Test that check returns True for 3 consecutive positive values after NaN."""
        # Create test data: NaN, NaN, val1, val2, val3, NaN
        df = pd.DataFrame({
            "sar_up": [float("nan")] * 4 + [100.0, 101.0, 102.0] + [float("nan")] * 3
        })
        
        checker = SARChecker(consecutive_positive_count=3)
        result = checker.check(df)
        
        assert result is True

    def test_check_no_signal_only_2_consecutive(self) -> None:
        """Test that check returns False for only 2 consecutive positive values."""
        # Create test data: only 2 consecutive values
        df = pd.DataFrame({
            "sar_up": [float("nan")] * 5 + [100.0, 101.0] + [float("nan")] * 3
        })
        
        checker = SARChecker(consecutive_positive_count=3)
        result = checker.check(df)
        
        assert result is False

    def test_check_no_signal_4_consecutive(self) -> None:
        """Test that check returns False for 4 consecutive positive values (not exactly 3)."""
        # Create test data: 4 consecutive values
        df = pd.DataFrame({
            "sar_up": [float("nan")] * 3 + [100.0, 101.0, 102.0, 103.0] + [float("nan")] * 3
        })
        
        checker = SARChecker(consecutive_positive_count=3)
        result = checker.check(df)
        
        assert result is False

    def test_check_no_signal_no_nan_after(self) -> None:
        """Test that check returns False when there's no NaN after consecutive values."""
        # Create test data: 3 consecutive values but no NaN after
        df = pd.DataFrame({
            "sar_up": [float("nan")] * 7 + [100.0, 101.0, 102.0]
        })
        
        checker = SARChecker(consecutive_positive_count=3)
        result = checker.check(df)
        
        assert result is False

    def test_check_custom_consecutive_count(self) -> None:
        """Test that checker works with custom consecutive count."""
        # Create test data: 5 consecutive values after NaN
        df = pd.DataFrame({
            "sar_up": [float("nan")] * 2 + [100.0, 101.0, 102.0, 103.0, 104.0] + [float("nan")] * 3
        })
        
        checker = SARChecker(consecutive_positive_count=5)
        result = checker.check(df)
        
        assert result is True

    def test_check_missing_sar_up_column(self) -> None:
        """Test that check returns False when sar_up column is missing."""
        df = pd.DataFrame({
            "close": [100.0, 101.0, 102.0]
        })
        
        checker = SARChecker(consecutive_positive_count=3)
        result = checker.check(df)
        
        assert result is False

    def test_check_empty_dataframe(self) -> None:
        """Test that check handles empty DataFrame gracefully."""
        df = pd.DataFrame({
            "sar_up": []
        })
        
        checker = SARChecker(consecutive_positive_count=3)
        result = checker.check(df)
        
        assert result is False

    def test_check_all_nan(self) -> None:
        """Test that check returns False when all values are NaN."""
        df = pd.DataFrame({
            "sar_up": [float("nan")] * 10
        })
        
        checker = SARChecker(consecutive_positive_count=3)
        result = checker.check(df)
        
        assert result is False
