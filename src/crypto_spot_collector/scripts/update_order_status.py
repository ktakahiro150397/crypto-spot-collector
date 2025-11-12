"""Script to monitor and update order status from exchange."""

from pathlib import Path

from loguru import logger

from crypto_spot_collector.database import db_manager
from crypto_spot_collector.exchange.bybit import BybitExchange
from crypto_spot_collector.repository.order_repository import OrderRepository
from crypto_spot_collector.utils.order_utils import update_open_orders
from crypto_spot_collector.utils.secrets import load_config


async def main() -> None:
    """Main function to update order statuses."""
    # Load configuration
    secrets_path = Path(__file__).parent.parent / "apps" / "secrets.json"
    settings_path = Path(__file__).parent.parent / "apps" / "settings.json"
    secrets = load_config(secrets_path, settings_path)

    # Initialize exchange
    bybit_exchange = BybitExchange(
        apiKey=secrets["bybit"]["apiKey"],
        secret=secrets["bybit"]["secret"]
    )

    # Ensure tables exist
    db_manager.create_tables()
    logger.info("Database tables created/verified")

    # Initialize order repository
    order_repo = OrderRepository()

    # Update order statuses
    updated_count = update_open_orders(
        exchange=bybit_exchange,
        order_repo=order_repo
    )

    logger.info(f"Order status update completed: {updated_count} orders updated")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
