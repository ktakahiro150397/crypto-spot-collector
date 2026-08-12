# HyperLiquid testnet acceptance — 2026-08-13

## Scope and safety boundary

- Network: HyperLiquid testnet only. No mainnet endpoint, balance, order, or
  position operation was used.
- Acceptance symbol: `BTC/USDC:USDC`, selected only after the exchange reported
  it flat.
- Acceptance notional: approximately 12.62 USDC at 3x leverage.
- A pre-existing `ETH/USDC:USDC` long was preserved and protected rather than
  included in the destructive transition scenario.
- The runner loads credentials from the ignored `.env` file, requires
  `HYPERLIQUID_TESTNET=true`, and never writes an address or private key to its
  report.

## Testnet findings addressed before the run

1. Testnet spot metadata included malformed entries. The testnet adapter now
   loads perpetual markets only; the mainnet adapter is unchanged.
2. A private key without the optional `0x` prefix is normalized locally.
3. Protection prices now use the leverage reported on the actual exchange
   position.
4. HyperLiquid rounds trigger prices to market precision. Pair verification now
   accepts only a small rounding tolerance (`5e-5` relative), while materially
   different protection levels still fail.
5. A stop price already crossed by the current market is rejected before any
   new protection order is created. The required recovery is an explicit
   reduce-only close.
6. A filled market order can be returned without a normalized status, and the
   lookup-by-cloid snapshot can remain `open`. The durable state machine now
   reconciles the immutable fill ledger by cloid before trusting that snapshot.
7. SQLite state connections are explicitly closed, including failure and
   cleanup paths on Windows.

The crossed-stop case was encountered on a pre-existing BTC testnet long
(`0.00617` BTC, entry `92322`). Its configured stop was already above the live
market near `63132`, so the position was closed reduce-only and its residual
orders were cancelled. No automatic retry or reversal was performed in that
recovery step.

## Continuous acceptance result

Command:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m crypto_spot_collector.scripts.hyperliquid_testnet_acceptance --monitor-seconds 600 --sample-seconds 10
```

Observed result:

| Check | Result |
|---|---|
| Continuous protected hold | 600.0 seconds |
| REST position/protection samples | 54 |
| Measured unprotected time | 0.0 seconds |
| WebSocket trade messages | 29 |
| Forced reconnect and reconciliation | 0.266 seconds, passed |
| Additional natural reconnect | passed; subscriptions restored |
| Duplicate long intent | same order, one submission |
| Long → confirmed flat | passed |
| Flat → short | passed |
| Duplicate short intent | same order, one submission |
| Short → confirmed flat | passed |
| Final BTC position | flat |
| Final BTC open orders | 0 |

The runner also reconciled TP/SL after every reconnect. HyperLiquid-created
attached TP/SL matched the desired production specifications, so no replacement
orders were needed during the successful run.

## Preserved position and final exchange state

At the end of acceptance, the pre-existing ETH testnet position remained long
`0.1553` ETH at 3x leverage. Its two exchange-visible reduce-only protections
were independently verified:

- Take-profit market trigger: `3899.4`
- Stop market trigger: `1819.7`

BTC was independently verified flat with zero open orders after the runner
finished.

## Automated regression evidence

The full suite covers deterministic duplicate intents, timeout/unknown
reconciliation, partial fills, stale order snapshots, exchange-price rounding,
crossed stops, trailing-stop monotonicity, reconnect deduplication, REST retry
and circuit-breaker behavior, shutdown ordering, network interlocks, strategy
transitions, and legacy SAR/average-price regressions.

Live partial fills are not forced because the matching engine cannot guarantee
one for a small market order. The fill aggregation and recovery path is covered
with deterministic adapter tests and was additionally exercised by a real
two-fill reduce-only BTC cleanup during the exploratory testnet run.

## Mainnet staged-acceptance gate

Mainnet remains disabled. Enabling it requires all three production interlocks
(`network=mainnet`, `allow_mainnet=true`, and the exact environment confirmation
phrase), plus explicit user approval for that operation.

The first approved mainnet canary should use one liquid symbol, one minimum-size
position, the same duplicate-intent and TP/SL checks, and continuous monitoring.
Rollback is: stop accepting new intents, reconcile the cloid/fill ledger, close
the canary reduce-only, cancel only verified orphan protection orders, confirm
flat/no-open-orders, and return configuration to testnet.
