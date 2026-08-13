"""Command-line entry point for the offline perpetual SAR backtest."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from loguru import logger

from .data import (
    CandleSeriesKey,
    CSVFormat,
    MarketType,
    load_ohlcv_csv,
    select_period,
)
from .engine import BacktestConfig, PerpetualSarBacktester
from .reporting import write_backtest_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay the Hyperliquid perpetual SAR strategy offline with native "
            "or explicitly permitted proxy candles."
        )
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument(
        "--csv-format",
        choices=[item.value for item in CSVFormat],
        default=CSVFormat.STANDARD.value,
    )
    parser.add_argument("--exchange", default="hyperliquid")
    parser.add_argument(
        "--market-type",
        choices=[item.value for item in MarketType],
        default=MarketType.PERPETUAL.value,
    )
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--source-timeframe", default="1m")
    parser.add_argument("--signal-timeframe", default="30m")
    parser.add_argument("--start", help="Inclusive ISO-8601 start timestamp")
    parser.add_argument("--end", help="Exclusive ISO-8601 end timestamp")
    parser.add_argument("--initial-equity", type=float, default=1_000.0)
    parser.add_argument("--order-notional", type=float, default=12.0)
    parser.add_argument("--leverage", type=int, default=3)
    parser.add_argument("--take-profit-roe", type=float, default=15.0)
    parser.add_argument("--stop-loss-roe", type=float, default=3.0)
    parser.add_argument("--trailing-activation-roe", type=float, default=7.0)
    parser.add_argument("--trailing-interval-minutes", type=int, default=3)
    parser.add_argument("--sar-consecutive-count", type=int, default=4)
    parser.add_argument("--sar-close-consecutive-count", type=int, default=2)
    parser.add_argument("--taker-fee-bps", type=float, required=True)
    parser.add_argument("--slippage-bps", type=float, default=0.0)
    parser.add_argument(
        "--allow-proxy-data",
        action="store_true",
        help=(
            "Permit supported non-Hyperliquid perpetual candles and mark the "
            "result as a proxy backtest"
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show strategy and trailing-stop diagnostic logs",
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    key = CandleSeriesKey(
        exchange=args.exchange,
        market_type=args.market_type,
        symbol=args.symbol,
        timeframe=args.source_timeframe,
    )
    series = load_ohlcv_csv(
        args.input,
        key=key,
        csv_format=args.csv_format,
    )
    series = select_period(series, start=args.start, end=args.end)
    config = BacktestConfig(
        signal_timeframe=args.signal_timeframe,
        initial_equity=args.initial_equity,
        order_notional=args.order_notional,
        leverage=args.leverage,
        take_profit_roe=args.take_profit_roe,
        stop_loss_roe=args.stop_loss_roe,
        trailing_activation_roe=args.trailing_activation_roe,
        trailing_interval_minutes=args.trailing_interval_minutes,
        sar_consecutive_count=args.sar_consecutive_count,
        sar_close_consecutive_count=args.sar_close_consecutive_count,
        taker_fee_bps=args.taker_fee_bps,
        slippage_bps=args.slippage_bps,
        allow_proxy_data=args.allow_proxy_data,
    )
    if not args.verbose:
        logger.disable("crypto_spot_collector")
    try:
        result = PerpetualSarBacktester(config).run(series)
    finally:
        if not args.verbose:
            logger.enable("crypto_spot_collector")
    paths = write_backtest_report(result, args.output_dir)
    print(json.dumps({name: str(path) for name, path in paths.items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
