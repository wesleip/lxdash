#!/usr/bin/env bash
# Verify that a docker-compose file declares the security hardening baseline.
#
# Checks each service for:
#   - security_opt contains no-new-privileges:true
#   - cap_drop contains ALL
#   - privileged: true is absent
#
# Usage:
#   scripts/check-security.sh [docker-compose.yml]
#
# Exits 0 on success, 1 if any check fails. The script has zero runtime
# dependencies (no docker, jq, python). It parses YAML structurally with
# awk; it does NOT validate the compose file the way `docker compose config`
# would (missing env_file, etc.). Run `docker compose config` separately
# when you need full validation.

set -euo pipefail

COMPOSE_FILE="${1:-docker-compose.yml}"

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "ERROR: $COMPOSE_FILE not found" >&2
    exit 1
fi

echo "Checking security hardening in $COMPOSE_FILE"
echo

# Extract top-level service names (keys two spaces indented under 'services:').
services=$(awk '
    /^services:$/ { in_services = 1; next }
    in_services && /^  [a-zA-Z][a-zA-Z0-9_-]*:$/ { sub(/:$/, ""); print $1; next }
    in_services && /^[^ ]/ { in_services = 0 }
' "$COMPOSE_FILE")

if [ -z "$services" ]; then
    echo "ERROR: no services found under 'services:' in $COMPOSE_FILE" >&2
    exit 1
fi

FAILED=0

for svc in $services; do
    # Capture the YAML block that belongs to this service: from its header
    # line until the next top-level service header (also at indent 2).
    block=$(awk -v header="^  ${svc}:$" '
        $0 ~ header { in_block = 1; next }
        in_block && /^  [a-zA-Z]/ { in_block = 0 }
        in_block { print }
    ' "$COMPOSE_FILE")

    echo "[$svc]"

    if grep -q "no-new-privileges:true" <<<"$block"; then
        echo "  OK    security_opt: no-new-privileges:true"
    else
        echo "  FAIL  missing security_opt: no-new-privileges:true"
        FAILED=1
    fi

    # Match '- ALL' as a list item under cap_drop. Tolerate leading spaces.
    if grep -qE "^[[:space:]]*-[[:space:]]*ALL[[:space:]]*$" <<<"$block"; then
        echo "  OK    cap_drop: [ALL]"
    else
        echo "  FAIL  missing cap_drop: [ALL]"
        FAILED=1
    fi

    if grep -q "privileged:[[:space:]]*true" <<<"$block"; then
        echo "  FAIL  privileged: true is forbidden"
        FAILED=1
    else
        echo "  OK    not privileged"
    fi

    echo
done

if [ "$FAILED" -ne 0 ]; then
    echo "Security check FAILED ($COMPOSE_FILE)"
    exit 1
fi

echo "Security check passed ($COMPOSE_FILE)"