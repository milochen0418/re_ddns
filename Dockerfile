FROM python:3.11-slim-bookworm

# ── System deps: BIND9, Node.js (for Reflex frontend build), utilities ──
RUN apt-get update && apt-get install -y --no-install-recommends \
        bind9 bind9utils bind9-dnsutils \
        curl unzip git lsof procps \
        gcc libffi-dev \
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

# ── BIND9 directories & permissions ──
RUN mkdir -p /etc/bind/zones /var/cache/bind /var/log/bind /run/named \
    && chown -R bind:bind /var/cache/bind /var/log/bind /run/named /etc/bind/zones

# ── Copy BIND9 configuration ──
COPY docker/named.conf       /etc/bind/named.conf
COPY docker/named.conf.local /etc/bind/named.conf.local
COPY docker/rndc.conf        /etc/bind/rndc.conf
COPY docker/zones/           /etc/bind/zones/
RUN chown -R bind:bind /etc/bind

# ── App workdir ──
WORKDIR /app

# ── Install Python deps (cached layer – only re-runs when lock changes) ──
COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-root || (poetry lock && poetry install --no-root)

# ── Copy application source (used for initial build; overridden by volume) ──
COPY . .

# ── Reflex init (pre-build the frontend skeleton so first start is faster) ──
RUN poetry run reflex init || true

# ── Entrypoint ──
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Ports: DNS 53 (TCP+UDP), Reflex frontend 3000, Reflex backend 8000
EXPOSE 53/tcp 53/udp 3000 8000

ENTRYPOINT ["/entrypoint.sh"]
