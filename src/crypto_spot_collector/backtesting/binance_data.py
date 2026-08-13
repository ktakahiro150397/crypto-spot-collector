"""Download official Binance USD-M kline archives as canonical backtest CSV."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from .data import CandleSeriesKey, MarketType, load_ohlcv_csv, provenance_path

BINANCE_DATA_BASE_URL = "https://data.binance.vision/data/futures/um"
CANONICAL_COLUMNS = (
    "exchange",
    "market_type",
    "symbol",
    "timeframe",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
)
FetchBytes = Callable[[str], bytes]


class RowWriter(Protocol):
    """Small structural type for csv.writer."""

    def writerow(self, row: Sequence[object]) -> object:
        """Write one CSV row."""


class BinanceDataError(RuntimeError):
    """Raised when an official archive cannot be verified or normalized."""


@dataclass(frozen=True)
class ArchiveSpec:
    """One official daily or monthly archive used by a requested range."""

    kind: str
    period: str
    url: str
    checksum_url: str


@dataclass(frozen=True)
class DownloadResult:
    """Paths and counts produced by a completed canonical download."""

    csv_path: Path
    manifest_path: Path
    candle_count: int
    archive_count: int


def plan_archives(
    *,
    symbol: str,
    timeframe: str,
    start: date,
    end: date,
    base_url: str = BINANCE_DATA_BASE_URL,
) -> list[ArchiveSpec]:
    """Use monthly archives for full months and daily archives at the edges."""

    if end <= start:
        raise BinanceDataError("end date must be later than start date")
    normalized_symbol = symbol.strip().upper()
    normalized_timeframe = timeframe.strip().lower()
    if not normalized_symbol or not normalized_timeframe:
        raise BinanceDataError("symbol and timeframe must not be empty")

    specs: list[ArchiveSpec] = []
    cursor = start
    while cursor < end:
        next_month = _next_month(cursor)
        if cursor.day == 1 and next_month <= end:
            kind = "monthly"
            period = cursor.strftime("%Y-%m")
            cursor = next_month
        else:
            kind = "daily"
            period = cursor.isoformat()
            cursor += timedelta(days=1)
        name = f"{normalized_symbol}-{normalized_timeframe}-{period}.zip"
        url = (
            f"{base_url.rstrip('/')}/{kind}/klines/{normalized_symbol}/"
            f"{normalized_timeframe}/{name}"
        )
        specs.append(
            ArchiveSpec(
                kind=kind,
                period=period,
                url=url,
                checksum_url=url + ".CHECKSUM",
            )
        )
    return specs


def download_binance_usdm_klines(
    *,
    source_symbol: str,
    canonical_symbol: str,
    timeframe: str,
    start: date,
    end: date,
    output: Path | str,
    overwrite: bool = False,
    fetch_bytes: FetchBytes | None = None,
    base_url: str = BINANCE_DATA_BASE_URL,
) -> DownloadResult:
    """Verify Binance archives and convert them into one identity-aware CSV."""

    output_path = Path(output)
    manifest_path = provenance_path(output_path)
    if not overwrite and (output_path.exists() or manifest_path.exists()):
        raise BinanceDataError(
            "output or provenance manifest already exists; pass --overwrite to replace"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    key = CandleSeriesKey(
        exchange="binance",
        market_type=MarketType.PERPETUAL,
        symbol=canonical_symbol,
        timeframe=timeframe,
    )
    archives = plan_archives(
        symbol=source_symbol,
        timeframe=key.timeframe,
        start=start,
        end=end,
        base_url=base_url,
    )
    fetch = fetch_bytes or _fetch_bytes
    start_ms = _date_milliseconds(start)
    end_ms = _date_milliseconds(end)
    archive_records: list[dict[str, object]] = []
    candle_count = 0
    csv_temp: Path | None = None
    manifest_temp: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=output_path.name + ".",
            suffix=".tmp",
            dir=output_path.parent,
            delete=False,
        ) as destination:
            csv_temp = Path(destination.name)
            writer = csv.writer(destination, lineterminator="\n")
            writer.writerow(CANONICAL_COLUMNS)
            for archive in archives:
                checksum_payload = _fetch(fetch, archive.checksum_url)
                expected_hash = _parse_checksum(checksum_payload, archive.checksum_url)
                archive_payload = _fetch(fetch, archive.url)
                actual_hash = hashlib.sha256(archive_payload).hexdigest()
                if actual_hash.lower() != expected_hash.lower():
                    raise BinanceDataError(
                        f"checksum mismatch for {archive.url}: "
                        f"expected {expected_hash}, got {actual_hash}"
                    )
                rows_written = _write_archive_rows(
                    archive_payload,
                    writer=writer,
                    key=key,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    source_url=archive.url,
                )
                candle_count += rows_written
                record = asdict(archive)
                record["sha256"] = actual_hash
                record["candle_count"] = rows_written
                archive_records.append(record)

        if candle_count == 0:
            raise BinanceDataError("requested archives contained no candles in range")
        load_ohlcv_csv(csv_temp, key=key)
        canonical_hash = hashlib.sha256(csv_temp.read_bytes()).hexdigest()
        manifest = {
            "schema_version": 1,
            "provider": "Binance Data Vision",
            "source_exchange": key.exchange,
            "market_type": str(key.market_type),
            "instrument_type": "USD-M Futures",
            "source_symbol": source_symbol.strip().upper(),
            "symbol": key.symbol,
            "timeframe": key.timeframe,
            "requested_range": {
                "start": _date_iso(start),
                "end": _date_iso(end),
                "end_inclusive": False,
            },
            "candle_count": candle_count,
            "archives": archive_records,
            "canonical_csv": {
                "filename": output_path.name,
                "sha256": canonical_hash,
                "columns": list(CANONICAL_COLUMNS),
            },
        }
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=manifest_path.name + ".",
            suffix=".tmp",
            dir=manifest_path.parent,
            delete=False,
        ) as destination:
            manifest_temp = Path(destination.name)
            json.dump(manifest, destination, indent=2, sort_keys=True)
            destination.write("\n")

        csv_temp.replace(output_path)
        csv_temp = None
        manifest_temp.replace(manifest_path)
        manifest_temp = None
    finally:
        if csv_temp is not None:
            csv_temp.unlink(missing_ok=True)
        if manifest_temp is not None:
            manifest_temp.unlink(missing_ok=True)

    return DownloadResult(
        csv_path=output_path,
        manifest_path=manifest_path,
        candle_count=candle_count,
        archive_count=len(archives),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download checksum-verified Binance USD-M kline archives and emit "
            "a canonical perpetual OHLCV CSV."
        )
    )
    parser.add_argument("--symbol", required=True, help="Binance symbol, e.g. ETHUSDT")
    parser.add_argument(
        "--canonical-symbol",
        required=True,
        help="Identity stored in the CSV, e.g. ETH/USDT:USDT",
    )
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--start", required=True, type=_parse_date)
    parser.add_argument(
        "--end",
        required=True,
        type=_parse_date,
        help="Exclusive UTC date",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = download_binance_usdm_klines(
        source_symbol=args.symbol,
        canonical_symbol=args.canonical_symbol,
        timeframe=args.timeframe,
        start=args.start,
        end=args.end,
        output=args.output,
        overwrite=args.overwrite,
    )
    print(
        json.dumps(
            {
                "csv": str(result.csv_path),
                "manifest": str(result.manifest_path),
                "candle_count": result.candle_count,
                "archive_count": result.archive_count,
            },
            sort_keys=True,
        )
    )
    return 0


def _write_archive_rows(
    payload: bytes,
    *,
    writer: RowWriter,
    key: CandleSeriesKey,
    start_ms: int,
    end_ms: int,
    source_url: str,
) -> int:
    try:
        archive_file = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise BinanceDataError(f"invalid ZIP archive: {source_url}") from exc
    with archive_file:
        members = [name for name in archive_file.namelist() if name.endswith(".csv")]
        if len(members) != 1:
            raise BinanceDataError(
                f"archive must contain exactly one CSV file: {source_url}"
            )
        count = 0
        with archive_file.open(members[0]) as raw:
            with io.TextIOWrapper(raw, encoding="utf-8", newline="") as text:
                for row_number, row in enumerate(csv.reader(text), start=1):
                    if not row:
                        continue
                    if row[0].strip().lower().replace(" ", "_") == "open_time":
                        continue
                    if len(row) < 6:
                        raise BinanceDataError(
                            f"archive row {row_number} has fewer than six columns: "
                            f"{source_url}"
                        )
                    timestamp_ms = _timestamp_milliseconds(row[0], source_url)
                    if not start_ms <= timestamp_ms < end_ms:
                        continue
                    writer.writerow(
                        [
                            key.exchange,
                            str(key.market_type),
                            key.symbol,
                            key.timeframe,
                            row[0],
                            row[1],
                            row[2],
                            row[3],
                            row[4],
                            row[5],
                        ]
                    )
                    count += 1
    return count


def _fetch(fetch: FetchBytes, url: str) -> bytes:
    try:
        return fetch(url)
    except BinanceDataError:
        raise
    except Exception as exc:
        raise BinanceDataError(f"failed to download {url}: {exc}") from exc


def _fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "crypto-spot-collector/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            buffer = io.BytesIO()
            shutil.copyfileobj(response, buffer)
            return buffer.getvalue()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise BinanceDataError(f"failed to download {url}: {exc}") from exc


def _parse_checksum(payload: bytes, url: str) -> str:
    try:
        checksum = payload.decode("ascii").split()[0]
    except (UnicodeDecodeError, IndexError) as exc:
        raise BinanceDataError(f"invalid checksum file: {url}") from exc
    if len(checksum) != 64 or any(
        character not in "0123456789abcdefABCDEF" for character in checksum
    ):
        raise BinanceDataError(f"invalid SHA-256 checksum: {url}")
    return checksum.lower()


def _timestamp_milliseconds(value: str, url: str) -> int:
    try:
        timestamp = int(value)
    except ValueError as exc:
        raise BinanceDataError(f"invalid candle timestamp in {url}: {value!r}") from exc
    magnitude = abs(timestamp)
    if magnitude >= 100_000_000_000_000:
        return timestamp // 1_000
    if magnitude >= 100_000_000_000:
        return timestamp
    return timestamp * 1_000


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from exc


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _date_milliseconds(value: date) -> int:
    timestamp = datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    return int(timestamp.timestamp() * 1_000)


def _date_iso(value: date) -> str:
    return (
        datetime.combine(
            value,
            datetime.min.time(),
            tzinfo=timezone.utc,
        )
        .isoformat()
        .replace("+00:00", "Z")
    )


if __name__ == "__main__":
    raise SystemExit(main())
