"""Leakage-controlled search and locked confirmation across technical strategies."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from statistics import pstdev
from typing import Any, Sequence

import pandas as pd
from loguru import logger

from .data import (
    CandleSeries,
    CandleSeriesKey,
    CSVFormat,
    load_ohlcv_csv,
    resample_ohlcv,
    select_period,
)
from .engine import BacktestConfig, PerpetualSarBacktester
from .strategy_signals import (
    SideMode,
    StrategyFamily,
    StrategySpec,
    prepare_strategy_signals,
)


class StrategySearchError(RuntimeError):
    """Raised when a search or confirmation protocol cannot be completed."""


@dataclass(frozen=True, order=True)
class ExecutionSpec:
    """Risk and exit settings applied identically to any signal family."""

    take_profit_roe: float
    stop_loss_roe: float
    trailing_activation_roe: float
    signal_exit_count: int = 2
    leverage: int = 1

    @property
    def identifier(self) -> str:
        return (
            f"lev={self.leverage}|tp={self.take_profit_roe:g}|"
            f"sl={self.stop_loss_roe:g}|trail={self.trailing_activation_roe:g}|"
            f"exit={self.signal_exit_count}"
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "take_profit_roe": self.take_profit_roe,
            "stop_loss_roe": self.stop_loss_roe,
            "trailing_activation_roe": self.trailing_activation_roe,
            "signal_exit_count": self.signal_exit_count,
            "leverage": self.leverage,
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> "ExecutionSpec":
        return cls(
            take_profit_roe=float(values["take_profit_roe"]),
            stop_loss_roe=float(values["stop_loss_roe"]),
            trailing_activation_roe=float(values["trailing_activation_roe"]),
            signal_exit_count=int(values["signal_exit_count"]),
            leverage=int(values["leverage"]),
        )


@dataclass(frozen=True)
class EvaluationTask:
    strategy: StrategySpec
    execution: ExecutionSpec
    role: str = "candidate"

    @property
    def identifier(self) -> str:
        return f"{self.strategy.identifier}||{self.execution.identifier}"


@dataclass(frozen=True)
class ValidationDataset:
    label: str
    symbol: str
    path: Path
    start: str
    end: str


PRODUCTION_EXECUTION = ExecutionSpec(15.0, 15.0, 7.0, leverage=1)
RESEARCH_EXECUTION = ExecutionSpec(25.0, 1.5, 3.0, leverage=3)
FUNDING_SENSITIVITY_RATE = 0.0001
FUNDING_INTERVAL_HOURS = 8

_WORKER_SERIES: CandleSeries | None = None
_WORKER_FOLDS: list[tuple[str, str]] | None = None
_WORKER_COSTS: dict[str, float] | None = None
_WORKER_SIGNAL_CACHE: dict[str, object] = {}


def build_signal_grid() -> list[StrategySpec]:
    """Return the fixed broad grid used before any validation data is opened."""

    base: set[StrategySpec] = set()
    sides = list(SideMode)

    for timeframe in ("30m", "1h", "2h", "4h"):
        for count in (1, 2, 4):
            for side in sides:
                base.add(
                    StrategySpec(
                        StrategyFamily.SAR,
                        timeframe,
                        side_mode=side,
                        sar_consecutive_count=count,
                    )
                )

    for ema_period in (20, 50, 100, 200):
        for adx_threshold in (None, 20.0, 30.0):
            for side in sides:
                base.add(
                    StrategySpec(
                        StrategyFamily.SAR,
                        "1h",
                        side_mode=side,
                        sar_consecutive_count=4,
                        filter_timeframe="4h",
                        ema_period=ema_period,
                        adx_threshold=adx_threshold,
                    )
                )
    for atr_min in (0.5, 1.0):
        for adx_threshold in (None, 20.0, 30.0):
            for side in sides:
                base.add(
                    StrategySpec(
                        StrategyFamily.SAR,
                        "1h",
                        side_mode=side,
                        sar_consecutive_count=4,
                        filter_timeframe="4h",
                        ema_period=50,
                        adx_threshold=adx_threshold,
                        atr_min_percent=atr_min,
                    )
                )

    for timeframe in ("1h", "4h"):
        for ema_period in (20, 50, 100, 200):
            for confirmation in (1, 3):
                for adx_threshold in (None, 20.0, 30.0):
                    for side in sides:
                        base.add(
                            StrategySpec(
                                StrategyFamily.EMA_PRICE,
                                timeframe,
                                side_mode=side,
                                confirmation=confirmation,
                                ema_period=ema_period,
                                adx_threshold=adx_threshold,
                            )
                        )
        for atr_min in (0.5, 1.0):
            for side in sides:
                base.add(
                    StrategySpec(
                        StrategyFamily.EMA_PRICE,
                        timeframe,
                        side_mode=side,
                        ema_period=50,
                        adx_threshold=20.0,
                        atr_min_percent=atr_min,
                    )
                )

    for timeframe in ("1h", "4h"):
        for fast_period, slow_period in ((10, 30), (20, 50), (50, 200)):
            for confirmation in (1, 3):
                for adx_threshold in (None, 20.0):
                    for side in sides:
                        base.add(
                            StrategySpec(
                                StrategyFamily.EMA_CROSS,
                                timeframe,
                                side_mode=side,
                                confirmation=confirmation,
                                fast_period=fast_period,
                                slow_period=slow_period,
                                adx_threshold=adx_threshold,
                            )
                        )

    for timeframe in ("1h", "4h"):
        for lookback in (20, 55, 100):
            for adx_value in (None, 20.0):
                for atr_min_value in (None, 0.5):
                    for side in sides:
                        base.add(
                            StrategySpec(
                                StrategyFamily.DONCHIAN,
                                timeframe,
                                side_mode=side,
                                lookback=lookback,
                                adx_threshold=adx_value,
                                atr_min_percent=atr_min_value,
                            )
                        )

    momentum_lookbacks = {"1h": (24, 72, 168), "4h": (6, 18, 42)}
    for timeframe, lookbacks in momentum_lookbacks.items():
        for lookback in lookbacks:
            for threshold in (0.0, 0.01):
                for side in sides:
                    base.add(
                        StrategySpec(
                            StrategyFamily.MOMENTUM,
                            timeframe,
                            side_mode=side,
                            lookback=lookback,
                            momentum_threshold=threshold,
                        )
                    )

    for timeframe in ("30m", "1h", "4h"):
        for lower, upper in ((25.0, 75.0), (30.0, 70.0)):
            for deviation in (2.0, 2.5):
                for side in sides:
                    base.add(
                        StrategySpec(
                            StrategyFamily.RSI_BOLLINGER,
                            timeframe,
                            side_mode=side,
                            rsi_lower=lower,
                            rsi_upper=upper,
                            bollinger_deviation=deviation,
                        )
                    )
    return sorted(base, key=lambda spec: spec.identifier)


def build_exit_grid() -> list[ExecutionSpec]:
    """Search broad price-risk exits at fixed one-times notional exposure."""

    values = {
        ExecutionSpec(tp, sl, trail, signal_exit_count=2, leverage=1)
        for tp in (4.0, 8.0, 15.0, 25.0)
        for sl in (1.5, 3.0, 6.0, 15.0)
        for trail in (2.0, 4.0, 7.0)
        if trail < tp
    }
    values.add(PRODUCTION_EXECUTION)
    return sorted(values)


def baseline_tasks() -> list[EvaluationTask]:
    return [
        EvaluationTask(
            StrategySpec(
                StrategyFamily.SAR,
                "30m",
                sar_consecutive_count=4,
            ),
            PRODUCTION_EXECUTION,
            "production_sar",
        ),
        EvaluationTask(
            StrategySpec(
                StrategyFamily.SAR,
                "1h",
                sar_consecutive_count=4,
            ),
            RESEARCH_EXECUTION,
            "prior_sar_candidate",
        ),
        EvaluationTask(
            StrategySpec(
                StrategyFamily.SAR,
                "1h",
                sar_consecutive_count=4,
                filter_timeframe="4h",
                ema_period=50,
                adx_threshold=30.0,
            ),
            RESEARCH_EXECUTION,
            "prior_sar_regime",
        ),
    ]


def select_screening_specs(rows: list[dict[str, Any]]) -> list[StrategySpec]:
    """Carry max-profit and stability leaders from every family into exit tuning."""

    viable = [
        row
        for row in rows
        if int(row["trade_count"]) >= 20 and float(row["total_net_pnl"]) > 0
    ]
    source = viable or rows
    selected: dict[str, StrategySpec] = {}
    families = sorted({str(row["family"]) for row in source})
    for family in families:
        family_rows = [row for row in source if row["family"] == family]
        for key in ("total_net_pnl", "robust_score"):
            winner = max(
                family_rows,
                key=lambda row: (
                    float(row[key]),
                    int(row["positive_fold_count"]),
                    -float(row["max_drawdown_percent"]),
                ),
            )
            spec = _strategy_from_row(winner)
            selected[spec.identifier] = spec
    for key in ("total_net_pnl", "robust_score"):
        leaders = sorted(
            source,
            key=lambda row: (
                float(row[key]),
                int(row["positive_fold_count"]),
                -float(row["max_drawdown_percent"]),
            ),
            reverse=True,
        )[:4]
        for row in leaders:
            spec = _strategy_from_row(row)
            selected[spec.identifier] = spec
    return sorted(selected.values(), key=lambda spec: spec.identifier)


def select_precision_tasks(rows: list[dict[str, Any]]) -> list[EvaluationTask]:
    """Freeze a small contender set before restoring one-minute execution."""

    viable = [
        row
        for row in rows
        if int(row["trade_count"]) >= 20 and float(row["total_net_pnl"]) > 0
    ]
    source = viable or rows
    selected: dict[str, EvaluationTask] = {}
    for key, limit in (("total_net_pnl", 8), ("robust_score", 4)):
        leaders = sorted(
            source,
            key=lambda row: (
                float(row[key]),
                int(row["positive_fold_count"]),
                -float(row["max_drawdown_percent"]),
            ),
            reverse=True,
        )[:limit]
        for row in leaders:
            task = _task_from_row(row)
            selected[task.identifier] = task
    for task in baseline_tasks():
        selected[task.identifier] = task
    return sorted(selected.values(), key=lambda task: task.identifier)


def lock_candidate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Choose maximum net profit only after every pre-registered gate passes."""

    eligible = [
        row
        for row in rows
        if row.get("role") == "candidate"
        and float(row["total_net_pnl"]) > 0
        and int(row["trade_count"]) >= 30
        and int(row["positive_fold_count"]) == int(row["fold_count"])
        and _profit_factor(row) > 1.0
        and float(row["adverse_funding_1bps_net_pnl"]) > 0
    ]
    maximum = max(
        [row for row in rows if row.get("role") == "candidate"],
        key=lambda row: (
            float(row["total_net_pnl"]),
            -float(row["max_drawdown_percent"]),
        ),
    )
    if not eligible:
        return {
            "status": "no_candidate",
            "reason": "No precision contender passed every development gate.",
            "maximum_development_result": maximum,
            "candidate": None,
        }
    winner = max(
        eligible,
        key=lambda row: (
            float(row["total_net_pnl"]),
            -float(row["max_drawdown_percent"]),
            float(row["robust_score"]),
        ),
    )
    return {
        "status": "locked",
        "reason": "Highest net profit among contenders passing every development gate.",
        "maximum_development_result": maximum,
        "candidate": winner,
    }


