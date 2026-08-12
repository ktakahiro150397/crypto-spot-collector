import json
import sqlite3
from pathlib import Path

import pytest

from crypto_spot_collector.scripts.state_admin import (
    backup_database,
    restore_database,
)
from crypto_spot_collector.trading.config import Network, TradingConfig
from crypto_spot_collector.trading.deployment import (
    DeploymentError,
    RuntimeState,
    check_health,
    required_runtime_path,
    validate_deployment_secrets,
)
from crypto_spot_collector.trading.order_state import (
    SQLiteOrderIntentStore,
    create_intent,
)


def config(**overrides: object) -> TradingConfig:
    values: dict[str, object] = {
        "symbols": ("ETH/USDC:USDC",),
        "timeframe": "30m",
        "amount_usdc": 12.0,
        "leverage": 3,
        "take_profit_roe": 3.0,
        "stop_loss_roe": 0.2,
        "trailing_interval_minutes": 3,
        "trailing_activation_roe": 7.0,
        "sar_consecutive_count": 4,
        "sar_close_consecutive_count": 2,
        "price_change_threshold_percent": 999.0,
        "max_order_notional_usdc": 12.0,
        "max_symbol_notional_usdc": 12.0,
        "max_total_notional_usdc": 12.0,
        "max_positions": 1,
        "max_leverage": 3,
        "min_free_collateral_usdc": 0.0,
        "canary_mode": True,
    }
    values.update(overrides)
    return TradingConfig(**values)  # type: ignore[arg-type]


def secrets(network: str = "testnet") -> dict[str, object]:
    return {
        "hyperliquid": {
            "network": network,
            "mainWalletAddress": "0xmain",
            "apiWalletAddress": "0xapi",
            "privatekey": "0xprivate",
        },
        "discord": {"discordWebhookUrlPerpetual": "https://example.invalid/hook"},
    }


def test_state_path_must_be_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYPERLIQUID_STATE_DIR", raising=False)
    with pytest.raises(DeploymentError, match="explicitly configured"):
        required_runtime_path("HYPERLIQUID_STATE_DIR")


def test_secret_and_deployment_network_must_match_config() -> None:
    with pytest.raises(DeploymentError, match="secret network"):
        validate_deployment_secrets(
            secrets("mainnet"),
            config(),
            expected_network="testnet",
        )
    with pytest.raises(DeploymentError, match="deployment network"):
        validate_deployment_secrets(
            secrets("testnet"),
            config(network=Network.MAINNET),
            expected_network="testnet",
        )


@pytest.mark.asyncio
async def test_state_and_cloid_survive_runtime_recreate(tmp_path: Path) -> None:
    state = RuntimeState.open(
        tmp_path,
        wallet_address="0xwallet",
        config=config(),
    )
    store = SQLiteOrderIntentStore(state.database_path)
    intent = create_intent(
        strategy="sar-v1",
        symbol="ETH/USDC:USDC",
        timeframe="30m",
        candle_open_ms=123,
        side="buy",
        amount=0.01,
    )
    store.prepare(intent)
    await state.close()

    restarted = RuntimeState.open(
        tmp_path,
        wallet_address="0xwallet",
        config=config(),
    )
    recovered = SQLiteOrderIntentStore(restarted.database_path).get(intent.intent_id)
    assert recovered is not None
    assert recovered.cloid == intent.cloid
    await restarted.close()


@pytest.mark.asyncio
async def test_second_instance_for_same_wallet_is_rejected(tmp_path: Path) -> None:
    first = RuntimeState.open(
        tmp_path,
        wallet_address="0xwallet",
        config=config(),
    )
    try:
        with pytest.raises(DeploymentError, match="another bot instance"):
            RuntimeState.open(
                tmp_path,
                wallet_address="0xwallet",
                config=config(),
            )
    finally:
        await first.close()


def test_corrupt_or_locked_state_fails_closed(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt"
    corrupt.mkdir()
    (corrupt / "order_intents.sqlite").write_bytes(b"not sqlite")
    with pytest.raises(DeploymentError, match="corrupt, locked, or unwritable"):
        RuntimeState.open(corrupt, wallet_address="0xwallet", config=config())

    locked = tmp_path / "locked"
    locked.mkdir()
    database = locked / "order_intents.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE lock_probe (id INTEGER)")
    connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(DeploymentError, match="corrupt, locked, or unwritable"):
            RuntimeState.open(locked, wallet_address="0xwallet", config=config())
    finally:
        connection.rollback()
        connection.close()


def test_unwritable_state_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_write_bytes = Path.write_bytes

    def reject_probe(path: Path, data: bytes) -> int:
        if path.name == ".write-probe":
            raise PermissionError("read-only state")
        return original_write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", reject_probe)
    with pytest.raises(DeploymentError, match="not writable"):
        RuntimeState.open(tmp_path, wallet_address="0xwallet", config=config())


@pytest.mark.asyncio
async def test_health_contains_only_non_secret_config(tmp_path: Path) -> None:
    state = RuntimeState.open(
        tmp_path,
        wallet_address="0xwallet-secret",
        config=config(),
    )
    state.health.write("running")
    payload = check_health(tmp_path / "health.json")
    serialized = json.dumps(payload)
    assert payload["network"] == "testnet"
    assert payload["max_positions"] == 1
    assert "wallet" not in serialized.lower()
    assert "private" not in serialized.lower()
    assert "webhook" not in serialized.lower()
    await state.close()


def test_verified_state_backup_and_restore(tmp_path: Path) -> None:
    state_directory = tmp_path / "state"
    state_directory.mkdir()
    database = state_directory / "order_intents.sqlite"
    store = SQLiteOrderIntentStore(database)
    intent = create_intent(
        strategy="sar-v1",
        symbol="ETH/USDC:USDC",
        timeframe="30m",
        candle_open_ms=123,
        side="buy",
        amount=0.01,
    )
    store.prepare(intent)
    backup = tmp_path / "backup.sqlite"
    backup_database(state_directory, backup)

    database.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(database) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    restore_database(state_directory, backup, confirmed=True)

    recovered = SQLiteOrderIntentStore(database).get(intent.intent_id)
    assert recovered is not None
    assert recovered.cloid == intent.cloid


def test_restore_requires_explicit_confirmation(tmp_path: Path) -> None:
    backup = tmp_path / "backup.sqlite"
    SQLiteOrderIntentStore(backup)
    with pytest.raises(DeploymentError, match="confirm-restore"):
        restore_database(tmp_path / "state", backup, confirmed=False)


def test_compose_declares_persistent_state_health_and_secret_boundary() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    for required in (
        "hyperliquid-perp-state:/var/lib/crypto-spot-collector",
        "HYPERLIQUID_SECRETS_FILE=/run/secrets/hyperliquid_credentials.json",
        "HYPERLIQUID_SETTINGS_FILE=/run/secrets/hyperliquid_settings.json",
        "restart: unless-stopped",
        "stop_grace_period: 45s",
        "crypto_spot_collector.scripts.healthcheck",
    ):
        assert required in compose


def test_sensitive_runtime_payloads_are_not_logged() -> None:
    hyperliquid = Path("src/crypto_spot_collector/exchange/hyperliquid.py").read_text(
        encoding="utf-8"
    )
    websocket = Path("src/crypto_spot_collector/exchange/hyperliquid_ws.py").read_text(
        encoding="utf-8"
    )
    assert "Balance data:" not in hyperliquid
    assert "(wallet:" not in hyperliquid
    assert "Received WebSocket message:" not in websocket
    assert "Parsed message data:" not in websocket
