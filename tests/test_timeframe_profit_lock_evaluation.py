from crypto_spot_collector.scripts.evaluate_profit_lock_timeframes import _config


def test_same_count_keeps_production_confirmation_counts() -> None:
    config = _config("4h", "baseline", "same_count")

    assert config.sar_consecutive_count == 4
    assert config.sar_close_consecutive_count == 2
    assert config.trailing_activation_roe == 7.0
    assert config.profit_lock_floor_roe == 0.0


def test_clock_normalized_counts_and_profit_floor() -> None:
    config = _config("5m", "profit_lock", "clock_normalized")

    assert config.sar_consecutive_count == 24
    assert config.sar_close_consecutive_count == 12
    assert config.trailing_activation_roe == 0.25
    assert config.profit_lock_floor_roe == 0.15
    assert config.trailing_interval_minutes == 1
