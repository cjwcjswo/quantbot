#!/usr/bin/env bash
# Production deploy for the QuantBot stack on Ubuntu (Docker Compose).
#
# Run from the repo root AFTER updating the code (git pull / reset):
#   cd /home/ubuntu/dev/quantbot && bash deploy/deploy.sh
#
# It stops & removes any existing quantbot containers, (re)builds the images, and
# starts postgres + redis + bot + api + web. The bot boots to STANDBY and never
# trades until a START command from the dashboard — even in LIVE mode.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
COMPOSE="docker compose -p quantbot -f deploy/docker-compose.yml"

echo "[1/6] Checking .env..."
if [ ! -f .env ]; then
  echo "ERROR: .env is missing. Create it from deploy/.env.example and fill in your keys:"
  echo "  cp deploy/.env.example .env && \$EDITOR .env"
  exit 1
fi

echo "[2/6] Building images..."
mkdir -p logs
$COMPOSE build

echo "[3/6] Reading runtime config from YAML..."
mapfile -t runtime_config < <(
  docker run --rm --env-file .env quantbot-app python -c '
from packages.config import load_app_config, load_secrets

config = load_app_config(load_secrets().quantbot_config)
print(config.bot.mode.value)
print(config.api.api_host)
print(config.api.api_port)
'
)
bot_mode="${runtime_config[0]:-}"
api_host="${runtime_config[1]:-0.0.0.0}"
api_port="${runtime_config[2]:-8000}"

if ! [[ "$api_port" =~ ^[0-9]+$ ]]; then
  echo "ERROR: config api.api_port must be a number, got: $api_port"
  exit 1
fi
export QUANTBOT_API_PORT="$api_port"

echo "  bot.mode=${bot_mode:-unknown}"
echo "  api.api_host=$api_host"
echo "  api.api_port=$api_port"

echo "[4/6] Stopping & removing any existing quantbot stack..."
# Old stack (root docker-compose.yml: bot/api/web) and/or a previous new stack.
docker compose -p quantbot down --remove-orphans --timeout 30 2>/dev/null || true
$COMPOSE down --remove-orphans --timeout 30 2>/dev/null || true
docker rm -f quantbot-bot-1 quantbot-api-1 quantbot-web-1 2>/dev/null || true

echo "[5/6] Starting the stack (postgres, redis, bot, api, web)..."
$COMPOSE up -d

echo "[6/6] Installing host nginx vhost (:8090) and reloading..."
if command -v nginx >/dev/null 2>&1; then
  sudo install -m 0644 deploy/nginx/quantbot.conf /etc/nginx/sites-available/quantbot.conf
  sudo ln -sf /etc/nginx/sites-available/quantbot.conf /etc/nginx/sites-enabled/quantbot.conf
  if sudo nginx -t; then
    sudo systemctl reload nginx
    echo "  host nginx reloaded (dashboard on :8090)."
  else
    echo "  WARNING: nginx config test failed; not reloading. Dashboard still on 127.0.0.1:8080."
  fi
else
  echo "  nginx not found on host; skipping. Dashboard reachable at 127.0.0.1:8080."
fi

echo "Waiting for API health..."
ok=0
for _ in $(seq 1 45); do
  if curl -fsS "http://127.0.0.1:${api_port}/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
echo
$COMPOSE ps
echo
if [ "$ok" = "1" ]; then
  curl -fsS "http://127.0.0.1:${api_port}/health" || true
  echo
  echo "Deploy OK. The bot mode is ${bot_mode:-"(see config/quantbot.yaml)"} and in STANDBY — press Start in the"
  echo "dashboard (http://<EC2-ip>:8090/) to begin trading."
else
  echo "API did not report healthy in time. Check logs:"
  echo "  $COMPOSE logs --tail=80 api bot"
  exit 1
fi
