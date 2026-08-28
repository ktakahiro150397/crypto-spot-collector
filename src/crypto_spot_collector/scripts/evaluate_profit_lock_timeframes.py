"""Compare the production SAR exit with an early profit lock across timeframes."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

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


@dataclass(frozen=True)
class DatasetSpec:
    label: str
    symbol: str
    paths: tuple[Path, ...]


def _dataset(value: str) -> DatasetSpec:
    parts = value.split(",")
    if len(parts) < 3:
        raise argparse.ArgumentTypeError("dataset must be LABEL,SYMBOL,PATH[,PATH...]")
    return DatasetSpec(parts[0], parts[1], tuple(Path(item) for item in parts[2:]))


def _load_dataset(spec: DatasetSpec) -> CandleSeries:
    key = CandleSeriesKey("binance", "perpetual", spec.symbol, "1m")
    frames = [load_ohlcv_csv(path, key=key).frame for path in spec.paths]
    combined = pd.concat(frames, ignore_index=True)
    return CandleSeries.from_frame(key, combined)


_CLOCK_NORMALIZED_COUNTS = {
    "5m": (24, 12),
    "15m": (8, 4),
    "30m": (4, 2),
    "1h": (2, 1),
    "2h": (1, 1),
    "4h": (1, 1),
}


def _config(
    timeframe: str,
    variant: str,
    confirmation_mode: str,
) -> BacktestConfig:
    if confirmation_mode == "same_count":
        entry_count, close_count = 4, 2
    elif confirmation_mode == "clock_normalized":
        try:
            entry_count, close_count = _CLOCK_NORMALIZED_COUNTS[timeframe]
        except KeyError as exc:
            raise ValueError(
                f"no clock-normalized confirmation count for {timeframe}"
            ) from exc
    else:
        raise ValueError(f"unsupported confirmation mode: {confirmation_mode}")
    common = {
        "signal_timeframe": timeframe,
        "initial_equity": 1_000.0,
        "order_notional": 12.5,
        "leverage": 1,
        "take_profit_roe": 15.0,
        "stop_loss_roe": 15.0,
        "sar_consecutive_count": entry_count,
        "sar_close_consecutive_count": close_count,
        "taker_fee_bps": 4.322,
        "slippage_bps": 1.0,
        "allow_proxy_data": True,
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


def _row(
    *,
    dataset: str,
    phase: str,
    timeframe: str,
    variant: str,
    confirmation_mode: str,
    entry_count: int,
    close_count: int,
    result: BacktestResult,
) -> dict[str, object]:
    trades = result.trades
    wins = trades.loc[trades["net_pnl"] > 0, "net_pnl"]
    losses = trades.loc[trades["net_pnl"] < 0, "net_pnl"]
    gross_profit = float(wins.sum())
    gross_loss = float(losses.sum())
    return {
        "dataset": dataset,
        "phase": phase,
        "timeframe": timeframe,
        "variant": variant,
        "confirmation_mode": confirmation_mode,
        "entry_count": entry_count,
        "close_count": close_count,
        "net_pnl": float(result.summary["total_net_pnl"]),
        "return_percent": float(result.summary["total_return_percent"]),
        "max_drawdown_percent": float(result.summary["max_drawdown_percent"]),
        "trade_count": int(result.summary["trade_count"]),
        "win_rate_percent": float(result.summary["win_rate_percent"]),
        "profit_factor": (gross_profit / abs(gross_loss) if gross_loss < 0 else None),
        "fee_total": float(trades["entry_fee"].sum() + trades["exit_fee"].sum()),
        "trailing_stop_count": int(trades["exit_reason"].eq("trailing_stop").sum()),
    }


def _aggregate(rows: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    groups = rows.groupby(
        ["phase", "confirmation_mode", "timeframe", "variant"],
        sort=False,
    )
    for (phase, confirmation_mode, timeframe, variant), group in groups:
        records.append(
            {
                "phase": phase,
                "confirmation_mode": confirmation_mode,
                "timeframe": timeframe,
                "variant": variant,
                "entry_count": int(group["entry_count"].iloc[0]),
                "close_count": int(group["close_count"].iloc[0]),
                "net_pnl": float(group["net_pnl"].sum()),
                "max_symbol_drawdown_percent": float(
                    group["max_drawdown_percent"].max()
                ),
                "trade_count": int(group["trade_count"].sum()),
                "profitable_symbols": int(group["net_pnl"].gt(0).sum()),
                "symbol_count": len(group),
                "fee_total": float(group["fee_total"].sum()),
                "trailing_stop_count": int(group["trailing_stop_count"].sum()),
            }
        )
    return pd.DataFrame.from_records(records)


def _report(aggregate: pd.DataFrame) -> str:
    lines = [
        "# BTC/ETH timeframe profit-lock evaluation",
        "",
        "Binance USD-M one-minute proxy candles; 1x, 12.5 USDT notional per trade, "
        "TP/SL 15% ROE, 4.322 bps taker fee per fill, and 1 bp adverse "
        "slippage per fill. Funding is omitted.",
        "",
        "Baseline uses 7% activation, entry floor, and a three-minute poll. "
        "Profit lock uses 0.25% activation, 0.15% floor, and a one-minute poll.",
        "",
        "Same-count uses 4/2 SAR confirmations at every timeframe. "
        "Clock-normalized approximates a two-hour entry confirmation and a "
        "one-hour close confirmation.",
        "",
        "| phase | confirmation | timeframe | counts | variant | net PnL | "
        "trades | profitable symbols | worst symbol DD | fees | trailing exits |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in aggregate.to_dict(orient="records"):
        lines.append(
            f"| {row['phase']} | {row['confirmation_mode']} | "
            f"{row['timeframe']} | {row['entry_count']}/{row['close_count']} | "
            f"{row['variant']} | "
            f"{row['net_pnl']:+.6f} | {row['trade_count']} | "
            f"{row['profitable_symbols']}/{row['symbol_count']} | "
            f"{row['max_symbol_drawdown_percent']:.4f}% | "
            f"{row['fee_total']:.6f} | {row['trailing_stop_count']} |"
        )
    lines.extend(
        [
            "",
            "Development is 2025-01-01 through 2026-01-01. Evaluation is "
            "2026-01-01 through 2026-08-24. Each phase starts flat and computes "
            "signals only from candles inside that phase.",
            "",
            "One-minute OHLC cannot reproduce the proposed 30-second observation "
            "or intraminute event order. Binance proxy candles also do not reproduce "
            "Hyperliquid execution, and the result is not a deployment approval.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", action="append", type=_dataset, required=True)
    parser.add_argument(
        "--timeframes",
        default="5m,15m,30m,1h,2h,4h",
    )
    parser.add_argument(
        "--confirmation-modes",
        default="same_count,clock_normalized",
    )
    parser.add_argument("--development-start", default="2025-01-01T00:00:00Z")
    parser.add_argument("--evaluation-start", default="2026-01-01T00:00:00Z")
    parser.add_argument("--end", default="2026-08-24T00:00:00Z")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    logger.disable("crypto_spot_collector")
    timeframes = [item.strip() for item in args.timeframes.split(",")]
    confirmation_modes = [item.strip() for item in args.confirmation_modes.split(",")]
    datasets = {spec.label: _load_dataset(spec) for spec in args.dataset}
    phases = {
        "development": (args.development_start, args.evaluation_start),
        "evaluation": (args.evaluation_start, args.end),
    }
    records: list[dict[str, object]] = []
    for phase, (start, end) in phases.items():
        for label, full_series in datasets.items():
            series = select_period(full_series, start=start, end=end)
            for confirmation_mode in confirmation_modes:
                for timeframe in timeframes:
                    baseline_config = _config(
                        timeframe,
                        "baseline",
                        confirmation_mode,
                    )
                    baseline = PerpetualSarBacktester(baseline_config)
                    prepared = baseline.prepare_signals(series)
                    for variant in ("baseline", "profit_lock"):
                        config = _config(timeframe, variant, confirmation_mode)
                        result = PerpetualSarBacktester(config).run(
                            series,
                            prepared_signals=prepared,
                        )
                        records.append(
                            _row(
                                dataset=label,
                                phase=phase,
                                timeframe=timeframe,
                                variant=variant,
                                confirmation_mode=confirmation_mode,
                                entry_count=config.sar_consecutive_count,
                                close_count=config.sar_close_consecutive_count,
                                result=result,
                            )
                        )

    detail = pd.DataFrame.from_records(records)
    aggregate = _aggregate(detail)
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    detail.to_csv(output / "per_symbol.csv", index=False)
    aggregate.to_csv(output / "aggregate.csv", index=False)
    (output / "report.md").write_text(_report(aggregate), encoding="utf-8")
    source_hashes = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for spec in args.dataset
        for path in spec.paths
    }
    summary = {
        "schema_version": 1,
        "datasets": [asdict(spec) for spec in args.dataset],
        "source_sha256": source_hashes,
        "development": [args.development_start, args.evaluation_start],
        "evaluation": [args.evaluation_start, args.end],
        "timeframes": timeframes,
        "confirmation_modes": confirmation_modes,
        "aggregate": aggregate.to_dict(orient="records"),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )
    print(output / "report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
