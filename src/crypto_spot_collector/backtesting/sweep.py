"""Walk-forward parameter sweep for the perpetual SAR backtest."""

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

_WORKER_SERIES: CandleSeries | None = None
_WORKER_FIXED_CONFIG: dict[str, Any] | None = None
_WORKER_SIGNAL_CACHE: dict[tuple[str, float, float, int], PreparedSarSignals] = {}


class SweepError(ValueError):
    """Raised when a parameter sweep is invalid or incomplete."""


@dataclass(frozen=True, order=True)
class ParameterSet:
    """Parameters varied by the coarse strategy search."""

    signal_timeframe: str
    take_profit_roe: float
    stop_loss_roe: float
    trailing_activation_roe: float
    trailing_interval_minutes: int = 3

    @property
    def identifier(self) -> str:
        return "|".join(
            (
                self.signal_timeframe,
                f"tp={self.take_profit_roe:g}",
                f"sl={self.stop_loss_roe:g}",
                f"trail={self.trailing_activation_roe:g}",
                f"trail_min={self.trailing_interval_minutes}",
            )
        )


def build_parameter_grid(
    *,
    signal_timeframes: list[str],
    take_profit_roes: list[float],
    stop_loss_roes: list[float],
    trailing_activation_roes: list[float],
    trailing_interval_minutes: int,
) -> list[ParameterSet]:
    """Build a deterministic grid and discard logically invalid combinations."""

    parameters: set[ParameterSet] = set()
    for timeframe in signal_timeframes:
        for take_profit in take_profit_roes:
            for stop_loss in stop_loss_roes:
                for activation in trailing_activation_roes:
                    if activation >= take_profit:
                        continue
                    parameters.add(
                        ParameterSet(
                            signal_timeframe=timeframe.strip().lower(),
                            take_profit_roe=float(take_profit),
                            stop_loss_roe=float(stop_loss),
                            trailing_activation_roe=float(activation),
                            trailing_interval_minutes=trailing_interval_minutes,
                        )
                    )
    if not parameters:
        raise SweepError("parameter grid contains no valid combinations")
    return sorted(parameters)


def select_train_candidates(
    train_rows: list[dict[str, Any]],
    *,
    baseline: ParameterSet,
) -> dict[str, ParameterSet]:
    """Lock candidates using training metrics only, before opening holdout data."""

    if not train_rows:
        raise SweepError("training sweep produced no results")
    by_identifier = {str(row["parameter_id"]): row for row in train_rows}
    if baseline.identifier not in by_identifier:
        raise SweepError("baseline parameter set is missing from the training grid")

    max_return_row = max(
        train_rows,
        key=lambda row: (
            float(row["total_return_percent"]),
            -float(row["max_drawdown_percent"]),
            float(row["positive_month_ratio"]),
        ),
    )
    robust_row = max(
        train_rows,
        key=lambda row: (
            float(row["robust_score"]),
            float(row["total_return_percent"]),
            float(row["positive_month_ratio"]),
        ),
    )
    return {
        "baseline": baseline,
        "max_train_return": _parameters_from_row(max_return_row),
        "robust_train": _parameters_from_row(robust_row),
    }


def run_sweep(
    *,
    input_path: Path,
    key: CandleSeriesKey,
    csv_format: CSVFormat,
    train_start: str,
    holdout_start: str,
    end: str,
    parameters: list[ParameterSet],
    baseline: ParameterSet,
    fixed_config: dict[str, Any],
    workers: int,
    output_dir: Path,
) -> dict[str, Any]:
    """Run training search, lock nominees, then evaluate holdout and full range."""

    _validate_ranges(train_start, holdout_start, end)
    if baseline not in parameters:
        parameters = sorted({*parameters, baseline})
    output_dir.mkdir(parents=True, exist_ok=True)

    train_rows = _evaluate_phase(
        phase="train",
        input_path=input_path,
        key=key,
        csv_format=csv_format,
        start=train_start,
        end=holdout_start,
        parameters=parameters,
        fixed_config=fixed_config,
        workers=workers,
    )
    selected = select_train_candidates(train_rows, baseline=baseline)
    unique_selected = sorted(set(selected.values()))
    holdout_rows = _evaluate_phase(
        phase="holdout",
        input_path=input_path,
        key=key,
        csv_format=csv_format,
        start=holdout_start,
        end=end,
        parameters=unique_selected,
        fixed_config=fixed_config,
        workers=min(workers, len(unique_selected)),
    )
    full_rows = _evaluate_phase(
        phase="full",
        input_path=input_path,
        key=key,
        csv_format=csv_format,
        start=train_start,
        end=end,
        parameters=unique_selected,
        fixed_config=fixed_config,
        workers=min(workers, len(unique_selected)),
    )

    train_frame = pd.DataFrame(train_rows).sort_values(
        ["total_return_percent", "max_drawdown_percent"],
        ascending=[False, True],
    )
    train_frame.to_csv(output_dir / "train_results.csv", index=False)
    evaluation_rows = _role_evaluation_rows(
        selected,
        train_rows=train_rows,
        holdout_rows=holdout_rows,
        full_rows=full_rows,
    )
    pd.DataFrame(evaluation_rows).to_csv(
        output_dir / "selected_evaluation.csv",
        index=False,
    )
    summary = {
        "schema_version": 1,
        "selection_policy": {
            "holdout_used_for_selection": False,
            "max_train_return": "highest training total_return_percent",
            "robust_train": (
                "highest robust_score, where robust_score = training return - "
                "training max drawdown - monthly return population stddev"
            ),
        },
        "data": {
            "input": str(input_path),
            "identity": key.as_dict(),
            "train": {"start": train_start, "end": holdout_start},
            "holdout": {"start": holdout_start, "end": end},
            "full": {"start": train_start, "end": end},
        },
        "fixed_config": fixed_config,
        "grid": {
            "candidate_count": len(parameters),
            "parameters": [asdict(parameter) for parameter in parameters],
        },
        "selected": {
            role: {
                "parameters": asdict(parameter),
                "parameter_id": parameter.identifier,
            }
            for role, parameter in selected.items()
        },
        "evaluation": evaluation_rows,
        "limitations": [
            "Binance USD-M candles are a proxy for the Hyperliquid strategy.",
            "Funding is absent from the source kline CSV and is not included.",
            "Fees and slippage are assumptions, not guaranteed future costs.",
            "A single ETH period cannot establish future profitability.",
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
        description="Search SAR parameters on a training period and evaluate holdout."
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument(
        "--csv-format", choices=[item.value for item in CSVFormat], default="standard"
    )
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--market-type", default="perpetual")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--source-timeframe", default="1m")
    parser.add_argument("--train-start", required=True)
    parser.add_argument("--holdout-start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--signal-timeframes", default="5m,15m,30m,1h,2h,4h")
    parser.add_argument("--take-profit-roes", default="8,15,25")
    parser.add_argument("--stop-loss-roes", default="1.5,3,6")
    parser.add_argument("--trailing-activation-roes", default="3,7")
    parser.add_argument("--trailing-interval-minutes", type=int, default=3)
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
        raise SweepError("workers must be positive")
    parameters = build_parameter_grid(
        signal_timeframes=_parse_strings(args.signal_timeframes),
        take_profit_roes=_parse_floats(args.take_profit_roes),
        stop_loss_roes=_parse_floats(args.stop_loss_roes),
        trailing_activation_roes=_parse_floats(args.trailing_activation_roes),
        trailing_interval_minutes=args.trailing_interval_minutes,
    )
    baseline = ParameterSet("30m", 15.0, 3.0, 7.0, 3)
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
    summary = run_sweep(
        input_path=args.input,
        key=CandleSeriesKey(
            args.exchange,
            args.market_type,
            args.symbol,
            args.source_timeframe,
        ),
        csv_format=CSVFormat(args.csv_format),
        train_start=args.train_start,
        holdout_start=args.holdout_start,
        end=args.end,
        parameters=parameters,
        baseline=baseline,
        fixed_config=fixed_config,
        workers=args.workers,
        output_dir=args.output_dir,
    )
    grid = summary["grid"]
    if not isinstance(grid, dict):
        raise SweepError("summary grid must be an object")
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "candidate_count": grid["candidate_count"],
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
    parameters: list[ParameterSet],
    fixed_config: dict[str, Any],
    workers: int,
) -> list[dict[str, Any]]:
    if not parameters:
        raise SweepError(f"{phase} phase contains no parameters")
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
        for index, parameter in enumerate(parameters, start=1):
            results.append(_evaluate_worker(parameter))
            _print_progress(phase, index, len(parameters))
        return results

    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_initialize_worker,
        initargs=init_args,
    ) as executor:
        futures = {
            executor.submit(_evaluate_worker, parameter): parameter
            for parameter in parameters
        }
        for index, future in enumerate(as_completed(futures), start=1):
            parameter = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                raise SweepError(
                    f"{phase} evaluation failed for {parameter.identifier}: {exc}"
                ) from exc
            _print_progress(phase, index, len(parameters))
    return results


