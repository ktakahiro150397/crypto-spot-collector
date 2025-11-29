"""Interface definition for exchange classes."""

from abc import ABC, abstractmethod
from datetime import datetime
from types import TracebackType
from typing import Any, Optional

from crypto_spot_collector.exchange.types import SpotAsset, SpotOrderResult


class IExchange(ABC):
    """Abstract base class for exchange interfaces.

    This interface defines async methods only for exchange operations.
    Implementations should provide concrete implementations for specific exchanges
    like Bybit, Hyperliquid, etc.
    """

    @abstractmethod
    async def __aenter__(self) -> "IExchange":
        """Async context manager entry."""
        pass

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType]
    ) -> bool:
        """Async context manager exit."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Explicitly close all exchange connections."""
        pass

    @abstractmethod
    async def fetch_balance_async(self) -> Any:
        """Fetch the account balance asynchronously."""
        pass

    @abstractmethod
    async def fetch_free_usdt_async(self) -> float:
        """Fetch the free USDT balance asynchronously."""
        pass

    @abstractmethod
    async def fetch_price_async(self, symbol: str) -> dict[Any, Any]:
        """Fetch the price for a symbol asynchronously."""
        pass

    @abstractmethod
    async def fetch_ohlcv_async(
        self,
        symbol: str,
        timeframe: str,
        fromDate: datetime,
        toDate: datetime
    ) -> dict[Any, Any]:
        """Fetch OHLCV data asynchronously."""
        pass

    @abstractmethod
    async def fetch_currency_async(self) -> dict[Any, Any]:
        """Fetch currency data asynchronously."""
        pass

    @abstractmethod
    async def create_order_spot_async(
        self,
        amountByUSDT: float,
        symbol: str
    ) -> tuple[Any, SpotOrderResult]:
        """Create a spot order asynchronously."""
        pass

    @abstractmethod
    async def create_order_perp_long_async(
        self,
        symbol: str,
        amount: float,
        price: float,
    ) -> Any:
        """Create a perpetual long order asynchronously."""
        pass

    @abstractmethod
    async def create_order_perp_short_async(
        self,
        symbol: str,
        amount: float,
        price: float,
    ) -> Any:
        """Create a perpetual short order asynchronously."""
        pass

    # @abstractmethod
    # async def close_position_perp_async(
    #     self,
    #     symbol: str,
    # ) -> Any:
    #     """Close a perpetual position asynchronously."""
    #     pass

    @abstractmethod
    async def fetch_average_buy_price_spot_async(self, symbol: str) -> float:
        """Fetch the average buy price for a symbol asynchronously."""
        pass

    @abstractmethod
    async def fetch_close_orders_all_async(
        self,
        symbol: str
    ) -> list[dict[str, Any]]:
        """Fetch all closed orders for a symbol asynchronously."""
        pass

    @abstractmethod
    async def fetch_open_orders_all_async(
        self,
        symbol: str
    ) -> list[dict[str, Any]]:
        """Fetch all open orders for a symbol asynchronously."""
        pass

    @abstractmethod
    async def fetch_canceled_orders_all_async(
        self,
        symbol: str
    ) -> list[dict[str, Any]]:
        """Fetch all canceled orders for a symbol asynchronously."""
        pass

    @abstractmethod
    async def get_current_spot_pnl_async(self, symbol: str) -> float:
        """Get the current spot PnL for a symbol asynchronously."""
        pass

    @abstractmethod
    async def get_spot_portfolio_async(self) -> list[SpotAsset]:
        """Get the spot portfolio asynchronously."""
        pass
