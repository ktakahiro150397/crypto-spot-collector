"""Data types for exchange operations."""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class PositionSide(Enum):
    """Position side for perpetual contracts."""
    LONG = "long"
    SHORT = "short"
    ALL = "all"


@dataclass
class SpotOrderResult:
    """スポット注文の結果を格納するクラス"""
    order_id: str
    symbol: str
    amount: float  # 実際に注文した数量
    price: float   # 実際に注文した価格
    order_value: float  # 注文総額 (amount * price)
    original_order: Any  # 元のorder情報


@dataclass
class SpotAsset:
    """スポット資産の情報を格納するクラス"""
    symbol: str
    total_amount: float  # 総数量
    current_value: float  # 現在価値
    profit_loss: float  # 損益


@dataclass
class PerpetualPosition:
    """Perpetual position information."""
    symbol: str
    side: PositionSide
    amount: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    leverage: float
    liquidation_price: float

    def __str__(self) -> str:
        return (f"PerpetualPosition(symbol={self.symbol}, side={self.side}, "
                f"amount={self.amount}, entry_price={self.entry_price}, "
                f"mark_price={self.mark_price}, unrealized_pnl={self.unrealized_pnl}, "
                f"leverage={self.leverage}, liquidation_price={self.liquidation_price})")