def run_search(
    *,
    input_paths: list[Path],
    key: CandleSeriesKey,
    csv_format: CSVFormat,
    start: str,
    fold_boundaries: list[str],
    end: str,
    workers: int,
    output_dir: Path,
    taker_fee_bps: float,
    slippage_bps: float,
) -> dict[str, Any]:
    """Screen, tune, precision-test, and lock exactly one development candidate."""

    folds = _build_folds(start, fold_boundaries, end)
    if workers <= 0:
        raise StrategySearchError("workers must be positive")
    output_dir.mkdir(parents=True, exist_ok=True)
    signal_grid = build_signal_grid()
    exit_grid = build_exit_grid()
    costs = {
        "initial_equity": 1_000.0,
        "order_notional": 12.0,
        "taker_fee_bps": taker_fee_bps,
        "slippage_bps": slippage_bps,
    }
    source = _load_combined_series(
        input_paths,
        key=key,
        csv_format=csv_format,
        start=start,
        end=end,
    )
    protocol = {
        "schema_version": 1,
        "status": "registered_before_search",
        "created_without_validation_data": True,
        "development": {
            "inputs": [_input_record(path) for path in input_paths],
            "identity": key.as_dict(),
            "start": start,
            "end": end,
            "folds": [{"start": left, "end": right} for left, right in folds],
            "candle_count": len(source.frame),
        },
        "costs": costs,
        "screening": {
            "execution_timeframe": "3m",
            "signal_count": len(signal_grid),
            "execution": PRODUCTION_EXECUTION.as_dict(),
            "selection": (
                "max-profit and robust-score leader per family, plus four global "
                "leaders for each objective"
            ),
        },
        "exit_tuning": {
            "execution_timeframe": "3m",
            "exit_count": len(exit_grid),
        },
        "precision": {
            "execution_timeframe": "1m",
            "selection": "top 8 net-profit and top 4 robust tuned rows plus baselines",
        },
        "development_gate": {
            "minimum_trades": 30,
            "all_folds_positive": True,
            "profit_factor_above": 1.0,
            "positive_after_adverse_funding": (
                "1 bp every 8 hours charged adversely to every open position"
            ),
            "objective_after_gates": "maximum total net PnL",
        },
        "confirmation_gate": confirmation_gate_contract(),
        "limitations": [
            "Binance USD-M prices remain a proxy for Hyperliquid execution.",
            "The search uses fixed 12 USDC notional, so leverage is not optimized.",
            "Funding is stress-tested, not reconstructed from historical funding files.",
            "Three-minute screening may order intrabar stop/target collisions "
            "conservatively; all locked contenders are rerun at one minute.",
        ],
    }
    _write_json(output_dir / "protocol.json", protocol)

    screen_series = _resample_series(source, "3m")
    screen_tasks = [
        EvaluationTask(strategy, PRODUCTION_EXECUTION) for strategy in signal_grid
    ]
    screen_rows = evaluate_tasks(
        screen_tasks,
        series=screen_series,
        folds=folds,
        costs=costs,
        workers=workers,
        phase="screen",
    )
    _write_rows(output_dir / "screening_results.csv", screen_rows)

    selected_specs = select_screening_specs(screen_rows)
    tuning_tasks = [
        EvaluationTask(strategy, execution)
        for strategy in selected_specs
        for execution in exit_grid
    ]
    tuning_rows = evaluate_tasks(
        tuning_tasks,
        series=screen_series,
        folds=folds,
        costs=costs,
        workers=workers,
        phase="tune",
    )
    _write_rows(output_dir / "exit_tuning_results.csv", tuning_rows)

    precision_tasks = select_precision_tasks(tuning_rows)
    precision_rows = evaluate_tasks(
        precision_tasks,
        series=source,
        folds=folds,
        costs=costs,
        workers=min(workers, len(precision_tasks)),
        phase="precision",
    )
    _write_rows(output_dir / "precision_results.csv", precision_rows)
    locked = lock_candidate(precision_rows)
    summary = {
        "schema_version": 1,
        "protocol_sha256": _sha256(output_dir / "protocol.json"),
        "grid_counts": {
            "signals": len(signal_grid),
            "screening_selected_signals": len(selected_specs),
            "exit_settings": len(exit_grid),
            "tuning_runs": len(tuning_tasks),
            "precision_runs": len(precision_tasks),
        },
        "lock": locked,
        "locked_before_validation_download": True,
        "candidate_strategy": (
            _strategy_from_row(locked["candidate"]).as_dict()
            if locked["candidate"] is not None
            else None
        ),
        "candidate_execution": (
            _execution_from_row(locked["candidate"]).as_dict()
            if locked["candidate"] is not None
            else None
        ),
        "baselines": [row for row in precision_rows if row.get("role") != "candidate"],
    }
    _write_json(output_dir / "locked_candidate.json", summary)
    (output_dir / "report.md").write_text(
        _search_report(protocol, summary, precision_rows),
        encoding="utf-8",
    )
    return summary


