# Trailing Stop with Acceleration Coefficient

## Overview

This implementation provides a trailing stop loss mechanism with an acceleration coefficient for Hyperliquid perpetual positions. The implementation is inspired by the Parabolic SAR (Stop And Reverse) indicator concept, where the stop loss accelerates as the position moves in profit.

## Features

- **Dynamic Stop Loss**: The stop loss automatically adjusts based on price movement
- **Acceleration Factor**: The rate at which the stop loss follows the price increases as new highs/lows are reached
- **Position Tracking**: Remembers entry price, highest/lowest price, and current acceleration factor for each position
- **Periodic Updates**: Automatically checks and updates stop losses at configurable intervals
- **Configurable Parameters**: All key parameters can be adjusted via `settings.json`

## How It Works

### For Long Positions

1. When price makes a new high:
   - Update highest price
   - Increase acceleration factor (AF) by increment value
   - Calculate new stop loss: `SL = highest_price - (highest_price - entry_price) * AF`

2. When price doesn't make new high:
   - Keep acceleration factor unchanged
   - Still calculate SL from highest price reached

### For Short Positions

1. When price makes a new low:
   - Update lowest price
   - Increase acceleration factor (AF) by increment value
   - Calculate new stop loss: `SL = lowest_price + (entry_price - lowest_price) * AF`

2. When price doesn't make new low:
   - Keep acceleration factor unchanged
   - Still calculate SL from lowest price reached

## Configuration

Edit `src/crypto_spot_collector/apps/settings.json`:

```json
{
  "settings": {
    "perpetual": {
      "trailing_stop": {
        "enabled": true,
        "initial_af": 0.02,
        "max_af": 0.2,
        "af_increment": 0.02,
        "check_interval_seconds": 60,
        "sl_update_threshold_percent": 0.1
      }
    }
  }
}
```

### Parameters Explained

- **enabled**: Enable/disable the trailing stop feature
- **initial_af**: Starting acceleration factor (default: 0.02 = 2%)
- **max_af**: Maximum acceleration factor (default: 0.2 = 20%)
- **af_increment**: How much to increase AF on each new high/low (default: 0.02)
- **check_interval_seconds**: How often to check and update positions (default: 60s)
- **sl_update_threshold_percent**: Minimum % change needed to update SL order (default: 0.1%)

## Usage

### Running the Trailing Stop Processor

```bash
cd src/crypto_spot_collector/apps
python hyperliquid_perp.py
```

The application will:
1. Initialize the HyperLiquid exchange connection
2. Start the trailing stop processor
3. Continuously monitor open positions
4. Update stop loss orders as prices move

### Manual Integration

```python
from crypto_spot_collector.exchange.hyperliquid import HyperLiquidExchange
from crypto_spot_collector.exchange.trailing_stop_manager import TrailingStopManager
from crypto_spot_collector.exchange.trailing_stop_processor import TrailingStopProcessor

# Initialize exchange
exchange = HyperLiquidExchange(...)

# Create trailing stop manager
tsm = TrailingStopManager(
    initial_af=0.02,
    max_af=0.2,
    af_increment=0.02,
)

# Create processor
processor = TrailingStopProcessor(
    exchange=exchange,
    trailing_stop_manager=tsm,
    check_interval_seconds=60,
    sl_update_threshold_percent=0.1,
)

# Start processing
await processor.start()
```

## Implementation Details

### Files Added

1. **trailing_stop_manager.py**: Core logic for calculating trailing stops with acceleration
2. **trailing_stop_processor.py**: Periodic processor that monitors positions and updates stop losses
3. **test_trailing_stop_manager.py**: Comprehensive test suite for the trailing stop logic

### Files Modified

1. **hyperliquid.py**: Added methods for managing positions and stop loss orders:
   - `fetch_positions_async()`: Fetch all open positions
   - `fetch_open_orders_all_async()`: Fetch open orders
   - `fetch_close_orders_all_async()`: Fetch closed orders
   - `fetch_canceled_orders_all_async()`: Fetch canceled orders
   - `modify_stop_loss_order_async()`: Modify existing stop loss order
   - `cancel_order_async()`: Cancel an order
   - `create_stop_loss_order_async()`: Create standalone stop loss order

2. **hyperliquid_perp.py**: Updated main function to use trailing stop processor

3. **settings.json**: Added trailing stop configuration section

## TODO Comments

The following operations have TODO comments for review:

1. **hyperliquid.py**:
   - `fetch_canceled_orders_all_async()`: Verify if HyperLiquid API supports fetching canceled orders separately
   - `modify_stop_loss_order_async()`: Verify if HyperLiquid supports editing trigger orders directly

2. **trailing_stop_processor.py**:
   - `_update_stop_loss()`: Verify if HyperLiquid supports modifying stop loss orders

## Example Scenario

Consider a long position entered at $100:

1. **Initial State**:
   - Entry: $100
   - Highest: $100
   - AF: 0.02 (2%)
   - SL: $100 - ($100 - $100) * 0.02 = $100

2. **Price rises to $110** (new high):
   - Entry: $100
   - Highest: $110
   - AF: 0.04 (4%) - increased
   - SL: $110 - ($110 - $100) * 0.04 = $109.60

3. **Price rises to $120** (new high):
   - Entry: $100
   - Highest: $120
   - AF: 0.06 (6%) - increased
   - SL: $120 - ($120 - $100) * 0.06 = $118.80

4. **Price drops to $115** (not a new high):
   - Entry: $100
   - Highest: $120 (unchanged)
   - AF: 0.06 (unchanged)
   - SL: $120 - ($120 - $100) * 0.06 = $118.80 (unchanged)

The stop loss progressively locks in more profit as the price moves favorably.

## Testing

Run the test suite:

```bash
pytest tests/test_trailing_stop_manager.py -v
```

The tests cover:
- Manager initialization
- Position tracking (add/remove)
- Long position calculations
- Short position calculations
- Acceleration factor limits
- Edge cases

## Notes

- The implementation only works for Hyperliquid perpetual positions
- The processor runs continuously and can be stopped with Ctrl+C
- Stop loss orders are only updated if the change exceeds the threshold to avoid excessive API calls
- The acceleration factor ensures the stop loss follows profitable moves more closely while still giving the price room to fluctuate
