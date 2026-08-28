"""Evaluate fixed entry candidates before changing the trailing-stop exit."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from loguru import logger

from crypto_spot_collector.backtesting.data import (
    CandleSeries,
    CandleSeriesKey,
    load_ohlcv_csv,
    select_period,
)
from crypto_spot_collector.backtesting.engine import (
    BacktestConfig,
    BacktestResult,
    PerpetualSarBacktester,
)
from crypto_spot_collector.backtesting.regime import (
    EntryFilterConfig,
    prepare_entry_filter,
)
from crypto_spot_collector.backtesting.strategy_signals import (
    SideMode,
    StrategyFamily,
    StrategySpec,
    prepare_strategy_signals,
)


@dataclass(frozen=True)
class DatasetSpec:
    label: str
    symbol: str
    paths: tuple[Path, ...]


@dataclass(frozen=True)
class Candidate:
    identifier: str
    description: str
    strategy: StrategySpec
    entry_filter: EntryFilterConfig | None = None


@dataclass(frozen=True)
class Fold:
    identifier: str
    start: str
    end: str


FOLDS = (
    Fold("2025-H1", "2025-01-01T00:00:00Z", "2025-07-01T00:00:00Z"),
    Fold("2025-H2", "2025-07-01T00:00:00Z", "2026-01-01T00:00:00Z"),
    Fold("2026-H1", "2026-01-01T00:00:00Z", "2026-07-01T00:00:00Z"),
    Fold("2026-late", "2026-07-01T00:00:00Z", "2026-08-24T00:00:00Z"),
)


def candidates() -> tuple[Candidate, ...]:
    """Return the fixed, pre-registered entry candidates."""

    return (
        Candidate(
            "control_30m_sar",
            "30m SAR control (four-candle entry confirmation)",
            StrategySpec(
                StrategyFamily.SAR,
                "30m",
                SideMode.BOTH,
                sar_consecutive_count=4,
            ),
        ),
        Candidate(
            "1h_sar_4h_ema100_adx20",
            "1h SAR with completed 4h EMA100 direction and ADX >= 20",
            StrategySpec(
                StrategyFamily.SAR,
                "1h",
                SideMode.BOTH,
                sar_consecutive_count=4,
            ),
            EntryFilterConfig(
                timeframe="4h",
                ema_period=100,
                adx_period=14,
                adx_threshold=20,
            ),
        ),
        Candidate(
            "4h_momentum_42_1pct",
            "4h 42-candle time-series momentum with a 1% threshold",
            StrategySpec(
                StrategyFamily.MOMENTUM,
                "4h",
                SideMode.BOTH,
                confirmation=1,
                lookback=42,
                momentum_threshold=0.01,
            ),
        ),
        Candidate(
            "4h_ema200",
            "4h close direction versus EMA200",
            StrategySpec(
                StrategyFamily.EMA_PRICE,
                "4h",
                SideMode.BOTH,
                confirmation=1,
                ema_period=200,
            ),
        ),
    )


def fixed_config(candidate: Candidate, variant: str = "baseline") -> BacktestConfig:
    """Build the execution contract shared by every entry candidate."""

    common: dict[str, object] = {
        "signal_timeframe": candidate.strategy.signal_timeframe,
        "initial_equity": 1_000.0,
        "order_notional": 12.5,
        "leverage": 1,
        "take_profit_roe": 15.0,
        "stop_loss_roe": 15.0,
        "sar_consecutive_count": candidate.strategy.sar_consecutive_count,
        "sar_close_consecutive_count": 2,
        "taker_fee_bps": 4.322,
        "slippage_bps": 1.0,
        "allow_proxy_data": True,
        "equity_curve_interval_minutes": 60,
    }
    if variant == "baseline":
        return BacktestConfig(
            **common,
            trailing_activation_roe=7.0,
            profit_lock_floor_roe=0.0,
            trailing_interval_minutes=3,
        )
    if variant == "profit_lock":
        return BacktestConfig(
            **common,
            trailing_activation_roe=0.25,
            profit_lock_floor_roe=0.15,
            trailing_interval_minutes=1,
        )
    raise ValueError(f"unsupported variant: {variant}")


def select_candidate(aggregate: pd.DataFrame) -> str:
    """Select a stable candidate deterministically, even if no candidate passes."""

    required = {
        "candidate",
        "passed",
        "positive_fold_count",
        "profitable_symbols",
        "adverse_funding_net_pnl",
        "worst_fold_net_pnl",
        "max_symbol_drawdown_percent",
        "net_pnl",
    }
    missing = required.difference(aggregate.columns)
    if missing:
        raise ValueError("aggregate is missing columns: " + ", ".join(sorted(missing)))
    ranked = aggregate.sort_values(
        by=[
            "passed",
            "positive_fold_count",
            "profitable_symbols",
            "adverse_funding_net_pnl",
            "worst_fold_net_pnl",
            "max_symbol_drawdown_percent",
            "net_pnl",
            "candidate",
        ],
        ascending=[False, False, False, False, False, True, False, True],
        kind="stable",
    )
    if ranked.empty:
        raise ValueError("cannot select from empty aggregate")
    return str(ranked.iloc[0]["candidate"])


def _dataset(value: str) -> DatasetSpec:
    parts = value.split(",")
    if len(parts) < 3:
        raise argparse.ArgumentTypeError("dataset must be LABEL,SYMBOL,PATH[,PATH...]")
    return DatasetSpec(parts[0], parts[1], tuple(Path(item) for item in parts[2:]))


def _load_dataset(spec: DatasetSpec) -> CandleSeries:
    key = CandleSeriesKey("binance", "perpetual", spec.symbol, "1m")
    components = [load_ohlcv_csv(path, key=key) for path in spec.paths]
    frame = pd.concat([component.frame for component in components], ignore_index=True)
    provenance = {
        "components": [component.provenance for component in components],
    }
    return CandleSeries.from_frame(key, frame, provenance=provenance)


def _adverse_funding_cost(
    trades: pd.DataFrame,
    *,
    rate: float = 0.0001,
    interval_hours: int = 8,
) -> float:
    if trades.empty:
        return 0.0
    interval = pd.Timedelta(hours=interval_hours)
    cost = 0.0
    for trade in trades.itertuples(index=False):
        entry = pd.Timestamp(trade.entry_time)
        exit_time = pd.Timestamp(trade.exit_time)
        first_event = entry.ceil(interval)
        if first_event <= entry:
            first_event += interval
        event_count = max(0, math.floor((exit_time - first_event) / interval) + 1)
        cost += float(trade.entry_price) * float(trade.quantity) * rate * event_count
    return cost


def _result_row(
    *,
    candidate: Candidate,
    dataset: str,
    fold: str,
    variant: str,
    result: BacktestResult,
) -> dict[str, object]:
    trades = result.trades
    wins = trades.loc[trades["net_pnl"] > 0, "net_pnl"]
    losses = trades.loc[trades["net_pnl"] < 0, "net_pnl"]
    funding_cost = _adverse_funding_cost(trades)
    net_pnl = float(result.summary["total_net_pnl"])
    return {
        "candidate": candidate.identifier,
        "dataset": dataset,
        "fold": fold,
        "variant": variant,
        "net_pnl": net_pnl,
        "adverse_funding_cost": funding_cost,
        "adverse_funding_net_pnl": net_pnl - funding_cost,
        "gross_profit": float(wins.sum()),
        "gross_loss": float(losses.sum()),
        "max_drawdown_percent": float(result.summary["max_drawdown_percent"]),
        "trade_count": int(result.summary["trade_count"]),
        "win_rate_percent": float(result.summary["win_rate_percent"]),
        "fee_total": float(trades["entry_fee"].sum() + trades["exit_fee"].sum()),
        "long_net_pnl": float(trades.loc[trades["side"] == "long", "net_pnl"].sum()),
        "short_net_pnl": float(trades.loc[trades["side"] == "short", "net_pnl"].sum()),
        "stop_loss_count": int(trades["exit_reason"].eq("stop_loss").sum()),
        "trailing_stop_count": int(trades["exit_reason"].eq("trailing_stop").sum()),
        "take_profit_count": int(trades["exit_reason"].eq("take_profit").sum()),
        "opposite_signal_count": int(
            trades["exit_reason"].isin(["opposite_signal", "opposite_sar"]).sum()
        ),
    }


def _candidate_aggregate(detail: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    baseline = detail.loc[detail["variant"] == "baseline"]
    for candidate, group in baseline.groupby("candidate", sort=False):
        fold_net = group.groupby("fold", sort=False)["net_pnl"].sum()
        symbol_net = group.groupby("dataset", sort=False)["net_pnl"].sum()
        gross_profit = float(group["gross_profit"].sum())
        gross_loss = float(group["gross_loss"].sum())
        net_pnl = float(group["net_pnl"].sum())
        funding_cost = float(group["adverse_funding_cost"].sum())
        positive_fold_count = int(fold_net.gt(0).sum())
        profitable_symbols = int(symbol_net.gt(0).sum())
        profit_factor = gross_profit / abs(gross_loss) if gross_loss < 0 else None
        trade_count = int(group["trade_count"].sum())
        adverse_funding_net = net_pnl - funding_cost
        checks = {
            "all_folds_positive": positive_fold_count == len(FOLDS),
            "four_of_six_symbols_positive": profitable_symbols >= 4,
            "profit_factor_above_one": profit_factor is not None and profit_factor > 1,
            "adverse_funding_positive": adverse_funding_net > 0,
            "minimum_120_trades": trade_count >= 120,
        }
        records.append(
            {
                "candidate": str(candidate),
                "net_pnl": net_pnl,
                "adverse_funding_cost": funding_cost,
                "adverse_funding_net_pnl": adverse_funding_net,
                "profit_factor": profit_factor,
                "trade_count": trade_count,
                "positive_fold_count": positive_fold_count,
                "profitable_symbols": profitable_symbols,
                "worst_fold_net_pnl": float(fold_net.min()),
                "max_symbol_drawdown_percent": float(
                    group["max_drawdown_percent"].max()
                ),
                **checks,
                "passed": all(checks.values()),
            }
        )
    return pd.DataFrame.from_records(records)


def _variant_aggregate(detail: pd.DataFrame, selected: str) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    selected_rows = detail.loc[detail["candidate"] == selected]
    for variant, group in selected_rows.groupby("variant", sort=False):
        fold_net = group.groupby("fold", sort=False)["net_pnl"].sum()
        symbol_net = group.groupby("dataset", sort=False)["net_pnl"].sum()
        gross_profit = float(group["gross_profit"].sum())
        gross_loss = float(group["gross_loss"].sum())
        records.append(
            {
                "candidate": selected,
                "variant": str(variant),
                "net_pnl": float(group["net_pnl"].sum()),
                "adverse_funding_net_pnl": float(
                    group["adverse_funding_net_pnl"].sum()
                ),
                "profit_factor": (
                    gross_profit / abs(gross_loss) if gross_loss < 0 else None
                ),
                "trade_count": int(group["trade_count"].sum()),
                "positive_fold_count": int(fold_net.gt(0).sum()),
                "profitable_symbols": int(symbol_net.gt(0).sum()),
                "worst_fold_net_pnl": float(fold_net.min()),
                "max_symbol_drawdown_percent": float(
                    group["max_drawdown_percent"].max()
                ),
                "fee_total": float(group["fee_total"].sum()),
                "trailing_stop_count": int(group["trailing_stop_count"].sum()),
            }
        )
    return pd.DataFrame.from_records(records)


def _render_table(frame: pd.DataFrame, columns: list[tuple[str, str]]) -> list[str]:
    header = "| " + " | ".join(label for _, label in columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, divider]
    for row in frame.to_dict(orient="records"):
        values: list[str] = []
        for key, _ in columns:
            value = row[key]
            if isinstance(value, bool):
                values.append("yes" if value else "no")
            elif isinstance(value, float):
                values.append(
                    f"{value:+.6f}" if key.endswith("pnl") else f"{value:.6f}"
                )
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return lines


def _report(
    aggregate: pd.DataFrame,
    variants: pd.DataFrame,
    fold_rows: pd.DataFrame,
    selected: str,
) -> str:
    passed = bool(aggregate.loc[aggregate["candidate"] == selected, "passed"].iloc[0])
    selection_label = (
        "retrospective entry-gate winner" if passed else "diagnostic winner"
    )
    baseline = variants.loc[variants["variant"] == "baseline"].iloc[0]
    profit_lock = variants.loc[variants["variant"] == "profit_lock"].iloc[0]
    profit_lock_improved = float(profit_lock["net_pnl"]) > float(baseline["net_pnl"])
    lines = [
        "# Fixed-entry robustness evaluation",
        "",
        "Four pre-registered entry definitions were compared on Binance USD-M "
        "one-minute proxy candles for BTC, ETH, SOL, XRP, BNB, and DOGE. Every "
        "symbol/fold starts flat with indicators rebuilt only from that fold.",
        "",
        "Execution is fixed at 1x, 12.5 USDT notional, TP/SL 15% ROE, trailing "
        "activation 7%, three-minute observation, 4.322 bps taker fee per fill, "
        "and one bp adverse slippage per fill. The stress test additionally "
        "charges one bp every eight hours for every held trade.",
        "",
        "Higher-timeframe filters become usable only when their candle closes. "
        "The 4h EMA100/ADX20 filter is therefore causally aligned to the 1h SAR.",
        "The opposite-direction exit uses two completed signal decisions for every "
        "candidate. That is one hour for 30m, two hours for 1h, and eight hours for "
        "4h signals, so this compares complete signal contracts rather than a pure "
        "entry-only attribution.",
        "",
        "## Candidate result",
        "",
        *_render_table(
            aggregate,
            [
                ("candidate", "candidate"),
                ("net_pnl", "net PnL"),
                ("adverse_funding_net_pnl", "stressed net"),
                ("profit_factor", "PF"),
                ("trade_count", "trades"),
                ("positive_fold_count", "+ folds /4"),
                ("profitable_symbols", "+ symbols /6"),
                ("worst_fold_net_pnl", "worst fold"),
                ("max_symbol_drawdown_percent", "worst symbol DD %"),
                ("passed", "passed"),
            ],
        ),
        "",
        "A candidate passes only with all four folds positive, at least four of "
        "six symbols positive, PF above one, positive stressed PnL, and at least "
        "120 trades.",
        "",
        f"Selected {selection_label}: `{selected}`.",
        "",
        "## Fold totals",
        "",
        *_render_table(
            fold_rows,
            [
                ("candidate", "candidate"),
                ("fold", "fold"),
                ("net_pnl", "net PnL"),
                ("adverse_funding_net_pnl", "stressed net"),
                ("trade_count", "trades"),
            ],
        ),
        "",
        "## Exit ablation on selected entry",
        "",
        "Only the selected entry is rerun with the proposed profit lock: 0.25% "
        "activation, 0.15% floor, and one-minute observation.",
        "",
        *_render_table(
            variants,
            [
                ("variant", "variant"),
                ("net_pnl", "net PnL"),
                ("adverse_funding_net_pnl", "stressed net"),
                ("profit_factor", "PF"),
                ("trade_count", "trades"),
                ("positive_fold_count", "+ folds /4"),
                ("profitable_symbols", "+ symbols /6"),
                ("worst_fold_net_pnl", "worst fold"),
                ("max_symbol_drawdown_percent", "worst symbol DD %"),
            ],
        ),
        "",
        (
            "The proposed profit lock improved aggregate net PnL."
            if profit_lock_improved
            else "The proposed profit lock reduced aggregate net PnL and is rejected."
        ),
        "",
        "The late-2026 fold is shorter than the half-year folds. Results use "
        "Binance proxy candles rather than Hyperliquid fills, order-book state, "
        "or actual funding. One-minute OHLC also cannot resolve intraminute event "
        "ordering. Candidate definitions were also chosen in earlier exploration "
        "that overlaps this history, so these folds are robustness slices, not a "
        "never-seen holdout. This is an offline rejection gate, not deployment "
        "approval.",
    ]
    return "\n".join(lines) + "\n"


def _fold_aggregate(detail: pd.DataFrame) -> pd.DataFrame:
    baseline = detail.loc[detail["variant"] == "baseline"]
    return (
        baseline.groupby(["candidate", "fold"], sort=False)
        .agg(
            net_pnl=("net_pnl", "sum"),
            adverse_funding_net_pnl=("adverse_funding_net_pnl", "sum"),
            trade_count=("trade_count", "sum"),
        )
        .reset_index()
    )


def _run_one(
    series: CandleSeries,
    candidate: Candidate,
    variant: str,
) -> BacktestResult:
    config = fixed_config(candidate, variant)
    prepared_signals = prepare_strategy_signals(series, candidate.strategy)
    prepared_filter = (
        prepare_entry_filter(series, candidate.entry_filter)
        if candidate.entry_filter is not None
        else None
    )
    return PerpetualSarBacktester(config).run(
        series,
        prepared_signals=prepared_signals,
        prepared_entry_filter=prepared_filter,
    )


def _write_outputs(
    *,
    output: Path,
    detail: pd.DataFrame,
    aggregate: pd.DataFrame,
    variants: pd.DataFrame,
    selected: str,
    dataset_specs: list[DatasetSpec],
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    folds = _fold_aggregate(detail)
    detail.to_csv(output / "per_symbol_fold.csv", index=False)
    aggregate.to_csv(output / "candidate_aggregate.csv", index=False)
    folds.to_csv(output / "fold_aggregate.csv", index=False)
    variants.to_csv(output / "selected_exit_variants.csv", index=False)
    report = _report(aggregate, variants, folds, selected)
    (output / "report.md").write_text(report, encoding="utf-8")
    source_hashes = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for spec in dataset_specs
        for path in spec.paths
    }
    summary: dict[str, Any] = {
        "schema_version": 1,
        "datasets": [asdict(spec) for spec in dataset_specs],
        "source_sha256": source_hashes,
        "folds": [asdict(fold) for fold in FOLDS],
        "candidates": [
            {
                "identifier": candidate.identifier,
                "description": candidate.description,
                "strategy": candidate.strategy.as_dict(),
                "entry_filter": (
                    asdict(candidate.entry_filter)
                    if candidate.entry_filter is not None
                    else None
                ),
            }
            for candidate in candidates()
        ],
        "selected_candidate": selected,
        "candidate_aggregate": aggregate.to_dict(orient="records"),
        "selected_exit_variants": variants.to_dict(orient="records"),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", action="append", type=_dataset, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    logger.disable("crypto_spot_collector")
    dataset_specs: list[DatasetSpec] = args.dataset
    datasets = {spec.label: _load_dataset(spec) for spec in dataset_specs}
    candidate_by_id = {item.identifier: item for item in candidates()}
    records: list[dict[str, object]] = []
    for fold in FOLDS:
        for label, full_series in datasets.items():
            series = select_period(full_series, start=fold.start, end=fold.end)
            for candidate in candidate_by_id.values():
                result = _run_one(series, candidate, "baseline")
                records.append(
                    _result_row(
                        candidate=candidate,
                        dataset=label,
                        fold=fold.identifier,
                        variant="baseline",
                        result=result,
                    )
                )

    baseline_detail = pd.DataFrame.from_records(records)
    aggregate = _candidate_aggregate(baseline_detail)
    selected = select_candidate(aggregate)
    selected_candidate = candidate_by_id[selected]
    for fold in FOLDS:
        for label, full_series in datasets.items():
            series = select_period(full_series, start=fold.start, end=fold.end)
            result = _run_one(series, selected_candidate, "profit_lock")
            records.append(
                _result_row(
                    candidate=selected_candidate,
                    dataset=label,
                    fold=fold.identifier,
                    variant="profit_lock",
                    result=result,
                )
            )

    detail = pd.DataFrame.from_records(records)
    variants = _variant_aggregate(detail, selected)
    _write_outputs(
        output=args.output_dir,
        detail=detail,
        aggregate=aggregate,
        variants=variants,
        selected=selected,
        dataset_specs=dataset_specs,
    )
    print(args.output_dir / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
