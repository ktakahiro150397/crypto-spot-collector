"""Offline, deterministic strategy backtesting."""

from .binance_data import (
    ArchiveSpec,
    BinanceDataError,
    DownloadResult,
    download_binance_usdm_klines,
    plan_archives,
)
from .data import (
    CandleDataError,
    CandleSeries,
    CandleSeriesKey,
    CSVFormat,
    MarketType,
    load_ohlcv_csv,
    provenance_path,
    resample_ohlcv,
    select_period,
    validate_ohlcv,
)
from .engine import (
    BacktestConfig,
    BacktestConfigError,
    BacktestResult,
    PerpetualSarBacktester,
    TradeRecord,
)
from .reporting import write_backtest_report

__all__ = [
    "BacktestConfig",
    "BacktestConfigError",
    "BacktestResult",
    "ArchiveSpec",
    "BinanceDataError",
    "CSVFormat",
    "CandleDataError",
    "CandleSeries",
    "CandleSeriesKey",
    "DownloadResult",
    "MarketType",
    "PerpetualSarBacktester",
    "TradeRecord",
    "download_binance_usdm_klines",
    "load_ohlcv_csv",
    "plan_archives",
    "provenance_path",
    "resample_ohlcv",
    "select_period",
    "validate_ohlcv",
    "write_backtest_report",
]
