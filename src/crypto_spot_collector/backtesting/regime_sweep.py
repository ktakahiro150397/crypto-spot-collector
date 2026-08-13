"""Walk-forward comparison of higher-timeframe EMA/ADX entry filters."""

from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import pstdev
from typing import Any

import pandas as pd
from loguru import logger

from .data import (
    CandleSeries,
    CandleSeriesKey,
    CSVFormat,
    load_ohlcv_csv,
    select_period,
)
from .engine import BacktestConfig, PerpetualSarBacktester, PreparedSarSignals
from .regime import EntryFilterConfig, PreparedEntryFilter, prepare_entry_filter

_WORKER_SERIES: CandleSeries | None = None
_WORKER_FIXED_CONFIG: dict[str, Any] | None = None
_WORKER_SIGNAL_CACHE: dict[tuple[str, float, float, int], PreparedSarSignals] = {}
_WORKER_FILTER_CACHE: dict[EntryFilterConfig, PreparedEntryFilter] = {}


class RegimeSweepError(ValueError):
    """Raised when a regime-filter comparison is invalid or incomplete."""


@dataclass(frozen=True)
class StrategyVariant:
    """Complete strategy variant used by the regime-filter comparison."""

    name: str
    signal_timeframe: str
    take_profit_roe: float
    stop_loss_roe: float
    trailing_activation_roe: float
    trailing_interval_minutes: int
    entry_filter: EntryFilterConfig | None
    selectable: bool

    @property
    def identifier(self) -> str:
        filter_id = self.entry_filter.identifier if self.entry_filter else "none"
        return "|".join(
            (
                self.signal_timeframe,
                f"tp={self.take_profit_roe:g}",
                f"sl={self.stop_loss_roe:g}",
                f"trail={self.trailing_activation_roe:g}",
                f"trail_min={self.trailing_interval_minutes}",
                f"filter={filter_id}",
            )
        )


def build_variants(
    *,
    filter_timeframe: str,
    ema_periods: list[int],
    adx_period: int,
    adx_thresholds: list[float],
) -> list[StrategyVariant]:
    """Build controls plus the deterministic EMA-only and EMA/ADX grid."""

    if not ema_periods or any(period <= 1 for period in ema_periods):
        raise RegimeSweepError("EMA periods must be greater than one")
    if adx_period <= 1:
        raise RegimeSweepError("ADX period must be greater than one")
    if any(not math.isfinite(value) or value < 0 for value in adx_thresholds):
        raise RegimeSweepError("ADX thresholds must be finite and non-negative")

    variants = [_baseline_30m(), _unfiltered_1h()]
    for ema_period in sorted(set(ema_periods)):
        configs = [
            EntryFilterConfig(
                timeframe=filter_timeframe,
                ema_period=ema_period,
                adx_period=adx_period,
                adx_threshold=None,
            ),
            *[
                EntryFilterConfig(
                    timeframe=filter_timeframe,
                    ema_period=ema_period,
                    adx_period=adx_period,
                    adx_threshold=threshold,
                )
                for threshold in sorted(set(adx_thresholds))
            ],
        ]
        variants.extend(_filtered_1h(config) for config in configs)
    return sorted(variants, key=lambda item: item.identifier)


def select_train_candidates(
    train_rows: list[dict[str, Any]],
    *,
    variants: list[StrategyVariant],
) -> dict[str, StrategyVariant]:
    """Select nominees using training rows only and keep both controls."""

    by_id = {variant.identifier: variant for variant in variants}
    rows = [row for row in train_rows if by_id[str(row["strategy_id"])].selectable]
    if not rows:
        raise RegimeSweepError("training comparison produced no selectable results")
    baseline = _variant_named(variants, "baseline_30m")
    unfiltered = _variant_named(variants, "sar_1h_unfiltered")
    max_return = max(
        rows,
        key=lambda row: (
            float(row["total_return_percent"]),
            -float(row["max_drawdown_percent"]),
            float(row["positive_month_ratio"]),
        ),
    )
    robust = max(
        rows,
        key=lambda row: (
            float(row["robust_score"]),
            float(row["total_return_percent"]),
            float(row["positive_month_ratio"]),
        ),
    )
    return {
        "baseline_30m": baseline,
        "sar_1h_unfiltered": unfiltered,
        "max_train_return": by_id[str(max_return["strategy_id"])],
        "robust_train": by_id[str(robust["strategy_id"])],
    }


