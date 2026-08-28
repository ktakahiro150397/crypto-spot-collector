#!/usr/bin/env sh
set -eu

: "${HYPERLIQUID_PERP_SECRETS_FILE:?set the mainnet credential JSON path}"
: "${HYPERLIQUID_PERP_SETTINGS_FILE:?set the disabled portfolio mainnet settings JSON path}"
: "${HYPERLIQUID_MAINNET_CONFIRMATION:?explicit mainnet confirmation is required}"

expected_confirmation="I_UNDERSTAND_THIS_WILL_TRADE_ON_HYPERLIQUID_MAINNET"
if [ "$HYPERLIQUID_MAINNET_CONFIRMATION" != "$expected_confirmation" ]; then
  echo "Refusing deployment: mainnet confirmation phrase is invalid." >&2
  exit 1
fi
export HYPERLIQUID_DEPLOYMENT_NETWORK=mainnet

observer_started=0
cleanup_on_error() {
  status="$?"
  trap - 0
  if [ "$status" -ne 0 ] && [ "$observer_started" -eq 1 ]; then
    docker compose --profile portfolio-mainnet-disabled stop \
      app_portfolio_mainnet_disabled >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup_on_error 0

for service in app_perp app_portfolio_testnet; do
  if docker compose --profile portfolio-testnet ps --status running -q "$service" | grep -q .; then
    echo "Refusing deployment while $service is running." >&2
    exit 1
  fi
done

docker compose --profile portfolio-mainnet-disabled config --quiet
mkdir -p backups

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
docker compose --profile portfolio-mainnet-disabled build app_portfolio_mainnet_disabled
image_id="$(docker compose --profile portfolio-mainnet-disabled images -q app_portfolio_mainnet_disabled | head -n 1)"
if [ -z "$image_id" ]; then
  echo "Built portfolio image could not be resolved." >&2
  exit 1
fi

docker run --rm --read-only --network none --tmpfs /tmp \
  --env HYPERLIQUID_MAINNET_CONFIRMATION \
  --volume "${HYPERLIQUID_PERP_SETTINGS_FILE}:/run/secrets/hyperliquid_settings.json:ro" \
  --volume "${HYPERLIQUID_PERP_SECRETS_FILE}:/run/secrets/hyperliquid_credentials.json:ro" \
  --entrypoint /app/.venv/bin/python "$image_id" \
  -m crypto_spot_collector.scripts.portfolio_mainnet_preflight \
  --settings /run/secrets/hyperliquid_settings.json \
  --secrets /run/secrets/hyperliquid_credentials.json

docker run --rm --read-only --tmpfs /tmp \
  --env HYPERLIQUID_MAINNET_CONFIRMATION \
  --volume "${HYPERLIQUID_PERP_SETTINGS_FILE}:/run/secrets/hyperliquid_settings.json:ro" \
  --volume "${HYPERLIQUID_PERP_SECRETS_FILE}:/run/secrets/hyperliquid_credentials.json:ro" \
  --entrypoint /app/.venv/bin/python "$image_id" \
  -m crypto_spot_collector.scripts.portfolio_mainnet_account_preflight \
  --settings /run/secrets/hyperliquid_settings.json \
  --secrets /run/secrets/hyperliquid_credentials.json

docker compose --profile portfolio-mainnet-disabled run --rm --no-deps \
  --entrypoint sh app_portfolio_mainnet_disabled -c \
  'touch /var/lib/crypto-spot-collector/ENTRY_KILL_SWITCH
  if [ -f /var/lib/crypto-spot-collector/order_intents.sqlite ]; then
    /app/.venv/bin/python -m crypto_spot_collector.scripts.state_admin \
      backup --state-dir /var/lib/crypto-spot-collector \
      --output "/backups/order_intents-'"$timestamp"'.sqlite"
  fi'

docker compose --profile portfolio-mainnet-disabled up -d --force-recreate \
  --no-deps app_portfolio_mainnet_disabled
observer_started=1

container_id="$(docker compose --profile portfolio-mainnet-disabled ps -q app_portfolio_mainnet_disabled)"
attempt=0
while [ "$attempt" -lt 36 ]; do
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id")"
  if [ "$health" = "healthy" ]; then
    break
  fi
  if [ "$health" = "unhealthy" ]; then
    echo "Portfolio mainnet observer failed health verification." >&2
    docker compose --profile portfolio-mainnet-disabled logs --tail=100 app_portfolio_mainnet_disabled >&2
    exit 1
  fi
  attempt=$((attempt + 1))
  sleep 5
done
if [ "$health" != "healthy" ]; then
  echo "Portfolio mainnet observer timed out during health verification." >&2
  docker compose --profile portfolio-mainnet-disabled logs --tail=100 app_portfolio_mainnet_disabled >&2
  exit 1
fi

actual_settings_source="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/run/secrets/hyperliquid_settings.json"}}{{.Source}}{{end}}{{end}}' "$container_id")"
actual_secrets_source="$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/run/secrets/hyperliquid_credentials.json"}}{{.Source}}{{end}}{{end}}' "$container_id")"
if [ "$actual_settings_source" != "$(readlink -f "$HYPERLIQUID_PERP_SETTINGS_FILE")" ] || \
   [ "$actual_secrets_source" != "$(readlink -f "$HYPERLIQUID_PERP_SECRETS_FILE")" ]; then
  echo "Portfolio mainnet observer secret mounts do not match deployment inputs." >&2
  exit 1
fi

docker run --rm --read-only --tmpfs /tmp \
  --env HYPERLIQUID_MAINNET_CONFIRMATION \
  --volume "${HYPERLIQUID_PERP_SETTINGS_FILE}:/run/secrets/hyperliquid_settings.json:ro" \
  --volume "${HYPERLIQUID_PERP_SECRETS_FILE}:/run/secrets/hyperliquid_credentials.json:ro" \
  --entrypoint /app/.venv/bin/python "$image_id" \
  -m crypto_spot_collector.scripts.portfolio_mainnet_account_preflight \
  --settings /run/secrets/hyperliquid_settings.json \
  --secrets /run/secrets/hyperliquid_credentials.json

docker compose --profile portfolio-mainnet-disabled exec -T \
  app_portfolio_mainnet_disabled /app/.venv/bin/python \
  -m crypto_spot_collector.scripts.healthcheck \
  --state-dir /var/lib/crypto-spot-collector

trap - 0
echo "Portfolio mainnet observer is healthy; entries and all order execution remain disabled."
