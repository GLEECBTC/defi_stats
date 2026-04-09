#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
COINS_CACHE="${ROOT_DIR}/api/cache/coins/coins.json"
BOOTSTRAP_SCRIPT="${ROOT_DIR}/scripts/bootstrap_coins_cache.sh"

if [[ ! -f "${COINS_CACHE}" ]]; then
    echo "api/cache/coins/coins.json not found, bootstrapping cache..."
    "${BOOTSTRAP_SCRIPT}"
fi

echo "Starting Komodo DeFi (mm2)"
cd "${ROOT_DIR}"
docker compose stop
cat "${COINS_CACHE}" | jq .data > "${ROOT_DIR}/mm2/coins"
cat "${COINS_CACHE}" | jq .data > "${ROOT_DIR}/mm2_8762/coins"
cat "${COINS_CACHE}" | jq .data > "${ROOT_DIR}/mm2_6133/coins"
docker compose build
docker compose up -d 
docker compose logs -f --tail 23
