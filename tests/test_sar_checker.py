"""Tests for SARChecker."""

import pandas as pd

from crypto_spot_collector.checkers.sar_checker import SARChecker


class TestSARChecker:
    """Test suite for SARChecker."""

    def test_check_valid_signal_3_consecutive(self) -> None:
        """The latest candle fires exactly when the run reaches three."""
        df = pd.DataFrame({"sar_up": [float("nan")] * 7 + [100.0, 101.0, 102.0]})

        checker = SARChecker(consecutive_positive_count=3)
        result = checker.check(df)

        assert result is True

    def test_check_no_signal_only_2_consecutive(self) -> None:
        """Test that check returns False for only 2 consecutive positive values."""
        df = pd.DataFrame({"sar_up": [float("nan")] * 8 + [100.0, 101.0]})

        checker = SARChecker(consecutive_positive_count=3)
        result = checker.check(df)

        assert result is False

    def test_check_no_signal_4_consecutive(self) -> None:
        """Continuing trends do not re-fire on every closed candle."""
        df = pd.DataFrame({"sar_up": [float("nan")] * 6 + [100.0, 101.0, 102.0, 103.0]})

        checker = SARChecker(consecutive_positive_count=3)
        result = checker.check(df)

        assert result is False

    def test_check_no_signal_without_transition_boundary(self) -> None:
        """Warm data with no NaN transition boundary is fail-closed."""
        df = pd.DataFrame({"sar_up": [99.0, 100.0, 101.0, 102.0]})

        checker = SARChecker(consecutive_positive_count=3)
        result = checker.check(df)

        assert result is False

    def test_check_custom_consecutive_count(self) -> None:
        """Test that checker works with custom consecutive count."""
        df = pd.DataFrame(
            {"sar_up": [float("nan")] * 5 + [100.0, 101.0, 102.0, 103.0, 104.0]}
        )

        checker = SARChecker(consecutive_positive_count=5)
        result = checker.check(df)

        assert result is True

    def test_check_missing_sar_up_column(self) -> None:
        """Test that check returns False when sar_up column is missing."""
        df = pd.DataFrame({"close": [100.0, 101.0, 102.0]})

        checker = SARChecker(consecutive_positive_count=3)
        result = checker.check(df)

        assert result is False

    def test_check_empty_dataframe(self) -> None:
        """Test that check handles empty DataFrame gracefully."""
        df = pd.DataFrame({"sar_up": []})

        checker = SARChecker(consecutive_positive_count=3)
        result = checker.check(df)

        assert result is False

    def test_check_all_nan(self) -> None:
        """Test that check returns False when all values are NaN."""
        df = pd.DataFrame({"sar_up": [float("nan")] * 10})

        checker = SARChecker(consecutive_positive_count=3)
        result = checker.check(df)

        assert result is False

    def test_historical_completed_run_is_not_a_current_signal(self) -> None:
        df = pd.DataFrame(
            {
                "sar_up": [
                    float("nan"),
                    100.0,
                    101.0,
                    102.0,
                    float("nan"),
                    float("nan"),
                    float("nan"),
                ]
            }
        )
        assert SARChecker(consecutive_count=3).check_long(df) is False

    def test_short_signal_uses_latest_transition(self) -> None:
        df = pd.DataFrame(
            {
                "sar_down": [float("nan"), 103.0, 102.0, 101.0],
            }
        )
        assert SARChecker(consecutive_count=3).check_short(df) is True

    def test_get_current_sar_direction_long(self) -> None:
        """Test that get_current_sar_direction returns 'long' when sar_up has value."""
        df = pd.DataFrame(
            {
                "sar_up": [float("nan"), float("nan"), 100.0],
                "sar_down": [101.0, 102.0, float("nan")],
            }
        )

        checker = SARChecker(consecutive_positive_count=3)
        direction = checker.get_current_sar_direction(df)

        assert direction == "long"

    def test_get_current_sar_direction_short(self) -> None:
        """Test that get_current_sar_direction returns 'short' when sar_down has value."""
        df = pd.DataFrame(
            {
                "sar_up": [100.0, 101.0, float("nan")],
                "sar_down": [float("nan"), float("nan"), 102.0],
            }
        )

        checker = SARChecker(consecutive_positive_count=3)
        direction = checker.get_current_sar_direction(df)

        assert direction == "short"

    def test_get_current_sar_direction_none(self) -> None:
        """Test that get_current_sar_direction returns None when both are NaN."""
        df = pd.DataFrame(
            {
                "sar_up": [100.0, 101.0, float("nan")],
                "sar_down": [float("nan"), float("nan"), float("nan")],
            }
        )

        checker = SARChecker(consecutive_positive_count=3)
        direction = checker.get_current_sar_direction(df)

        assert direction is None

    def test_get_current_sar_direction_rejects_both_sides(self) -> None:
        df = pd.DataFrame({"sar_up": [100.0], "sar_down": [101.0]})
        assert SARChecker().get_current_sar_direction(df) is None

    def test_check_sar_direction_switch_detected(self) -> None:
        """Test that check_sar_direction_switch detects a switch from long to short."""
        df = pd.DataFrame(
            {
                "sar_up": [100.0, 101.0, float("nan")],
                "sar_down": [float("nan"), float("nan"), 102.0],
            }
        )

        checker = SARChecker(consecutive_positive_count=3)
        switched, current = checker.check_sar_direction_switch(df, "long")

        assert switched is True
        assert current == "short"

    def test_check_sar_direction_no_switch(self) -> None:
        """Test that check_sar_direction_switch returns False when direction unchanged."""
        df = pd.DataFrame(
            {
                "sar_up": [float("nan"), float("nan"), 100.0],
                "sar_down": [101.0, 102.0, float("nan")],
            }
        )

        checker = SARChecker(consecutive_positive_count=3)
        switched, current = checker.check_sar_direction_switch(df, "long")

        assert switched is False
        assert current == "long"

    def test_check_sar_direction_switch_from_none(self) -> None:
        """Test that check_sar_direction_switch returns False when previous is None."""
        df = pd.DataFrame(
            {
                "sar_up": [float("nan"), float("nan"), 100.0],
                "sar_down": [101.0, 102.0, float("nan")],
            }
        )

        checker = SARChecker(consecutive_positive_count=3)
        switched, current = checker.check_sar_direction_switch(df, None)

        assert switched is False
        assert current == "long"
