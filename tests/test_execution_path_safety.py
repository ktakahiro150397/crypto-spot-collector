"""Static safety checks for executable HyperLiquid entrypoints."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from crypto_spot_collector.exchange.hyperliquid import HyperLiquidExchange
from crypto_spot_collector.trading.config import Network, TradingConfig

REPOSITORY_ROOT = Path(__file__).parents[1]
EXECUTABLE_ROOTS = (
    REPOSITORY_ROOT / "src" / "crypto_spot_collector" / "apps",
    REPOSITORY_ROOT / "src" / "crypto_spot_collector" / "scripts",
)
FORBIDDEN_ORDER_CALLS = {
    "create_order",
    "create_order_perp_long_async",
    "create_order_perp_short_async",
    "close_all_positions_perp_async",
}


def _python_sources() -> list[Path]:
    return sorted(path for root in EXECUTABLE_ROOTS for path in root.glob("*.py"))


def _valid_config(**overrides: object) -> TradingConfig:
    values: dict[str, object] = {
        "symbols": ("BTC/USDC:USDC",),
        "timeframe": "30m",
        "amount_usdc": 10.0,
        "leverage": 3,
        "take_profit_roe": 15.0,
        "stop_loss_roe": 3.0,
        "trailing_interval_minutes": 3,
        "trailing_activation_roe": 7.0,
        "sar_consecutive_count": 4,
        "sar_close_consecutive_count": 2,
        "price_change_threshold_percent": 999.0,
        "max_order_notional_usdc": 25.0,
        "max_symbol_notional_usdc": 50.0,
        "max_total_notional_usdc": 100.0,
        "max_positions": 2,
        "max_leverage": 5,
        "min_free_collateral_usdc": 10.0,
    }
    values.update(overrides)
    return TradingConfig(**values)  # type: ignore[arg-type]


def test_removed_mainnet_smoke_entrypoint_does_not_return() -> None:
    unsafe_entrypoint = (
        REPOSITORY_ROOT
        / "src"
        / "crypto_spot_collector"
        / "apps"
        / "hyperliquid_perp.py"
    )
    assert not unsafe_entrypoint.exists()


def test_executable_paths_cannot_call_raw_or_legacy_order_apis() -> None:
    violations: list[str] = []
    for path in _python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in FORBIDDEN_ORDER_CALLS:
                    violations.append(f"{path.name}:{node.lineno}:{node.func.attr}")
            if (
                isinstance(node.func, ast.Name)
                and node.func.id == "HyperLiquidExchange"
            ):
                keywords = {keyword.arg for keyword in node.keywords}
                if "trading_config" not in keywords or "testnet" in keywords:
                    violations.append(
                        f"{path.name}:{node.lineno}:unvalidated HyperLiquidExchange"
                    )
    assert violations == []


def test_production_app_has_no_hard_coded_symbols_or_raw_setting_bypass() -> None:
    app_path = (
        REPOSITORY_ROOT / "src" / "crypto_spot_collector" / "apps" / "buy_perp.py"
    )
    tree = ast.parse(app_path.read_text(encoding="utf-8"), filename=str(app_path))
    hard_coded_symbol_lists: list[int] = []
    raw_settings_reads: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "perp_symbols"
            for target in node.targets
        ):
            if isinstance(node.value, (ast.List, ast.Tuple)):
                hard_coded_symbol_lists.append(node.lineno)
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "secrets"
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == "settings"
        ):
            raw_settings_reads.append(node.lineno)

    assert hard_coded_symbol_lists == []
    # One read is required to construct TradingConfig; runtime code may not
    # return to the raw settings mapping after that boundary.
    assert len(raw_settings_reads) == 1


def test_exchange_rejects_unvalidated_mainnet_before_client_creation() -> None:
    invalid_mainnet = _valid_config(network=Network.MAINNET)
    with pytest.raises(ValueError, match="mainnet"):
        HyperLiquidExchange(
            mainWalletAddress="unused",
            apiWalletAddress="unused",
            privateKey="unused",
            trading_config=invalid_mainnet,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name, arguments",
    [
        ("create_order_perp_long_async", ("BTC/USDC:USDC", 1.0, 1.0)),
        ("create_order_perp_short_async", ("BTC/USDC:USDC", 1.0, 1.0)),
        ("close_all_positions_perp_async", ()),
    ],
)
async def test_legacy_hyperliquid_order_apis_are_disabled(
    method_name: str, arguments: tuple[object, ...]
) -> None:
    adapter = object.__new__(HyperLiquidExchange)
    method = getattr(adapter, method_name)
    with pytest.raises(RuntimeError, match="legacy"):
        await method(*arguments)
