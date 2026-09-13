FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------

FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Create a non-root user.
# LXD_GID must match the host's lxd group GID so the process can access the
# Unix socket mounted at runtime. Override with: --build-arg LXD_GID=<gid>
ARG LXD_GID=998
RUN groupadd -g "${LXD_GID}" lxd 2>/dev/null || true \
    && useradd -r -u 999 -g 999 -G "${LXD_GID}" -d /app appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

COPY --chown=appuser:appuser . .

RUN chmod +x entrypoint.sh

USER appuser

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
