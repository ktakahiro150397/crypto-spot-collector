# Hyperliquid deployment runbook

## Environment separation

Create files from the samples without placing the resulting `.json` files in
Git. Testnet and mainnet must have different credential files and preferably a
different Discord webhook:

- `deploy/secrets/hyperliquid.testnet.json.sample`
- `deploy/secrets/hyperliquid.mainnet.json.sample`
- `deploy/settings/hyperliquid.testnet.json.sample`
- `deploy/settings/hyperliquid.mainnet-canary.json.sample`

The mainnet settings sample is intentionally invalid (`allow_mainnet=false`,
`entries_enabled=false`, zero order/risk values and an unapproved symbol).
Fill the user-approved symbol and amount, keep `canary_mode=true`, set all risk
caps, then explicitly enable mainnet and entries only for the authorized run.

Set deployment inputs in the operator shell. Do not put the confirmation phrase
or credential paths in a committed `.env` file.

```sh
export HYPERLIQUID_PERP_SECRETS_FILE=/secure/path/hyperliquid.testnet.json
export HYPERLIQUID_PERP_SETTINGS_FILE=/secure/path/hyperliquid.testnet.json
./deploy.sh testnet
```

For mainnet, also export the exact confirmation phrase already enforced by
`TradingConfig`. The credential JSON's `hyperliquid.network`, settings
`network`, deploy argument and confirmation must all agree or startup fails
before an exchange client is created.

## Persistent state and single instance

Compose mounts `hyperliquid-perp-state` at
`/var/lib/crypto-spot-collector`. The SQLite intent/SAR database, lease,
entry kill switch and non-secret health file live there and survive image and
container recreation. Missing/unwritable state, failed SQLite `quick_check`, a
write-lock conflict or an existing same-wallet lease stops startup.

The lease fingerprint is one-way and the health file contains only network,
allowlist and aggregate risk settings. It never contains a wallet address,
private key, webhook URL or balance payload.

## Health, graceful stop and emergency entry stop

Compose waits up to the configured health window for `health.json` to report a
fresh `running` pulse. `restart: unless-stopped`, an init process and a 45
second stop grace period allow SIGTERM to inhibit new intents, cancel workers,
close exchange clients and release the lease.

To stop only new entries immediately while leaving protection, trailing and
reduce-only close paths active:

```sh
docker compose exec app_perp sh -c \
  'touch /var/lib/crypto-spot-collector/ENTRY_KILL_SWITCH'
```

Remove the file to permit entries again after investigating current positions,
open orders and risk usage.

## Backup and restore

`deploy.sh` creates a verified SQLite backup in `./backups` before replacing a
running container. Manual backup is also available:

```sh
docker compose run --rm --no-deps --entrypoint uv app_perp \
  run python -m crypto_spot_collector.scripts.state_admin backup \
  --state-dir /var/lib/crypto-spot-collector \
  --output /backups/order_intents-manual.sqlite
```

Restore only while the bot is stopped. The explicit confirmation is required:

```sh
docker compose stop app_perp
docker compose run --rm --no-deps --entrypoint uv app_perp \
  run python -m crypto_spot_collector.scripts.state_admin restore \
  --state-dir /var/lib/crypto-spot-collector \
  --backup /backups/order_intents-manual.sqlite \
  --confirm-restore
docker compose up -d --no-build app_perp
```

Both backup and restore run SQLite `quick_check`; restore uses a temporary
database and atomic replacement.

## Rollback

Before deploying, record `git rev-parse HEAD`, `docker compose images app_perp`
and the generated backup name. If the new container is unhealthy:

1. Keep or create `ENTRY_KILL_SWITCH` and stop `app_perp`.
2. Retag the recorded previous image ID to the compose service image name.
3. Restore the pre-deploy SQLite backup only when schema/state rollback is
   required; otherwise keep the newer durable state to preserve cloid history.
4. Run `docker compose up -d --no-build app_perp`.
5. Require a healthy container and inspect only sanitized startup/heartbeat
   logs before removing the entry kill switch.

Never use `docker compose down -v` for rollback; it deletes the persistent
state volume.
