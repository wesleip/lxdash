# syntax=docker/dockerfile:1.7
# lxdash frontend (React SPA) served by Nginx — production image.
#
# Hardening posture:
#   - multi-stage: Node builds the SPA, Nginx serves it (Node never ships)
#   - master and workers all run as non-root 'nginx' (UID 101, Alpine default)
#   - listens on unprivileged port 8080 inside the container; compose maps
#     host:80 -> container:8080 so CAP_NET_BIND_SERVICE is not needed
#   - access and error logs go to /dev/stdout and /dev/stderr, captured by
#     the container runtime instead of written to ephemeral disk
#   - compose layer (docker-compose.yml) adds:
#       security_opt: no-new-privileges:true
#       cap_drop: [ALL]
#       read_only: true (only tmpfs mounts under /var/cache, /var/run, /tmp
#                    are writable)
#       init: true

# Stage 1: build the React app
FROM node:20-alpine AS frontend-builder

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --prefer-offline

COPY frontend/ ./
RUN npm run build


# Stage 2: serve with Nginx (unprivileged)
FROM nginx:1.27-alpine

# Replace the stock default server with our config (listens on 8080, see
# nginx/nginx.conf).
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf

# Static assets from the builder; chown to nginx so the SPA files are owned
# by the runtime user.
COPY --from=frontend-builder --chown=nginx:nginx /app/dist /usr/share/nginx/html

# Send logs to stdout/stderr. These symlinks live in /var/log/nginx (writable
# by the nginx user) and point at the container's stdio, so 'docker logs'
# captures every request/response without needing a log driver.
RUN ln -sf /dev/stdout /var/log/nginx/access.log \
    && ln -sf /dev/stderr /var/log/nginx/error.log

# Make the pidfile directory writable by the nginx user.
RUN touch /var/run/nginx.pid \
    && chown nginx:nginx /var/run/nginx.pid

# Master + workers all run as UID 101 (the numeric form satisfies
# hadolint DL3066 — user names are not always resolvable by the host
# kernel's NSS). With 'listen 8080' this process does not need
# CAP_NET_BIND_SERVICE.
USER 101

EXPOSE 8080

# JSON exec form (satisfies hadolint DL3025) so CMD arguments are not
# re-parsed by a shell.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["wget", "-qO-", "http://localhost:8080/api/health"]
