#!/usr/bin/env bash

set -euo pipefail

# Downloads the latest coins cache artifacts so run_mm2/run.sh have data even on
# a fresh checkout (files are gitignored).

FORCE_REFRESH=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)
            FORCE_REFRESH=1
            shift
            ;;
        *)
            echo "Usage: $0 [--force]" >&2
            exit 1
            ;;
    esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE_DIR="${REPO_ROOT}/api/cache/coins"
COINS_JSON="${CACHE_DIR}/coins.json"
COINS_CONFIG_JSON="${CACHE_DIR}/coins_config.json"

COINS_CACHE_URL="${COINS_CACHE_URL:-https://raw.githubusercontent.com/GLEECBTC/coins/master/coins}"
COINS_CONFIG_URL="${COINS_CONFIG_URL:-https://raw.githubusercontent.com/GLEECBTC/coins/master/utils/coins_config.json}"

mkdir -p "${CACHE_DIR}"

download_file() {
    local url="$1"
    local dest="$2"
    local label="$3"

    echo "Downloading ${label} from ${url}"
    tmp_file="$(mktemp)"
    curl -fsSL "${url}" -o "${tmp_file}"
    mv "${tmp_file}" "${dest}"
}

if [[ ! -f "${COINS_JSON}" || "${FORCE_REFRESH}" -eq 1 ]]; then
    download_file "${COINS_CACHE_URL}" "${COINS_JSON}" "coins cache"
else
    echo "Coins cache already exists at ${COINS_JSON} (use --force to refresh)"
fi

if [[ ! -f "${COINS_CONFIG_JSON}" || "${FORCE_REFRESH}" -eq 1 ]]; then
    download_file "${COINS_CONFIG_URL}" "${COINS_CONFIG_JSON}" "coins_config"
else
    echo "coins_config cache already exists at ${COINS_CONFIG_JSON} (use --force to refresh)"
fi

echo "Coin cache bootstrap complete."

