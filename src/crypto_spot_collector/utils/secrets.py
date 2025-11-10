from typing import Any

from loguru import logger


def load_secrets(secrets_path: str) -> Any:
    import json

    logger.info(f"Loading secrets from {secrets_path}")
    with open(secrets_path, "r") as f:
        secrets = json.load(f)
    logger.info("Secrets loaded successfully")
    return secrets


def load_settings(settings_path: str) -> Any:
    import json

    logger.info(f"Loading settings from {settings_path}")
    with open(settings_path, "r") as f:
        settings = json.load(f)
    logger.info("Settings loaded successfully")
    return settings


def load_config(secrets_path: str, settings_path: str) -> dict[str, Any]:
    """Load both secrets and settings, merging them into a single config dict.

    This function maintains backward compatibility by returning a structure
    similar to the old secrets.json format.

    Args:
        secrets_path: Path to secrets.json file
        settings_path: Path to settings.json file

    Returns:
        A dictionary containing both secrets and settings
    """
    secrets = load_secrets(secrets_path)
    settings = load_settings(settings_path)

    # Merge settings into the config
    config = secrets.copy()
    config.update(settings)

    return config
