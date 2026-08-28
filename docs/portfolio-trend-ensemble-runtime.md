# Daily trend-ensemble runtime contract

## Scope

`trading/portfolio_strategy.py` is the production-shaped core for the portfolio
candidate selected in `backtest-portfolio-arsenal-analysis.md`. It is deliberately
not imported by `apps/buy_perp.py` yet. The current live application evaluates and
enters one symbol at a time and its execution coordinator only confirms full closes;
silently attaching a synchronized, partially rebalanced portfolio to that path would
make sizing and restart behavior unsafe.

The core is now connected to a dedicated testnet-only runtime in
`trading/portfolio_execution.py` and `apps/buy_portfolio.py`. It remains rejected on
mainnet and is not accepted by the legacy per-symbol application. Deployment and
activation are separate explicit operations described in
`portfolio-testnet-deployment-preparation.md`.

## Frozen strategy

- Binance-compatible perpetual symbols are evaluated together on daily candles.
- Only a candle with a completed close at or before `observed_at_ms` may be used.
- Input must be contiguous UTC candles opening at 00:00, aligned across every
  allowlisted symbol, and no more than six hours old by default.
- Direction is a two-of-three vote:
  - 28-day close-to-close momentum;
  - close versus the 56-day EMA;
  - 28-day Donchian breakout direction, carried forward until the opposite breakout.
- Active symbols are inverse-weighted by trailing seven-day volatility.
- Approximate portfolio daily volatility is scaled toward 4%, but scale is clamped
  to 0.25-1.0; the volatility overlay can reduce exposure but never lever above the
  base cap.
- Default gross notional is 75 USDT. Per-symbol notional, position count, symbol
  allowlist, per-order notional, finite values, and the gross cap are checked again
  before planning. A required adjustment larger than the order cap is clipped to one
  safe step and must be replanned from the next exchange snapshot.

The implementation uses the same formulas as `prepare_weights()` in the backtest.
The parity test compares both paths on identical candles so a later formula drift is
visible in CI.

## Rebalance safety contract

Positions and targets use signed USDT notionals: positive is long and negative is
short. `plan_rebalance()` produces exactly one phase:

1. `reduce`: close reversals, unwanted positions, and excess same-side exposure with
   reduce-only actions. No opening or increase appears in this phase.
2. Fetch and validate a new complete exchange position snapshot.
3. Call `plan_rebalance()` again with the same durable decision.
4. `increase`: open or add only after no required reduction remains.
5. Fetch positions again and re-plan. Only `complete` means the snapshot is within
   the configured USDT tolerance.

Every plan hashes both the durable decision and the exact position snapshot. A plan
must be discarded if positions change before submission. Converting USDT notional to
exchange amount, enforcing market minimums/precision, serializing submissions, and
protecting every resulting position remain responsibilities of the existing
execution/risk layers when an integration is implemented.

## Restart behavior

`SQLitePortfolioDecisionStore` persists the exact target and its phase. Repeating the
same candle and target is idempotent. A different target for the same candle fails
closed, and a later candle cannot be prepared while an earlier decision is unfinished.
On restart the caller must:

1. reconcile existing order intents;
2. load `latest()`;
3. fetch exchange positions rather than trusting saved position state;
4. re-plan the saved target;
5. resume only the phase permitted by the refreshed plan.

`blocked` and `complete` are terminal. Marking a decision blocked is an explicit
operator action; it must not be used to bypass unresolved orders or unverified
positions.

## Testnet wiring status

The dedicated testnet path now provides:

- one portfolio observation that fetches and strictly aligns all symbols;
- safe partial-reduction quantity confirmation;
- per-action amount normalization and order/collateral gates;
- protection reconciliation after every increase or partial reduction;
- an entry-disabled deployment and a separately confirmed testnet activation.

No external testnet acceptance has been run for this portfolio runtime. Minimum-order
tracking error, fixed TP/SL behavior, restart recovery on actual fills, and final-flat
cleanup remain mandatory testnet evidence. Mainnet remains unsupported.
