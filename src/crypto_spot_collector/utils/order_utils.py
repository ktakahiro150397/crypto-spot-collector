"""Utility functions for order management."""

from loguru import logger

from crypto_spot_collector.exchange.bybit import BybitExchange
from crypto_spot_collector.repository.order_repository import OrderRepository


def update_open_orders(
    exchange: BybitExchange,
    order_repo: OrderRepository
) -> int:
    """Update status of all open orders by checking with the exchange.

    Args:
        exchange: Exchange instance
        order_repo: Order repository instance

    Returns:
        Number of orders updated
    """
    logger.info("Updating status of open orders")

    # Get all open orders from database
    open_orders = order_repo.get_open_orders()
    logger.info(f"Found {len(open_orders)} open orders in database")

    updated_count = 0

    for order in open_orders:
        try:
            # Extract base symbol (e.g., BTC from BTC/USDT)
            base_symbol = order.symbol.split("/")[0]

            # Fetch order status from exchange
            logger.debug(
                f"Checking order {order.order_id} for {order.symbol}"
            )

            # Try to get order details from exchange
            try:
                # Use ccxt's fetch_order method
                exchange_order = exchange.exchange.fetch_order(
                    id=order.order_id,
                    symbol=order.symbol
                )

                # Get status from exchange
                exchange_status = exchange_order.get("status", "open")

                # Map exchange status to our status
                new_status = None
                if exchange_status == "closed":
                    new_status = "closed"
                elif exchange_status == "canceled":
                    new_status = "canceled"
                elif exchange_status in ["open", "pending"]:
                    new_status = "open"

                # Update status if changed
                if new_status and new_status != order.status:
                    logger.info(
                        f"Order {order.order_id} status changed: "
                        f"{order.status} -> {new_status}"
                    )
                    order_repo.update_order_status(order.order_id, new_status)
                    updated_count += 1
                else:
                    logger.debug(
                        f"Order {order.order_id} status unchanged: {order.status}"
                    )

            except Exception as e:
                # Order might not be found (very old or already processed)
                logger.warning(
                    f"Could not fetch order {order.order_id} from exchange: {e}"
                )
                # Try to get closed orders to check if it was filled
                try:
                    closed_orders = exchange.fetch_close_orders_all(
                        symbol=base_symbol
                    )
                    found = False
                    for closed_order in closed_orders:
                        if closed_order.get("id") == order.order_id:
                            found = True
                            status = closed_order.get("status", "open")
                            if status == "closed" and order.status != "closed":
                                logger.info(
                                    f"Order {order.order_id} found in closed "
                                    f"orders, updating to closed"
                                )
                                order_repo.update_order_status(
                                    order.order_id, "closed"
                                )
                                updated_count += 1
                            elif status == "canceled" and order.status != "canceled":
                                logger.info(
                                    f"Order {order.order_id} found in closed "
                                    f"orders, updating to canceled"
                                )
                                order_repo.update_order_status(
                                    order.order_id, "canceled"
                                )
                                updated_count += 1
                            break

                    if not found:
                        logger.warning(
                            f"Order {order.order_id} not found in closed orders"
                        )

                except Exception as inner_e:
                    logger.error(
                        f"Failed to check closed orders for {base_symbol}: {inner_e}"
                    )

        except Exception as e:
            logger.error(f"Failed to update order {order.order_id}: {e}")
            continue

    logger.info(f"Updated {updated_count} orders")
    return updated_count
