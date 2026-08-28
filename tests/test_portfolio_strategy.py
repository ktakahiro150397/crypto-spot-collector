from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from crypto_spot_collector.backtesting.portfolio_arsenal import (
    PortfolioFamily,
    PortfolioMarket,
    PortfolioSide,
    PortfolioSpec,
    prepare_weights,
)
from crypto_spot_collector.trading.portfolio_strategy import (
    DAY_MS,
    DecisionStatus,
    PortfolioDecision,
    PortfolioTarget,
    RebalancePhase,
    SQLitePortfolioDecisionStore,
    TrendEnsembleConfig,
    calculate_trend_ensemble_target,
    plan_rebalance,
)

SYMBOLS = ("BTC/USDC:USDC", "ETH/USDC:USDC", "SOL/USDC:USDC")


def market(rows: int = 100) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    index = pd.date_range("2026-01-01", periods=rows, freq="1D", tz="UTC")
    step = np.arange(rows, dtype=float)
    close = pd.DataFrame(
        {
            SYMBOLS[0]: 100 * np.exp(0.008 * step + 0.02 * np.sin(step / 3)),
            SYMBOLS[1]: 200 * np.exp(-0.006 * step + 0.03 * np.cos(step / 5)),
            SYMBOLS[2]: 50 * np.exp(0.001 * step + 0.08 * np.sin(step / 2)),
        },
        index=index,
    )
    return close * 1.02, close * 0.98, close


def config(**overrides: object) -> TrendEnsembleConfig:
    values: dict[str, object] = {
        "symbols": SYMBOLS,
        "max_positions": len(SYMBOLS),
    }
    values.update(overrides)
    return TrendEnsembleConfig(**values)  # type: ignore[arg-type]


def calculate(
    *,
    highs: pd.DataFrame | None = None,
    lows: pd.DataFrame | None = None,
    closes: pd.DataFrame | None = None,
    observed_at_ms: int | None = None,
    settings: TrendEnsembleConfig | None = None,
) -> PortfolioDecision:
    default_highs, default_lows, default_closes = market()
    actual_highs = default_highs if highs is None else highs
    actual_lows = default_lows if lows is None else lows
    actual_closes = default_closes if closes is None else closes
    final_close_ms = int(actual_closes.index[-1].timestamp() * 1_000) + DAY_MS
    return calculate_trend_ensemble_target(
        highs=actual_highs,
        lows=actual_lows,
        closes=actual_closes,
        observed_at_ms=final_close_ms if observed_at_ms is None else observed_at_ms,
        config=config() if settings is None else settings,
    )


def manual_decision(targets: dict[str, float]) -> PortfolioDecision:
    target_rows = tuple(
        PortfolioTarget(
            symbol=symbol,
            momentum_direction=1 if value > 0 else -1 if value < 0 else 0,
            ema_direction=1 if value > 0 else -1 if value < 0 else 0,
            donchian_direction=0,
            votes=2 if value > 0 else -2 if value < 0 else 0,
            daily_volatility=0.02,
            weight=value / 75,
            signed_notional_usdc=value,
        )
        for symbol, value in targets.items()
    )
    return PortfolioDecision(
        decision_id="decision-1",
        strategy="daily_trend_ensemble_v1",
        candle_close_ms=DAY_MS,
        observed_at_ms=DAY_MS,
        gross_notional_usdc=75,
        targets=target_rows,
    )


def test_live_target_matches_backtest_weight_formula() -> None:
    highs, lows, closes = market()
    decision = calculate(highs=highs, lows=lows, closes=closes)
    backtest_market = PortfolioMarket(
        timeframe="1d",
        opens=closes,
        highs=highs,
        lows=lows,
        closes=closes,
    )
    expected = prepare_weights(
        backtest_market,
        PortfolioSpec(
            PortfolioFamily.TREND_ENSEMBLE,
            "1d",
            28,
            PortfolioSide.BOTH,
            volatility_managed=True,
        ),
    ).iloc[-1]

    actual = pd.Series({target.symbol: target.weight for target in decision.targets})
    pd.testing.assert_series_equal(actual, expected, check_names=False)
    assert sum(abs(value) for value in decision.target_notionals.values()) <= 75


def test_target_is_deterministic_and_uses_completed_candle() -> None:
    highs, lows, closes = market()
    first = calculate(highs=highs, lows=lows, closes=closes)
    second = calculate(highs=highs.copy(), lows=lows.copy(), closes=closes.copy())

    assert first == second
    with pytest.raises(ValueError, match="not complete"):
        calculate(
            highs=highs,
            lows=lows,
            closes=closes,
            observed_at_ms=first.candle_close_ms - 1,
        )


