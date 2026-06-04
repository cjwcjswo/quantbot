# Python image shared by the `bot` and `api` services (same codebase, different
# command — see deploy/docker-compose.yml). Built with uv from uv.lock for
# reproducible installs. First-party packages (apps/, packages/) are imported via
# PYTHONPATH=/app, so only third-party deps are installed into the venv.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH

RUN pip install --no-cache-dir uv

WORKDIR /app

# Dependency layer: only the lockfiles, so editing app code doesn't reinstall deps.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application code + config.
COPY packages ./packages
COPY apps ./apps
COPY config ./config

# Logs are written here (packages/observability) — mounted to a host dir in compose.
RUN mkdir -p /app/logs

EXPOSE 8000

# Overridden per service in docker-compose.yml.
CMD ["python", "-m", "apps.bot.main"]