def run_regime_sweep(
    *,
    input_path: Path,
    confirmation_input_path: Path,
    key: CandleSeriesKey,
    csv_format: CSVFormat,
    train_start: str,
    holdout_start: str,
    holdout_end: str,
    confirmation_start: str,
    confirmation_end: str,
    variants: list[StrategyVariant],
    fixed_config: dict[str, Any],
    workers: int,
    output_dir: Path,
) -> dict[str, Any]:
    """Search train, lock nominees, then evaluate two non-selection periods."""

    _validate_ranges(
        train_start,
        holdout_start,
        holdout_end,
        confirmation_start,
        confirmation_end,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    train_rows = _evaluate_phase(
        phase="train",
        input_path=input_path,
        key=key,
        csv_format=csv_format,
        start=train_start,
        end=holdout_start,
        variants=variants,
        fixed_config=fixed_config,
        workers=workers,
    )
    selected = select_train_candidates(train_rows, variants=variants)
    locked = _unique_variants(selected.values())
    holdout_rows = _evaluate_phase(
        phase="holdout",
        input_path=input_path,
        key=key,
        csv_format=csv_format,
        start=holdout_start,
        end=holdout_end,
        variants=locked,
        fixed_config=fixed_config,
        workers=min(workers, len(locked)),
    )
    confirmation_rows = _evaluate_phase(
        phase="confirmation",
        input_path=confirmation_input_path,
        key=key,
        csv_format=csv_format,
        start=confirmation_start,
        end=confirmation_end,
        variants=locked,
        fixed_config=fixed_config,
        workers=min(workers, len(locked)),
    )

    pd.DataFrame(train_rows).sort_values(
        ["total_return_percent", "max_drawdown_percent"],
        ascending=[False, True],
    ).to_csv(output_dir / "train_results.csv", index=False)
    evaluation = _role_evaluation_rows(
        selected,
        train_rows=train_rows,
        holdout_rows=holdout_rows,
        confirmation_rows=confirmation_rows,
    )
    pd.DataFrame(evaluation).to_csv(
        output_dir / "selected_evaluation.csv",
        index=False,
    )
    summary = {
        "schema_version": 1,
        "selection_policy": {
            "holdout_used_for_selection": False,
            "confirmation_used_for_selection": False,
            "max_train_return": "highest training total_return_percent",
            "robust_train": (
                "highest robust_score, where robust_score = training return - "
                "training max drawdown - monthly return population stddev"
            ),
        },
        "data": {
            "train_and_holdout_input": str(input_path),
            "confirmation_input": str(confirmation_input_path),
            "identity": key.as_dict(),
            "train": {"start": train_start, "end": holdout_start},
            "holdout": {"start": holdout_start, "end": holdout_end},
            "confirmation": {
                "start": confirmation_start,
                "end": confirmation_end,
            },
        },
        "fixed_config": fixed_config,
        "grid": {
            "variant_count": len(variants),
            "variants": [_variant_dict(item) for item in variants],
        },
        "selected": {
            role: {
                "strategy_id": variant.identifier,
                "variant": _variant_dict(variant),
            }
            for role, variant in selected.items()
        },
        "evaluation": evaluation,
        "limitations": [
            "Binance USD-M candles are a proxy for the Hyperliquid strategy.",
            "Funding is absent from the source kline CSV and is not included.",
            "Fees and slippage are assumptions, not guaranteed future costs.",
            "Each phase starts flat and recalculates indicator warm-up.",
            "One ETH history cannot establish future profitability.",
        ],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(
        _markdown_report(summary),
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare closed-4h EMA/ADX filters for the 1h SAR strategy."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--confirmation-input", required=True, type=Path)
    parser.add_argument(
        "--csv-format", choices=[item.value for item in CSVFormat], default="standard"
    )
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--market-type", default="perpetual")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--source-timeframe", default="1m")
    parser.add_argument("--train-start", required=True)
    parser.add_argument("--holdout-start", required=True)
    parser.add_argument("--holdout-end", required=True)
    parser.add_argument("--confirmation-start", required=True)
    parser.add_argument("--confirmation-end", required=True)
    parser.add_argument("--filter-timeframe", default="4h")
    parser.add_argument("--ema-periods", default="20,50,100,200")
    parser.add_argument("--adx-period", type=int, default=14)
    parser.add_argument("--adx-thresholds", default="15,20,25,30")
    parser.add_argument("--initial-equity", type=float, default=1_000.0)
    parser.add_argument("--order-notional", type=float, default=12.0)
    parser.add_argument("--leverage", type=int, default=3)
    parser.add_argument("--sar-consecutive-count", type=int, default=4)
    parser.add_argument("--sar-close-consecutive-count", type=int, default=2)
    parser.add_argument("--taker-fee-bps", type=float, required=True)
    parser.add_argument("--slippage-bps", type=float, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.workers <= 0:
        raise RegimeSweepError("workers must be positive")
    variants = build_variants(
        filter_timeframe=args.filter_timeframe,
        ema_periods=_parse_ints(args.ema_periods),
        adx_period=args.adx_period,
        adx_thresholds=_parse_floats(args.adx_thresholds),
    )
    fixed_config: dict[str, Any] = {
        "initial_equity": args.initial_equity,
        "order_notional": args.order_notional,
        "leverage": args.leverage,
        "sar_consecutive_count": args.sar_consecutive_count,
        "sar_close_consecutive_count": args.sar_close_consecutive_count,
        "taker_fee_bps": args.taker_fee_bps,
        "slippage_bps": args.slippage_bps,
        "allow_proxy_data": args.exchange.lower() != "hyperliquid",
    }
    summary = run_regime_sweep(
        input_path=args.input,
        confirmation_input_path=args.confirmation_input,
        key=CandleSeriesKey(
            args.exchange,
            args.market_type,
            args.symbol,
            args.source_timeframe,
        ),
        csv_format=CSVFormat(args.csv_format),
        train_start=args.train_start,
        holdout_start=args.holdout_start,
        holdout_end=args.holdout_end,
        confirmation_start=args.confirmation_start,
        confirmation_end=args.confirmation_end,
        variants=variants,
        fixed_config=fixed_config,
        workers=args.workers,
        output_dir=args.output_dir,
    )
    grid = summary["grid"]
    if not isinstance(grid, dict):
        raise RegimeSweepError("summary grid must be an object")
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "variant_count": grid["variant_count"],
                "selected": summary["selected"],
            },
            sort_keys=True,
        )
    )
    return 0


