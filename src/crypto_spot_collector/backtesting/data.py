"""Validated, identity-aware OHLCV input for offline backtests."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype, is_numeric_dtype

from crypto_spot_collector.trading.config import timeframe_milliseconds

OHLCV_COLUMNS: Final[tuple[str, ...]] = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
)
IDENTITY_COLUMNS: Final[tuple[str, ...]] = (
    "exchange",
    "market_type",
    "symbol",
    "timeframe",
)


class CandleDataError(ValueError):
    """Raised when historical candle input is ambiguous or unsafe to replay."""


class MarketType(StrEnum):
    SPOT = "spot"
    PERPETUAL = "perpetual"


class CSVFormat(StrEnum):
    STANDARD = "standard"
    BINANCE_KLINES = "binance_klines"


@dataclass(frozen=True)
class CandleSeriesKey:
    """Identity that prevents unrelated market series from being mixed."""

    exchange: str
    market_type: MarketType | str
    symbol: str
    timeframe: str

    def __post_init__(self) -> None:
        exchange = self.exchange.strip().lower()
        symbol = self.symbol.strip().upper()
        timeframe = self.timeframe.strip().lower()
        try:
            market_type = MarketType(str(self.market_type).strip().lower())
        except ValueError as exc:
            raise CandleDataError(
                f"unsupported market type: {self.market_type!r}"
            ) from exc
        if not exchange:
            raise CandleDataError("exchange must not be empty")
        if not symbol:
            raise CandleDataError("symbol must not be empty")
        try:
            timeframe_milliseconds(timeframe)
        except ValueError as exc:
            raise CandleDataError(str(exc)) from exc
        object.__setattr__(self, "exchange", exchange)
        object.__setattr__(self, "market_type", market_type)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "timeframe", timeframe)

    def as_dict(self) -> dict[str, str]:
        return {
            "exchange": self.exchange,
            "market_type": str(self.market_type),
            "symbol": self.symbol,
            "timeframe": self.timeframe,
        }


@dataclass
class CandleSeries:
    """A validated frame and the complete identity under which it was loaded."""

    key: CandleSeriesKey
    frame: pd.DataFrame
    funding_available: bool
    provenance: dict[str, object] | None = None

    @classmethod
    def from_frame(
        cls,
        key: CandleSeriesKey,
        frame: pd.DataFrame,
        *,
        provenance: dict[str, object] | None = None,
    ) -> "CandleSeries":
        normalized = validate_ohlcv(frame, key.timeframe, key=key)
        return cls(
            key=key,
            frame=normalized,
            funding_available="funding_rate" in normalized.columns,
            provenance=provenance,
        )


def load_ohlcv_csv(
    path: Path | str,
    *,
    key: CandleSeriesKey,
    csv_format: CSVFormat | str = CSVFormat.STANDARD,
) -> CandleSeries:
    """Load either the canonical CSV or a raw Binance kline CSV."""

    source = Path(path)
    if not source.is_file():
        raise CandleDataError(f"candle CSV does not exist: {source}")
    try:
        normalized_format = CSVFormat(str(csv_format).lower())
    except ValueError as exc:
        raise CandleDataError(f"unsupported CSV format: {csv_format!r}") from exc

    if normalized_format is CSVFormat.BINANCE_KLINES:
        raw = pd.read_csv(source, header=None)
        if raw.shape[1] < len(OHLCV_COLUMNS):
            raise CandleDataError("Binance kline CSV requires at least six columns")
        frame = raw.iloc[:, : len(OHLCV_COLUMNS)].copy()
        frame.columns = list(OHLCV_COLUMNS)
    else:
        frame = pd.read_csv(source)
    provenance = _load_provenance(source, key)
    return CandleSeries.from_frame(key, frame, provenance=provenance)


def select_period(
    series: CandleSeries,
    *,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> CandleSeries:
    """Select an inclusive start and exclusive end from a validated series."""

    start_timestamp = _utc_boundary(start, "start") if start is not None else None
    end_timestamp = _utc_boundary(end, "end") if end is not None else None
    if (
        start_timestamp is not None
        and end_timestamp is not None
        and end_timestamp <= start_timestamp
    ):
        raise CandleDataError("period end must be later than period start")
    selected = series.frame
    if start_timestamp is not None:
        selected = selected.loc[selected["timestamp"] >= start_timestamp]
    if end_timestamp is not None:
        selected = selected.loc[selected["timestamp"] < end_timestamp]
    if selected.empty:
        raise CandleDataError("selected period contains no candles")
    return CandleSeries.from_frame(
        series.key,
        selected.reset_index(drop=True),
        provenance=series.provenance,
    )


def validate_ohlcv(
    frame: pd.DataFrame,
    timeframe: str,
    *,
    key: CandleSeriesKey | None = None,
) -> pd.DataFrame:
    """Normalize a candle frame and reject gaps, duplicates, or mixed identity."""

    missing = [column for column in OHLCV_COLUMNS if column not in frame.columns]
    if missing:
        raise CandleDataError("missing OHLCV columns: " + ", ".join(missing))
    if frame.empty:
        raise CandleDataError("candle frame must not be empty")

    interval_ms = _timeframe_ms(timeframe)
    if key is not None:
        if key.timeframe != timeframe.lower():
            raise CandleDataError(
                f"series key timeframe {key.timeframe!r} does not match {timeframe!r}"
            )
        _validate_identity(frame, key)

    output_columns = list(OHLCV_COLUMNS)
    if "funding_rate" in frame.columns:
        output_columns.append("funding_rate")
    normalized = frame.loc[:, output_columns].copy()
    normalized["timestamp"] = _parse_timestamps(normalized["timestamp"])
    if normalized["timestamp"].isna().any():
        raise CandleDataError("candle timestamps contain invalid values")
    if normalized["timestamp"].duplicated().any():
        raise CandleDataError("candle timestamps contain duplicates")
    if not normalized["timestamp"].is_monotonic_increasing:
        raise CandleDataError("candle timestamps must be strictly increasing")

    open_ms = normalized["timestamp"].astype("int64") // 1_000_000
    if (open_ms % interval_ms != 0).any():
        raise CandleDataError("candle timestamps are not aligned to the timeframe")
    deltas = open_ms.diff().dropna()
    if not deltas.eq(interval_ms).all():
        raise CandleDataError("candle sequence contains a gap or wrong interval")

    for column in ("open", "high", "low", "close", "volume"):
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce").astype(
            float
        )
        if not normalized[column].map(math.isfinite).all():
            raise CandleDataError(f"{column} contains a non-finite value")
    if (normalized[["open", "high", "low", "close"]] <= 0).any().any():
        raise CandleDataError("OHLC prices must be greater than zero")
    if (normalized["volume"] < 0).any():
        raise CandleDataError("volume must not be negative")
    if (
        (normalized["high"] < normalized[["open", "close", "low"]].max(axis=1))
        | (normalized["low"] > normalized[["open", "close", "high"]].min(axis=1))
    ).any():
        raise CandleDataError("OHLC bounds are inconsistent")

    if "funding_rate" in normalized.columns:
        normalized["funding_rate"] = pd.to_numeric(
            normalized["funding_rate"], errors="coerce"
        )
        if not normalized["funding_rate"].map(math.isfinite).all():
            raise CandleDataError("funding_rate contains a non-finite value")
    return normalized.reset_index(drop=True)


def resample_ohlcv(
    frame: pd.DataFrame,
    *,
    source_timeframe: str,
    target_timeframe: str,
) -> pd.DataFrame:
    """Aggregate complete source candles into a larger target timeframe."""

    source_ms = _timeframe_ms(source_timeframe)
    target_ms = _timeframe_ms(target_timeframe)
    if target_ms <= source_ms or target_ms % source_ms != 0:
        raise CandleDataError(
            "target timeframe must be an integer multiple larger than source timeframe"
        )
    source = validate_ohlcv(frame, source_timeframe)
    expected_count = target_ms // source_ms
    open_ms = source["timestamp"].astype("int64") // 1_000_000
    source = source.assign(_bucket_ms=(open_ms // target_ms) * target_ms)
    counts = source.groupby("_bucket_ms", sort=True).size()
    if not counts.eq(expected_count).all():
        raise CandleDataError("cannot aggregate incomplete target-timeframe bucket")

    grouped = source.groupby("_bucket_ms", sort=True)
    result = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index()
    result.insert(
        0,
        "timestamp",
        pd.to_datetime(result.pop("_bucket_ms"), unit="ms", utc=True),
    )
    return validate_ohlcv(result, target_timeframe)


def _validate_identity(frame: pd.DataFrame, key: CandleSeriesKey) -> None:
    expected = key.as_dict()
    for column in IDENTITY_COLUMNS:
        if column not in frame.columns:
            continue
        values = frame[column].dropna().astype(str).str.strip()
        normalized = values.str.lower()
        expected_value = expected[column].lower()
        if normalized.nunique() != 1 or normalized.iloc[0] != expected_value:
            raise CandleDataError(
                f"{column} contains mixed data or does not match series identity"
            )


def _parse_timestamps(values: pd.Series) -> pd.Series:
    if is_datetime64_any_dtype(values):
        return pd.to_datetime(values, utc=True, errors="coerce")
    numeric: pd.Series | None = None
    if is_numeric_dtype(values):
        numeric = pd.to_numeric(values, errors="coerce")
    else:
        candidate = pd.to_numeric(values, errors="coerce")
        if candidate.notna().all():
            numeric = candidate
    if numeric is None:
        return pd.to_datetime(values, utc=True, errors="coerce")

    magnitude = float(numeric.abs().max())
    if magnitude >= 100_000_000_000_000:
        unit = "us"
    elif magnitude >= 100_000_000_000:
        unit = "ms"
    else:
        unit = "s"
    return pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")


def provenance_path(csv_path: Path | str) -> Path:
    """Return the sidecar path used for reproducible source metadata."""

    source = Path(csv_path)
    return source.with_suffix(source.suffix + ".manifest.json")


def _load_provenance(
    source: Path,
    key: CandleSeriesKey,
) -> dict[str, object] | None:
    manifest_path = provenance_path(source)
    if not manifest_path.exists():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandleDataError(f"invalid provenance manifest: {manifest_path}") from exc
    if not isinstance(payload, dict):
        raise CandleDataError("provenance manifest root must be an object")

    expected_identity = {
        "source_exchange": key.exchange,
        "market_type": str(key.market_type),
        "symbol": key.symbol,
        "timeframe": key.timeframe,
    }
    for field, expected in expected_identity.items():
        value = payload.get(field)
        if not isinstance(value, str) or value.lower() != expected.lower():
            raise CandleDataError(f"provenance {field} does not match series identity")

    canonical = payload.get("canonical_csv")
    if not isinstance(canonical, dict):
        raise CandleDataError("provenance canonical_csv must be an object")
    expected_hash = canonical.get("sha256")
    if not isinstance(expected_hash, str) or len(expected_hash) != 64:
        raise CandleDataError("provenance canonical CSV hash is invalid")
    actual_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if actual_hash.lower() != expected_hash.lower():
        raise CandleDataError("canonical CSV does not match provenance hash")
    return payload


def _timeframe_ms(timeframe: str) -> int:
    try:
        return int(timeframe_milliseconds(timeframe.lower()))
    except ValueError as exc:
        raise CandleDataError(str(exc)) from exc


def _utc_boundary(value: str | pd.Timestamp, name: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise CandleDataError(f"invalid {name} timestamp: {value!r}") from exc
    if pd.isna(timestamp):
        raise CandleDataError(f"invalid {name} timestamp: {value!r}")
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp
