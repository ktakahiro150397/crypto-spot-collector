"""Safety-critical trading primitives.

The modules in this package are intentionally independent from CCXT and the
application entrypoint so they can be tested without opening a network
connection.
"""

from .config import Network, TradingConfig
from .strategy import CandleGate, StrategyAction, StrategyStateMachine

__all__ = [
    "CandleGate",
    "Network",
    "StrategyAction",
    "StrategyStateMachine",
    "TradingConfig",
]
