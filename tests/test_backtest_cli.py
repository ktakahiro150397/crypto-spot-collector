"""CLI artifact tests for the offline backtest."""

import json
from pathlib import Path

import pandas as pd

from crypto_spot_collector.backtesting.cli import main


def test_cli_writes_deterministic_report_artifacts(tmp_path: Path) -> None:
    input_path = tmp_path / "candles.csv"
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=12, freq="1min", tz="UTC"),
            "open": [100 + index * 0.1 for index in range(12)],
            "high": [101 + index * 0.1 for index in range(12)],
            "low": [99 + index * 0.1 for index in range(12)],
            "close": [100.5 + index * 0.1 for index in range(12)],
            "volume": [10.0] * 12,
        }
    )
    frame.to_csv(input_path, index=False)
    first = tmp_path / "first"
    second = tmp_path / "second"
    common = [
        "--input",
        str(input_path),
        "--symbol",
        "ETH/USDC:USDC",
        "--source-timeframe",
        "1m",
        "--signal-timeframe",
        "3m",
        "--start",
        "2026-01-01T00:03:00Z",
        "--end",
        "2026-01-01T00:12:00Z",
        "--trailing-interval-minutes",
        "1",
        "--sar-consecutive-count",
        "1",
        "--taker-fee-bps",
        "3.5",
    ]

    assert main([*common, "--output-dir", str(first)]) == 0
    assert main([*common, "--output-dir", str(second)]) == 0

    for name in ("summary.json", "trades.csv", "equity.csv"):
        assert (first / name).read_bytes() == (second / name).read_bytes()

    assert len(pd.read_csv(first / "equity.csv")) == 9


def test_cli_requires_and_records_explicit_proxy_mode(tmp_path: Path) -> None:
    input_path = tmp_path / "binance.csv"
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=6, freq="1min", tz="UTC"),
            "open": [100.0] * 6,
            "high": [100.0] * 6,
            "low": [100.0] * 6,
            "close": [100.0] * 6,
            "volume": [1.0] * 6,
        }
    )
    frame.to_csv(input_path, index=False)
    output = tmp_path / "proxy"

    assert (
        main(
            [
                "--input",
                str(input_path),
                "--exchange",
                "binance",
                "--symbol",
                "ETH/USDT:USDT",
                "--source-timeframe",
                "1m",
                "--signal-timeframe",
                "3m",
                "--trailing-interval-minutes",
                "1",
                "--taker-fee-bps",
                "5",
                "--allow-proxy-data",
                "--output-dir",
                str(output),
            ]
        )
        == 0
    )
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["data_mode"] == "proxy"
    assert summary["series"]["exchange"] == "binance"
