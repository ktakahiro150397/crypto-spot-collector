"""Data types for exchange operations."""

from dataclasses import dataclass
from typing import Any


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
