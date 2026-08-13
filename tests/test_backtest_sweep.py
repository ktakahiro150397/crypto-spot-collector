"""Tests for walk-forward parameter sweep selection and reporting."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from crypto_spot_collector.backtesting.data import CandleSeriesKey, CSVFormat
from crypto_spot_collector.backtesting.sweep import (
    ParameterSet,
    _monthly_returns,
    build_parameter_grid,
    run_sweep,
    select_train_candidates,
)


def _result_row(
    parameter: ParameterSet,
    *,
    total_return: float,
    drawdown: float,
    monthly_std: float,
) -> dict[str, object]:
    return {
        "parameter_id": parameter.identifier,
        "signal_timeframe": parameter.signal_timeframe,
        "take_profit_roe": parameter.take_profit_roe,
        "stop_loss_roe": parameter.stop_loss_roe,
        "trailing_activation_roe": parameter.trailing_activation_roe,
        "trailing_interval_minutes": parameter.trailing_interval_minutes,
        "total_return_percent": total_return,
        "max_drawdown_percent": drawdown,
        "trade_count": 100,
        "win_rate_percent": 50.0,
        "profit_factor": 1.1,
        "final_equity": 1_000 + total_return * 10,
        "positive_month_ratio": 0.5,
        "monthly_return_mean": total_return / 6,
        "monthly_return_std": monthly_std,
        "worst_month_return": -0.1,
        "robust_score": total_return - drawdown - monthly_std,
        "monthly_returns": "{}",
    }


def test_grid_excludes_activation_at_or_above_take_profit() -> None:
    grid = build_parameter_grid(
        signal_timeframes=["30m"],
        take_profit_roes=[5.0, 10.0],
        stop_loss_roes=[3.0],
        trailing_activation_roes=[3.0, 7.0],
        trailing_interval_minutes=3,
    )

    assert [item.identifier for item in grid] == [
        "30m|tp=5|sl=3|trail=3|trail_min=3",
        "30m|tp=10|sl=3|trail=3|trail_min=3",
        "30m|tp=10|sl=3|trail=7|trail_min=3",
    ]


def test_candidate_selection_uses_return_and_documented_robust_score() -> None:
    baseline = ParameterSet("30m", 15.0, 3.0, 7.0)
    max_return = ParameterSet("15m", 25.0, 6.0, 7.0)
    robust = ParameterSet("1h", 15.0, 3.0, 3.0)
    rows = [
        _result_row(baseline, total_return=1.0, drawdown=0.5, monthly_std=0.2),
        _result_row(max_return, total_return=3.0, drawdown=2.5, monthly_std=1.0),
        _result_row(robust, total_return=2.0, drawdown=0.4, monthly_std=0.2),
    ]

    selected = select_train_candidates(rows, baseline=baseline)

    assert selected == {
        "baseline": baseline,
        "max_train_return": max_return,
        "robust_train": robust,
    }


def test_monthly_returns_use_previous_month_end_equity() -> None:
    equity = pd.DataFrame(
        {
            "timestamp": [
                "2025-01-15T00:00:00Z",
                "2025-02-01T00:00:00Z",
                "2025-03-01T00:00:00Z",
            ],
            "equity": [1_050.0, 1_100.0, 990.0],
        }
    )

    returns = _monthly_returns(equity, initial_equity=1_000.0)

    assert returns == pytest.approx({"2025-01": 10.0, "2025-02": -10.0})


def test_run_sweep_locks_training_candidates_and_writes_artifacts(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    baseline = ParameterSet("30m", 15.0, 3.0, 7.0)
    candidate = ParameterSet("1h", 25.0, 3.0, 7.0)

    def fake_phase(**kwargs: object) -> list[dict[str, object]]:
        phase = str(kwargs["phase"])
        parameters = kwargs["parameters"]
        assert isinstance(parameters, list)
        if phase == "train":
            return [
                _result_row(
                    parameter,
                    total_return=2.0 if parameter == candidate else 1.0,
                    drawdown=0.5,
                    monthly_std=0.2,
                )
                for parameter in parameters
            ]
        return [
            _result_row(
                parameter,
                total_return=-1.0 if parameter == candidate else 0.5,
                drawdown=0.7,
                monthly_std=0.3,
            )
            for parameter in parameters
        ]

    monkeypatch.setattr(  # type: ignore[attr-defined]
        "crypto_spot_collector.backtesting.sweep._evaluate_phase",
        fake_phase,
    )
    output = tmp_path / "sweep"

    summary = run_sweep(
        input_path=tmp_path / "unused.csv",
        key=CandleSeriesKey("binance", "perpetual", "ETH/USDT:USDT", "1m"),
        csv_format=CSVFormat.STANDARD,
        train_start="2025-01-01",
        holdout_start="2025-07-01",
        end="2025-11-01",
        parameters=[baseline, candidate],
        baseline=baseline,
        fixed_config={"taker_fee_bps": 5.0},
        workers=1,
        output_dir=output,
    )

    assert summary["selection_policy"]["holdout_used_for_selection"] is False  # type: ignore[index]
    assert summary["selected"]["max_train_return"]["parameter_id"] == candidate.identifier  # type: ignore[index]
    assert (output / "train_results.csv").is_file()
    assert (output / "selected_evaluation.csv").is_file()
    assert (output / "report.md").is_file()
    stored = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert stored["grid"]["candidate_count"] == 2
