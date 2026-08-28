import pandas as pd

from crypto_spot_collector.scripts.evaluate_entry_candidates import (
    FOLDS,
    candidates,
    fixed_config,
    select_candidate,
)


def test_candidate_registry_is_fixed() -> None:
    entries = {candidate.identifier: candidate for candidate in candidates()}

    assert set(entries) == {
        "control_30m_sar",
        "1h_sar_4h_ema100_adx20",
        "4h_momentum_42_1pct",
        "4h_ema200",
    }
    filtered = entries["1h_sar_4h_ema100_adx20"]
    assert filtered.strategy.signal_timeframe == "1h"
    assert filtered.entry_filter is not None
    assert filtered.entry_filter.identifier == "4h|ema=100|adx=14:20"
    momentum = entries["4h_momentum_42_1pct"].strategy
    assert momentum.lookback == 42
    assert momentum.momentum_threshold == 0.01


def test_folds_are_independent_contiguous_periods() -> None:
    assert [fold.identifier for fold in FOLDS] == [
        "2025-H1",
        "2025-H2",
        "2026-H1",
        "2026-late",
    ]
    assert all(left.end == right.start for left, right in zip(FOLDS, FOLDS[1:]))


def test_fixed_exit_contract_changes_only_profit_lock() -> None:
    candidate = candidates()[2]
    baseline = fixed_config(candidate, "baseline")
    profit_lock = fixed_config(candidate, "profit_lock")

    assert baseline.signal_timeframe == profit_lock.signal_timeframe == "4h"
    assert baseline.take_profit_roe == profit_lock.take_profit_roe == 15
    assert baseline.stop_loss_roe == profit_lock.stop_loss_roe == 15
    assert baseline.taker_fee_bps == profit_lock.taker_fee_bps == 4.322
    assert baseline.trailing_activation_roe == 7
    assert baseline.profit_lock_floor_roe == 0
    assert profit_lock.trailing_activation_roe == 0.25
    assert profit_lock.profit_lock_floor_roe == 0.15
    assert profit_lock.trailing_interval_minutes == 1


def test_selector_prefers_robustness_before_total_profit() -> None:
    rows = pd.DataFrame(
        [
            {
                "candidate": "high_profit",
                "passed": False,
                "positive_fold_count": 2,
                "profitable_symbols": 5,
                "adverse_funding_net_pnl": 100.0,
                "worst_fold_net_pnl": -10.0,
                "max_symbol_drawdown_percent": 1.0,
                "net_pnl": 110.0,
            },
            {
                "candidate": "stable",
                "passed": False,
                "positive_fold_count": 3,
                "profitable_symbols": 4,
                "adverse_funding_net_pnl": 5.0,
                "worst_fold_net_pnl": -1.0,
                "max_symbol_drawdown_percent": 2.0,
                "net_pnl": 6.0,
            },
        ]
    )

    assert select_candidate(rows) == "stable"
