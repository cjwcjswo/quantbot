# Deploying QuantBot (Ubuntu / Docker Compose)

The production stack runs entirely in Docker — no `uv`/`node` needed on the host:

| Service    | Image          | Purpose                                   | Host port        |
|------------|----------------|-------------------------------------------|------------------|
| `postgres` | postgres:16    | persistence                               | internal         |
| `redis`    | redis:7        | realtime state / command queue            | internal         |
| `bot`      | `quantbot-app` | Bot Engine (`python -m apps.bot.main`)    | internal         |
| `api`      | `quantbot-app` | FastAPI control plane                     | 127.0.0.1:`api.api_port` |
| `web`      | `quantbot-web` | React dashboard (nginx, proxies /api,/ws) | 127.0.0.1:8080   |

The host nginx (`deploy/nginx/quantbot.conf`, **:8090**) is the public entry point and
forwards everything to the `web` container. Dashboard: `http://<EC2-ip>:8090/`.

> **Safety:** the bot boots to **STANDBY** and never places an order until you press
> **Start** in the dashboard — even with `bot.mode: "LIVE"`. LIVE just wires the real
> Bybit account; trading begins only on an explicit START command (arch §3.4).

## First-time deploy / migration

```bash
ssh comabot-aws
cd /home/ubuntu/dev/quantbot

# 1) get the new code
git fetch origin
git reset --hard origin/main        # diverged history -> reset, not pull
git clean -fd                       # remove old layout (keeps gitignored .env)

# 2) configure secrets (NOT committed)
cp deploy/.env.example .env
$EDITOR .env                        # set BYBIT_API_KEY/SECRET
$EDITOR config/quantbot.yaml        # set bot.mode, API options, strategy/risk tuning

# 3) deploy
bash deploy/deploy.sh
```

`deploy.sh` stops & removes any existing quantbot containers, builds the images,
reads `bot.mode` and `api.api_port` from YAML inside the app image, starts the
stack, installs/reloads the host nginx vhost, and waits for `/health`.

## Routine redeploy

```bash
cd /home/ubuntu/dev/quantbot && git pull && bash deploy/deploy.sh
```

## Operating

```bash
# status / logs
docker compose -p quantbot -f deploy/docker-compose.yml ps
docker compose -p quantbot -f deploy/docker-compose.yml logs -f bot api
tail -f logs/bot.log logs/api.log          # file logs (also persisted on host)

# start LIVE trading (or use the dashboard Start button; replace 8000 if api.api_port differs)
curl -X POST http://127.0.0.1:8000/bot/start \
     -H 'Content-Type: application/json' \
     -d '{"live_confirm":true}'

# stop the stack
docker compose -p quantbot -f deploy/docker-compose.yml down
```
