from typing import Any

from loguru import logger


def load_secrets(secrets_path: str) -> Any:
    import json

    logger.info(f"Loading secrets from {secrets_path}")
    with open(secrets_path, "r") as f:
        secrets = json.load(f)
    logger.info("Secrets loaded successfully")
    return secrets
