"""Backup and restore the durable Hyperliquid SQLite state."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from crypto_spot_collector.trading.deployment import DeploymentError, check_health

DATABASE_NAME = "order_intents.sqlite"


def backup_database(state_directory: Path, output: Path) -> None:
    source = state_directory / DATABASE_NAME
    if not source.is_file():
        raise DeploymentError(f"state database does not exist: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise DeploymentError(f"backup output already exists: {output}")
    _copy_sqlite(source, output)


def restore_database(
    state_directory: Path,
    backup: Path,
    *,
    confirmed: bool,
) -> None:
    if not confirmed:
        raise DeploymentError("restore requires --confirm-restore")
    if not backup.is_file():
        raise DeploymentError(f"backup does not exist: {backup}")
    health_path = state_directory / "health.json"
    if health_path.exists():
        try:
            check_health(health_path)
        except DeploymentError:
            pass
        else:
            raise DeploymentError("stop the running bot before state restore")
    destination = state_directory / DATABASE_NAME
    state_directory.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".restore.tmp")
    if temporary.exists():
        temporary.unlink()
    _copy_sqlite(backup, temporary)
    temporary.replace(destination)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(destination) + suffix)
        if sidecar.exists():
            sidecar.unlink()


def _copy_sqlite(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        health = source_connection.execute("PRAGMA quick_check").fetchone()
        if health is None or health[0] != "ok":
            raise DeploymentError(f"SQLite quick_check failed: {source}")
        source_connection.backup(destination_connection)
        copied_health = destination_connection.execute("PRAGMA quick_check").fetchone()
        if copied_health is None or copied_health[0] != "ok":
            raise DeploymentError(f"backup verification failed: {destination}")
    except Exception:
        destination_connection.close()
        source_connection.close()
        if destination.exists():
            destination.unlink()
        raise
    destination_connection.close()
    source_connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup")
    backup.add_argument("--state-dir", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    restore = subparsers.add_parser("restore")
    restore.add_argument("--state-dir", type=Path, required=True)
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--confirm-restore", action="store_true")
    args = parser.parse_args()
    if args.command == "backup":
        backup_database(args.state_dir, args.output)
    else:
        restore_database(
            args.state_dir,
            args.backup,
            confirmed=args.confirm_restore,
        )


if __name__ == "__main__":
    main()
