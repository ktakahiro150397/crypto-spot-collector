import copy
import json
import sys
from pathlib import Path
from typing import cast

import pytest

from crypto_spot_collector.scripts.portfolio_testnet_preflight import (
    main as preflight_main,
)
from crypto_spot_collector.scripts.portfolio_testnet_preflight import (
    sanitized_summary,
    validate_portfolio_testnet_settings,
)
from crypto_spot_collector.trading.deployment import DeploymentError

ROOT = Path(__file__).parents[1]
SAMPLE = ROOT / "deploy" / "settings" / "hyperliquid.portfolio-testnet.json.sample"


def document() -> dict[str, object]:
    return cast(dict[str, object], json.loads(SAMPLE.read_text(encoding="utf-8")))


def test_portfolio_testnet_sample_is_valid_but_execution_disabled() -> None:
    config = validate_portfolio_testnet_settings(document())
    summary = sanitized_summary(config)

    assert summary["network"] == "testnet"
    assert summary["signal_mode"] == "portfolio_trend_ensemble"
    assert summary["entries_enabled"] is False
    assert summary["max_total_notional_usdc"] == 75
    assert summary["leverage"] == 1
    assert "wallet" not in json.dumps(summary).lower()
    assert "private" not in json.dumps(summary).lower()


def test_initial_preflight_rejects_enabled_or_non_testnet_settings() -> None:
    enabled = copy.deepcopy(document())
    enabled["settings"]["perpetual"]["entries_enabled"] = True  # type: ignore[index]
    with pytest.raises(ValueError, match="entries_enabled=false"):
        validate_portfolio_testnet_settings(enabled)
    validate_portfolio_testnet_settings(enabled, require_entries_disabled=False)

    mainnet = copy.deepcopy(document())
    mainnet["settings"]["network"] = "mainnet"  # type: ignore[index]
    with pytest.raises(ValueError, match="testnet-only"):
        validate_portfolio_testnet_settings(mainnet)


def test_cli_preflight_validates_secret_affinity_without_printing_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(document()), encoding="utf-8")
    secret_payload = {
        "hyperliquid": {
            "network": "testnet",
            "mainWalletAddress": "0xmain-secret",
            "apiWalletAddress": "0xapi-secret",
            "privatekey": "0xprivate-secret",
        },
        "discord": {
            "discordWebhookUrlPerpetual": "https://example.invalid/secret-hook"
        },
    }
    secrets = tmp_path / "secrets.json"
    secrets.write_text(json.dumps(secret_payload), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["preflight", "--settings", str(settings), "--secrets", str(secrets)],
    )

    preflight_main()

    output = capsys.readouterr().out
    assert '"network": "testnet"' in output
    assert "main-secret" not in output
    assert "private-secret" not in output
    assert "secret-hook" not in output

    secret_payload["hyperliquid"]["network"] = "mainnet"
    secrets.write_text(json.dumps(secret_payload), encoding="utf-8")
    with pytest.raises(DeploymentError, match="secret network"):
        preflight_main()


def test_compose_uses_dedicated_profile_and_shared_wallet_lease_volume() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'profiles: ["portfolio-testnet"]' in compose
    assert "crypto_spot_collector.apps.buy_portfolio" in compose
    assert compose.count("hyperliquid-perp-state:/var/lib/crypto-spot-collector") == 2
    assert "HYPERLIQUID_DEPLOYMENT_NETWORK=testnet" in compose


def test_deploy_script_requires_disabled_preflight_and_refuses_old_bot() -> None:
    script = (ROOT / "deploy-portfolio-testnet.sh").read_text(encoding="utf-8")
    assert "portfolio_testnet_preflight" in script
    assert "app_perp exists" in script
    assert "--profile portfolio-testnet" in script
    assert 'HYPERLIQUID_MAINNET_CONFIRMATION=""' in script
    assert "--force-recreate" in script


def test_activation_requires_exact_phrase_and_enabled_preflight() -> None:
    script = (ROOT / "activate-portfolio-testnet.sh").read_text(encoding="utf-8")
    assert "I_UNDERSTAND_THIS_ENABLES_HYPERLIQUID_TESTNET_PORTFOLIO_ORDERS" in script
    assert "--allow-entries-enabled" in script
    assert "portfolio_testnet_preflight" in script
    assert "state_admin" in script
    assert "--force-recreate" in script
