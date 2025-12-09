from crypto_spot_collector.exchange.trailingstop.trailingstop_manager import (
    TrailingStopManagerHyperLiquid,
)
from crypto_spot_collector.exchange.types import PositionSide


async def main() -> None:

    trailing_manager = TrailingStopManagerHyperLiquid()

    symbol = "test"
    entry_price = 100
    stoploss_price = 90
    trailing_manager.add_or_update_position(
        symbol=symbol,
        side=PositionSide.LONG,
        entry_price=entry_price,
        stoploss_order_id="order123",
        initial_stoploss_price=stoploss_price,
    )

    # Simulate price updates
    price_updates = [102, 95, 105, 120, 115, 130, 125]
    for price in price_updates:
        updated = trailing_manager.update_stoploss_price(
            symbol=symbol,
            current_price=price,
        )
        position = trailing_manager.get_position(symbol=symbol)
        if updated:
            print(
                f"Price: {price}, New Stoploss Price: {position.current_stoploss_price}, AF Factor: {position.current_af_factor}")
        else:
            print(
                f"Price: {price}, No update to Stoploss Price: {position.current_stoploss_price}, AF Factor: {position.current_af_factor}")

    # trailing_manager.remove_position(symbol=symbol)

    stoploss_price_short = 110
    trailing_manager.add_or_update_position(
        symbol=symbol,
        side=PositionSide.SHORT,
        entry_price=entry_price,
        stoploss_order_id="order456",
        initial_stoploss_price=stoploss_price_short,
    )

    price_updates_short = [98, 105,  120, 85, 90, 80, 95]
    for price in price_updates_short:
        updated = trailing_manager.update_stoploss_price(
            symbol=symbol,
            current_price=price,
        )
        position = trailing_manager.get_position(symbol=symbol)
        if updated:
            print(
                f"[SHORT] Price: {price}, New Stoploss Price: {position.current_stoploss_price}, AF Factor: {position.current_af_factor}")
        else:
            print(
                f"[SHORT] Price: {price}, No update to Stoploss Price: {position.current_stoploss_price}, AF Factor: {position.current_af_factor}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
