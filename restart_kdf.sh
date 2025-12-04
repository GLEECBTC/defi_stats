#!/bin/bash

# This script is used to restart the Komodo DeFi (kdf) services
# If not restarted periodically, KDF cpu usage can spike to 100%
# Add this to cron and run every hour

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "${ROOT_DIR}"
/usr/bin/docker compose restart komodefi_8762

