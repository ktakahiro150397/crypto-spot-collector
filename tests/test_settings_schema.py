import json
from pathlib import Path

from crypto_spot_collector.trading.config import TradingConfig

REPOSITORY_ROOT = Path(__file__).parents[1]
SETTINGS_DIRECTORY = REPOSITORY_ROOT / "src" / "crypto_spot_collector" / "apps"


def load(name: str) -> dict[str, object]:
    return json.loads((SETTINGS_DIRECTORY / name).read_text(encoding="utf-8"))


def test_sample_and_runtime_perpetual_schema_are_synchronized() -> None:
    runtime = load("settings.json")["settings"]
    sample = load("settings.json.sample")["settings"]
    assert isinstance(runtime, dict)
    assert isinstance(sample, dict)
    runtime_perpetual = runtime["perpetual"]
    sample_perpetual = sample["perpetual"]
    assert isinstance(runtime_perpetual, dict)
    assert isinstance(sample_perpetual, dict)
    assert set(runtime_perpetual) == set(sample_perpetual)
    assert set(runtime_perpetual["risk"]) == set(sample_perpetual["risk"])

    TradingConfig.from_mapping(runtime)
    TradingConfig.from_mapping(sample)
