#!/usr/bin/env python3
"""Historical data import script for crypto spot collector."""

import csv
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

from loguru import logger
from sqlalchemy.dialects.mysql import insert

from crypto_spot_collector.database import db_manager, get_db_session
from crypto_spot_collector.models import Cryptocurrency, OHLCVData


class HistoricalDataImporter:
    """Historical data importer for cryptocurrency OHLCV data."""

    def __init__(
        self,
        historical_data_dir: str = "historical_data",
        batch_size: int = 5000
    ):
        """Initialize the importer with the historical data directory."""
        self.historical_data_dir = Path(historical_data_dir)
        self.session = get_db_session()
        self.batch_size = batch_size

    def extract_symbol_from_path(self, file_path: Path) -> Optional[str]:
        """Extract cryptocurrency symbol from file path.

        Args:
            file_path: Path to the CSV file

        Returns:
            Cryptocurrency symbol (e.g., 'BTC' from 'btcusdt' directory)
        """
        # Get parent directory name (e.g., 'btcusdt')
        parent_dir = file_path.parent.name.lower()

        # Remove 'usdt' suffix to get the base currency symbol
        if parent_dir.endswith('usdt'):
            symbol = parent_dir[:-4].upper()  # Remove 'usdt' and convert to uppercase
            return symbol

        logger.warning(f"Could not extract symbol from path: {file_path}")
        return None

    def get_or_create_cryptocurrency(self, symbol: str) -> Cryptocurrency:
        """Get existing cryptocurrency or create a new one.

        Args:
            symbol: Cryptocurrency symbol (e.g., 'BTC')

        Returns:
            Cryptocurrency model instance
        """
        # Check if cryptocurrency already exists
        crypto = self.session.query(Cryptocurrency).filter_by(symbol=symbol).first()

        if not crypto:
            # Create new cryptocurrency
            crypto = Cryptocurrency(
                symbol=symbol,
                name=f"{symbol} Token"  # Generic name for now
            )
            self.session.add(crypto)
            self.session.commit()
            logger.info(f"Created new cryptocurrency: {symbol}")

        return crypto

    def bulk_upsert_ohlcv_data(self, records: List[dict]) -> int:
        """Perform bulk upsert of OHLCV data using MySQL ON DUPLICATE KEY UPDATE.

        Args:
            records: List of OHLCV data dictionaries

        Returns:
            Number of records processed
        """
        if not records:
            return 0

        try:
            # Use MySQL's INSERT ... ON DUPLICATE KEY UPDATE for upsert
            stmt = insert(OHLCVData).values(records)

            # Update all fields except id and created_at on duplicate key
            upsert_stmt = stmt.on_duplicate_key_update(
                open_price=stmt.inserted.open_price,
                high_price=stmt.inserted.high_price,
                low_price=stmt.inserted.low_price,
                close_price=stmt.inserted.close_price,
                volume=stmt.inserted.volume
                # timestamp_utc and cryptocurrency_id remain the same (unique key)
            )

            # Execute the bulk upsert
            self.session.execute(upsert_stmt)
            self.session.commit()

            # Return the number of affected rows
            return len(records)

        except Exception as e:
            logger.error(f"Error during bulk upsert: {e}")
            self.session.rollback()
            raise

    def parse_csv_line(self, row: List[str]) -> Optional[dict]:
        """Parse a CSV line into OHLCV data dictionary.

        Args:
            row: CSV row as list of strings

        Returns:
            Dictionary with OHLCV data or None if parsing fails
        """
        try:
            if len(row) < 6:
                logger.warning(f"Invalid row format: {row}")
                return None

            # Convert timestamp from microseconds to datetime
            timestamp_microseconds = int(row[0])
            timestamp_seconds = timestamp_microseconds / 1_000_000
            timestamp_utc = datetime.fromtimestamp(timestamp_seconds, tz=timezone.utc)

            return {
                'open_price': Decimal(row[1]),
                'high_price': Decimal(row[2]),
                'low_price': Decimal(row[3]),
                'close_price': Decimal(row[4]),
                'volume': Decimal(row[5]),
                'timestamp_utc': timestamp_utc
            }
        except (ValueError, IndexError) as e:
            logger.error(f"Error parsing CSV row {row}: {e}")
            return None

    def import_csv_file(self, file_path: Path) -> int:
        """Import data from a single CSV file using bulk operations.

        Args:
            file_path: Path to the CSV file

        Returns:
            Number of records imported
        """
        logger.info(f"Importing data from: {file_path}")

        # Extract symbol from file path
        symbol = self.extract_symbol_from_path(file_path)
        if not symbol:
            logger.error(f"Could not extract symbol from file path: {file_path}")
            return 0

        # Get or create cryptocurrency
        crypto = self.get_or_create_cryptocurrency(symbol)

        # Read all data from CSV file
        ohlcv_records = []

        try:
            with open(file_path, 'r', encoding='utf-8') as csvfile:
                reader = csv.reader(csvfile)

                for row_num, row in enumerate(reader, 1):
                    # Parse CSV line
                    ohlcv_dict = self.parse_csv_line(row)
                    if not ohlcv_dict:
                        continue

                    # Add cryptocurrency_id to the record
                    ohlcv_dict['cryptocurrency_id'] = crypto.id
                    ohlcv_records.append(ohlcv_dict)

                    if len(ohlcv_records) % 10000 == 0:
                        logger.info(
                            f"Parsed {len(ohlcv_records)} records from "
                            f"{file_path.name}"
                        )

        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return 0

        if not ohlcv_records:
            logger.warning(f"No valid records found in {file_path}")
            return 0

        logger.info(f"Parsed {len(ohlcv_records)} records, starting batch upsert...")

        # Process records in batches
        total_processed = 0
        batch_count = 0

        for i in range(0, len(ohlcv_records), self.batch_size):
            batch = ohlcv_records[i:i + self.batch_size]
            batch_count += 1

            try:
                processed = self.bulk_upsert_ohlcv_data(batch)
                total_processed += processed

                logger.info(
                    f"Batch {batch_count}: Processed {processed} records "
                    f"({total_processed}/{len(ohlcv_records)})"
                )

            except Exception as e:
                logger.error(f"Error in batch {batch_count} for {file_path}: {e}")
                continue

        logger.info(
            f"Completed importing {file_path.name}: "
            f"{total_processed} records processed"
        )
        return total_processed

    def find_csv_files(self) -> List[Path]:
        """Find all CSV files in the historical data directory.

        Returns:
            List of CSV file paths
        """
        csv_files: List[Path] = []

        if not self.historical_data_dir.exists():
            logger.error(
                f"Historical data directory not found: "
                f"{self.historical_data_dir}"
            )
            return csv_files

        # Search for CSV files recursively
        for csv_file in self.historical_data_dir.rglob("*.csv"):
            csv_files.append(csv_file)

        # Sort files by name for consistent processing order
        csv_files.sort()

        logger.info(f"Found {len(csv_files)} CSV files to import")
        return csv_files

    def import_all_data(self) -> int:
        """Import all historical data from CSV files.

        Returns:
            Total number of records imported
        """
        logger.info("Starting historical data import")

        # Ensure database tables exist
        db_manager.create_tables()

        # Find all CSV files
        csv_files = self.find_csv_files()

        total_imported = 0

        for csv_file in csv_files:
            try:
                imported = self.import_csv_file(csv_file)
                total_imported += imported
            except Exception as e:
                logger.error(f"Failed to import {csv_file}: {e}")
                continue

        logger.info(
            f"Historical data import completed. "
            f"Total records imported: {total_imported}"
        )
        return total_imported

    def close(self) -> None:
        """Close database session."""
        self.session.close()


def main() -> int:
    """Main function to run the historical data import."""
    # Configure logging
    logger.add(
        "logs/import_historical_data.log",
        rotation="1 day",
        retention="30 days",
        level="INFO"
    )

    # Test database connection
    if not db_manager.test_connection():
        logger.error(
            "Database connection failed. "
            "Please check your database configuration."
        )
        return 1

    importer = HistoricalDataImporter()

    try:
        total_imported = importer.import_all_data()
        logger.info(
            f"Import process completed successfully. "
            f"Total records: {total_imported}"
        )
        return 0
    except Exception as e:
        logger.error(f"Import process failed: {e}")
        return 1
    finally:
        importer.close()


if __name__ == "__main__":
    exit(main())
