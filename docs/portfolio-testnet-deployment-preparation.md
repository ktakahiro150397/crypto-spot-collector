# Portfolio trend ensemble — testnet deployment preparation

## Preparation status

The dedicated runtime, offline preflight, disabled-entry settings sample,
Compose profile, deployment script, activation interlock, durable decision state,
partial-reduction confirmation, and protection reconciliation are implemented.

No testnet deployment, account query, order, container restart, or settings mutation
was performed while preparing these artifacts.

## Safety boundary

The portfolio mode is accepted only when all of these conditions hold:

- `network=testnet` and `signal_mode=portfolio_trend_ensemble`;
- the frozen six-symbol order is BTC, ETH, SOL, XRP, BNB, and DOGE perpetuals;
- daily candles, 1x leverage, six-position limit, and gross cap at or below 75 USDC;
- the dedicated `buy_portfolio` application is used; `buy_perp` rejects this mode;
- the dedicated service shares `hyperliquid-perp-state` with the old service so the
  same-wallet lease prevents both runtimes from using that wallet concurrently.

Mainnet portfolio execution is rejected by configuration validation.

The initial sample has `entries_enabled=false`. In this state the service validates
credentials, account affinity, durable state, OHLCV alignment, signals, current
positions, and protection, but it does not persist or execute a rebalance decision.

## Files to create on the deployment host

Copy these samples to untracked files outside the repository or to a protected local
path:

- credentials: `deploy/secrets/hyperliquid.testnet.json.sample`;
- settings: `deploy/settings/hyperliquid.portfolio-testnet.json.sample`.

Keep `entries_enabled=false` for the first deployment. Do not place wallet addresses,
private keys, webhook URLs, or their paths in Git.

## Offline preflight

This performs no network operation and prints only a sanitized configuration summary:

```sh
export HYPERLIQUID_PERP_SECRETS_FILE=/secure/path/hyperliquid.testnet.json
export HYPERLIQUID_PERP_SETTINGS_FILE=/secure/path/hyperliquid.portfolio-testnet.json

uv run python -m crypto_spot_collector.scripts.portfolio_testnet_preflight \
  --settings "$HYPERLIQUID_PERP_SETTINGS_FILE" \
  --secrets "$HYPERLIQUID_PERP_SECRETS_FILE"
```

It rejects placeholders, secret/settings network mismatch, mainnet, the wrong app
mode, changed symbol order, leverage above 1x, gross exposure above 75 USDC, and an
initial settings file with entries already enabled.

## Disabled-entry deployment

Before running this externally, confirm that the old `app_perp` service is stopped and
that any existing testnet positions remain protected or are flat. The script refuses
to proceed while the old service is running.

```sh
./deploy-portfolio-testnet.sh
```

The script runs the offline preflight, validates the Compose graph, backs up an
existing SQLite state, builds the image, force-recreates the service so secret/config
source changes cannot reuse an old container, and waits for health. It does not accept
an enabled settings file.

After it becomes healthy, verify:

1. health reports `network=testnet`, `signal_mode=portfolio_trend_ensemble`,
   `entries_enabled=false`, six symbols, 1x, six positions, and the 75 USDC cap;
2. logs contain no wallet, private key, webhook, balance payload, or raw API response;
3. the latest completed daily candle is aligned across all six symbols and no more
   than six hours old;
4. the dry plan contains only `reduce`, only `increase`, or `complete`, never a mix;
5. each non-zero planned action is currently executable after live amount precision,
   the HyperLiquid minimum notional, and the 12.5 USDC order cap are applied.

Item 5 is intentionally a live pre-activation gate. The backtest ignored discrete
minimum order sizes. The 10 USDC rebalance tolerance in the sample avoids repeatedly
trying to trade very small differences, but it also creates tracking error that was
not present in the backtest and must be measured on testnet.

## Explicit testnet activation

Activation is a separate external operation. It requires a settings copy with
`entries_enabled=true`, a fresh offline preflight, and the exact confirmation phrase:

```sh
export PORTFOLIO_TESTNET_ACTIVATION_CONFIRMATION=\
I_UNDERSTAND_THIS_ENABLES_HYPERLIQUID_TESTNET_PORTFOLIO_ORDERS
./activate-portfolio-testnet.sh
```

The runtime executes one action at a time. Before every action it re-fetches positions
and requires the snapshot-bound plan hash to match. After a fully confirmed fill it
requires the position quantity to move in the planned direction, reconciles TP/SL for
the actual remaining quantity, fetches positions again, and re-plans. Reductions are
always complete before an increase is allowed.

## Testnet acceptance gate

Do not consider preparation complete for mainnet based only on a healthy container.
Record evidence for at least these scenarios:

- aligned six-symbol daily data and deterministic target parity;
- minimum/precision preflight for every non-zero action;
- flat-to-long and flat-to-short entry with exact TP/SL quantities;
- same-side addition and partial reduction with replacement protection verified before
  stale protection is cancelled;
- long-to-short and short-to-long reversal, proving flat before the new side;
- per-order cap requiring multiple action/re-fetch/re-plan cycles;
- restart after `prepared`, `reducing`, and `increasing`, with no duplicate order;
- forced stale plan, incomplete candle, stale candle, unaligned symbol data, unknown
  position, non-reduce-only open order, kill switch, and insufficient collateral;
- final global flat state, zero open orders, zero unsettled intents, and a verified
  SQLite backup.

The fixed TP/SL protection and the 10 USDC execution tolerance were not included in
the winning portfolio backtest. Testnet validates operational behavior, not
profitability; a separate replay including those execution overlays is required before
any mainnet proposal.

## Stop and rollback

To stop new increases without interrupting protection or reduce-only reconciliation:

```sh
docker compose --profile portfolio-testnet exec app_portfolio_testnet sh -c \
  'touch /var/lib/crypto-spot-collector/ENTRY_KILL_SWITCH'
```

Do not shrink the symbol allowlist while a removed symbol has a position, protection
order, unsettled intent, or pending portfolio decision. Keep all six symbols monitored,
confirm protection or reduce-only flat them, reconcile orphan orders and intents, and
only then change configuration. Never use `docker compose down -v`; the shared volume
contains the order and portfolio decision ledger.
