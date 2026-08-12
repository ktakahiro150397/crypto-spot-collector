#!/usr/bin/env sh
set -eu

network="${1:-}"
case "$network" in
  testnet|mainnet) ;;
  *) echo "usage: ./deploy.sh testnet|mainnet" >&2; exit 2 ;;
esac

: "${HYPERLIQUID_PERP_SECRETS_FILE:?set environment-specific secret JSON path}"
: "${HYPERLIQUID_PERP_SETTINGS_FILE:?set environment-specific settings JSON path}"
export HYPERLIQUID_DEPLOYMENT_NETWORK="$network"

if [ "$network" = "mainnet" ]; then
  : "${HYPERLIQUID_MAINNET_CONFIRMATION:?explicit mainnet confirmation is required}"
fi

mkdir -p backups
docker compose config --quiet

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
if docker compose ps -q app_perp | grep -q .; then
  docker compose run --rm --no-deps --entrypoint uv app_perp \
    run python -m crypto_spot_collector.scripts.state_admin backup \
    --state-dir /var/lib/crypto-spot-collector \
    --output "/backups/order_intents-${timestamp}.sqlite"
fi

docker compose build app_perp
docker compose up -d --no-deps app_perp

container_id="$(docker compose ps -q app_perp)"
attempt=0
while [ "$attempt" -lt 36 ]; do
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id")"
  if [ "$health" = "healthy" ]; then
    echo "Deployment healthy: network=$network"
    exit 0
  fi
  if [ "$health" = "unhealthy" ]; then
    break
  fi
  attempt=$((attempt + 1))
  sleep 5
done

echo "Deployment failed health verification. Follow the documented rollback procedure." >&2
docker compose logs --tail=100 app_perp >&2
exit 1
