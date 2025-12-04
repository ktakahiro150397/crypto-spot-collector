from pathlib import Path

from loguru import logger

from crypto_spot_collector.exchange.hyperliquid import HyperLiquidExchange
from crypto_spot_collector.notification.discord import discordNotification
from crypto_spot_collector.utils.secrets import load_config

logger.info("Initializing crypto perp collector script")
secret_file = Path(__file__).parent.parent / "apps" / "secrets.json"
settings_file = Path(__file__).parent.parent / "apps" / "settings.json"
secrets = load_config(secret_file, settings_file)

notificator = discordNotification(
    secrets["discord"]["discordWebhookUrlPerpetual"])


async def main() -> None:

    wallet_address = secrets["hyperliquid"]["mainWalletAddress"]

    exchange = HyperLiquidExchange(
        mainWalletAddress=wallet_address,
        apiWalletAddress="",
        leverage=20,
        privateKey="",
        stop_loss_rate=0.95,
        take_profit_rate=1.05,
        testnet=False
    )

    positions = await exchange.fetch_positions_perp_async()
    for position in positions:
        logger.debug(f"Position: {position}")
    embeds = discordNotification.embed_object_create_helper_perp_position(
        positions)

    await notificator.send_notification_embed_with_file(
        message=f"{len(embeds)}つのポジションを保持しています！",
        embeds=embeds,
        image_buffers=[]
    )

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
