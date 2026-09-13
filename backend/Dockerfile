# syntax=docker/dockerfile:1.7
# lxdash backend (FastAPI) — production image.
#
# Hardening posture:
#   - multi-stage build keeps gcc/libffi out of the runtime image
#   - runs as non-root 'appuser' (UID 999)
#   - PYTHONDONTWRITEBYTECODE=1 so Python does not try to write .pyc files
#     when the compose layer mounts the root filesystem read-only
#   - LXD_GID build arg lets the operator match the host's lxd group GID so
#     the process can read /var/snap/lxd/common/lxd/unix.socket
#   - compose layer (docker-compose.yml) adds:
#       security_opt: no-new-privileges:true
#       cap_drop: [ALL]
#       read_only: true (only /app/data via named volume is writable)
#       tmpfs:   /tmp
#       mem_limit / cpus / pids_limit
#       init:    true

FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
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

# No .pyc writes — required when the compose layer mounts the root FS read-only.
ENV PYTHONDONTWRITEBYTECODE=1

# Built-in Docker healthcheck — same logic as the compose healthcheck but
# having it here means `docker run` and ad-hoc invocations also probe it.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"]

ENTRYPOINT ["./entrypoint.sh"]
