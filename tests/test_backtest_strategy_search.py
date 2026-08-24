"""Tests for the fixed multi-strategy selection protocol."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from crypto_spot_collector.backtesting.strategy_search import (
    StrategySearchError,
    _build_folds,
    _load_best_non_sar_task,
    build_exit_grid,
    build_signal_grid,
    lock_candidate,
    promote_final_candidate,
    select_screening_specs,
)
from crypto_spot_collector.backtesting.strategy_signals import (
    SideMode,
    StrategyFamily,
    StrategySpec,
)


def _row(
    *,
    family: str = "ema_price",
    pnl: float,
    robust: float | None = None,
    folds: int = 3,
    positive_folds: int = 3,
    trades: int = 40,
    profit_factor: float | None = 1.2,
    stressed_pnl: float | None = None,
    role: str = "candidate",
) -> dict[str, Any]:
    spec = StrategySpec(
        family,
        "1h",
        ema_period=20 if family == "ema_price" else None,
        lookback=20 if family == "donchian" else None,
    )
    return {
        "role": role,
        **spec.as_dict(),
        "take_profit_roe": 15.0,
        "stop_loss_roe": 6.0,
        "trailing_activation_roe": 7.0,
        "signal_exit_count": 2,
        "leverage": 1,
        "total_net_pnl": pnl,
        "total_return_percent": pnl / 10,
        "max_drawdown_percent": 0.2,
        "trade_count": trades,
        "profit_factor": profit_factor,
        "positive_fold_count": positive_folds,
        "fold_count": folds,
        "robust_score": robust if robust is not None else pnl / 10 - 0.2,
        "adverse_funding_1bps_net_pnl": (
            pnl - 0.1 if stressed_pnl is None else stressed_pnl
        ),
    }


def test_fixed_grid_covers_all_requested_families_sides_and_risk_filters() -> None:
    signals = build_signal_grid()
    families = {spec.family for spec in signals}
    sides = {spec.side_mode for spec in signals}

    assert families == set(StrategyFamily)
    assert sides == set(SideMode)
    assert any(spec.adx_threshold is not None for spec in signals)
    assert any(spec.atr_min_percent is not None for spec in signals)
    assert len(build_exit_grid()) >= 40


def test_screening_keeps_profit_and_robust_leaders_per_family() -> None:
    rows = [
        _row(family="ema_price", pnl=4.0, robust=0.1),
        _row(family="ema_price", pnl=2.0, robust=1.0),
        _row(family="donchian", pnl=3.0, robust=0.5),
    ]

    selected = select_screening_specs(rows)

    assert {spec.family for spec in selected} == {
        StrategyFamily.EMA_PRICE,
        StrategyFamily.DONCHIAN,
    }


def test_lock_chooses_maximum_profit_only_among_rows_passing_every_gate() -> None:
    higher_but_unstable = _row(pnl=8.0, positive_folds=2)
    eligible_lower = _row(pnl=6.0)
    eligible_higher = _row(pnl=7.0)

    locked = lock_candidate([higher_but_unstable, eligible_lower, eligible_higher])

    assert locked["status"] == "locked"
    assert locked["candidate"]["total_net_pnl"] == 7.0
    assert locked["maximum_development_result"]["total_net_pnl"] == 8.0


def test_lock_returns_explicit_no_candidate_when_funding_stress_fails() -> None:
    locked = lock_candidate([_row(pnl=5.0, stressed_pnl=-0.1)])

    assert locked["status"] == "no_candidate"
    assert locked["candidate"] is None


def test_fold_boundaries_are_validated_in_order() -> None:
    assert _build_folds("2025-01-01", ["2025-07-01"], "2026-01-01") == [
        ("2025-01-01", "2025-07-01"),
        ("2025-07-01", "2026-01-01"),
    ]
    with pytest.raises(StrategySearchError, match="strictly increasing"):
        _build_folds("2025-01-01", ["2024-07-01"], "2026-01-01")


def test_best_non_sar_supplement_is_selected_from_development_only(
    tmp_path: Path,
) -> None:
    rows = [
        _row(family="ema_price", pnl=6.0),
        _row(family="donchian", pnl=5.0),
        _row(family="ema_price", pnl=7.0, positive_folds=2),
        _row(family="sar", pnl=9.0),
    ]
    path = tmp_path / "precision_results.csv"
    pd.DataFrame(rows).to_csv(path, index=False)

    task = _load_best_non_sar_task(path)

    assert task.role == "best_non_sar_development"
    assert task.strategy.family is StrategyFamily.EMA_PRICE


def test_promotion_locks_maximum_qualified_intermediate_candidate(
    tmp_path: Path,
) -> None:
    confirmation = tmp_path / "confirmation.json"
    confirmation.write_text(
        json.dumps(
            {
                "candidate_strategy": StrategySpec(StrategyFamily.SAR, "1h").as_dict(),
                "candidate_execution": {
                    "take_profit_roe": 15,
                    "stop_loss_roe": 3,
                    "trailing_activation_roe": 7,
                    "signal_exit_count": 2,
                    "leverage": 1,
                },
                "supplemental": {
                    "tasks": [
                        {
                            "role": "best_non_sar_development",
                            "strategy": StrategySpec(
                                StrategyFamily.MOMENTUM, "4h", lookback=42
                            ).as_dict(),
                            "execution": {
                                "take_profit_roe": 8,
                                "stop_loss_roe": 6,
                                "trailing_activation_roe": 7,
                                "signal_exit_count": 2,
                                "leverage": 1,
                            },
                        }
                    ]
                },
                "rows": [
                    {
                        "dataset": dataset,
                        "role": role,
                        "total_net_pnl": pnl,
                        "adverse_funding_1bps_net_pnl": pnl - 0.1,
                        "max_drawdown_percent": 0.5,
                    }
                    for dataset in ("A", "B", "C")
                    for role, pnl in (
                        ("locked_candidate", 1.0),
                        ("best_non_sar_development", 2.0),
                    )
                ],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "promoted.json"

    promoted = promote_final_candidate(
        confirmation_path=confirmation,
        output_path=output,
    )

    assert promoted["candidate_strategy"]["family"] == "momentum"
    assert output.is_file()
