"""Fail-closed deployment state, secret boundary and single-instance lease."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Mapping, cast

from crypto_spot_collector.trading.config import Network, TradingConfig


class DeploymentError(RuntimeError):
    """Raised before exchange connectivity when deployment state is unsafe."""


def required_runtime_path(environment_name: str) -> Path:
    raw = os.getenv(environment_name, "").strip()
    if not raw:
        raise DeploymentError(f"{environment_name} must be explicitly configured")
    return Path(raw).expanduser().resolve()


def validate_deployment_secrets(
    secrets: Mapping[str, Any],
    config: TradingConfig,
    *,
    expected_network: str,
) -> dict[str, str]:
    """Validate environment affinity without logging secret values."""

    expected = expected_network.strip().lower()
    if expected not in {Network.TESTNET.value, Network.MAINNET.value}:
        raise DeploymentError("HYPERLIQUID_DEPLOYMENT_NETWORK is invalid or missing")
    if expected != config.network.value:
        raise DeploymentError("deployment network does not match validated settings")
    hyperliquid = secrets.get("hyperliquid")
    if not isinstance(hyperliquid, Mapping):
        raise DeploymentError("hyperliquid secret object is missing")
    secret_network = str(hyperliquid.get("network", "")).lower()
    if secret_network != expected:
        raise DeploymentError("secret network does not match deployment network")
    required = ("mainWalletAddress", "apiWalletAddress", "privatekey")
    normalized: dict[str, str] = {}
    for key in required:
        value = str(hyperliquid.get(key, "")).strip()
        if not value or value.upper().startswith("YOUR_"):
            raise DeploymentError(f"hyperliquid secret field {key} is missing")
        normalized[key] = value
    discord = secrets.get("discord")
    if not isinstance(discord, Mapping):
        raise DeploymentError("discord secret object is missing")
    webhook = str(discord.get("discordWebhookUrlPerpetual", "")).strip()
    if not webhook or webhook.upper().startswith("YOUR_"):
        raise DeploymentError("perpetual Discord webhook secret is missing")
    normalized["discordWebhookUrlPerpetual"] = webhook
    return normalized


class SingleInstanceLease:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: BinaryIO | None = None

    def acquire(self, metadata: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        handle = self.path.open("r+b", buffering=0)
        try:
            handle.seek(0)
            if handle.read(1) == b"":
                handle.seek(0)
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            _lock_file(handle)
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(dict(metadata), sort_keys=True).encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        except Exception:
            handle.close()
            raise
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            _unlock_file(self._handle)
        finally:
            self._handle.close()
            self._handle = None


class RuntimeHealth:
    def __init__(self, path: Path, summary: Mapping[str, Any]) -> None:
        self.path = path
        self.summary = dict(summary)

    def write(self, status: str) -> None:
        payload = {
            **self.summary,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(self.path)


@dataclass
class RuntimeState:
    directory: Path
    database_path: Path
    lease: SingleInstanceLease
    health: RuntimeHealth

    @classmethod
    def open(
        cls,
        directory: Path | str,
        *,
        wallet_address: str,
        config: TradingConfig,
    ) -> "RuntimeState":
        raw = str(directory).strip()
        if not raw:
            raise DeploymentError("runtime state directory is required")
        state_directory = Path(raw).expanduser().resolve()
        try:
            state_directory.mkdir(parents=True, exist_ok=True)
            probe = state_directory / ".write-probe"
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as exc:
            raise DeploymentError("runtime state directory is not writable") from exc

        database_path = state_directory / "order_intents.sqlite"
        _validate_sqlite(database_path)
        wallet_fingerprint = hashlib.sha256(
            wallet_address.strip().lower().encode("utf-8")
        ).hexdigest()[:16]
        lease = SingleInstanceLease(
            state_directory / f"bot-{config.network.value}-{wallet_fingerprint}.lease"
        )
        summary = {
            "network": config.network.value,
            "symbols": list(config.symbols),
            "symbol_count": len(config.symbols),
            "canary_mode": config.canary_mode,
            "entries_enabled": config.entries_enabled,
            "max_order_notional_usdc": config.max_order_notional_usdc,
            "max_total_notional_usdc": config.max_total_notional_usdc,
            "max_positions": config.max_positions,
            "max_leverage": config.max_leverage,
        }
        try:
            lease.acquire(
                {
                    "pid": os.getpid(),
                    "network": config.network.value,
                    "symbol_count": len(config.symbols),
                    "started_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        except (OSError, BlockingIOError) as exc:
            raise DeploymentError(
                "another bot instance holds the wallet deployment lease"
            ) from exc
        health = RuntimeHealth(state_directory / "health.json", summary)
        health.write("starting")
        return cls(state_directory, database_path, lease, health)

    async def close(self) -> None:
        try:
            self.health.write("stopped")
        finally:
            self.lease.release()


def check_health(path: Path | str, *, max_age_seconds: float = 90.0) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        updated = datetime.fromisoformat(str(payload["updated_at"]))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise DeploymentError("runtime health file is missing or invalid") from exc
    age = (
        datetime.now(timezone.utc) - updated.astimezone(timezone.utc)
    ).total_seconds()
    if payload.get("status") != "running" or age < 0 or age > max_age_seconds:
        raise DeploymentError("runtime health is stale or not running")
    return cast(dict[str, Any], payload)


def _validate_sqlite(path: Path) -> None:
    try:
        connection = sqlite3.connect(path, timeout=0.25)
        try:
            result = connection.execute("PRAGMA quick_check").fetchone()
            if result is None or result[0] != "ok":
                raise DeploymentError("runtime SQLite quick_check failed")
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise DeploymentError(
            "runtime SQLite is corrupt, locked, or unwritable"
        ) from exc


def _lock_file(handle: BinaryIO) -> None:
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle: BinaryIO) -> None:
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