def _evaluate_phase(
    *,
    phase: str,
    input_path: Path,
    key: CandleSeriesKey,
    csv_format: CSVFormat,
    start: str,
    end: str,
    variants: list[StrategyVariant],
    fixed_config: dict[str, Any],
    workers: int,
) -> list[dict[str, Any]]:
    if not variants:
        raise RegimeSweepError(f"{phase} phase contains no variants")
    init_args = (
        str(input_path),
        key.as_dict(),
        csv_format.value,
        start,
        end,
        fixed_config,
    )
    results: list[dict[str, Any]] = []
    if workers == 1:
        _initialize_worker(*init_args)
        for index, variant in enumerate(variants, start=1):
            results.append(_evaluate_worker(variant))
            _print_progress(phase, index, len(variants))
        return results

    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_initialize_worker,
        initargs=init_args,
    ) as executor:
        futures = {
            executor.submit(_evaluate_worker, variant): variant for variant in variants
        }
        for index, future in enumerate(as_completed(futures), start=1):
            variant = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                raise RegimeSweepError(
                    f"{phase} evaluation failed for {variant.identifier}: {exc}"
                ) from exc
            _print_progress(phase, index, len(variants))
    return results


def _initialize_worker(
    input_path: str,
    key_values: dict[str, str],
    csv_format: str,
    start: str,
    end: str,
    fixed_config: dict[str, Any],
) -> None:
    global _WORKER_FILTER_CACHE, _WORKER_FIXED_CONFIG, _WORKER_SERIES
    global _WORKER_SIGNAL_CACHE
    logger.disable("crypto_spot_collector")
    key = CandleSeriesKey(
        key_values["exchange"],
        key_values["market_type"],
        key_values["symbol"],
        key_values["timeframe"],
    )
    series = load_ohlcv_csv(
        Path(input_path),
        key=key,
        csv_format=CSVFormat(csv_format),
    )
    _WORKER_SERIES = select_period(series, start=start, end=end)
    _WORKER_FIXED_CONFIG = dict(fixed_config)
    _WORKER_SIGNAL_CACHE = {}
    _WORKER_FILTER_CACHE = {}


