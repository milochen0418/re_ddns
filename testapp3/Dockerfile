FROM python:3.11-slim-bookworm

# ── System deps: Node.js (for Reflex frontend build), utilities ──
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl unzip git gcc libffi-dev \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g bun \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ── Poetry ──
ENV POETRY_VERSION=1.8.4 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_NO_INTERACTION=1
RUN curl -sSL https://install.python-poetry.org | python - \
    && ln -s /opt/poetry/bin/poetry /usr/local/bin/poetry

# ── App workdir ──
WORKDIR /app

# ── Install Python deps (cached layer) ──
COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-root || (poetry lock && poetry install --no-root)

# ── Copy application source ──
COPY . .

# ── Reflex init (pre-build frontend skeleton) ──
RUN poetry run reflex init || true

# Patch Reflex Vite config to allow any hostname
RUN sed -i 's/port: process.env.PORT,/port: process.env.PORT,\n    allowedHosts: true,/' \
    /app/.venv/lib/python3.11/site-packages/reflex/compiler/templates.py 2>/dev/null || true

# ── Create upload directory ──
RUN mkdir -p /app/uploaded_files

# ── Entrypoint ──
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Ports: standard Reflex ports (same as every other Reflex container)
EXPOSE 3000 8000

ENTRYPOINT ["/entrypoint.sh"]
