
from dataclasses import dataclass, field

from crypto_spot_collector.exchange.types import PositionSide


@dataclass
class TrailingStopPositionBase:
    symbol: str
    side: PositionSide
    entry_price: float

    highest_price: float
    lowest_price: float

    current_stoploss_price: float
    current_af_factor: float

    # トレーリングが有効化されたかどうか（PnL条件を満たした後にTrue）
    trailing_activated: bool = field(default=False)


@dataclass
class TrailingStopPositionHyperLiquid(TrailingStopPositionBase):
    stoploss_order_id: str = field(default="")
