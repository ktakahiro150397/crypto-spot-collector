# Hyperliquid runtime operations

## REST policy

- Read-only calls use a 15-second timeout, at most four attempts, exponential
  backoff and jitter.
- Entry and protection-order creation are not blindly retried. A timed-out
  entry is reconciled by cloid, open orders, fills and position before any
  future action.
- Cancellation is idempotent and may be retried up to three times.
- Calls are aggregated behind a process-wide rate limiter. Each operation has
  a circuit breaker and heartbeat counters for calls, retries and failures.

## WebSocket recovery

- Reconnection continues until shutdown with capped exponential backoff and
  jitter.
- Subscriptions are keyed and deduplicated. Reconnect restores one copy of each
  subscription.
- A bounded content fingerprint suppresses duplicate snapshots/payloads.
- After reconnect, position and TP/SL state is reconciled from the exchange
  before the reconnect callback returns.

## Graceful shutdown

SIGINT and SIGTERM immediately inhibit new order intents. Background loops are
cancelled, then WebSocket and both CCXT clients are closed. Startup, reconnect,
heartbeat, fatal error and shutdown notifications contain no wallet address,
key or webhook value.

## Dead man's switch decision

Hyperliquid `scheduleCancel` is **not enabled**. It cancels resting orders and
could therefore remove reduce-only TP/SL protection after a process failure,
which is worse than leaving the verified protection pair on the exchange. It
may only be adopted later with an independent watchdog that can distinguish
entry orders from protection orders and prove the position remains protected.
