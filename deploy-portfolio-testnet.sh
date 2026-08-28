#!/usr/bin/env sh
set -eu

: "${HYPERLIQUID_PERP_SECRETS_FILE:?set the testnet credential JSON path}"
: "${HYPERLIQUID_PERP_SETTINGS_FILE:?set the portfolio testnet settings JSON path}"
export HYPERLIQUID_DEPLOYMENT_NETWORK=testnet
export HYPERLIQUID_MAINNET_CONFIRMATION=""

if docker compose ps -q app_perp | grep -q .; then
  echo "Refusing portfolio deployment while app_perp exists; stop and verify it first." >&2
  exit 1
fi

uv run python -m crypto_spot_collector.scripts.portfolio_testnet_preflight \
  --settings "$HYPERLIQUID_PERP_SETTINGS_FILE" \
  --secrets "$HYPERLIQUID_PERP_SECRETS_FILE"
docker compose --profile portfolio-testnet config --quiet
mkdir -p backups

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
if docker compose --profile portfolio-testnet ps -q app_portfolio_testnet | grep -q .; then
  docker compose --profile portfolio-testnet run --rm --no-deps --entrypoint uv \
    app_portfolio_testnet run python -m crypto_spot_collector.scripts.state_admin \
    backup --state-dir /var/lib/crypto-spot-collector \
    --output "/backups/order_intents-${timestamp}.sqlite"
fi

docker compose --profile portfolio-testnet build app_portfolio_testnet
docker compose --profile portfolio-testnet up -d --force-recreate --no-deps \
  app_portfolio_testnet

container_id="$(docker compose --profile portfolio-testnet ps -q app_portfolio_testnet)"
attempt=0
while [ "$attempt" -lt 36 ]; do
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id")"
  if [ "$health" = "healthy" ]; then
    echo "Portfolio testnet deployment is healthy with entries disabled."
    exit 0
  fi
  if [ "$health" = "unhealthy" ]; then
    break
  fi
  attempt=$((attempt + 1))
  sleep 5
done

echo "Portfolio testnet deployment failed health verification." >&2
docker compose --profile portfolio-testnet logs --tail=100 app_portfolio_testnet >&2
exit 1
