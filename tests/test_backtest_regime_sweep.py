"""Tests for walk-forward EMA/ADX regime-filter comparisons."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from crypto_spot_collector.backtesting.data import CandleSeriesKey, CSVFormat
from crypto_spot_collector.backtesting.regime_sweep import (
    StrategyVariant,
    _result_row,
    build_variants,
    run_regime_sweep,
    select_train_candidates,
)


def _row(
    variant: StrategyVariant,
    *,
    total_return: float,
    drawdown: float = 0.3,
    monthly_std: float = 0.1,
) -> dict[str, object]:
    return {
        "strategy_id": variant.identifier,
        "name": variant.name,
        "selectable": variant.selectable,
        "signal_timeframe": variant.signal_timeframe,
        "take_profit_roe": variant.take_profit_roe,
        "stop_loss_roe": variant.stop_loss_roe,
        "trailing_activation_roe": variant.trailing_activation_roe,
        "trailing_interval_minutes": variant.trailing_interval_minutes,
        "filter_timeframe": (
            variant.entry_filter.timeframe if variant.entry_filter else None
        ),
        "ema_period": variant.entry_filter.ema_period if variant.entry_filter else None,
        "adx_period": variant.entry_filter.adx_period if variant.entry_filter else None,
        "adx_threshold": (
            variant.entry_filter.adx_threshold if variant.entry_filter else None
        ),
        "total_return_percent": total_return,
        "max_drawdown_percent": drawdown,
        "trade_count": 10,
        "win_rate_percent": 40.0,
        "profit_factor": 1.1,
        "final_equity": 1_000.0 + total_return * 10,
        "total_gross_pnl": 2.0,
        "total_fees": 1.0,
        "total_net_pnl": total_return * 10,
        "entry_signal_count": 20,
        "filtered_entry_signal_count": 5,
        "positive_month_ratio": 0.5,
        "monthly_return_std": monthly_std,
        "worst_month_return": -0.2,
        "robust_score": total_return - drawdown - monthly_std,
        "monthly_returns": "{}",
        "side_metrics": "{}",
        "exit_reason_counts": "{}",
    }


def test_variant_grid_contains_controls_ema_only_and_ema_adx() -> None:
    variants = build_variants(
        filter_timeframe="4h",
        ema_periods=[20, 50],
        adx_period=14,
        adx_thresholds=[20.0, 25.0],
    )

    assert len(variants) == 8
    assert sum(variant.name == "baseline_30m" for variant in variants) == 1
    assert sum(variant.name == "sar_1h_unfiltered" for variant in variants) == 1
    assert sum(variant.entry_filter is not None for variant in variants) == 6


def test_training_selection_can_keep_unfiltered_control_or_choose_filter() -> None:
    variants = build_variants(
        filter_timeframe="4h",
        ema_periods=[20],
        adx_period=14,
        adx_thresholds=[20.0],
    )
    filtered = next(
        variant
        for variant in variants
        if variant.entry_filter is not None
        and variant.entry_filter.adx_threshold == 20.0
    )
    rows = [
        _row(
            variant,
            total_return=2.0 if variant == filtered else 1.0,
        )
        for variant in variants
    ]

    selected = select_train_candidates(rows, variants=variants)

    assert selected["max_train_return"] == filtered
    assert selected["robust_train"] == filtered
    assert selected["baseline_30m"].name == "baseline_30m"
    assert selected["sar_1h_unfiltered"].name == "sar_1h_unfiltered"


def test_result_row_reports_cost_side_and_exit_breakdowns() -> None:
    variant = next(
        item
        for item in build_variants(
            filter_timeframe="4h",
            ema_periods=[20],
            adx_period=14,
            adx_thresholds=[20.0],
        )
        if item.name == "sar_1h_unfiltered"
    )
    trades = pd.DataFrame(
        {
            "side": ["long", "short"],
            "gross_pnl": [2.0, -0.5],
            "entry_fee": [0.1, 0.1],
            "exit_fee": [0.1, 0.1],
            "net_pnl": [1.8, -0.7],
            "exit_reason": ["take_profit", "stop_loss"],
        }
    )
    equity = pd.DataFrame(
        {
            "timestamp": ["2025-01-31T23:00:00Z", "2025-02-28T23:00:00Z"],
            "equity": [1_001.8, 1_001.1],
        }
    )
    summary = {
        "final_equity": 1_001.1,
        "total_net_pnl": 1.1,
        "total_return_percent": 0.11,
        "max_drawdown_percent": 0.07,
        "trade_count": 2,
        "win_rate_percent": 50.0,
        "profit_factor": 1.5,
        "entry_signal_count": 2,
        "filtered_entry_signal_count": 0,
    }

    row = _result_row(variant, summary, trades, equity)

    assert row["total_gross_pnl"] == 1.5
    assert row["total_fees"] == 0.4
    assert json.loads(str(row["side_metrics"]))["short"]["net_pnl"] == -0.7
    assert json.loads(str(row["exit_reason_counts"])) == {
        "stop_loss": 1,
        "take_profit": 1,
    }


def test_regime_sweep_locks_train_nominees_before_later_phases(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    variants = build_variants(
        filter_timeframe="4h",
        ema_periods=[20],
        adx_period=14,
        adx_thresholds=[20.0],
    )
    winner = next(
        variant
        for variant in variants
        if variant.entry_filter is not None
        and variant.entry_filter.adx_threshold == 20.0
    )
    phase_variants: dict[str, list[str]] = {}

    def fake_phase(**kwargs: object) -> list[dict[str, object]]:
        phase = str(kwargs["phase"])
        supplied = kwargs["variants"]
        assert isinstance(supplied, list)
        phase_variants[phase] = [variant.identifier for variant in supplied]
        return [
            _row(
                variant,
                total_return=(
                    3.0
                    if phase == "train" and variant == winner
                    else -2.0 if phase != "train" and variant == winner else 1.0
                ),
            )
            for variant in supplied
        ]

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "crypto_spot_collector.backtesting.regime_sweep._evaluate_phase",
        fake_phase,
    )
    output = tmp_path / "regime"
    summary = run_regime_sweep(
        input_path=tmp_path / "train.csv",
        confirmation_input_path=tmp_path / "confirmation.csv",
        key=CandleSeriesKey("binance", "perpetual", "ETH/USDT:USDT", "1m"),
        csv_format=CSVFormat.STANDARD,
        train_start="2025-01-01",
        holdout_start="2025-07-01",
        holdout_end="2025-11-01",
        confirmation_start="2025-11-01",
        confirmation_end="2026-08-01",
        variants=variants,
        fixed_config={"taker_fee_bps": 5.0},
        workers=1,
        output_dir=output,
    )

    assert summary["selection_policy"]["holdout_used_for_selection"] is False  # type: ignore[index]
    assert summary["selection_policy"]["confirmation_used_for_selection"] is False  # type: ignore[index]
    assert summary["selected"]["max_train_return"]["strategy_id"] == winner.identifier  # type: ignore[index]
    assert set(phase_variants["holdout"]) == set(phase_variants["confirmation"])
    assert len(phase_variants["holdout"]) == 3
    assert (output / "train_results.csv").is_file()
    assert (output / "selected_evaluation.csv").is_file()
    assert (output / "report.md").is_file()
    stored = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert stored["grid"]["variant_count"] == 4
