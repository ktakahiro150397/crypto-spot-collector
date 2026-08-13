"""Tests for verified Binance USD-M archive normalization."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from crypto_spot_collector.backtesting.binance_data import (
    BinanceDataError,
    download_binance_usdm_klines,
    plan_archives,
)
from crypto_spot_collector.backtesting.data import CandleSeriesKey, load_ohlcv_csv


def _archive_bytes(start: date, count: int) -> bytes:
    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer, lineterminator="\n")
    writer.writerow(
        [
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_volume",
            "trade_count",
            "taker_base",
            "taker_quote",
            "ignore",
        ]
    )
    for index in range(count):
        instant = datetime.combine(
            start + timedelta(days=index),
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
        open_time = int(instant.timestamp() * 1_000)
        writer.writerow(
            [
                open_time,
                100 + index,
                102 + index,
                99 + index,
                101 + index,
                10 + index,
                open_time + 86_399_999,
                0,
                0,
                0,
                0,
                0,
            ]
        )
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ETHUSDT-1d-2025-01.csv", csv_buffer.getvalue())
    return zip_buffer.getvalue()


def test_archive_plan_uses_monthly_files_and_daily_edges() -> None:
    full_months = plan_archives(
        symbol="ethusdt",
        timeframe="1m",
        start=date(2025, 1, 1),
        end=date(2025, 11, 1),
    )
    partial = plan_archives(
        symbol="ETHUSDT",
        timeframe="1m",
        start=date(2025, 1, 30),
        end=date(2025, 2, 2),
    )

    assert len(full_months) == 10
    assert {archive.kind for archive in full_months} == {"monthly"}
    assert full_months[0].period == "2025-01"
    assert full_months[-1].period == "2025-10"
    assert [archive.kind for archive in partial] == ["daily", "daily", "daily"]


def test_download_verifies_archive_and_emits_identity_and_provenance(
    tmp_path: Path,
) -> None:
    payload = _archive_bytes(date(2025, 1, 1), 31)
    archive_hash = hashlib.sha256(payload).hexdigest()
    base_url = "https://example.test/binance"
    spec = plan_archives(
        symbol="ETHUSDT",
        timeframe="1d",
        start=date(2025, 1, 1),
        end=date(2025, 2, 1),
        base_url=base_url,
    )[0]
    responses = {
        spec.url: payload,
        spec.checksum_url: f"{archive_hash}  archive.zip\n".encode(),
    }
    output = tmp_path / "eth.csv"

    result = download_binance_usdm_klines(
        source_symbol="ETHUSDT",
        canonical_symbol="ETH/USDT:USDT",
        timeframe="1d",
        start=date(2025, 1, 1),
        end=date(2025, 2, 1),
        output=output,
        fetch_bytes=responses.__getitem__,
        base_url=base_url,
    )

    assert result.candle_count == 31
    assert result.archive_count == 1
    series = load_ohlcv_csv(
        output,
        key=CandleSeriesKey("binance", "perpetual", "ETH/USDT:USDT", "1d"),
    )
    assert len(series.frame) == 31
    assert series.provenance is not None
    assert series.provenance["provider"] == "Binance Data Vision"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["archives"][0]["sha256"] == archive_hash
    first_row = output.read_text(encoding="utf-8").splitlines()[1]
    assert first_row.startswith("binance,perpetual,ETH/USDT:USDT,1d,")


def test_download_rejects_checksum_mismatch_without_leaving_output(
    tmp_path: Path,
) -> None:
    payload = _archive_bytes(date(2025, 1, 1), 31)
    base_url = "https://example.test/binance"
    spec = plan_archives(
        symbol="ETHUSDT",
        timeframe="1d",
        start=date(2025, 1, 1),
        end=date(2025, 2, 1),
        base_url=base_url,
    )[0]
    responses = {
        spec.url: payload,
        spec.checksum_url: ("0" * 64 + "  archive.zip\n").encode(),
    }
    output = tmp_path / "eth.csv"

    with pytest.raises(BinanceDataError, match="checksum mismatch"):
        download_binance_usdm_klines(
            source_symbol="ETHUSDT",
            canonical_symbol="ETH/USDT:USDT",
            timeframe="1d",
            start=date(2025, 1, 1),
            end=date(2025, 2, 1),
            output=output,
            fetch_bytes=responses.__getitem__,
            base_url=base_url,
        )

    assert not output.exists()
    assert not list(tmp_path.glob("*.tmp"))
