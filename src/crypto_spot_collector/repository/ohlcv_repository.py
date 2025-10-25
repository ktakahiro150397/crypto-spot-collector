"""OHLCV data repository for retrieving crypto market data."""

from datetime import datetime
from typing import List, Literal, Optional, Type

from sqlalchemy import and_, func, text
from sqlalchemy.orm import Session, joinedload

from ..database import get_db_session
from ..models import Cryptocurrency, OHLCVData


class OHLCVRepository:
    """Repository for OHLCV data operations."""

    def __init__(self, session: Optional[Session] = None) -> None:
        """Initialize repository with database session.

        Args:
            session: Database session. If None, creates a new session.
        """
        self.session = session or get_db_session()
        self._own_session = session is None

    def __enter__(self) -> "OHLCVRepository":
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[object]
    ) -> None:
        """Context manager exit."""
        if self._own_session and self.session:
            self.session.close()

    def _get_interval_minutes(self, interval: str) -> int:
        """Convert interval string to minutes.

        Args:
            interval: Time interval (1m, 5m, 10m, 1h, 2h, 4h, 6h)

        Returns:
            Interval in minutes

        Raises:
            ValueError: If interval is not supported
        """
        interval_map = {
            "1m": 1,
            "5m": 5,
            "10m": 10,
            "1h": 60,
            "2h": 120,
            "4h": 240,
            "6h": 360,
        }

        if interval not in interval_map:
            supported = list(interval_map.keys())
            raise ValueError(
                f"Unsupported interval: {interval}. Supported: {supported}"
            )

        return interval_map[interval]

    def _create_interval_filter(self, interval: str) -> str:
        """Create SQL condition for filtering data by interval.

        Args:
            interval: Time interval (1m, 5m, 10m, 1h, 2h, 4h, 6h)

        Returns:
            SQL condition string for MySQL
        """
        if interval.endswith("m"):
            # For minute intervals
            minutes = self._get_interval_minutes(interval)
            return (
                f"MINUTE(timestamp_utc) % {minutes} = 0 "
                "AND SECOND(timestamp_utc) = 0"
            )
        elif interval.endswith("h"):
            # For hour intervals
            hours = self._get_interval_minutes(interval) // 60
            return (
                f"HOUR(timestamp_utc) % {hours} = 0 "
                "AND MINUTE(timestamp_utc) = 0 "
                "AND SECOND(timestamp_utc) = 0"
            )
        else:
            raise ValueError(f"Invalid interval format: {interval}")

    def get_ohlcv_data(
        self,
        symbol: str,
        interval: Literal["1m", "5m", "10m", "1h", "2h", "4h", "6h"],
        from_datetime: datetime,
        to_datetime: datetime,
    ) -> List[OHLCVData]:
        """Get OHLCV data for specified symbol, interval, and time range.

        This method retrieves data only at "clean" time intervals:
        - For minute intervals: at exact minute marks with second = 0
        - For hour intervals: at exact hour marks with minute = 0, second = 0
        - Examples:
          - 4h interval: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00
          - 1h interval: 00:00, 01:00, 02:00, etc.
          - 5m interval: 00:00, 00:05, 00:10, etc.

        Args:
            symbol: Cryptocurrency symbol (e.g., 'BTCUSDT')
            interval: Time interval for data aggregation
            from_datetime: Start datetime (inclusive)
            to_datetime: End datetime (inclusive)

        Returns:
            List of OHLCVData objects ordered by timestamp

        Raises:
            ValueError: If symbol not found or interval not supported
        """
        # Validate interval
        self._get_interval_minutes(interval)

        # Find cryptocurrency by symbol
        crypto = (
            self.session.query(Cryptocurrency)
            .filter(Cryptocurrency.symbol == symbol.upper())
            .first()
        )

        if not crypto:
            raise ValueError(f"Cryptocurrency with symbol '{symbol}' not found")

        # Create interval condition
        interval_condition = self._create_interval_filter(interval)

        # Build query
        query = (
            self.session.query(OHLCVData)
            .options(joinedload(OHLCVData.cryptocurrency))
            .filter(
                and_(
                    OHLCVData.cryptocurrency_id == crypto.id,
                    OHLCVData.timestamp_utc >= from_datetime,
                    OHLCVData.timestamp_utc <= to_datetime,
                )
            )
            .filter(text(interval_condition))
            .order_by(OHLCVData.timestamp_utc)
        )

        return query.all()

    def get_latest_ohlcv_data(
        self,
        symbol: str,
        limit: int = 100,
    ) -> List[OHLCVData]:
        """Get latest OHLCV data for specified symbol.

        Args:
            symbol: Cryptocurrency symbol (e.g., 'BTCUSDT')
            limit: Maximum number of records to return

        Returns:
            List of OHLCVData objects ordered by timestamp (latest first)

        Raises:
            ValueError: If symbol not found
        """
        # Find cryptocurrency by symbol
        crypto = (
            self.session.query(Cryptocurrency)
            .filter(Cryptocurrency.symbol == symbol.upper())
            .first()
        )

        if not crypto:
            raise ValueError(f"Cryptocurrency with symbol '{symbol}' not found")

        # Build query
        query = (
            self.session.query(OHLCVData)
            .options(joinedload(OHLCVData.cryptocurrency))
            .filter(OHLCVData.cryptocurrency_id == crypto.id)
            .order_by(OHLCVData.timestamp_utc.desc())
            .limit(limit)
        )

        return query.all()

    def get_ohlcv_data_count(
        self,
        symbol: str,
        interval: Literal["1m", "5m", "10m", "1h", "2h", "4h", "6h"],
        from_datetime: datetime,
        to_datetime: datetime,
    ) -> int:
        """Get count of OHLCV data records for specified parameters.

        Args:
            symbol: Cryptocurrency symbol (e.g., 'BTCUSDT')
            interval: Time interval for data aggregation
            from_datetime: Start datetime (inclusive)
            to_datetime: End datetime (inclusive)

        Returns:
            Number of records that match the criteria

        Raises:
            ValueError: If symbol not found or interval not supported
        """
        # Validate interval
        self._get_interval_minutes(interval)

        # Find cryptocurrency by symbol
        crypto = (
            self.session.query(Cryptocurrency)
            .filter(Cryptocurrency.symbol == symbol.upper())
            .first()
        )

        if not crypto:
            raise ValueError(f"Cryptocurrency with symbol '{symbol}' not found")

        # Create interval condition
        interval_condition = self._create_interval_filter(interval)

        # Build count query
        query = (
            self.session.query(func.count(OHLCVData.id))
            .filter(
                and_(
                    OHLCVData.cryptocurrency_id == crypto.id,
                    OHLCVData.timestamp_utc >= from_datetime,
                    OHLCVData.timestamp_utc <= to_datetime,
                )
            )
            .filter(text(interval_condition))
        )

        return query.scalar() or 0

    def get_available_symbols(self) -> List[str]:
        """Get list of available cryptocurrency symbols.

        Returns:
            List of cryptocurrency symbols
        """
        symbols = (
            self.session.query(Cryptocurrency.symbol)
            .order_by(Cryptocurrency.symbol)
            .all()
        )

        return [symbol[0] for symbol in symbols]

    def get_date_range(self, symbol: str) -> tuple[datetime, datetime]:
        """Get the date range of available data for a symbol.

        Args:
            symbol: Cryptocurrency symbol (e.g., 'BTCUSDT')

        Returns:
            Tuple of (earliest_date, latest_date)

        Raises:
            ValueError: If symbol not found or no data available
        """
        # Find cryptocurrency by symbol
        crypto = (
            self.session.query(Cryptocurrency)
            .filter(Cryptocurrency.symbol == symbol.upper())
            .first()
        )

        if not crypto:
            raise ValueError(f"Cryptocurrency with symbol '{symbol}' not found")

        # Get min and max timestamps
        result = (
            self.session.query(
                func.min(OHLCVData.timestamp_utc),
                func.max(OHLCVData.timestamp_utc)
            )
            .filter(OHLCVData.cryptocurrency_id == crypto.id)
            .first()
        )

        if not result or not result[0] or not result[1]:
            raise ValueError(f"No data available for symbol '{symbol}'")

        return result[0], result[1]