def confirmation_gate_contract() -> dict[str, object]:
    return {
        "candidate_may_not_change": True,
        "minimum_positive_dataset_ratio": "ceil(2/3)",
        "aggregate_net_pnl_positive": True,
        "aggregate_adverse_funding_net_pnl_positive": True,
        "must_beat_production_sar_aggregate_net_pnl": True,
        "maximum_per_dataset_drawdown_percent": 2.0,
    }


def run_confirmation(
    *,
    locked_candidate_path: Path,
    datasets: list[ValidationDataset],
    workers: int,
    output_dir: Path,
    include_best_non_sar: bool = False,
) -> dict[str, Any]:
    """Evaluate a frozen candidate once on untouched instruments or time ranges."""

    locked_payload = json.loads(locked_candidate_path.read_text(encoding="utf-8"))
    if locked_payload.get("lock", {}).get("status") != "locked":
        raise StrategySearchError(
            "confirmation requires a successfully locked candidate"
        )
    strategy_values = locked_payload.get("candidate_strategy")
    execution_values = locked_payload.get("candidate_execution")
    if not isinstance(strategy_values, dict) or not isinstance(execution_values, dict):
        raise StrategySearchError("locked candidate is missing strategy or execution")
    candidate = EvaluationTask(
        StrategySpec.from_dict(strategy_values),
        ExecutionSpec.from_dict(execution_values),
        "locked_candidate",
    )
    supplemental: list[EvaluationTask] = []
    precision_path = locked_candidate_path.with_name("precision_results.csv")
    if include_best_non_sar:
        supplemental.append(_load_best_non_sar_task(precision_path))
    costs_payload = _read_protocol_costs(locked_candidate_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for dataset in datasets:
        key = CandleSeriesKey(
            "binance",
            "perpetual",
            dataset.symbol,
            "1m",
        )
        series = _load_combined_series(
            [dataset.path],
            key=key,
            csv_format=CSVFormat.STANDARD,
            start=dataset.start,
            end=dataset.end,
        )
        tasks = [candidate, *supplemental, *baseline_tasks()]
        dataset_rows = evaluate_tasks(
            tasks,
            series=series,
            folds=[(dataset.start, dataset.end)],
            costs=costs_payload,
            workers=min(workers, len(tasks)),
            phase=f"confirm:{dataset.label}",
        )
        for row in dataset_rows:
            row["dataset"] = dataset.label
            row["validation_symbol"] = dataset.symbol
            row["validation_start"] = dataset.start
            row["validation_end"] = dataset.end
        rows.extend(dataset_rows)
    _write_rows(output_dir / "confirmation_results.csv", rows)
    decision = _confirmation_decision(rows, len(datasets))
    summary = {
        "schema_version": 1,
        "locked_candidate_sha256": _sha256(locked_candidate_path),
        "candidate_strategy": strategy_values,
        "candidate_execution": execution_values,
        "datasets": [
            {
                "label": dataset.label,
                "symbol": dataset.symbol,
                "path": str(dataset.path),
                "sha256": _sha256(dataset.path),
                "start": dataset.start,
                "end": dataset.end,
            }
            for dataset in datasets
        ],
        "gate": confirmation_gate_contract(),
        "supplemental": (
            {
                "selection": "maximum development net PnL among non-SAR precision rows passing the same development gates",
                "precision_results": str(precision_path),
                "precision_results_sha256": _sha256(precision_path),
                "tasks": [
                    {
                        "role": task.role,
                        "strategy": task.strategy.as_dict(),
                        "execution": task.execution.as_dict(),
                    }
                    for task in supplemental
                ],
            }
            if supplemental
            else None
        ),
        "decision": decision,
        "rows": rows,
    }
    _write_json(output_dir / "confirmation.json", summary)
    (output_dir / "report.md").write_text(
        _confirmation_report(summary),
        encoding="utf-8",
    )
    return summary


def promote_final_candidate(
    *,
    confirmation_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Lock the best intermediate-validation candidate for a final holdout."""

    payload = json.loads(confirmation_path.read_text(encoding="utf-8"))
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise StrategySearchError("confirmation artifact is missing result rows")
    definitions: dict[str, tuple[dict[str, object], dict[str, object]]] = {
        "locked_candidate": (
            payload["candidate_strategy"],
            payload["candidate_execution"],
        )
    }
    supplemental = payload.get("supplemental")
    if isinstance(supplemental, dict):
        tasks = supplemental.get("tasks")
        if isinstance(tasks, list):
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                role = task.get("role")
                strategy = task.get("strategy")
                execution = task.get("execution")
                if (
                    isinstance(role, str)
                    and isinstance(strategy, dict)
                    and isinstance(execution, dict)
                ):
                    definitions[role] = (strategy, execution)

    dataset_count = len({str(row["dataset"]) for row in rows if isinstance(row, dict)})
    required_positive = math.ceil(dataset_count * 2 / 3)
    evaluations: list[dict[str, Any]] = []
    for role in definitions:
        role_rows = [row for row in rows if row.get("role") == role]
        if len(role_rows) != dataset_count:
            raise StrategySearchError(f"intermediate results are incomplete for {role}")
        aggregate_net = sum(float(row["total_net_pnl"]) for row in role_rows)
        aggregate_stressed = sum(
            float(row["adverse_funding_1bps_net_pnl"]) for row in role_rows
        )
        positive_count = sum(float(row["total_net_pnl"]) > 0 for row in role_rows)
        evaluations.append(
            {
                "role": role,
                "aggregate_net_pnl": aggregate_net,
                "aggregate_adverse_funding_1bps_net_pnl": aggregate_stressed,
                "positive_dataset_count": positive_count,
                "maximum_drawdown_percent": max(
                    float(row["max_drawdown_percent"]) for row in role_rows
                ),
                "eligible": (
                    positive_count >= required_positive
                    and aggregate_net > 0
                    and aggregate_stressed > 0
                    and all(
                        float(row["max_drawdown_percent"]) <= 2.0 for row in role_rows
                    )
                ),
            }
        )
    eligible = [item for item in evaluations if item["eligible"]]
    if not eligible:
        raise StrategySearchError(
            "no intermediate candidate qualifies for final promotion"
        )
    winner = max(
        eligible,
        key=lambda item: (
            float(item["aggregate_net_pnl"]),
            float(item["aggregate_adverse_funding_1bps_net_pnl"]),
            -float(item["maximum_drawdown_percent"]),
        ),
    )
    strategy, execution = definitions[str(winner["role"])]
    output = {
        "schema_version": 1,
        "lock": {
            "status": "locked",
            "reason": (
                "Maximum aggregate intermediate-validation net PnL among "
                "pre-development candidates passing the promotion gate."
            ),
            "candidate": winner,
        },
        "candidate_strategy": strategy,
        "candidate_execution": execution,
        "promotion": {
            "source": str(confirmation_path),
            "source_sha256": _sha256(confirmation_path),
            "required_positive_dataset_count": required_positive,
            "evaluations": evaluations,
            "final_holdout_must_not_change_candidate": True,
        },
    }
    _write_json(output_path, output)
    return output


def evaluate_tasks(
    tasks: list[EvaluationTask],
    *,
    series: CandleSeries,
    folds: list[tuple[str, str]],
    costs: dict[str, float],
    workers: int,
    phase: str,
) -> list[dict[str, Any]]:
    if not tasks:
        raise StrategySearchError(f"{phase} has no evaluation tasks")
    if workers <= 0:
        raise StrategySearchError("workers must be positive")
    init_args = (series, folds, costs)
    rows: list[dict[str, Any]] = []
    if workers == 1:
        _initialize_worker(*init_args)
        for index, task in enumerate(tasks, start=1):
            rows.append(_evaluate_worker(task))
            _print_progress(phase, index, len(tasks))
        return rows

    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_initialize_worker,
        initargs=init_args,
    ) as executor:
        futures = {executor.submit(_evaluate_worker, task): task for task in tasks}
        for index, future in enumerate(as_completed(futures), start=1):
            task = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:
                raise StrategySearchError(
                    f"{phase} failed for {task.identifier}: {exc}"
                ) from exc
            _print_progress(phase, index, len(tasks))
    return rows


def _initialize_worker(
    series: CandleSeries,
    folds: list[tuple[str, str]],
    costs: dict[str, float],
) -> None:
    global _WORKER_SERIES, _WORKER_FOLDS, _WORKER_COSTS, _WORKER_SIGNAL_CACHE
    logger.disable("crypto_spot_collector")
    _WORKER_SERIES = series
    _WORKER_FOLDS = folds
    _WORKER_COSTS = costs
    _WORKER_SIGNAL_CACHE = {}


def _evaluate_worker(task: EvaluationTask) -> dict[str, Any]:
    if _WORKER_SERIES is None or _WORKER_FOLDS is None or _WORKER_COSTS is None:
        raise RuntimeError("strategy-search worker is not initialized")
    strategy = task.strategy
    execution = task.execution
    config = BacktestConfig(
        signal_timeframe=strategy.signal_timeframe,
        initial_equity=_WORKER_COSTS["initial_equity"],
        order_notional=_WORKER_COSTS["order_notional"],
        leverage=execution.leverage,
        take_profit_roe=execution.take_profit_roe,
        stop_loss_roe=execution.stop_loss_roe,
        trailing_activation_roe=execution.trailing_activation_roe,
        trailing_interval_minutes=3,
        sar_consecutive_count=strategy.sar_consecutive_count,
        sar_close_consecutive_count=execution.signal_exit_count,
        taker_fee_bps=_WORKER_COSTS["taker_fee_bps"],
        slippage_bps=_WORKER_COSTS["slippage_bps"],
        allow_proxy_data=True,
        equity_curve_interval_minutes=60,
    )
    prepared = _WORKER_SIGNAL_CACHE.get(strategy.identifier)
    if prepared is None:
        prepared = prepare_strategy_signals(_WORKER_SERIES, strategy)
        _WORKER_SIGNAL_CACHE[strategy.identifier] = prepared
    result = PerpetualSarBacktester(config).run(
        _WORKER_SERIES,
        prepared_signals=prepared,  # type: ignore[arg-type]
    )
    summary: Any = result.summary
    folds = _fold_returns(
        result.equity_curve,
        folds=_WORKER_FOLDS,
        initial_equity=config.initial_equity,
    )
    monthly = _monthly_returns(
        result.equity_curve,
        initial_equity=config.initial_equity,
    )
    monthly_values = list(monthly.values())
    monthly_std = pstdev(monthly_values) if len(monthly_values) > 1 else 0.0
    trades = result.trades
    entry_fees = float(trades["entry_fee"].sum()) if not trades.empty else 0.0
    exit_fees = float(trades["exit_fee"].sum()) if not trades.empty else 0.0
    gross_pnl = float(trades["gross_pnl"].sum()) if not trades.empty else 0.0
    long_net = (
        float(trades.loc[trades["side"] == "long", "net_pnl"].sum())
        if not trades.empty
        else 0.0
    )
    short_net = (
        float(trades.loc[trades["side"] == "short", "net_pnl"].sum())
        if not trades.empty
        else 0.0
    )
    funding_cost = _adverse_funding_cost(
        trades,
        rate=FUNDING_SENSITIVITY_RATE,
        interval_hours=FUNDING_INTERVAL_HOURS,
    )
    total_return = float(summary["total_return_percent"])
    drawdown = float(summary["max_drawdown_percent"])
    return {
        "task_id": task.identifier,
        "role": task.role,
        **strategy.as_dict(),
        **execution.as_dict(),
        "total_net_pnl": float(summary["total_net_pnl"]),
        "total_return_percent": total_return,
        "max_drawdown_percent": drawdown,
        "trade_count": int(summary["trade_count"]),
        "win_rate_percent": float(summary["win_rate_percent"]),
        "profit_factor": summary["profit_factor"],
        "gross_pnl": gross_pnl,
        "assumed_fees": entry_fees + exit_fees,
        "long_net_pnl": long_net,
        "short_net_pnl": short_net,
        "fold_count": len(folds),
        "positive_fold_count": sum(value > 0 for value in folds.values()),
        "worst_fold_return_percent": min(folds.values()),
        "fold_returns": folds,
        "positive_month_ratio": (
            sum(value > 0 for value in monthly_values) / len(monthly_values)
            if monthly_values
            else 0.0
        ),
        "monthly_return_std": monthly_std,
        "monthly_returns": monthly,
        "robust_score": total_return - drawdown - monthly_std,
        "adverse_funding_1bps_cost": funding_cost,
        "adverse_funding_1bps_net_pnl": (
            float(summary["total_net_pnl"]) - funding_cost
        ),
    }


def _load_combined_series(
    paths: list[Path],
    *,
    key: CandleSeriesKey,
    csv_format: CSVFormat,
    start: str,
    end: str,
) -> CandleSeries:
    if not paths:
        raise StrategySearchError("at least one input path is required")
    components = [
        load_ohlcv_csv(path, key=key, csv_format=csv_format) for path in paths
    ]
    frame = pd.concat([component.frame for component in components], ignore_index=True)
    combined = CandleSeries.from_frame(
        key,
        frame,
        provenance={
            "components": [
                {
                    "path": str(path),
                    "sha256": _sha256(path),
                    "manifest": component.provenance,
                }
                for path, component in zip(paths, components, strict=True)
            ]
        },
    )
    return select_period(combined, start=start, end=end)


def _resample_series(series: CandleSeries, timeframe: str) -> CandleSeries:
    frame = resample_ohlcv(
        series.frame,
        source_timeframe=series.key.timeframe,
        target_timeframe=timeframe,
    )
    key = CandleSeriesKey(
        series.key.exchange,
        series.key.market_type,
        series.key.symbol,
        timeframe,
    )
    return CandleSeries.from_frame(key, frame, provenance=series.provenance)


def _fold_returns(
    equity_curve: pd.DataFrame,
    *,
    folds: list[tuple[str, str]],
    initial_equity: float,
) -> dict[str, float]:
    timestamps = pd.to_datetime(equity_curve["timestamp"], utc=True)
    equities = equity_curve["equity"].astype(float)
    values: dict[str, float] = {}
    previous_equity = initial_equity
    for index, (start, end) in enumerate(folds, start=1):
        start_time = pd.Timestamp(start)
        end_time = pd.Timestamp(end)
        if start_time.tzinfo is None:
            start_time = start_time.tz_localize("UTC")
        else:
            start_time = start_time.tz_convert("UTC")
        if end_time.tzinfo is None:
            end_time = end_time.tz_localize("UTC")
        else:
            end_time = end_time.tz_convert("UTC")
        if index > 1:
            before_start = equities.loc[timestamps <= start_time]
            if before_start.empty:
                raise StrategySearchError("equity curve has no fold-start observation")
            previous_equity = float(before_start.iloc[-1])
        through_end = equities.loc[timestamps <= end_time]
        if through_end.empty:
            raise StrategySearchError("equity curve has no fold-end observation")
        ending_equity = float(through_end.iloc[-1])
        values[f"fold_{index}:{start}/{end}"] = (
            ending_equity / previous_equity - 1
        ) * 100
        previous_equity = ending_equity
    return values


def _monthly_returns(
    equity_curve: pd.DataFrame,
    *,
    initial_equity: float,
) -> dict[str, float]:
    timestamps = pd.to_datetime(equity_curve["timestamp"], utc=True)
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


def _adverse_funding_cost(
    trades: pd.DataFrame,
    *,
    rate: float,
    interval_hours: int,
) -> float:
    if trades.empty:
        return 0.0
    cost = 0.0
    interval = pd.Timedelta(hours=interval_hours)
    for trade in trades.itertuples(index=False):
        entry = pd.Timestamp(trade.entry_time)
        exit_time = pd.Timestamp(trade.exit_time)
        first_event = entry.ceil(interval)
        if first_event <= entry:
            first_event += interval
        event_count = max(
            0,
            math.floor((exit_time - first_event) / interval) + 1,
        )
        notional = float(trade.entry_price) * float(trade.quantity)
        cost += notional * rate * event_count
    return cost


def _confirmation_decision(
    rows: list[dict[str, Any]],
    dataset_count: int,
) -> dict[str, Any]:
    candidates = [row for row in rows if row["role"] == "locked_candidate"]
    production = [row for row in rows if row["role"] == "production_sar"]
    if len(candidates) != dataset_count or len(production) != dataset_count:
        raise StrategySearchError("confirmation results are incomplete")
    aggregate_net = sum(float(row["total_net_pnl"]) for row in candidates)
    aggregate_stressed = sum(
        float(row["adverse_funding_1bps_net_pnl"]) for row in candidates
    )
    production_net = sum(float(row["total_net_pnl"]) for row in production)
    positive_count = sum(float(row["total_net_pnl"]) > 0 for row in candidates)
    required_positive = math.ceil(dataset_count * 2 / 3)
    checks = {
        "positive_dataset_ratio": positive_count >= required_positive,
        "aggregate_net_pnl_positive": aggregate_net > 0,
        "aggregate_adverse_funding_net_pnl_positive": aggregate_stressed > 0,
        "beats_production_sar": aggregate_net > production_net,
        "drawdown_within_limit": all(
            float(row["max_drawdown_percent"]) <= 2.0 for row in candidates
        ),
    }
    return {
        "status": "accepted" if all(checks.values()) else "rejected",
        "checks": checks,
        "positive_dataset_count": positive_count,
        "required_positive_dataset_count": required_positive,
        "aggregate_net_pnl": aggregate_net,
        "aggregate_adverse_funding_1bps_net_pnl": aggregate_stressed,
        "production_sar_aggregate_net_pnl": production_net,
    }


def _load_best_non_sar_task(precision_path: Path) -> EvaluationTask:
    if not precision_path.is_file():
        raise StrategySearchError(
            "best non-SAR confirmation requires sibling precision_results.csv"
        )
    rows = pd.read_csv(precision_path).to_dict(orient="records")
    eligible = [
        row
        for row in rows
        if row.get("role") == "candidate"
        and row.get("family") != StrategyFamily.SAR.value
        and float(row["total_net_pnl"]) > 0
        and int(row["trade_count"]) >= 30
        and int(row["positive_fold_count"]) == int(row["fold_count"])
        and _profit_factor(row) > 1.0
        and float(row["adverse_funding_1bps_net_pnl"]) > 0
    ]
    if not eligible:
        raise StrategySearchError("no non-SAR precision row passed development gates")
    winner = max(
        eligible,
        key=lambda row: (
            float(row["total_net_pnl"]),
            -float(row["max_drawdown_percent"]),
        ),
    )
    selected = _task_from_row(winner)
    return EvaluationTask(
        selected.strategy,
        selected.execution,
        "best_non_sar_development",
    )


def _strategy_from_row(row: dict[str, Any]) -> StrategySpec:
    fields = {
        name: row[name] for name in StrategySpec.__dataclass_fields__ if name in row
    }
    for name in (
        "ema_period",
        "fast_period",
        "slow_period",
        "lookback",
        "adx_threshold",
        "atr_min_percent",
        "filter_timeframe",
    ):
        if name in fields and pd.isna(fields[name]):
            fields[name] = None
    for name in ("ema_period", "fast_period", "slow_period", "lookback"):
        if fields.get(name) is not None:
            fields[name] = int(fields[name])
    for name in (
        "confirmation",
        "sar_consecutive_count",
        "adx_period",
        "atr_period",
        "rsi_period",
        "bollinger_period",
    ):
        if name in fields:
            fields[name] = int(fields[name])
    return StrategySpec.from_dict(fields)


def _execution_from_row(row: dict[str, Any]) -> ExecutionSpec:
    return ExecutionSpec(
        take_profit_roe=float(row["take_profit_roe"]),
        stop_loss_roe=float(row["stop_loss_roe"]),
        trailing_activation_roe=float(row["trailing_activation_roe"]),
        signal_exit_count=int(row["signal_exit_count"]),
        leverage=int(row["leverage"]),
    )


def _task_from_row(row: dict[str, Any]) -> EvaluationTask:
    return EvaluationTask(
        _strategy_from_row(row),
        _execution_from_row(row),
        str(row.get("role", "candidate")),
    )


def _profit_factor(row: dict[str, Any]) -> float:
    value = row.get("profit_factor")
    return math.inf if value is None else float(value)


def _build_folds(
    start: str,
    boundaries: list[str],
    end: str,
) -> list[tuple[str, str]]:
    values = [pd.Timestamp(item) for item in [start, *boundaries, end]]
    if any(pd.isna(value) for value in values):
        raise StrategySearchError("fold boundary contains an invalid timestamp")
    if any(left >= right for left, right in zip(values, values[1:], strict=False)):
        raise StrategySearchError("fold boundaries must be strictly increasing")
    return list(zip([start, *boundaries], [*boundaries, end], strict=True))


def _input_record(path: Path) -> dict[str, object]:
    return {"path": str(path), "sha256": _sha256(path)}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    serializable: list[dict[str, Any]] = []
    for row in rows:
        output = dict(row)
        for key in ("fold_returns", "monthly_returns"):
            if isinstance(output.get(key), dict):
                output[key] = json.dumps(output[key], sort_keys=True)
        serializable.append(output)
    pd.DataFrame(serializable).sort_values(
        ["total_net_pnl", "max_drawdown_percent"],
        ascending=[False, True],
    ).to_csv(path, index=False)


def _read_protocol_costs(locked_candidate_path: Path) -> dict[str, float]:
    protocol_path = locked_candidate_path.with_name("protocol.json")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    costs = protocol.get("costs")
    if not isinstance(costs, dict):
        raise StrategySearchError("search protocol is missing costs")
    return {
        "initial_equity": float(costs["initial_equity"]),
        "order_notional": float(costs["order_notional"]),
        "taker_fee_bps": float(costs["taker_fee_bps"]),
        "slippage_bps": float(costs["slippage_bps"]),
    }


def _search_report(
    protocol: dict[str, Any],
    summary: dict[str, Any],
    precision_rows: list[dict[str, Any]],
) -> str:
    lock = summary["lock"]
    candidate = lock["candidate"]
    lines = [
        "# Multi-strategy development search",
        "",
        "Validation instruments and later dates were not loaded by this command. "
        "The candidate below was locked from ETH development data only.",
        "",
        "## Search size",
        "",
        f"- signal definitions: {summary['grid_counts']['signals']}",
        f"- exit-tuning runs: {summary['grid_counts']['tuning_runs']}",
        f"- one-minute precision runs: {summary['grid_counts']['precision_runs']}",
        "",
        "## Locked result",
        "",
        f"Status: **{lock['status']}**",
        "",
        str(lock["reason"]),
        "",
    ]
    if candidate is not None:
        lines.extend(
            [
                f"- strategy: `{candidate['task_id']}`",
                f"- net PnL: `{float(candidate['total_net_pnl']):.6f}`",
                f"- return: `{float(candidate['total_return_percent']):.6f}%`",
                f"- maximum drawdown: `{float(candidate['max_drawdown_percent']):.6f}%`",
                f"- trades: `{int(candidate['trade_count'])}`",
                f"- adverse 1 bp / 8h funding net PnL: "
                f"`{float(candidate['adverse_funding_1bps_net_pnl']):.6f}`",
                "",
            ]
        )
    lines.extend(
        [
            "## One-minute contenders",
            "",
            "| role | family | side | timeframe | net PnL | return | max DD | trades | positive folds |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in sorted(
        precision_rows,
        key=lambda item: float(item["total_net_pnl"]),
        reverse=True,
    ):
        lines.append(
            "| {role} | {family} | {side} | {timeframe} | {pnl:.6f} | "
            "{ret:.6f}% | {dd:.6f}% | {trades} | {positive}/{folds} |".format(
                role=row["role"],
                family=row["family"],
                side=row["side_mode"],
                timeframe=row["signal_timeframe"],
                pnl=float(row["total_net_pnl"]),
                ret=float(row["total_return_percent"]),
                dd=float(row["max_drawdown_percent"]),
                trades=int(row["trade_count"]),
                positive=int(row["positive_fold_count"]),
                folds=int(row["fold_count"]),
            )
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in protocol["limitations"])
    lines.append("")
    return "\n".join(lines)


def _confirmation_report(summary: dict[str, Any]) -> str:
    decision = summary["decision"]
    lines = [
        "# Locked multi-strategy confirmation",
        "",
        f"Decision: **{decision['status']}**",
        "",
        "The development candidate was not changed after validation data was opened.",
        "",
        "| dataset | role | family | side | net PnL | stressed net | max DD | trades |",
        "|---|---|---|---|---:|---:|---:|---:|",
    ]
    for row in summary["rows"]:
        lines.append(
            "| {dataset} | {role} | {family} | {side} | {pnl:.6f} | "
            "{stressed:.6f} | {dd:.6f}% | {trades} |".format(
                dataset=row["dataset"],
                role=row["role"],
                family=row["family"],
                side=row["side_mode"],
                pnl=float(row["total_net_pnl"]),
                stressed=float(row["adverse_funding_1bps_net_pnl"]),
                dd=float(row["max_drawdown_percent"]),
                trades=int(row["trade_count"]),
            )
        )
    lines.extend(["", "## Gate checks", ""])
    for name, passed in decision["checks"].items():
        lines.append(f"- {name}: {'PASS' if passed else 'FAIL'}")
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search technical strategies and confirm one frozen candidate."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    search = subparsers.add_parser("search")
    search.add_argument("--input", type=Path, action="append", required=True)
    search.add_argument(
        "--csv-format", choices=[item.value for item in CSVFormat], default="standard"
    )
    search.add_argument("--exchange", default="binance")
    search.add_argument("--market-type", default="perpetual")
    search.add_argument("--symbol", required=True)
    search.add_argument("--source-timeframe", default="1m")
    search.add_argument("--start", required=True)
    search.add_argument(
        "--fold-boundaries",
        required=True,
        help="Comma-separated UTC boundaries between development folds.",
    )
    search.add_argument("--end", required=True)
    search.add_argument("--taker-fee-bps", type=float, required=True)
    search.add_argument("--slippage-bps", type=float, required=True)
    search.add_argument("--workers", type=int, default=1)
    search.add_argument("--output-dir", type=Path, required=True)

    confirm = subparsers.add_parser("confirm")
    confirm.add_argument("--locked-candidate", type=Path, required=True)
    confirm.add_argument(
        "--dataset",
        action="append",
        required=True,
        type=_parse_validation_dataset,
        help="LABEL,SYMBOL,PATH,START,END (repeat for each untouched dataset).",
    )
    confirm.add_argument("--workers", type=int, default=1)
    confirm.add_argument("--output-dir", type=Path, required=True)
    confirm.add_argument("--include-best-non-sar", action="store_true")

    promote = subparsers.add_parser("promote")
    promote.add_argument("--confirmation", type=Path, required=True)
    promote.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "search":
        summary = run_search(
            input_paths=args.input,
            key=CandleSeriesKey(
                args.exchange,
                args.market_type,
                args.symbol,
                args.source_timeframe,
            ),
            csv_format=CSVFormat(args.csv_format),
            start=args.start,
            fold_boundaries=_parse_boundaries(args.fold_boundaries),
            end=args.end,
            workers=args.workers,
            output_dir=args.output_dir,
            taker_fee_bps=args.taker_fee_bps,
            slippage_bps=args.slippage_bps,
        )
        print(
            json.dumps(
                {
                    "output_dir": str(args.output_dir),
                    "status": summary["lock"]["status"],
                    "candidate": summary["candidate_strategy"],
                },
                sort_keys=True,
            )
        )
        return 0

    if args.command == "promote":
        summary = promote_final_candidate(
            confirmation_path=args.confirmation,
            output_path=args.output,
        )
        print(
            json.dumps(
                {
                    "output": str(args.output),
                    "candidate": summary["candidate_strategy"],
                },
                sort_keys=True,
            )
        )
        return 0

    summary = run_confirmation(
        locked_candidate_path=args.locked_candidate,
        datasets=args.dataset,
        workers=args.workers,
        output_dir=args.output_dir,
        include_best_non_sar=args.include_best_non_sar,
    )
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir),
                "decision": summary["decision"]["status"],
            },
            sort_keys=True,
        )
    )
    return 0


def _parse_boundaries(value: str) -> list[str]:
    values = [item.strip() for item in value.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("fold boundaries must not be empty")
    return values


def _parse_validation_dataset(value: str) -> ValidationDataset:
    parts = [item.strip() for item in value.split(",", maxsplit=4)]
    if len(parts) != 5 or not all(parts):
        raise argparse.ArgumentTypeError("dataset must be LABEL,SYMBOL,PATH,START,END")
    return ValidationDataset(
        label=parts[0],
        symbol=parts[1],
        path=Path(parts[2]),
        start=parts[3],
        end=parts[4],
    )


def _print_progress(phase: str, completed: int, total: int) -> None:
    if completed == total or completed == 1 or completed % 10 == 0:
        print(f"[{phase}] {completed}/{total}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
