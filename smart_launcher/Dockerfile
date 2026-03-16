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

# ── Copy launcher scripts ──
COPY entrypoint.sh /entrypoint.sh
COPY register_dns.py /app/register_dns.py
RUN chmod +x /entrypoint.sh

# Ports: standard Reflex ports
EXPOSE 3000 8000

ENTRYPOINT ["/entrypoint.sh"]