def test_target_rejects_stale_or_noncanonical_daily_data() -> None:
    highs, lows, closes = market()
    final_close_ms = int(closes.index[-1].timestamp() * 1_000) + DAY_MS
    with pytest.raises(ValueError, match="stale"):
        calculate(
            highs=highs,
            lows=lows,
            closes=closes,
            observed_at_ms=final_close_ms + 21_600_001,
        )

    shifted_closes = closes.shift(freq="1h")
    with pytest.raises(ValueError, match="00:00 UTC"):
        calculate(
            highs=highs.shift(freq="1h"),
            lows=lows.shift(freq="1h"),
            closes=shifted_closes,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("gap", "contiguous"),
        ("missing", "finite and positive"),
        ("unaligned", "timestamps do not align"),
        ("wrong_symbol", "exactly match"),
        ("bad_range", "outside the high-low"),
    ],
)
def test_target_rejects_unsafe_market_data(mutation: str, message: str) -> None:
    highs, lows, closes = market()
    if mutation == "gap":
        highs, lows, closes = (
            highs.drop(highs.index[10]),
            lows.drop(lows.index[10]),
            closes.drop(closes.index[10]),
        )
    elif mutation == "missing":
        closes.iloc[10, 0] = np.nan
    elif mutation == "unaligned":
        highs = highs.shift(freq="1D")
    elif mutation == "wrong_symbol":
        closes = closes.rename(columns={SYMBOLS[0]: "DOGE/USDC:USDC"})
    else:
        highs.iloc[10, 0] = closes.iloc[10, 0] * 0.99

    with pytest.raises(ValueError, match=message):
        calculate(highs=highs, lows=lows, closes=closes)


def test_target_rejects_insufficient_warmup() -> None:
    highs, lows, closes = market(55)
    with pytest.raises(ValueError, match="at least 56"):
        calculate(highs=highs, lows=lows, closes=closes)


def test_rebalance_reduces_and_closes_before_any_increase() -> None:
    decision = manual_decision({SYMBOLS[0]: -30, SYMBOLS[1]: 25, SYMBOLS[2]: 20})
    plan = plan_rebalance(
        decision,
        {SYMBOLS[0]: 20, SYMBOLS[1]: 35},
        config(),
    )

    assert plan.phase is RebalancePhase.REDUCE
    assert plan.requires_position_refresh is True
    assert [
        (action.symbol, action.side, action.notional_usdc) for action in plan.actions
    ] == [
        (SYMBOLS[0], "sell", 20),
        (SYMBOLS[1], "sell", 10),
    ]
    assert all(action.reduce_only for action in plan.actions)


def test_rebalance_opens_only_after_refreshed_flat_snapshot() -> None:
    decision = manual_decision({SYMBOLS[0]: -30, SYMBOLS[1]: 25, SYMBOLS[2]: 20})
    plan = plan_rebalance(
        decision,
        {SYMBOLS[1]: 25},
        config(),
    )

    assert plan.phase is RebalancePhase.INCREASE
    assert [
        (action.symbol, action.side, action.notional_usdc) for action in plan.actions
    ] == [
        (SYMBOLS[0], "sell", 30),
        (SYMBOLS[2], "buy", 20),
    ]
    assert not any(action.reduce_only for action in plan.actions)


def test_rebalance_caps_each_action_and_requires_another_snapshot() -> None:
    decision = manual_decision({SYMBOLS[0]: -30, SYMBOLS[1]: 25, SYMBOLS[2]: 20})
    settings = config(
        max_order_notional_usdc=10,
        max_symbol_notional_usdc=75,
    )

    reduction = plan_rebalance(decision, {SYMBOLS[0]: 20}, settings)
    increase = plan_rebalance(decision, {}, settings)

    assert reduction.actions[0].notional_usdc == 10
    assert reduction.actions[0].reduce_only is True
    assert increase.actions[0].notional_usdc == 10
    assert increase.actions[0].reduce_only is False
    assert reduction.requires_position_refresh is True
    assert increase.requires_position_refresh is True


def test_rebalance_is_complete_inside_tolerance() -> None:
    decision = manual_decision({SYMBOLS[0]: 30, SYMBOLS[1]: 25, SYMBOLS[2]: 20})
    plan = plan_rebalance(
        decision,
        {SYMBOLS[0]: 30.1, SYMBOLS[1]: 24.9, SYMBOLS[2]: 20},
        config(rebalance_tolerance_usdc=0.25),
    )

    assert plan.phase is RebalancePhase.COMPLETE
    assert plan.actions == ()
    assert plan.requires_position_refresh is False