def _evaluate_worker(variant: StrategyVariant) -> dict[str, Any]:
    if _WORKER_SERIES is None or _WORKER_FIXED_CONFIG is None:
        raise RuntimeError("regime sweep worker is not initialized")
    config = BacktestConfig(
        **_WORKER_FIXED_CONFIG,
        signal_timeframe=variant.signal_timeframe,
        take_profit_roe=variant.take_profit_roe,
        stop_loss_roe=variant.stop_loss_roe,
        trailing_activation_roe=variant.trailing_activation_roe,
        trailing_interval_minutes=variant.trailing_interval_minutes,
    )
    backtester = PerpetualSarBacktester(config)
    signal_key = (
        config.signal_timeframe,
        config.sar_step,
        config.sar_max_step,
        config.sar_consecutive_count,
    )
    signals = _WORKER_SIGNAL_CACHE.get(signal_key)
    if signals is None:
        signals = backtester.prepare_signals(_WORKER_SERIES)
        _WORKER_SIGNAL_CACHE[signal_key] = signals
    entry_filter = None
    if variant.entry_filter is not None:
        entry_filter = _WORKER_FILTER_CACHE.get(variant.entry_filter)
        if entry_filter is None:
            entry_filter = prepare_entry_filter(_WORKER_SERIES, variant.entry_filter)
            _WORKER_FILTER_CACHE[variant.entry_filter] = entry_filter
    result = backtester.run(
        _WORKER_SERIES,
        prepared_signals=signals,
        prepared_entry_filter=entry_filter,
    )
    return _result_row(variant, result.summary, result.trades, result.equity_curve)


