"""
HyperLiquid WebSocket client for real-time OHLCV data subscription.
CCXTがHyperliquidのWebSocketをサポートしていないため、自作実装。
"""
import asyncio
import json
from typing import Any, Callable, Optional

import websockets
from loguru import logger
from websockets.client import WebSocketClientProtocol


class HyperLiquidWebSocket:
    """HyperLiquid WebSocket client for subscribing to candle (OHLCV) data."""

    WS_URL_MAINNET = "wss://api.hyperliquid.xyz/ws"
    WS_URL_TESTNET = "wss://api.hyperliquid-testnet.xyz/ws"

    # サポートされている時間足
    SUPPORTED_INTERVALS = [
        "1m", "3m", "5m", "15m", "30m",
        "1h", "2h", "4h", "8h", "12h",
        "1d", "3d", "1w", "1M"
    ]

    def __init__(self, testnet: bool = False, max_retries: int = 5, retry_delay: float = 5.0):
        """
        Initialize HyperLiquid WebSocket client.

        Args:
            testnet: Use testnet if True, mainnet if False (default)
            max_retries: Maximum number of reconnection attempts (default: 5)
            retry_delay: Initial delay between reconnection attempts in seconds (default: 5.0)
        """
        self.ws_url = self.WS_URL_TESTNET if testnet else self.WS_URL_MAINNET
        self.ws: Optional[WebSocketClientProtocol] = None
        self._running = False
        self._callbacks: dict[str, Callable] = {}
        self._subscriptions: list[dict[str, Any]] = []
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._reconnecting = False

        logger.info(
            f"Initialized HyperLiquid WebSocket client "
            f"({'testnet' if testnet else 'mainnet'})"
        )

    async def connect(self) -> None:
        """Establish WebSocket connection."""
        if self.ws is not None:
            logger.warning("WebSocket is already connected")
            return

        try:
            self.ws = await websockets.connect(self.ws_url)
            self._running = True
            logger.info(f"WebSocket connected to {self.ws_url}")
        except Exception as e:
            logger.error(f"Failed to connect to WebSocket: {e}")
            raise

    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        self._running = False

        if self.ws is not None:
            await self.ws.close()
            self.ws = None
            logger.info("WebSocket disconnected")

    async def _reconnect(self) -> bool:
        """
        Attempt to reconnect to WebSocket with exponential backoff.

        Returns:
            True if reconnection was successful, False otherwise
        """
        if self._reconnecting:
            logger.debug("Already attempting to reconnect")
            return False

        self._reconnecting = True
        retry_count = 0
        delay = self._retry_delay

        try:
            while retry_count < self._max_retries and self._running:
                retry_count += 1
                logger.info(
                    f"Reconnection attempt {retry_count}/{self._max_retries}")

                try:
                    # Close existing connection if any
                    if self.ws is not None:
                        try:
                            await self.ws.close()
                        except Exception:
                            pass
                        self.ws = None

                    # Attempt to reconnect
                    self.ws = await websockets.connect(self.ws_url)
                    logger.info(f"WebSocket reconnected to {self.ws_url}")

                    # Restore all subscriptions
                    await self._restore_subscriptions()

                    self._reconnecting = False
                    return True

                except Exception as e:
                    logger.warning(
                        f"Reconnection attempt {retry_count} failed: {e}")
                    if retry_count < self._max_retries:
                        logger.info(
                            f"Waiting {delay:.1f}s before next attempt...")
                        await asyncio.sleep(delay)
                        # Exponential backoff with max 60 seconds
                        delay = min(delay * 2, 60.0)

            logger.error(
                f"Failed to reconnect after {self._max_retries} attempts")
            return False

        finally:
            self._reconnecting = False

    async def _restore_subscriptions(self) -> None:
        """
        Restore all subscriptions after reconnection.
        """
        if not self._subscriptions:
            logger.debug("No subscriptions to restore")
            return

        logger.info(f"Restoring {len(self._subscriptions)} subscription(s)...")

        for subscription in self._subscriptions:
            try:
                if self.ws is not None:
                    await self.ws.send(json.dumps(subscription))
                    coin = subscription["subscription"]["coin"]
                    interval = subscription["subscription"]["interval"]
                    logger.info(f"Restored subscription for {coin} {interval}")
            except Exception as e:
                logger.error(
                    f"Failed to restore subscription {subscription}: {e}")

        logger.info("Subscription restoration complete")

    async def subscribe_candle(
        self,
        coin: str,
        interval: str,
        callback: Callable[[dict[str, Any]], None]
    ) -> None:
        """
        Subscribe to candle (OHLCV) updates for a specific coin and interval.

        Args:
            coin: Coin symbol (e.g., "BTC", "ETH", "SOL")
            interval: Candle interval (e.g., "1m", "5m", "1h", "1d")
            callback: Callback function to handle incoming candle data

        Raises:
            ValueError: If interval is not supported
            RuntimeError: If WebSocket is not connected
        """
        if interval not in self.SUPPORTED_INTERVALS:
            raise ValueError(
                f"Unsupported interval: {interval}. "
                f"Supported intervals: {', '.join(self.SUPPORTED_INTERVALS)}"
            )

        if self.ws is None:
            raise RuntimeError(
                "WebSocket is not connected. Call connect() first.")

        subscription = {
            "method": "subscribe",
            "subscription": {
                "type": "candle",
                "coin": coin,
                "interval": interval
            }
        }

        # Send subscription message
        await self.ws.send(json.dumps(subscription))
        logger.info(f"Subscribed to {coin} candles with {interval} interval")

        # Store subscription and callback
        sub_key = f"candle_{coin}_{interval}"
        self._callbacks[sub_key] = callback
        self._subscriptions.append(subscription)

    async def subscribe_trade(self,
                              coin: str,
                              callback: Callable[[dict[str, Any]], None]) -> None:
        if self.ws is None:
            raise RuntimeError(
                "WebSocket is not connected. Call connect() first.")

        subscription = {
            "method": "subscribe",
            "subscription": {
                "type": "trades",
                "coin": coin
            }
        }

        # Send subscription message
        await self.ws.send(json.dumps(subscription))
        logger.info(f"Subscribed to {coin} trades")

        # Store subscription and callback
        sub_key = f"trade_{coin}"
        self._callbacks[sub_key] = callback
        self._subscriptions.append(subscription)

    async def subscribe_userFills(self,
                                  walletAddress: str,
                                  callback: Callable[[dict[str, Any]], None]) -> None:
        walletAddress = walletAddress.lower()
        if self.ws is None:
            raise RuntimeError(
                "WebSocket is not connected. Call connect() first.")
        subscription = {
            "method": "subscribe",
            "subscription": {
                "type": "userFills",
                "user": walletAddress
            }
        }

        # Send subscription message
        await self.ws.send(json.dumps(subscription))
        logger.info(f"Subscribed to userFills for {walletAddress}")

        # Store subscription and callback
        sub_key = f"userFills_{walletAddress}"
        self._callbacks[sub_key] = callback
        self._subscriptions.append(subscription)

    async def unsubscribe_candle(self, coin: str, interval: str) -> None:
        """
        Unsubscribe from candle updates.

        Args:
            coin: Coin symbol
            interval: Candle interval
        """
        if self.ws is None:
            logger.warning("WebSocket is not connected")
            return

        unsubscription = {
            "method": "unsubscribe",
            "subscription": {
                "type": "candle",
                "coin": coin,
                "interval": interval
            }
        }

        await self.ws.send(json.dumps(unsubscription))
        logger.info(
            f"Unsubscribed from {coin} candles with {interval} interval")

        # Remove callback
        sub_key = f"candle_{coin}_{interval}"
        if sub_key in self._callbacks:
            del self._callbacks[sub_key]

    async def listen(self) -> None:
        """
        Listen for incoming WebSocket messages and dispatch to callbacks.

        This method should be run in a separate task/coroutine.
        """
        if self.ws is None:
            raise RuntimeError(
                "WebSocket is not connected. Call connect() first.")

        logger.info("Started listening for WebSocket messages")

        try:
            while self._running:
                try:
                    message = await asyncio.wait_for(self.ws.recv(), timeout=30.0)
                    logger.debug(f"Received WebSocket message: {message}")
                    data = json.loads(message)
                    logger.debug(f"Parsed message data: {data}")

                    # Handle subscription response
                    if data.get("channel") == "subscriptionResponse":
                        logger.info(f"Subscription confirmed: {data}")
                        continue

                    # Handle candle data
                    if data.get("channel") == "candle":
                        candle_data = data.get("data", [])
                        logger.info(f"Received candle data: {candle_data}")
                        if candle_data:
                            # Extract coin and interval from first candle
                            first_candle = candle_data[0] if isinstance(
                                candle_data, list) else candle_data
                            coin = first_candle.get("s")
                            interval = first_candle.get("i")

                            # Find and call the appropriate callback
                            sub_key = f"candle_{coin}_{interval}"
                            logger.debug(
                                f"Looking for callback with key: {sub_key}")
                            if sub_key in self._callbacks:
                                self._callbacks[sub_key](candle_data)
                            else:
                                logger.warning(
                                    f"No callback found for {sub_key}. Available callbacks: {list(self._callbacks.keys())}")
                    elif data.get("channel") == "trades":
                        trade_data = data.get("data", [])
                        logger.info(f"Received trade data: {trade_data}")
                        if trade_data:
                            # Extract coin from first trade
                            first_trade = trade_data[0] if isinstance(
                                trade_data, list) else trade_data
                            coin = first_trade.get("coin")

                            # Find and call the appropriate callback
                            sub_key = f"trade_{coin}"
                            logger.debug(
                                f"Looking for callback with key: {sub_key}")
                            if sub_key in self._callbacks:
                                self._callbacks[sub_key](trade_data)
                            else:
                                logger.warning(
                                    f"No callback found for {sub_key}. Available callbacks: {list(self._callbacks.keys())}")
                    elif data.get("channel") == "userFills":
                        user_fills_data = data.get("data", None)
                        logger.info(
                            f"Received userFills data: {user_fills_data}")
                        if user_fills_data:
                            # Extract user from first fill
                            user = user_fills_data.get("user")

                            # Find and call the appropriate callback
                            sub_key = f"userFills_{user}"
                            logger.debug(
                                f"Looking for callback with key: {sub_key}")
                            if sub_key in self._callbacks:
                                self._callbacks[sub_key](user_fills_data)
                            else:
                                logger.warning(
                                    f"No callback found for {sub_key}. Available callbacks: {list(self._callbacks.keys())}")
                    else:
                        logger.debug(
                            f"Received message with channel: {data.get('channel')}")

                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    logger.debug("WebSocket receive timeout, sending ping")
                    if self.ws:
                        try:
                            await self.ws.ping()
                        except Exception as e:
                            logger.warning(f"Failed to send ping: {e}")
                            # Connection might be dead, trigger reconnection
                            if self._running:
                                logger.info("Attempting to reconnect...")
                                if await self._reconnect():
                                    continue
                                else:
                                    self._running = False
                                    break
                    continue
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("WebSocket connection closed")
                    if self._running:
                        logger.info("Attempting to reconnect...")
                        if await self._reconnect():
                            continue
                        else:
                            self._running = False
                            break
                    else:
                        self._running = False
                        break
                except Exception as e:
                    logger.error(
                        f"Error processing WebSocket message: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Error in listen loop: {e}", exc_info=True)
        finally:
            logger.info("Stopped listening for WebSocket messages")

    async def __aenter__(self) -> "HyperLiquidWebSocket":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()