def _initialize_worker(
    input_path: str,
    key_values: dict[str, str],
    csv_format: str,
    start: str,
    end: str,
    fixed_config: dict[str, Any],
) -> None:
    global _WORKER_FIXED_CONFIG, _WORKER_SERIES, _WORKER_SIGNAL_CACHE
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


def _evaluate_worker(parameter: ParameterSet) -> dict[str, Any]:
    if _WORKER_SERIES is None or _WORKER_FIXED_CONFIG is None:
        raise RuntimeError("sweep worker is not initialized")
    config = BacktestConfig(
        **_WORKER_FIXED_CONFIG,
        signal_timeframe=parameter.signal_timeframe,
        take_profit_roe=parameter.take_profit_roe,
        stop_loss_roe=parameter.stop_loss_roe,
        trailing_activation_roe=parameter.trailing_activation_roe,
        trailing_interval_minutes=parameter.trailing_interval_minutes,
    )
    backtester = PerpetualSarBacktester(config)
    cache_key = (
        config.signal_timeframe,
        config.sar_step,
        config.sar_max_step,
        config.sar_consecutive_count,
    )
    prepared = _WORKER_SIGNAL_CACHE.get(cache_key)
    if prepared is None:
        prepared = backtester.prepare_signals(_WORKER_SERIES)
        _WORKER_SIGNAL_CACHE[cache_key] = prepared
    result = backtester.run(_WORKER_SERIES, prepared_signals=prepared)
    monthly_returns = _monthly_returns(
        result.equity_curve,
        initial_equity=config.initial_equity,
    )
    monthly_values = list(monthly_returns.values())
    monthly_std = pstdev(monthly_values) if len(monthly_values) > 1 else 0.0
    summary: Any = result.summary
    total_return = float(summary["total_return_percent"])
    drawdown = float(summary["max_drawdown_percent"])
    return {
        "parameter_id": parameter.identifier,
        **asdict(parameter),
        "total_return_percent": total_return,
        "max_drawdown_percent": drawdown,
        "trade_count": int(summary["trade_count"]),
        "win_rate_percent": float(summary["win_rate_percent"]),
        "profit_factor": summary["profit_factor"],
        "final_equity": float(summary["final_equity"]),
        "positive_month_ratio": (
            sum(value > 0 for value in monthly_values) / len(monthly_values)
        ),
        "monthly_return_mean": (
            sum(monthly_values) / len(monthly_values) if monthly_values else 0.0
        ),
        "monthly_return_std": monthly_std,
        "worst_month_return": min(monthly_values) if monthly_values else 0.0,
        "robust_score": total_return - drawdown - monthly_std,
        "monthly_returns": json.dumps(monthly_returns, sort_keys=True),
    }


def _monthly_returns(
    equity_curve: pd.DataFrame,
    *,
    initial_equity: float,
) -> dict[str, float]:
    if equity_curve.empty:
        return {}
    timestamps = pd.to_datetime(equity_curve["timestamp"], utc=True)
    # Equity timestamps are candle close times. A candle that opens at 23:59
    # and closes exactly at 00:00 belongs to the month in which it traded.
    month_labels = (timestamps - pd.Timedelta(nanoseconds=1)).dt.strftime("%Y-%m")
    month_ends = (
        equity_curve.assign(_month=month_labels).groupby("_month")["equity"].last()
    )
    previous = initial_equity
    returns: dict[str, float] = {}
    for month, value in month_ends.items():
        equity = float(value)
        returns[str(month)] = (equity / previous - 1) * 100
        previous = equity
    return returns


