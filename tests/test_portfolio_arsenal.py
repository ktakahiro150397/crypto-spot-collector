import pandas as pd
import pytest

from crypto_spot_collector.backtesting.portfolio_arsenal import (
    PortfolioCosts,
    PortfolioFamily,
    PortfolioMarket,
    PortfolioSide,
    PortfolioSpec,
    build_portfolio_grid,
    evaluate_portfolio,
    prepare_weights,
    select_candidate,
)


def _market() -> PortfolioMarket:
    index = pd.date_range("2026-01-01", periods=20, freq="4h", tz="UTC")
    closes = pd.DataFrame(
        {
            "A": [100 + index for index in range(20)],
            "B": [100 - index * 0.5 for index in range(20)],
        },
        index=index,
        dtype=float,
    )
    opens = closes.shift(1).fillna(closes.iloc[0])
    return PortfolioMarket(
        "4h",
        opens,
        pd.DataFrame(closes.to_numpy() + 0.5, index=index, columns=closes.columns),
        pd.DataFrame(closes.to_numpy() - 0.5, index=index, columns=closes.columns),
        closes,
    )


def test_grid_covers_distinct_portfolio_families() -> None:
    grid = build_portfolio_grid()

    assert {spec.family for spec in grid} == set(PortfolioFamily)
    assert len({spec.identifier for spec in grid}) == len(grid)
    assert len(grid) >= 300


def test_signal_is_executed_one_candle_after_it_becomes_available() -> None:
    market = _market()
    spec = PortfolioSpec(
        PortfolioFamily.TIME_SERIES_MOMENTUM,
        "4h",
        0.5,
        PortfolioSide.BOTH,
    )
    close_time_weights = prepare_weights(market, spec)

    assert close_time_weights.iloc[2].eq(0).all()
    assert close_time_weights.iloc[3]["A"] > 0
    result = evaluate_portfolio(market, spec, PortfolioCosts(gross_notional=10))
    assert result["position_change_count"] > 0
    assert result["transaction_cost"] > 0
    assert sum(result["symbol_net_pnl"].values()) == pytest.approx(result["net_pnl"])
    assert sum(result["symbol_double_cost_net_pnl"].values()) == pytest.approx(
        result["double_cost_net_pnl"]
    )


def test_volatility_management_never_increases_base_gross_exposure() -> None:
    spec = PortfolioSpec(
        PortfolioFamily.EMA_TREND,
        "4h",
        0.5,
        volatility_managed=True,
    )

    weights = prepare_weights(_market(), spec)

    assert weights.abs().sum(axis=1).le(1.0 + 1e-12).all()


def test_selector_uses_robustness_before_raw_net_profit() -> None:
    common = {
        "timeframe": "4h",
        "lookback_days": 3.0,
        "side": "both",
        "top_k": 1,
        "absolute_gate": False,
        "volatility_managed": False,
        "stressed_net_pnl": 1.0,
        "double_cost_net_pnl": 1.0,
        "max_drawdown_percent": 0.2,
        "rebalance_count": 20,
        "position_change_count": 40,
        "transaction_cost": 1.0,
        "adverse_funding_cost": 0.1,
    }
    rows = pd.DataFrame(
        [
            {
                **common,
                "candidate": "unstable",
                "neighborhood": "unstable",
                "family": "time_series_momentum",
                "fold": "a",
                "net_pnl": 100.0,
                "double_cost_net_pnl": -1.0,
            },
            {
                **common,
                "candidate": "stable",
                "neighborhood": "stable",
                "family": "ema_trend",
                "fold": "a",
                "net_pnl": 2.0,
            },
        ]
    )

    assert select_candidate(rows)["candidate"] == "stable"
