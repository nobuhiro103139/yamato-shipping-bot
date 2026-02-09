#!/bin/sh
set -e

if [ -n "$OP_SERVICE_ACCOUNT_TOKEN" ] && command -v op >/dev/null 2>&1; then
    echo "[entrypoint] 1Password CLI detected. Injecting secrets from vault..."
    exec op run --env-file=/app/.env.op --no-masking -- "$@"
else
    exec "$@"
fi