def _role_evaluation_rows(
    selected: dict[str, ParameterSet],
    *,
    train_rows: list[dict[str, Any]],
    holdout_rows: list[dict[str, Any]],
    full_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    phases = {
        "train": {str(row["parameter_id"]): row for row in train_rows},
        "holdout": {str(row["parameter_id"]): row for row in holdout_rows},
        "full": {str(row["parameter_id"]): row for row in full_rows},
    }
    rows: list[dict[str, Any]] = []
    for role, parameter in selected.items():
        for phase, values in phases.items():
            row = values.get(parameter.identifier)
            if row is None:
                raise SweepError(
                    f"selected parameter {parameter.identifier} missing from {phase}"
                )
            rows.append({"role": role, "phase": phase, **row})
    return rows


def _markdown_report(summary: dict[str, Any]) -> str:
    evaluations = summary["evaluation"]
    if not isinstance(evaluations, list):
        raise SweepError("summary evaluation must be a list")
    lookup = {
        (str(row["role"]), str(row["phase"])): row
        for row in evaluations
        if isinstance(row, dict)
    }
    lines = [
        "# SAR parameter sweep",
        "",
        "Candidates were selected from the training period only. The holdout was",
        "opened after the baseline, max-return, and robust nominees were locked.",
        "",
        "| role | timeframe | TP ROE | SL ROE | trail ROE | train return | holdout return | full return | full max DD | full trades |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    selected = summary["selected"]
    if not isinstance(selected, dict):
        raise SweepError("summary selected must be an object")
    for role in ("baseline", "max_train_return", "robust_train"):
        item = selected[role]
        if not isinstance(item, dict):
            raise SweepError("selected item must be an object")
        parameters = item["parameters"]
        if not isinstance(parameters, dict):
            raise SweepError("selected parameters must be an object")
        train = lookup[(role, "train")]
        holdout = lookup[(role, "holdout")]
        full = lookup[(role, "full")]
        lines.append(
            "| {role} | {timeframe} | {tp:g} | {sl:g} | {trail:g} | "
            "{train:.6f}% | {holdout:.6f}% | {full_return:.6f}% | "
            "{drawdown:.6f}% | {trades} |".format(
                role=role,
                timeframe=parameters["signal_timeframe"],
                tp=float(parameters["take_profit_roe"]),
                sl=float(parameters["stop_loss_roe"]),
                trail=float(parameters["trailing_activation_roe"]),
                train=float(train["total_return_percent"]),
                holdout=float(holdout["total_return_percent"]),
                full_return=float(full["total_return_percent"]),
                drawdown=float(full["max_drawdown_percent"]),
                trades=int(full["trade_count"]),
            )
        )
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            *[f"- {item}" for item in summary["limitations"]],  # type: ignore[union-attr]
            "",
        ]
    )
    return "\n".join(lines)


def _parameters_from_row(row: dict[str, Any]) -> ParameterSet:
    return ParameterSet(
        signal_timeframe=str(row["signal_timeframe"]),
        take_profit_roe=float(row["take_profit_roe"]),
        stop_loss_roe=float(row["stop_loss_roe"]),
        trailing_activation_roe=float(row["trailing_activation_roe"]),
        trailing_interval_minutes=int(row["trailing_interval_minutes"]),
    )


def _parse_strings(value: str) -> list[str]:
    values = [item.strip() for item in value.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("comma-separated list must not be empty")
    return values


def _parse_floats(value: str) -> list[float]:
    try:
        values = [float(item.strip()) for item in value.split(",") if item.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated numbers") from exc
    if not values or not all(math.isfinite(item) and item > 0 for item in values):
        raise argparse.ArgumentTypeError("parameter values must be finite and positive")
    return values


def _validate_ranges(train_start: str, holdout_start: str, end: str) -> None:
    boundaries = [pd.Timestamp(value) for value in (train_start, holdout_start, end)]
    if any(pd.isna(value) for value in boundaries):
        raise SweepError("sweep range contains an invalid timestamp")
    if not boundaries[0] < boundaries[1] < boundaries[2]:
        raise SweepError("range must satisfy train_start < holdout_start < end")


def _print_progress(phase: str, completed: int, total: int) -> None:
    print(f"[{phase}] {completed}/{total}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
