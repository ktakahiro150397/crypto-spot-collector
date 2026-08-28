"""Run the broad cross-asset portfolio arsenal on local Binance proxy data."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from crypto_spot_collector.backtesting.data import (
    CandleSeries,
    CandleSeriesKey,
    load_ohlcv_csv,
    resample_ohlcv,
    select_period,
)
from crypto_spot_collector.backtesting.portfolio_arsenal import (
    PortfolioCosts,
    PortfolioMarket,
    PortfolioSpec,
    aggregate_candidates,
    build_portfolio_grid,
    evaluate_portfolio,
    family_leaders,
    select_candidate,
)


@dataclass(frozen=True)
class DatasetSpec:
    label: str
    symbol: str
    paths: tuple[Path, ...]


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


def _dataset(value: str) -> DatasetSpec:
    parts = value.split(",")
    if len(parts) < 3:
        raise argparse.ArgumentTypeError("dataset must be LABEL,SYMBOL,PATH[,PATH...]")
    return DatasetSpec(parts[0], parts[1], tuple(Path(item) for item in parts[2:]))


def _load_dataset(spec: DatasetSpec) -> CandleSeries:
    key = CandleSeriesKey("binance", "perpetual", spec.symbol, "1m")
    components = [load_ohlcv_csv(path, key=key) for path in spec.paths]
    frame = pd.concat([component.frame for component in components], ignore_index=True)
    return CandleSeries.from_frame(
        key,
        frame,
        provenance={"components": [item.provenance for item in components]},
    )


def _market(
    datasets: dict[str, CandleSeries],
    *,
    fold: Fold,
    timeframe: str,
) -> PortfolioMarket:
    fields: dict[str, dict[str, pd.Series]] = {
        "open": {},
        "high": {},
        "low": {},
        "close": {},
    }
    expected_index: pd.DatetimeIndex | None = None
    for label, full_series in datasets.items():
        selected = select_period(full_series, start=fold.start, end=fold.end)
        candles = resample_ohlcv(
            selected.frame,
            source_timeframe="1m",
            target_timeframe=timeframe,
        ).set_index("timestamp")
        if expected_index is None:
            expected_index = pd.DatetimeIndex(candles.index)
        elif not candles.index.equals(expected_index):
            raise ValueError(f"{label} does not align with the portfolio timestamps")
        for field in fields:
            fields[field][label] = candles[field]
    market = PortfolioMarket(
        timeframe=timeframe,
        opens=pd.DataFrame(fields["open"]),
        highs=pd.DataFrame(fields["high"]),
        lows=pd.DataFrame(fields["low"]),
        closes=pd.DataFrame(fields["close"]),
    )
    market.validate()
    return market


def _evaluate(
    datasets: dict[str, CandleSeries],
    specs: list[PortfolioSpec],
    costs: PortfolioCosts,
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for fold in FOLDS:
        markets = {
            timeframe: _market(datasets, fold=fold, timeframe=timeframe)
            for timeframe in sorted({spec.timeframe for spec in specs})
        }
        for spec in specs:
            result = evaluate_portfolio(markets[spec.timeframe], spec, costs)
            result.pop("equity_curve")
            records.append({"fold": fold.identifier, **result})
    return pd.DataFrame.from_records(records)


def _reuse_detail(path: Path, specs: list[PortfolioSpec]) -> pd.DataFrame:
    detail = pd.read_csv(
        path,
        converters={
            "symbol_gross_pnl": ast.literal_eval,
            "symbol_net_pnl": ast.literal_eval,
            "symbol_stressed_net_pnl": ast.literal_eval,
            "symbol_double_cost_net_pnl": ast.literal_eval,
        },
    )
    expected_candidates = {spec.identifier for spec in specs}
    expected_folds = {fold.identifier for fold in FOLDS}
    if set(detail["candidate"]) != expected_candidates:
        raise ValueError("reused detail does not match the registered candidate grid")
    if set(detail["fold"]) != expected_folds:
        raise ValueError("reused detail does not match the registered folds")
    if len(detail) != len(expected_candidates) * len(expected_folds):
        raise ValueError("reused detail is incomplete or duplicated")
    return detail


def walk_forward(detail: pd.DataFrame) -> pd.DataFrame:
    """Select on prior folds and evaluate exactly once on the next fold."""

    records: list[dict[str, object]] = []
    for evaluation_index in range(1, len(FOLDS)):
        training_folds = [fold.identifier for fold in FOLDS[:evaluation_index]]
        evaluation_fold = FOLDS[evaluation_index].identifier
        selected = select_candidate(detail.loc[detail["fold"].isin(training_folds)])
        evaluation = detail.loc[
            detail["fold"].eq(evaluation_fold)
            & detail["candidate"].eq(selected["candidate"])
        ].iloc[0]
        records.append(
            {
                "evaluation_fold": evaluation_fold,
                "training_folds": ",".join(training_folds),
                "candidate": selected["candidate"],
                "family": selected["family"],
                "training_passed": bool(selected["passed"]),
                "training_double_cost_net_pnl": selected["double_cost_net_pnl"],
                "evaluation_net_pnl": float(evaluation["net_pnl"]),
                "evaluation_stressed_net_pnl": float(evaluation["stressed_net_pnl"]),
                "evaluation_double_cost_net_pnl": float(
                    evaluation["double_cost_net_pnl"]
                ),
                "evaluation_max_drawdown_percent": float(
                    evaluation["max_drawdown_percent"]
                ),
                "evaluation_position_change_count": int(
                    evaluation["position_change_count"]
                ),
            }
        )
    return pd.DataFrame.from_records(records)


def leave_one_symbol_out(
    datasets: dict[str, CandleSeries],
    spec: PortfolioSpec,
    costs: PortfolioCosts,
) -> pd.DataFrame:
    """Measure whether one symbol is essential to the frozen portfolio rule."""

    records: list[dict[str, object]] = []
    for omitted in datasets:
        subset = {
            label: series for label, series in datasets.items() if label != omitted
        }
        fold_results: list[dict[str, Any]] = []
        for fold in FOLDS:
            market = _market(subset, fold=fold, timeframe=spec.timeframe)
            fold_results.append(evaluate_portfolio(market, spec, costs))
        records.append(
            {
                "omitted_symbol": omitted,
                "net_pnl": sum(float(row["net_pnl"]) for row in fold_results),
                "stressed_net_pnl": sum(
                    float(row["stressed_net_pnl"]) for row in fold_results
                ),
                "double_cost_net_pnl": sum(
                    float(row["double_cost_net_pnl"]) for row in fold_results
                ),
                "positive_double_cost_fold_count": sum(
                    float(row["double_cost_net_pnl"]) > 0 for row in fold_results
                ),
                "max_drawdown_percent": max(
                    float(row["max_drawdown_percent"]) for row in fold_results
                ),
            }
        )
    return pd.DataFrame.from_records(records)


def _report(
    aggregate: pd.DataFrame,
    leaders: pd.DataFrame,
    forward: pd.DataFrame,
    winner: dict[str, Any],
    contributions: pd.DataFrame,
    leave_one_out: pd.DataFrame,
    candidate_count: int,
) -> str:
    lines = [
        "# Cross-asset portfolio arsenal",
        "",
        f"Evaluated {candidate_count} pre-registered portfolio candidates across "
        "four independently restarted folds and six Binance USD-M proxy symbols.",
        "",
        "All candidates use at most 75 USDT gross notional at 1x, next-open "
        "execution, 4.322 bps taker fee plus one bp adverse slippage per turnover, "
        "flat fold-end liquidation, a one-bp/eight-hour adverse funding stress, "
        "and a separate double-transaction-cost stress.",
        "",
        "## Family leaders",
        "",
        "| family | candidate | net | funding stress | double-cost | +cost folds | "
        "neighbor ratio | max DD | passed |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in leaders.to_dict(orient="records"):
        lines.append(
            f"| {row['family']} | `{row['candidate']}` | "
            f"{float(row['net_pnl']):+.6f} | "
            f"{float(row['stressed_net_pnl']):+.6f} | "
            f"{float(row['double_cost_net_pnl']):+.6f} | "
            f"{int(row['positive_double_cost_fold_count'])}/{int(row['fold_count'])} | "
            f"{float(row['positive_neighbor_ratio']):.2f} | "
            f"{float(row['max_drawdown_percent']):.4f}% | "
            f"{'yes' if bool(row['passed']) else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Retrospective robustness leader",
            "",
            f"`{winner['candidate']}`",
            "",
            f"- net PnL: `{float(winner['net_pnl']):+.6f}`",
            f"- adverse-funding net: `{float(winner['stressed_net_pnl']):+.6f}`",
            f"- double-cost net: `{float(winner['double_cost_net_pnl']):+.6f}`",
            f"- positive double-cost folds: "
            f"`{int(winner['positive_double_cost_fold_count'])}/"
            f"{int(winner['fold_count'])}`",
            f"- neighboring profitable lookbacks: "
            f"`{float(winner['positive_neighbor_ratio']):.2f}`",
            f"- gate passed: `{'yes' if bool(winner['passed']) else 'no'}`",
            "",
            "## Retrospective leader by symbol",
            "",
            "| symbol | net | funding stress | double-cost |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in contributions.to_dict(orient="records"):
        lines.append(
            f"| {row['symbol']} | {float(row['net_pnl']):+.6f} | "
            f"{float(row['stressed_net_pnl']):+.6f} | "
            f"{float(row['double_cost_net_pnl']):+.6f} |"
        )
    lines.extend(
        [
            "",
            "## Frozen-rule leave-one-symbol-out sensitivity",
            "",
            "| omitted | net | funding stress | double-cost | +cost folds | max DD |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in leave_one_out.to_dict(orient="records"):
        lines.append(
            f"| {row['omitted_symbol']} | {float(row['net_pnl']):+.6f} | "
            f"{float(row['stressed_net_pnl']):+.6f} | "
            f"{float(row['double_cost_net_pnl']):+.6f} | "
            f"{int(row['positive_double_cost_fold_count'])}/4 | "
            f"{float(row['max_drawdown_percent']):.4f}% |"
        )
    lines.extend(
        [
            "",
            "## Sequential walk-forward",
            "",
            "| evaluation | trained on | family | candidate | train gate | net | "
            "funding stress | double-cost | max DD |",
            "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in forward.to_dict(orient="records"):
        lines.append(
            f"| {row['evaluation_fold']} | {row['training_folds']} | "
            f"{row['family']} | `{row['candidate']}` | "
            f"{'pass' if bool(row['training_passed']) else 'diagnostic'} | "
            f"{float(row['evaluation_net_pnl']):+.6f} | "
            f"{float(row['evaluation_stressed_net_pnl']):+.6f} | "
            f"{float(row['evaluation_double_cost_net_pnl']):+.6f} | "
            f"{float(row['evaluation_max_drawdown_percent']):.4f}% |"
        )
    lines.extend(
        [
            "",
            "The gate requires every fold to remain positive after doubling "
            "transaction costs, positive adverse-funding PnL, at least 30 position "
            "changes, and at least half of adjacent lookbacks in the same strategy "
            "neighborhood to survive doubled costs.",
            "",
            "All history has been inspected in prior research, so even sequential "
            "selection is a retrospective process simulation rather than a truly "
            "untouched holdout. Portfolio accounting omits order-book depth, partial "
            "fills, liquidation, borrow constraints, and actual funding. No result "
            "is deployment approval.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_outputs(
    output: Path,
    *,
    detail: pd.DataFrame,
    aggregate: pd.DataFrame,
    leaders: pd.DataFrame,
    forward: pd.DataFrame,
    winner: dict[str, Any],
    leave_one_out: pd.DataFrame,
    specs: list[PortfolioSpec],
    dataset_specs: list[DatasetSpec],
    costs: PortfolioCosts,
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    contributions = _symbol_contributions(detail, str(winner["candidate"]))
    detail.to_csv(output / "candidate_folds.csv", index=False)
    aggregate.to_csv(output / "candidate_aggregate.csv", index=False)
    leaders.to_csv(output / "family_leaders.csv", index=False)
    forward.to_csv(output / "walk_forward.csv", index=False)
    contributions.to_csv(output / "leader_symbol_contributions.csv", index=False)
    leave_one_out.to_csv(output / "leader_leave_one_out.csv", index=False)
    (output / "report.md").write_text(
        _report(
            aggregate,
            leaders,
            forward,
            winner,
            contributions,
            leave_one_out,
            len(specs),
        ),
        encoding="utf-8",
    )
    summary: dict[str, Any] = {
        "schema_version": 1,
        "datasets": [asdict(spec) for spec in dataset_specs],
        "source_sha256": {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for spec in dataset_specs
            for path in spec.paths
        },
        "folds": [asdict(fold) for fold in FOLDS],
        "costs": asdict(costs),
        "candidate_count": len(specs),
        "candidates": [spec.as_dict() for spec in specs],
        "retrospective_leader": winner,
        "leader_symbol_contributions": contributions.to_dict(orient="records"),
        "leader_leave_one_out": leave_one_out.to_dict(orient="records"),
        "walk_forward": forward.to_dict(orient="records"),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )


def _symbol_contributions(detail: pd.DataFrame, candidate: str) -> pd.DataFrame:
    selected = detail.loc[detail["candidate"].eq(candidate)]
    if selected.empty:
        raise ValueError("selected portfolio candidate has no fold rows")
    records: list[dict[str, object]] = []
    symbols = sorted(selected.iloc[0]["symbol_net_pnl"])
    for symbol in symbols:
        records.append(
            {
                "symbol": symbol,
                "net_pnl": sum(
                    float(values[symbol]) for values in selected["symbol_net_pnl"]
                ),
                "stressed_net_pnl": sum(
                    float(values[symbol])
                    for values in selected["symbol_stressed_net_pnl"]
                ),
                "double_cost_net_pnl": sum(
                    float(values[symbol])
                    for values in selected["symbol_double_cost_net_pnl"]
                ),
            }
        )
    return pd.DataFrame.from_records(records)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", action="append", type=_dataset, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reuse-detail", type=Path)
    args = parser.parse_args()

    dataset_specs: list[DatasetSpec] = args.dataset
    if len(dataset_specs) < 2:
        parser.error("at least two datasets are required")
    datasets = {spec.label: _load_dataset(spec) for spec in dataset_specs}
    specs = build_portfolio_grid()
    costs = PortfolioCosts()
    detail = (
        _reuse_detail(args.reuse_detail, specs)
        if args.reuse_detail is not None
        else _evaluate(datasets, specs, costs)
    )
    aggregate = aggregate_candidates(detail)
    leaders = family_leaders(aggregate)
    forward = walk_forward(detail)
    winner = select_candidate(detail)
    winner_spec = next(
        spec for spec in specs if spec.identifier == str(winner["candidate"])
    )
    leave_one_out = leave_one_symbol_out(datasets, winner_spec, costs)
    _write_outputs(
        args.output_dir,
        detail=detail,
        aggregate=aggregate,
        leaders=leaders,
        forward=forward,
        winner=winner,
        leave_one_out=leave_one_out,
        specs=specs,
        dataset_specs=dataset_specs,
        costs=costs,
    )
    print(args.output_dir / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
