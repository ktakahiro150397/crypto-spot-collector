# Portfolio mainnet observer deployment

This service connects to the Hyperliquid mainnet account but is deliberately
unable to submit, cancel, reconcile, or reduce orders. It validates API wallet
authorization, requires a flat account with zero open orders, calculates the
frozen daily portfolio signal, and emits a sanitized health heartbeat.

## Safety contract

- `network=mainnet`, `allow_mainnet=true`, and the exact environment-only
  mainnet confirmation phrase are all required.
- `entries_enabled=false` is mandatory. Configuration validation rejects a
  mainnet portfolio with entries enabled.
- The mainnet coordinator rejects every execution call, including reduce-only
  actions.
- Disabled startup does not recover order intents or reconcile protection
  orders. It requires zero unsettled local intents, a flat account, and zero
  open orders.
- The persistent `ENTRY_KILL_SWITCH` is created before startup and remains in
  place after deployment.
- Read-only live account gates run before and after startup without mounting the
  persistent state volume.

## Deployment

Create an uncommitted settings file from
`deploy/settings/hyperliquid.portfolio-mainnet-disabled.json.sample`. Use the
already authorized mainnet credential file; never paste a private key into the
repository or shell history.

```sh
export HYPERLIQUID_PERP_SECRETS_FILE=/secure/path/mainnet-credentials.json
export HYPERLIQUID_PERP_SETTINGS_FILE=/secure/path/portfolio-mainnet-disabled.json
export HYPERLIQUID_MAINNET_CONFIRMATION=I_UNDERSTAND_THIS_WILL_TRADE_ON_HYPERLIQUID_MAINNET
./deploy-portfolio-mainnet-disabled.sh
```

The script refuses to run beside the legacy perpetual or testnet portfolio
service. It builds the exact image, validates settings and secret affinity,
audits the live account, creates a verified SQLite backup when state exists,
engages the kill switch, starts only the observer service, waits for healthy,
then repeats the live account audit.

Do not remove the kill switch or change `entries_enabled`. Order activation is
outside this deployment contract and requires a separate implementation,
review, testnet acceptance, and explicit authorization.
