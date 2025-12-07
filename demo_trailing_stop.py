"""
Quick verification script to demonstrate trailing stop functionality.

This script simulates price movements and shows how the trailing stop works.
It does NOT connect to any exchange - it's purely for demonstration.
"""

from crypto_spot_collector.exchange.trailing_stop_manager import TrailingStopManager


def simulate_long_position():
    """Simulate a long position with trailing stop."""
    print("=" * 60)
    print("SIMULATING LONG POSITION WITH TRAILING STOP")
    print("=" * 60)

    tsm = TrailingStopManager(
        initial_af=0.02,
        max_af=0.2,
        af_increment=0.02,
    )

    # Add a long position at $100
    tsm.add_position("BTC/USDC:USDC", "long", 100.0)

    # Simulate price movements
    price_sequence = [
        100,  # Entry
        105,  # +5%
        110,  # +10%
        108,  # Pullback
        115,  # +15%
        120,  # +20%
        118,  # Pullback
    ]

    print("\nEntry Price: $100")  # noqa: F541
    print(f"Initial AF: {tsm.initial_af:.4f}")
    print(f"AF Increment: {tsm.af_increment:.4f}")
    print(f"Max AF: {tsm.max_af:.4f}\n")

    for price in price_sequence:
        sl_price = tsm.update_and_calculate_sl("BTC/USDC:USDC", float(price))
        position = tsm.get_position("BTC/USDC:USDC")

        pnl_percent = ((price - 100) / 100) * 100
        sl_distance = price - sl_price if sl_price else 0

        print(
            f"Price: ${price:6.2f} | "
            f"PnL: {pnl_percent:+6.2f}% | "
            f"AF: {position.acceleration_factor:.4f} | "
            f"SL: ${sl_price:6.2f} | "
            f"Distance: ${sl_distance:5.2f}"
        )


def simulate_short_position():
    """Simulate a short position with trailing stop."""
    print("\n" + "=" * 60)
    print("SIMULATING SHORT POSITION WITH TRAILING STOP")
    print("=" * 60)

    tsm = TrailingStopManager(
        initial_af=0.02,
        max_af=0.2,
        af_increment=0.02,
    )

    # Add a short position at $100
    tsm.add_position("BTC/USDC:USDC", "short", 100.0)

    # Simulate price movements
    price_sequence = [
        100,  # Entry
        95,  # -5%
        90,  # -10%
        92,  # Bounce
        85,  # -15%
        80,  # -20%
        82,  # Bounce
    ]

    print("\nEntry Price: $100")  # noqa: F541
    print(f"Initial AF: {tsm.initial_af:.4f}")
    print(f"AF Increment: {tsm.af_increment:.4f}")
    print(f"Max AF: {tsm.max_af:.4f}\n")

    for price in price_sequence:
        sl_price = tsm.update_and_calculate_sl("BTC/USDC:USDC", float(price))
        position = tsm.get_position("BTC/USDC:USDC")

        pnl_percent = ((100 - price) / 100) * 100
        sl_distance = sl_price - price if sl_price else 0

        print(
            f"Price: ${price:6.2f} | "
            f"PnL: {pnl_percent:+6.2f}% | "
            f"AF: {position.acceleration_factor:.4f} | "
            f"SL: ${sl_price:6.2f} | "
            f"Distance: ${sl_distance:5.2f}"
        )


def demonstrate_acceleration():
    """Demonstrate acceleration factor behavior."""
    print("\n" + "=" * 60)
    print("DEMONSTRATING ACCELERATION FACTOR BEHAVIOR")
    print("=" * 60)

    tsm = TrailingStopManager(
        initial_af=0.02,
        max_af=0.10,  # Lower max for demonstration
        af_increment=0.02,
    )

    tsm.add_position("BTC/USDC:USDC", "long", 100.0)

    print("\nShowing how AF increases with each new high:")
    print(f"(Max AF: {tsm.max_af:.4f})\n")

    # Make many new highs to reach max AF
    for i in range(8):
        price = 100 + (i * 5)
        tsm.update_and_calculate_sl("BTC/USDC:USDC", float(price))
        position = tsm.get_position("BTC/USDC:USDC")

        is_max = "✓ MAX" if position.acceleration_factor >= tsm.max_af else ""

        print(
            f"New High #{i+1}: ${price:6.2f} → "
            f"AF: {position.acceleration_factor:.4f} {is_max}"
        )


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("TRAILING STOP WITH ACCELERATION COEFFICIENT")
    print("DEMONSTRATION SCRIPT")
    print("=" * 60)
    print("\nThis script demonstrates the trailing stop logic without")
    print("connecting to any exchange. It simulates price movements")
    print("and shows how the stop loss and acceleration factor change.\n")

    simulate_long_position()
    simulate_short_position()
    demonstrate_acceleration()

    print("\n" + "=" * 60)
    print("DEMONSTRATION COMPLETE")
    print("=" * 60)
    print("\nKey Observations:")
    print("- AF increases each time a new high/low is reached")
    print("- SL tightens (follows price more closely) as AF increases")
    print("- SL doesn't change when price retraces (pullbacks)")
    print("- AF is capped at max_af to prevent over-optimization")
    print("\nFor real trading, run: python hyperliquid_perp.py")
    print("=" * 60 + "\n")
