# syntax=docker/dockerfile:1.7
# lxdash frontend (React SPA) served by Nginx — production image.
#
# Hardening posture:
#   - multi-stage: Node builds the SPA, Nginx serves it (Node never ships)
#   - uses nginxinc/nginx-unprivileged, which runs as non-root UID 101 from
#     image build, pre-creates /var/cache/nginx/*_temp and pid directory as
#     the nginx user, and ships with logs symlinked to stdout/stderr
#   - listens on unprivileged port 8080; compose maps host:80 -> container:8080
#     so CAP_NET_BIND_SERVICE is not needed
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
FROM nginxinc/nginx-unprivileged:1.27-alpine

# Replace the stock default server with our config (listens on 8080, see
# nginx/nginx.conf). The unprivileged image's main /etc/nginx/nginx.conf has
# no `user` directive, so workers inherit UID 101 from PID 1 — no privilege
# drop attempt is made and cap_drop: ALL in compose is safe.
COPY nginx/nginx.conf /etc/nginx/conf.d/default.conf

# Static assets from the builder; chown to nginx so the SPA files are owned
# by the runtime user.
COPY --from=frontend-builder --chown=nginx:nginx /app/dist /usr/share/nginx/html

EXPOSE 8080

# JSON exec form (satisfies hadolint DL3025) so CMD arguments are not
# re-parsed by a shell.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD ["wget", "-qO-", "http://localhost:8080/api/health"]
