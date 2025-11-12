"""Script to import all orders from exchange API to database."""

from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from crypto_spot_collector.database import db_manager
from crypto_spot_collector.exchange.bybit import BybitExchange
from crypto_spot_collector.repository.order_repository import OrderRepository
from crypto_spot_collector.utils.secrets import load_config


def import_orders_for_symbol(
    exchange: BybitExchange,
    order_repo: OrderRepository,
    symbol: str
) -> int:
    """Import all orders for a specific symbol.

    Args:
        exchange: Exchange instance
        order_repo: Order repository instance
        symbol: Symbol to import orders for (e.g., 'BTC')

    Returns:
        Number of orders imported
    """
    logger.info(f"Importing orders for {symbol}")

    try:
        # Fetch all closed orders from exchange
        all_orders = exchange.fetch_close_orders_all(symbol=symbol)
        logger.info(f"Fetched {len(all_orders)} orders for {symbol}")

        imported_count = 0
        skipped_count = 0

        for order in all_orders:
            try:
                order_id = order.get("id", "")
                if not order_id:
                    logger.warning(f"Order without ID found, skipping: {order}")
                    continue

                # Check if order already exists
                existing_order = order_repo.get_order_by_order_id(order_id)
                if existing_order:
                    logger.debug(f"Order {order_id} already exists, skipping")
                    skipped_count += 1
                    continue

                # Extract order information
                symbol_pair = order.get("symbol", f"{symbol}/USDT")
                side = order.get("side", "buy")
                order_type = order.get("type", "limit")
                price = float(order.get("price", 0))
                quantity = float(order.get("amount", 0))

                # Determine status
                order_status = order.get("status", "open")
                if order_status == "closed":
                    status = "closed"
                elif order_status == "canceled":
                    status = "canceled"
                else:
                    status = "open"

                # Get order timestamp
                timestamp_ms = order.get("timestamp", 0)
                if timestamp_ms:
                    order_timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
                else:
                    logger.warning(
                        f"Order {order_id} has no timestamp, using current time"
                    )
                    order_timestamp = datetime.now(timezone.utc)

                # Create order in database
                order_repo.create_order(
                    order_id=order_id,
                    symbol=symbol_pair,
                    side=side,
                    order_type=order_type,
                    price=price,
                    quantity=quantity,
                    status=status,
                    order_timestamp_utc=order_timestamp
                )

                imported_count += 1
                logger.debug(
                    f"Imported order {order_id}: {side} {quantity} {symbol_pair} "
                    f"@ {price} ({status})"
                )

            except Exception as e:
                logger.error(f"Failed to import order: {e}")
                logger.debug(f"Order data: {order}")
                continue

        logger.info(
            f"Completed importing orders for {symbol}: "
            f"{imported_count} imported, {skipped_count} skipped"
        )
        return imported_count

    except Exception as e:
        logger.error(f"Failed to fetch orders for {symbol}: {e}")
        return 0


async def main() -> None:
    """Main function to import all orders."""
    # Load configuration
    secrets_path = Path(__file__).parent.parent / "apps" / "secrets.json"
    settings_path = Path(__file__).parent.parent / "apps" / "settings.json"
    secrets = load_config(secrets_path, settings_path)

    # Initialize exchange
    bybit_exchange = BybitExchange(
        apiKey=secrets["bybit"]["apiKey"],
        secret=secrets["bybit"]["secret"]
    )

    # Create tables if they don't exist
    db_manager.create_tables()
    logger.info("Database tables created/verified")

    # Initialize order repository
    order_repo = OrderRepository()

    # List of symbols to import (same as buy_spot.py)
    spot_symbols = [
        "btc", "eth", "xrp", "sol", "link",
        "avax", "hype", "bnb", "doge", "wld",
        "ltc", "pol", "xaut"
    ]

    total_imported = 0

    # Import orders for each symbol
    for symbol in spot_symbols:
        try:
            count = import_orders_for_symbol(
                exchange=bybit_exchange,
                order_repo=order_repo,
                symbol=symbol.upper()
            )
            total_imported += count
        except Exception as e:
            logger.error(f"Failed to import orders for {symbol}: {e}")
            continue

    logger.info(f"Total orders imported: {total_imported}")
    logger.info("Order import completed successfully")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
