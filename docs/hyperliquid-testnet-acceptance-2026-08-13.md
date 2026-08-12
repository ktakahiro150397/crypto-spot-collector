# HyperLiquid production-path testnet acceptance — 2026-08-13

## Result

The production SAR runtime path passed a destructive end-to-end acceptance on
HyperLiquid testnet. No mainnet endpoint, balance, order, or position operation
was used. The test ended with the account flat for the selected symbol and zero
open orders.

The runner imported the production `buy_perp` application and used its normal
configuration parser, SAR strategy transition, durable order executor, entry
risk gate, TP/SL reconciler, trailing manager, restart recovery, WebSocket
client, and graceful-shutdown supervisor. The only injected input was a
testnet-only controlled closed-candle DataFrame; production/mainnet rejects that
input path.

## Final run

Command:

```powershell
uv run python -m crypto_spot_collector.scripts.hyperliquid_testnet_acceptance `
  --monitor-seconds 180 --sample-seconds 2 --initial-side short
```

The runner requires `HYPERLIQUID_TESTNET=true`, refuses to select mainnet,
requires the entire testnet account to be flat before it begins, disables
external notifications, and never emits the wallet address, private key, or
webhook in its result.

| Check | Observed result |
|---|---|
| Selected symbol | `ARB/USDC:USDC` |
| Stale SAR interval | Rejected; no order |
| Short entry | Filled; exactly two reduce-only TP/SL orders |
| Duplicate closed candle | Zero additional intents |
| Durable restart | Position and both protections restored; no replay |
| Forced WebSocket disconnect | Reconnected and restored subscription in 0.266 s |
| Protected monitoring | 5 samples; measured unprotected time 0.0 s |
| Trailing activation | Activated after 29.17 s of safe favorable movement |
| Stop movement | Short stop moved from `0.07716` to break-even `0.0764` |
| Restart after trailing update | Stop recovered without retreat |
| Opposite SAR | Reduce-only close; flat proven before reversal |
| Long reversal | Filled only after flat; exactly two TP/SL orders |
| External/manual settlement | Reconciled through the production adapter |
| Durable intents | 3 filled, 0 unsettled |
| Final state | Account independently verified flat, zero open orders, zero unresolved errors |

Earlier testnet runs additionally held both a long and a short with continuous
TP/SL monitoring for 300 seconds per side. A safe favorable trailing condition
did not occur during those windows, so those runs deliberately did not force a
trailing update.

## Findings fixed during acceptance

1. Unified/portfolio-margin collateral is exposed through HyperLiquid's spot
   clearinghouse balance. The entry risk gate now selects that balance after
   checking account-abstraction mode and fails closed on unknown modes.
2. HyperLiquid condition orders can be temporarily absent from an immediately
   following open-order snapshot. Verification now retries while keeping prior
   protection intact.
3. CCXT may place native condition-order fields under `info.order`. TP/SL
   verification now handles both response shapes and uses the deterministic
   cloid as the authoritative identity when present.
4. Production entry helpers now propagate execution-safety failures to the
   supervisor after attempting notification, instead of logging and continuing.
5. The Windows acceptance runner tolerates delayed release of its disposable
   SQLite directory without changing the durable-state assertions.

## Automated evidence

- Full regression suite: 172 passed.
- Changed-file `flake8`: passed.
- Changed-file `mypy`: passed.
- Coverage includes duplicate intents, unknown/timeouts, partial fills, stale
  snapshots, nested condition-order payloads, protection replacement ordering,
  trailing-stop monotonicity, reconnect deduplication, shutdown, network
  interlocks, unified collateral, and SAR transitions.

A live partial fill is not forced because a small testnet market order cannot
reliably cause one. The equivalent partial/unknown-state recovery paths are
covered deterministically by adapter tests.

## Mainnet go/no-go

**GO for a separately approved, one-symbol, minimum-notional mainnet canary.**
This does not authorize a mainnet connection or order. Before that run, the
operator must create the uncommitted mainnet secret/settings files, build the
image on a functioning Docker host, verify the healthcheck, obtain explicit
approval, and enable all three mainnet interlocks. Unattended or multi-symbol
mainnet rollout remains a no-go until the canary is observed and closed or left
protected according to the approved plan.

Rollback is: engage the entry kill switch, inhibit new intents, reconcile the
cloid/fill ledger, reduce-only close the canary if required, cancel only verified
orphan protection orders, confirm flat/no-open-orders, and restore the prior
image without deleting the persistent state volume.
