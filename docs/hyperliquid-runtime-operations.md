# Hyperliquid runtime operations

## Approved execution paths

- `crypto_spot_collector/apps/buy_perp.py` is the only production trading
  entrypoint. It constructs the exchange adapter from a validated
  `TradingConfig`; mainnet requires `network=mainnet`, `allow_mainnet=true`,
  and the exact `HYPERLIQUID_MAINNET_CONFIRMATION` phrase.
- `crypto_spot_collector/scripts/hyperliquid_testnet_acceptance.py` is the only
  destructive acceptance runner. It requires `HYPERLIQUID_TESTNET=true`,
  creates a testnet-only `TradingConfig`, scopes cleanup to its selected
  symbol, and must never be repurposed for mainnet.
- `crypto_spot_collector/scripts/test_hyperliquid.py` is a read-only testnet
  diagnostic. It does not submit or cancel orders.
- The former `apps/hyperliquid_perp.py` mainnet smoke script was deleted.
  Legacy `create_order_perp_*` and bulk-close APIs raise immediately. Runtime
  entries and exits must use `IdempotentOrderExecutor` with durable cloids.
- `tests/test_execution_path_safety.py` scans executable app/script sources so
  raw `create_order`, legacy order calls, or a raw `testnet` constructor flag
  cannot be reintroduced unnoticed.

## SAR evaluation contract

- `signal_mode=sar_only` is the production default and is explicit in the
  production and sample settings. The optional price-change strategy is an
  exclusive `price_change_only` mode; the former implicit SAR-or-price rule is
  not used.
- Candles must be UTC, unique, strictly increasing, contiguous across the SAR
  warm-up tail, and include the most recently closed slot. Missing, stale,
  duplicate, reversed, or insufficient input is rejected before state changes.
- A SAR entry signal fires only on the newest closed candle that reaches the
  configured run length. Historical runs and later candles in the same run do
  not produce another entry intent.
- The last processed candle, SAR direction, and consecutive opposite-position
  count are stored in the runtime SQLite database. Restarting cannot count the
  same candle twice; an aligned SAR or a flat position resets the counter.

## Order and protection contract

- `margin_mode` is explicitly `cross` or `isolated`. Before every entry the
  configured mode and leverage are submitted to Hyperliquid and the exchange
  acknowledgement is required. The resulting live position must report the
  same values.
- Amount and reference price are normalized to market precision. Orders below
  the live amount minimum or the 10 USDC Hyperliquid perp minimum are rejected
  before submission.
- Entry, SAR close, and an unprotected-position emergency close all use the
  durable `IdempotentOrderExecutor`. Only a full fill is successful; open,
  partial, rejected, cancelled, statusless and timed-out states inhibit the
  strategy transition.
- A close must also produce a flat exchange position before a later cycle may
  reverse. An entry must expose its actual side, average price, contracts,
  leverage and margin mode, then pass TP/SL reconciliation on both sides.
- TP/SL prices express ROE percentages: price distance is
  `(configured_roe / 100) / actual_leverage`. Replacement protection is
  created and verified before stale protection is cancelled.
- If entry protection or account settings cannot be verified, new signals are
  inhibited and a deterministic reduce-only emergency close is attempted. A
  failure to prove that close is fatal and leaves the durable intent blocking
  future orders for the symbol.
- Startup reconciles every non-terminal SQLite intent before strategy workers
  start. Unknown or otherwise unresolved state prevents startup.

## Entry risk boundary and kill switch

- The symbol allowlist comes only from validated `perpetual.symbols`; the app
  contains no fallback trading-symbol list. `canary_mode=true` requires exactly
  one symbol and `max_positions=1`.
- Every entry reserves risk against a fresh all-position, all-open-order and
  free-collateral snapshot. It enforces order, per-symbol and total notional,
  maximum leverage, concurrent-position count and post-order collateral floor.
  Existing target positions, out-of-allowlist exposure, pending entry orders
  and protection orders without a position all fail closed.
- Concurrent signals are counted through in-process reservations, so two
  signals cannot both pass using the same remaining limit.
- Set `perpetual.entries_enabled=false` for a startup-time entry stop. For an
  immediate runtime stop, create
  `src/crypto_spot_collector/apps/state/ENTRY_KILL_SWITCH` (or the configured
  path). The file is checked before every entry reservation. Removing it
  re-enables entries only if all other gates pass.
- The entry kill switch is intentionally not consulted by startup/reconnect
  protection reconciliation, trailing updates, or reduce-only closes.
- `TradingConfig` is the only runtime source for symbols, timeframe, order
  amount, leverage, strategy, trailing and risk values. The scheduler uses the
  same minute/hour/day parser as validation.

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