def _result_row(
    variant: StrategyVariant,
    summary: Any,
    trades: pd.DataFrame,
    equity_curve: pd.DataFrame,
) -> dict[str, Any]:
    monthly_returns = _monthly_returns(
        equity_curve,
        initial_equity=float(summary["final_equity"]) - float(summary["total_net_pnl"]),
    )
    monthly_values = list(monthly_returns.values())
    monthly_std = pstdev(monthly_values) if len(monthly_values) > 1 else 0.0
    total_return = float(summary["total_return_percent"])
    drawdown = float(summary["max_drawdown_percent"])
    gross_pnl = float(trades["gross_pnl"].sum()) if not trades.empty else 0.0
    fees = (
        float((trades["entry_fee"] + trades["exit_fee"]).sum())
        if not trades.empty
        else 0.0
    )
    side_metrics = {
        side: {
            "trade_count": int(len(side_rows)),
            "net_pnl": float(side_rows["net_pnl"].sum()),
        }
        for side, side_rows in trades.groupby("side")
    }
    exit_counts = (
        {
            str(key): int(value)
            for key, value in trades["exit_reason"].value_counts().items()
        }
        if not trades.empty
        else {}
    )
    filter_config = variant.entry_filter
    return {
        "strategy_id": variant.identifier,
        "name": variant.name,
        "selectable": variant.selectable,
        "signal_timeframe": variant.signal_timeframe,
        "take_profit_roe": variant.take_profit_roe,
        "stop_loss_roe": variant.stop_loss_roe,
        "trailing_activation_roe": variant.trailing_activation_roe,
        "trailing_interval_minutes": variant.trailing_interval_minutes,
        "filter_timeframe": filter_config.timeframe if filter_config else None,
        "ema_period": filter_config.ema_period if filter_config else None,
        "adx_period": filter_config.adx_period if filter_config else None,
        "adx_threshold": filter_config.adx_threshold if filter_config else None,
        "total_return_percent": total_return,
        "max_drawdown_percent": drawdown,
        "trade_count": int(summary["trade_count"]),
        "win_rate_percent": float(summary["win_rate_percent"]),
        "profit_factor": summary["profit_factor"],
        "final_equity": float(summary["final_equity"]),
        "total_gross_pnl": gross_pnl,
        "total_fees": fees,
        "total_net_pnl": float(summary["total_net_pnl"]),
        "entry_signal_count": int(summary["entry_signal_count"]),
        "filtered_entry_signal_count": int(summary["filtered_entry_signal_count"]),
        "positive_month_ratio": (
            sum(value > 0 for value in monthly_values) / len(monthly_values)
            if monthly_values
            else 0.0
        ),
        "monthly_return_std": monthly_std,
        "worst_month_return": min(monthly_values) if monthly_values else 0.0,
        "robust_score": total_return - drawdown - monthly_std,
        "monthly_returns": json.dumps(monthly_returns, sort_keys=True),
        "side_metrics": json.dumps(side_metrics, sort_keys=True),
        "exit_reason_counts": json.dumps(exit_counts, sort_keys=True),
    }


def _monthly_returns(
    equity_curve: pd.DataFrame,
    *,
    initial_equity: float,
) -> dict[str, float]:
    if equity_curve.empty:
        return {}
    timestamps = pd.to_datetime(equity_curve["timestamp"], utc=True)
    labels = (timestamps - pd.Timedelta(nanoseconds=1)).dt.strftime("%Y-%m")
    month_ends = equity_curve.assign(_month=labels).groupby("_month")["equity"].last()
    previous = initial_equity
    returns: dict[str, float] = {}
    for month, value in month_ends.items():
        equity = float(value)
        returns[str(month)] = (equity / previous - 1) * 100
        previous = equity
    return returns


