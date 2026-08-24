# Hyperliquid ETH + BTC mainnet Phase 1 rollout

## Scope and authorization boundary

Phase 1 expands the accepted ETH mainnet runtime to the following ordered
allowlist:

1. `ETH/USDC:USDC`
2. `BTC/USDC:USDC`

The bot may hold both positions at the same time. Each entry and each symbol is
capped at 12.5 USDC, while the combined position and in-process reservation cap
is 25 USDC. Leverage remains 1x.

This document and the tracked sample do not authorize a mainnet connection,
account query, deployment, or order. Obtain explicit approval for those
operations after presenting the exact commit, image, settings diff, current
account state, and rollback target.

## Tracked configuration contract

Use
`deploy/settings/hyperliquid.mainnet-phase1.json.sample` as the Phase 1 source
template. It intentionally remains unable to start mainnet trading because
`allow_mainnet=false` and `entries_enabled=false`. Copy it to an untracked,
access-controlled settings path before deployment.

The accepted limits are:

| Setting | Value |
| --- | ---: |
| Symbols | ETH, BTC |
| `canary_mode` | `false` |
| `max_positions` | 2 |
| Entry amount | 12.5 USDC |
| Maximum order notional | 12.5 USDC |
| Maximum symbol notional | 12.5 USDC |
| Maximum total notional | 25.0 USDC |
| Leverage / maximum leverage | 1x / 1x |
| Minimum free collateral | 10.0 USDC |

The accepted strategy settings remain 30-minute closed candles, SAR-only,
cross margin, 15% ROE take profit, 15% ROE stop loss, 7% ROE trailing
activation, and a three-minute trailing interval.

`max_positions=2` and `max_total_notional_usdc=25.0` must change together.
Increasing only the position count must not increase the combined notional
past 25 USDC. The runtime risk guard counts both exchange positions and
in-process reservations, so simultaneous ETH and BTC signals can reserve one
12.5 USDC entry each but cannot exceed either per-symbol or total limits.

## Pre-deployment gate

Perform no exchange or deployment operation until it is explicitly approved.
For an approved preflight:

1. Create the runtime settings from the tracked Phase 1 sample without placing
   the resulting file in Git.
2. Keep the entry kill switch present and `entries_enabled=false`.
3. Record the exact source commit, built image ID, current ETH-only image, and
   verified SQLite backup.
4. Verify the API wallet authorization and main-wallet relationship without
   logging either credential.
5. Verify active positions, all open orders, unsettled intents, SQLite
   `quick_check`, collateral reserve, and the absence of out-of-allowlist
   exposure.
6. For both ETH and BTC, use live market metadata and a conservative price to
   prove that a precision-normalized amount exists between the 10 USDC exchange
   minimum and the 12.5 USDC hard cap.
7. Validate the final settings with `TradingConfig`, including the mainnet
   confirmation interlock, before creating an exchange client.

If any check fails, do not enable entries or remove the kill switch.

## Staged activation and monitoring

After a separate activation approval:

1. Deploy the exact approved image with entries disabled and the kill switch
   present.
2. Require a healthy runtime, zero unresolved intents, sanitized logs, and a
   health summary showing two symbols, two maximum positions, and a 25 USDC
   total cap.
3. Enable entries only for the approved settings, restart once, repeat the
   startup checks, and then remove the entry kill switch.
4. Monitor both symbols independently. Every open position must have exactly
   one verified TP and one verified SL covering its live size. Verify trailing
   state recovery and notification identity per symbol.
5. Treat a third position, total notional above 25 USDC, an out-of-allowlist
   position/order, an orphan protection order, or an unresolved intent as a
   fail-closed incident.

## Rollback

1. Recreate the entry kill switch immediately. Protection, trailing, and
   reduce-only close paths remain active.
2. Reconcile ETH and BTC positions, protection orders, fills, and durable
   intents before changing images or settings.
3. Restore the previous ETH-only settings and image only when doing so will not
   make an existing BTC position out-of-allowlist. If BTC is open, keep the
   two-symbol allowlist until it is proven protected or is closed through the
   normal reduce-only path.
4. Preserve the newest valid durable state unless a schema/state rollback is
   explicitly required and the verified backup is selected.
5. Require healthy status, protected positions, no orphan orders, and zero
   unresolved intents before entries can be re-enabled.

SOL remains a later phase. Do not add it until Phase 1 has produced accepted
BTC entry, protection, trailing, and exit-or-protected-hold evidence.
