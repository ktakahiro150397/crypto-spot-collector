import copy
import json
from pathlib import Path
from typing import cast

import pytest

from crypto_spot_collector.scripts.portfolio_mainnet_preflight import (
    validate_portfolio_mainnet_disabled_settings,
)
from crypto_spot_collector.scripts.portfolio_testnet_preflight import sanitized_summary
from crypto_spot_collector.trading.config import MAINNET_CONFIRMATION, Network

ROOT = Path(__file__).parents[1]
SAMPLE = (
    ROOT
    / "deploy"
    / "settings"
    / "hyperliquid.portfolio-mainnet-disabled.json.sample"
)


def document() -> dict[str, object]:
    return cast(dict[str, object], json.loads(SAMPLE.read_text(encoding="utf-8")))


def test_mainnet_sample_is_valid_only_as_disabled_observer() -> None:
    config = validate_portfolio_mainnet_disabled_settings(
        document(), mainnet_confirmation=MAINNET_CONFIRMATION
    )
    summary = sanitized_summary(config)

    assert config.network is Network.MAINNET
    assert summary["entries_enabled"] is False
    assert summary["signal_mode"] == "portfolio_trend_ensemble"
    assert summary["max_total_notional_usdc"] == 75

    enabled = copy.deepcopy(document())
    enabled["settings"]["perpetual"]["entries_enabled"] = True  # type: ignore[index]
    with pytest.raises(ValueError, match="entries_enabled=false"):
        validate_portfolio_mainnet_disabled_settings(
            enabled, mainnet_confirmation=MAINNET_CONFIRMATION
        )


def test_mainnet_preflight_requires_confirmation_and_mainnet_affinity() -> None:
    with pytest.raises(ValueError, match="confirmation"):
        validate_portfolio_mainnet_disabled_settings(
            document(), mainnet_confirmation=""
        )

    testnet = copy.deepcopy(document())
    testnet["settings"]["network"] = "testnet"  # type: ignore[index]
    testnet["settings"]["sandbox_mode"] = True  # type: ignore[index]
    testnet["settings"]["allow_mainnet"] = False  # type: ignore[index]
    with pytest.raises(ValueError, match="network=mainnet"):
        validate_portfolio_mainnet_disabled_settings(
            testnet, mainnet_confirmation=MAINNET_CONFIRMATION
        )


def test_compose_declares_dedicated_mainnet_observer() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'profiles: ["portfolio-mainnet-disabled"]' in compose
    assert "app_portfolio_mainnet_disabled:" in compose
    assert "image: crypto-spot-collector:portfolio-mainnet-disabled" in compose
    assert "HYPERLIQUID_DEPLOYMENT_NETWORK=mainnet" in compose
    assert "crypto_spot_collector.apps.buy_portfolio" in compose


def test_deploy_script_gates_mainnet_before_start_and_rechecks_after() -> None:
    script = (ROOT / "deploy-portfolio-mainnet-disabled.sh").read_text(
        encoding="utf-8"
    )
    assert MAINNET_CONFIRMATION in script
    assert "portfolio_mainnet_preflight" in script
    assert script.count("portfolio_mainnet_account_preflight") == 2
    assert "--read-only" in script
    assert "--network none" in script
    assert "/app/.venv/bin/python" in script
    assert "docker image inspect" in script
    assert "ENTRY_KILL_SWITCH" in script
    assert "state_admin" in script
    assert "--force-recreate" in script
    assert "actual_settings_source" in script
    assert "cleanup_on_error" in script
    assert script.index("portfolio_mainnet_account_preflight") < script.index(
        "state_admin"
    )
    assert script.index("state_admin") < script.index(
        "up -d --force-recreate"
    )
