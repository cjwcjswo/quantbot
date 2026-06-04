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

echo "[1/5] Checking .env..."
if [ ! -f .env ]; then
  echo "ERROR: .env is missing. Create it from deploy/.env.example and fill in your keys:"
  echo "  cp deploy/.env.example .env && \$EDITOR .env"
  exit 1
fi

echo "[2/5] Stopping & removing any existing quantbot stack..."
# Old stack (root docker-compose.yml: bot/api/web) and/or a previous new stack.
docker compose -p quantbot down --remove-orphans --timeout 30 2>/dev/null || true
$COMPOSE down --remove-orphans --timeout 30 2>/dev/null || true
docker rm -f quantbot-bot-1 quantbot-api-1 quantbot-web-1 2>/dev/null || true

echo "[3/5] Building & starting the stack (postgres, redis, bot, api, web)..."
mkdir -p logs
$COMPOSE up -d --build

echo "[4/5] Installing host nginx vhost (:8090) and reloading..."
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

echo "[5/5] Waiting for API health..."
ok=0
for _ in $(seq 1 45); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
echo
$COMPOSE ps
echo
if [ "$ok" = "1" ]; then
  curl -fsS http://127.0.0.1:8000/health || true
  echo
  echo "Deploy OK. The bot is ${BOT_MODE:-(see .env)} and in STANDBY — press Start in the"
  echo "dashboard (http://<EC2-ip>:8090/) to begin trading."
else
  echo "API did not report healthy in time. Check logs:"
  echo "  $COMPOSE logs --tail=80 api bot"
  exit 1
fi
