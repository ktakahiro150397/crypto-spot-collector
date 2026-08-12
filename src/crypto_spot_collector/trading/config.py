"""Validated configuration and the mainnet activation interlock."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence


class Network(str, Enum):
    TESTNET = "testnet"
    MAINNET = "mainnet"


MAINNET_CONFIRMATION = "I_UNDERSTAND_THIS_WILL_TRADE_ON_HYPERLIQUID_MAINNET"


@dataclass(frozen=True)
class TradingConfig:
    """Configuration accepted by the trading runtime.

    Mainnet requires three independent, explicit inputs: ``network=mainnet``,
    ``allow_mainnet=true`` and an exact confirmation phrase. Omitting any of
    them fails before an exchange client is constructed.
    """

    symbols: tuple[str, ...]
    timeframe: str
    amount_usdc: float
    leverage: int
    take_profit_roe: float
    stop_loss_roe: float
    trailing_interval_minutes: int
    trailing_activation_roe: float
    sar_consecutive_count: int
    sar_close_consecutive_count: int
    price_change_threshold_percent: float
    network: Network = Network.TESTNET
    allow_mainnet: bool = False
    mainnet_confirmation: str = ""

    @property
    def testnet(self) -> bool:
        return self.network is Network.TESTNET

    def validate(self) -> None:
        errors: list[str] = []
        if not self.symbols:
            errors.append("at least one symbol is required")
        if len(set(self.symbols)) != len(self.symbols):
            errors.append("symbols must not contain duplicates")
        if any("/" not in symbol or ":" not in symbol for symbol in self.symbols):
            errors.append("symbols must use the CCXT perpetual format BASE/QUOTE:SETTLE")
        _timeframe_seconds(self.timeframe)
        if self.amount_usdc <= 0:
            errors.append("amount_usdc must be greater than zero")
        if not 1 <= self.leverage <= 50:
            errors.append("leverage must be between 1 and 50")
        if self.take_profit_roe <= 0:
            errors.append("take_profit_roe must be greater than zero")
        if self.stop_loss_roe <= 0:
            errors.append("stop_loss_roe must be greater than zero")
        if self.trailing_interval_minutes <= 0:
            errors.append("trailing_interval_minutes must be greater than zero")
        if self.trailing_activation_roe <= 0:
            errors.append("trailing_activation_roe must be greater than zero")
        if self.sar_consecutive_count <= 0:
            errors.append("sar_consecutive_count must be greater than zero")
        if self.sar_close_consecutive_count <= 0:
            errors.append("sar_close_consecutive_count must be greater than zero")
        if self.price_change_threshold_percent <= 0:
            errors.append("price_change_threshold_percent must be greater than zero")
        if self.network is Network.MAINNET:
            if not self.allow_mainnet:
                errors.append("mainnet requires allow_mainnet=true")
            if self.mainnet_confirmation != MAINNET_CONFIRMATION:
                errors.append("mainnet confirmation phrase is missing or invalid")
        if errors:
            raise ValueError("invalid trading configuration: " + "; ".join(errors))

    @classmethod
    def from_mapping(
        cls,
        settings: Mapping[str, Any],
        *,
        symbols: Sequence[str],
        mainnet_confirmation: str = "",
    ) -> "TradingConfig":
        perpetual = settings.get("perpetual", {})
        network_value = settings.get("network")
        if network_value is None:
            # Backward-compatible parsing with a safe default. A missing legacy
            # sandbox flag is testnet, never mainnet.
            sandbox_mode = settings.get("sandbox_mode", True)
            network_value = "testnet" if sandbox_mode else "mainnet"
        try:
            network = Network(str(network_value).lower())
        except ValueError as exc:
            raise ValueError(f"unsupported network: {network_value!r}") from exc

        config = cls(
            symbols=tuple(symbols),
            timeframe=str(perpetual.get("timeframe", "30m")),
            amount_usdc=float(perpetual.get("amountByUSDC", 10.0)),
            leverage=int(perpetual.get("leverage", 1)),
            take_profit_roe=float(perpetual.get("take_profit_rate", 1.0)),
            stop_loss_roe=float(perpetual.get("stop_loss_rate", 1.0)),
            trailing_interval_minutes=int(
                perpetual.get("trailing_stop_interval_minutes", 15)
            ),
            trailing_activation_roe=float(
                perpetual.get("trailing_stop_activation_pnl_percent", 10.0)
            ),
            sar_consecutive_count=int(perpetual.get("consecutivePositiveCount", 3)),
            sar_close_consecutive_count=int(
                perpetual.get("sar_close_consecutive_count", 2)
            ),
            price_change_threshold_percent=float(
                perpetual.get("price_change_threshold_percent", 0.5)
            ),
            network=network,
            allow_mainnet=bool(settings.get("allow_mainnet", False)),
            mainnet_confirmation=mainnet_confirmation,
        )
        config.validate()
        return config


def _timeframe_seconds(timeframe: str) -> int:
    if len(timeframe) < 2 or timeframe[-1] not in {"m", "h", "d"}:
        raise ValueError(f"unsupported timeframe: {timeframe!r}")
    try:
        value = int(timeframe[:-1])
    except ValueError as exc:
        raise ValueError(f"unsupported timeframe: {timeframe!r}") from exc
    if value <= 0:
        raise ValueError(f"unsupported timeframe: {timeframe!r}")
    multiplier = {"m": 60, "h": 3600, "d": 86400}[timeframe[-1]]
    return value * multiplier


def timeframe_milliseconds(timeframe: str) -> int:
    return _timeframe_seconds(timeframe) * 1000
