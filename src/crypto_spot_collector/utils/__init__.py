"""Crypto Spot Collector main module."""

from .secrets import load_config, load_secrets, load_settings
from .trade_data import create_update_trade_data

__version__ = "0.1.0"
__all__ = ["load_secrets", "load_settings",
           "load_config", "create_update_trade_data"]