def _role_evaluation_rows(
    selected: dict[str, StrategyVariant],
    *,
    train_rows: list[dict[str, Any]],
    holdout_rows: list[dict[str, Any]],
    confirmation_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    phases = {
        "train": {str(row["strategy_id"]): row for row in train_rows},
        "holdout": {str(row["strategy_id"]): row for row in holdout_rows},
        "confirmation": {str(row["strategy_id"]): row for row in confirmation_rows},
    }
    rows: list[dict[str, Any]] = []
    for role, variant in selected.items():
        for phase, values in phases.items():
            row = values.get(variant.identifier)
            if row is None:
                raise RegimeSweepError(
                    f"selected variant {variant.identifier} missing from {phase}"
                )
            rows.append({"role": role, "phase": phase, **row})
    return rows


def _markdown_report(summary: dict[str, Any]) -> str:
    evaluations = summary["evaluation"]
    selected = summary["selected"]
    if not isinstance(evaluations, list) or not isinstance(selected, dict):
        raise RegimeSweepError("summary selection data is malformed")
    lookup = {
        (str(row["role"]), str(row["phase"])): row
        for row in evaluations
        if isinstance(row, dict)
    }
    lines = [
        "# EMA/ADX regime-filter comparison",
        "",
        "Candidates were selected from training only. Holdout and confirmation",
        "were evaluated after the nominees were locked.",
        "",
        "| role | filter | train return | holdout return | confirmation return | confirmation max DD | confirmation PF | trades |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for role in (
        "baseline_30m",
        "sar_1h_unfiltered",
        "max_train_return",
        "robust_train",
    ):
        item = selected[role]
        if not isinstance(item, dict):
            raise RegimeSweepError("selected item must be an object")
        variant = item["variant"]
        if not isinstance(variant, dict):
            raise RegimeSweepError("selected variant must be an object")
        train = lookup[(role, "train")]
        holdout = lookup[(role, "holdout")]
        confirmation = lookup[(role, "confirmation")]
        filter_id = variant["entry_filter_id"] or "none"
        profit_factor = confirmation["profit_factor"]
        pf_text = "n/a" if profit_factor is None else f"{float(profit_factor):.4f}"
        lines.append(
            f"| {role} | {filter_id} | "
            f"{float(train['total_return_percent']):.6f}% | "
            f"{float(holdout['total_return_percent']):.6f}% | "
            f"{float(confirmation['total_return_percent']):.6f}% | "
            f"{float(confirmation['max_drawdown_percent']):.6f}% | "
            f"{pf_text} | {int(confirmation['trade_count'])} |"
        )
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            *[f"- {item}" for item in summary["limitations"]],
            "",
        ]
    )
    return "\n".join(lines)


def _variant_dict(variant: StrategyVariant) -> dict[str, Any]:
    values = asdict(variant)
    values["entry_filter_id"] = (
        variant.entry_filter.identifier if variant.entry_filter else None
    )
    return values


def _baseline_30m() -> StrategyVariant:
    return StrategyVariant("baseline_30m", "30m", 15.0, 3.0, 7.0, 3, None, False)


def _unfiltered_1h() -> StrategyVariant:
    return StrategyVariant("sar_1h_unfiltered", "1h", 25.0, 1.5, 3.0, 3, None, True)


def _filtered_1h(config: EntryFilterConfig) -> StrategyVariant:
    return StrategyVariant("sar_1h_filtered", "1h", 25.0, 1.5, 3.0, 3, config, True)


def _variant_named(
    variants: list[StrategyVariant],
    name: str,
) -> StrategyVariant:
    matches = [variant for variant in variants if variant.name == name]
    if len(matches) != 1:
        raise RegimeSweepError(f"expected exactly one {name} variant")
    return matches[0]


def _unique_variants(variants: Any) -> list[StrategyVariant]:
    by_id = {variant.identifier: variant for variant in variants}
    return [by_id[key] for key in sorted(by_id)]


def _parse_ints(value: str) -> list[int]:
    try:
        values = [int(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated integers") from exc
    if not values:
        raise argparse.ArgumentTypeError("integer list must not be empty")
    return values


def _parse_floats(value: str) -> list[float]:
    try:
        values = [float(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated numbers") from exc
    if not values:
        raise argparse.ArgumentTypeError("number list must not be empty")
    return values


def _validate_ranges(
    train_start: str,
    holdout_start: str,
    holdout_end: str,
    confirmation_start: str,
    confirmation_end: str,
) -> None:
    boundaries = [
        pd.Timestamp(value)
        for value in (
            train_start,
            holdout_start,
            holdout_end,
            confirmation_start,
            confirmation_end,
        )
    ]
    if any(pd.isna(value) for value in boundaries):
        raise RegimeSweepError("comparison range contains an invalid timestamp")
    if not boundaries[0] < boundaries[1] < boundaries[2]:
        raise RegimeSweepError("train/holdout boundaries must be strictly increasing")
    if boundaries[3] < boundaries[2]:
        raise RegimeSweepError("confirmation must not overlap train or holdout")
    if not boundaries[3] < boundaries[4]:
        raise RegimeSweepError("confirmation boundaries must be strictly increasing")


def _print_progress(phase: str, completed: int, total: int) -> None:
    print(f"[{phase}] {completed}/{total}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