def test_tolerance_never_hides_small_opposite_or_unwanted_position() -> None:
    reverse = manual_decision({SYMBOLS[0]: -30, SYMBOLS[1]: 25, SYMBOLS[2]: 20})
    flatten = manual_decision({SYMBOLS[0]: 0, SYMBOLS[1]: 25, SYMBOLS[2]: 20})
    settings = config(rebalance_tolerance_usdc=10)

    reverse_plan = plan_rebalance(reverse, {SYMBOLS[0]: 5}, settings)
    flatten_plan = plan_rebalance(flatten, {SYMBOLS[0]: 5}, settings)

    assert reverse_plan.phase is RebalancePhase.REDUCE
    assert flatten_plan.phase is RebalancePhase.REDUCE
    assert reverse_plan.actions[0].notional_usdc == 5
    assert flatten_plan.actions[0].notional_usdc == 5
    assert reverse_plan.actions[0].reduce_only is True
    assert flatten_plan.actions[0].reduce_only is True


def test_tolerance_never_permits_live_gross_above_hard_limit() -> None:
    target = manual_decision({SYMBOLS[0]: 30, SYMBOLS[1]: 25, SYMBOLS[2]: 20})
    plan = plan_rebalance(
        target,
        {SYMBOLS[0]: 35, SYMBOLS[1]: 30, SYMBOLS[2]: 25},
        config(rebalance_tolerance_usdc=10),
    )

    assert plan.phase is RebalancePhase.REDUCE
    assert [action.notional_usdc for action in plan.actions] == [5, 5, 5]
    assert all(action.reduce_only for action in plan.actions)


@pytest.mark.parametrize(
    "positions",
    [
        {"DOGE/USDC:USDC": 10},
        {SYMBOLS[0]: np.nan},
        {SYMBOLS[0].lower(): 10, SYMBOLS[0]: 10},
    ],
)
def test_rebalance_rejects_untrusted_position_snapshots(
    positions: dict[str, float],
) -> None:
    decision = manual_decision({SYMBOLS[0]: 30, SYMBOLS[1]: 25, SYMBOLS[2]: 20})
    with pytest.raises(ValueError):
        plan_rebalance(decision, positions, config())


def test_rebalance_rejects_decision_above_runtime_limit() -> None:
    decision = manual_decision({SYMBOLS[0]: 30, SYMBOLS[1]: 25, SYMBOLS[2]: 20})
    unsafe = replace(
        decision,
        targets=(replace(decision.targets[0], signed_notional_usdc=31),)
        + decision.targets[1:],
    )
    with pytest.raises(ValueError, match="gross notional"):
        plan_rebalance(unsafe, {}, config())


def test_store_is_idempotent_and_restores_exact_target(tmp_path: object) -> None:
    store = SQLitePortfolioDecisionStore(str(tmp_path) + "/portfolio.sqlite3")
    decision = calculate()

    first, created = store.prepare(decision)
    duplicate, created_again = store.prepare(decision)

    assert created is True
    assert created_again is False
    assert duplicate == first
    assert store.latest() == first


def test_store_rejects_conflict_and_unfinished_new_candle(tmp_path: object) -> None:
    store = SQLitePortfolioDecisionStore(str(tmp_path) + "/portfolio.sqlite3")
    decision = calculate()
    store.prepare(decision)

    with pytest.raises(ValueError, match="conflicting target"):
        store.prepare(replace(decision, observed_at_ms=decision.observed_at_ms + 1))
    with pytest.raises(RuntimeError, match="earlier portfolio decision"):
        store.prepare(
            replace(
                decision,
                decision_id="later",
                candle_close_ms=decision.candle_close_ms + DAY_MS,
                observed_at_ms=decision.observed_at_ms + DAY_MS,
            )
        )


def test_store_tracks_restart_safe_phase_transitions(tmp_path: object) -> None:
    store = SQLitePortfolioDecisionStore(str(tmp_path) + "/portfolio.sqlite3")
    decision = calculate()
    store.prepare(decision)

    reducing = store.transition(decision.decision_id, DecisionStatus.REDUCING)
    assert reducing.status is DecisionStatus.REDUCING
    assert store.latest() == reducing
    increasing = store.transition(decision.decision_id, DecisionStatus.INCREASING)
    complete = store.transition(decision.decision_id, DecisionStatus.COMPLETE)
    assert increasing.status is DecisionStatus.INCREASING
    assert complete.status is DecisionStatus.COMPLETE
    with pytest.raises(ValueError, match="invalid portfolio decision transition"):
        store.transition(decision.decision_id, DecisionStatus.REDUCING)
