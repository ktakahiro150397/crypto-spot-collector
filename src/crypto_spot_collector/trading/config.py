"""Validated configuration and the mainnet activation interlock."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence


class Network(str, Enum):
    TESTNET = "testnet"
    MAINNET = "mainnet"


class SignalMode(str, Enum):
    SAR_ONLY = "sar_only"
    PRICE_CHANGE_ONLY = "price_change_only"


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
    max_order_notional_usdc: float
    max_symbol_notional_usdc: float
    max_total_notional_usdc: float
    max_positions: int
    max_leverage: int
    min_free_collateral_usdc: float
    signal_mode: SignalMode = SignalMode.SAR_ONLY
    margin_mode: str = "cross"
    canary_mode: bool = False
    entries_enabled: bool = True
    entry_kill_switch_file: str = "state/ENTRY_KILL_SWITCH"
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
            errors.append(
                "symbols must use the CCXT perpetual format BASE/QUOTE:SETTLE"
            )
        _timeframe_seconds(self.timeframe)
        if not _positive_number(self.amount_usdc):
            errors.append("amount_usdc must be greater than zero")
        if not 1 <= self.leverage <= 50:
            errors.append("leverage must be between 1 and 50")
        if not _positive_number(self.take_profit_roe):
            errors.append("take_profit_roe must be greater than zero")
        if not _positive_number(self.stop_loss_roe):
            errors.append("stop_loss_roe must be greater than zero")
        if self.trailing_interval_minutes <= 0:
            errors.append("trailing_interval_minutes must be greater than zero")
        if not _positive_number(self.trailing_activation_roe):
            errors.append("trailing_activation_roe must be greater than zero")
        elif self.trailing_activation_roe >= self.take_profit_roe:
            errors.append("trailing_activation_roe must be lower than take_profit_roe")
        if self.sar_consecutive_count <= 0:
            errors.append("sar_consecutive_count must be greater than zero")
        if self.sar_close_consecutive_count <= 0:
            errors.append("sar_close_consecutive_count must be greater than zero")
        if not _positive_number(self.price_change_threshold_percent):
            errors.append("price_change_threshold_percent must be greater than zero")
        if not _positive_number(self.max_order_notional_usdc):
            errors.append("max_order_notional_usdc must be greater than zero")
        if not _positive_number(self.max_symbol_notional_usdc):
            errors.append("max_symbol_notional_usdc must be greater than zero")
        elif self.max_symbol_notional_usdc < self.max_order_notional_usdc:
            errors.append("max_symbol_notional_usdc must cover max order notional")
        if not _positive_number(self.max_total_notional_usdc):
            errors.append("max_total_notional_usdc must be greater than zero")
        elif self.max_total_notional_usdc < self.max_symbol_notional_usdc:
            errors.append("max_total_notional_usdc must cover max symbol notional")
        if self.amount_usdc > self.max_order_notional_usdc:
            errors.append("amount_usdc exceeds max_order_notional_usdc")
        if self.max_positions <= 0:
            errors.append("max_positions must be greater than zero")
        if not 1 <= self.max_leverage <= 50:
            errors.append("max_leverage must be between 1 and 50")
        if self.leverage > self.max_leverage:
            errors.append("leverage exceeds max_leverage")
        if (
            not math.isfinite(self.min_free_collateral_usdc)
            or self.min_free_collateral_usdc < 0
        ):
            errors.append("min_free_collateral_usdc must not be negative")
        if not self.entry_kill_switch_file.strip():
            errors.append("entry_kill_switch_file must not be empty")
        if self.signal_mode not in {SignalMode.SAR_ONLY, SignalMode.PRICE_CHANGE_ONLY}:
            errors.append("unsupported signal mode")
        if self.margin_mode not in {"cross", "isolated"}:
            errors.append("margin_mode must be cross or isolated")
        if self.network is Network.MAINNET:
            if not self.allow_mainnet:
                errors.append("mainnet requires allow_mainnet=true")
            if self.mainnet_confirmation != MAINNET_CONFIRMATION:
                errors.append("mainnet confirmation phrase is missing or invalid")
        if self.canary_mode:
            if len(self.symbols) != 1:
                errors.append("canary mode requires exactly one symbol")
            if self.max_positions != 1:
                errors.append("canary mode requires max_positions=1")
        if errors:
            raise ValueError("invalid trading configuration: " + "; ".join(errors))

    @classmethod
    def from_mapping(
        cls,
        settings: Mapping[str, Any],
        *,
        symbols: Sequence[str] | None = None,
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

        try:
            signal_mode = SignalMode(
                str(perpetual.get("signal_mode", SignalMode.SAR_ONLY.value)).lower()
            )
        except ValueError as exc:
            raise ValueError(
                f"unsupported signal mode: {perpetual.get('signal_mode')!r}"
            ) from exc

        configured_symbols = (
            symbols if symbols is not None else perpetual.get("symbols", ())
        )
        amount_usdc = float(perpetual.get("amountByUSDC", 10.0))
        leverage = int(perpetual.get("leverage", 1))
        risk = perpetual.get("risk", {})
        required_mainnet_risk_keys = {
            "max_order_notional_usdc",
            "max_symbol_notional_usdc",
            "max_total_notional_usdc",
            "max_positions",
            "max_leverage",
            "min_free_collateral_usdc",
        }
        if network is Network.MAINNET:
            missing = required_mainnet_risk_keys - set(risk)
            if missing:
                raise ValueError(
                    "mainnet requires explicit risk limits: "
                    + ", ".join(sorted(missing))
                )

        config = cls(
            symbols=tuple(str(symbol) for symbol in configured_symbols),
            timeframe=str(perpetual.get("timeframe", "30m")),
            amount_usdc=amount_usdc,
            leverage=leverage,
            take_profit_roe=float(perpetual.get("take_profit_rate", 15.0)),
            stop_loss_roe=float(perpetual.get("stop_loss_rate", 3.0)),
            trailing_interval_minutes=int(
                perpetual.get("trailing_stop_interval_minutes", 15)
            ),
            trailing_activation_roe=float(
                perpetual.get("trailing_stop_activation_pnl_percent", 7.0)
            ),
            sar_consecutive_count=int(perpetual.get("consecutivePositiveCount", 3)),
            sar_close_consecutive_count=int(
                perpetual.get("sar_close_consecutive_count", 2)
            ),
            price_change_threshold_percent=float(
                perpetual.get("price_change_threshold_percent", 0.5)
            ),
            max_order_notional_usdc=float(
                risk.get("max_order_notional_usdc", amount_usdc)
            ),
            max_symbol_notional_usdc=float(
                risk.get("max_symbol_notional_usdc", amount_usdc)
            ),
            max_total_notional_usdc=float(
                risk.get(
                    "max_total_notional_usdc",
                    amount_usdc * max(1, len(configured_symbols)),
                )
            ),
            max_positions=int(
                risk.get("max_positions", max(1, len(configured_symbols)))
            ),
            max_leverage=int(risk.get("max_leverage", leverage)),
            min_free_collateral_usdc=float(risk.get("min_free_collateral_usdc", 0)),
            signal_mode=signal_mode,
            margin_mode=str(perpetual.get("margin_mode", "cross")).lower(),
            canary_mode=bool(perpetual.get("canary_mode", False)),
            entries_enabled=bool(perpetual.get("entries_enabled", True)),
            entry_kill_switch_file=str(
                perpetual.get(
                    "entry_kill_switch_file",
                    "state/ENTRY_KILL_SWITCH",
                )
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


def _positive_number(value: float) -> bool:
    return math.isfinite(value) and value > 0


def next_timeframe_boundary(now: datetime, timeframe: str) -> datetime:
    """Return the next UTC scheduler boundary supported by validation."""

    if now.tzinfo is None:
        raise ValueError("scheduler datetime must be timezone-aware")
    interval_seconds = _timeframe_seconds(timeframe)
    now_utc = now.astimezone(timezone.utc)
    next_epoch = (int(now_utc.timestamp()) // interval_seconds + 1) * interval_seconds
    return datetime.fromtimestamp(next_epoch, tz=timezone.utc)
