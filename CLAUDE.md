# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DeFi Stats API — a FastAPI service that aggregates AtomicDEX (Komodo DeFi SDK) trading statistics and exposes them via REST endpoints compatible with CoinGecko, CoinMarketCap, and internal market consumers.

Production: https://defi-stats.komodo.earth/docs#/

## Common Commands

```bash
# Install dependencies
cd api && poetry install

# Run API (standalone)
./run_api.sh
# or: cd api && poetry run uvicorn main:app --host 0.0.0.0 --port 7068 --reload

# Run background cache processing loops
./run_cron.sh

# Run all tests with coverage
cd api && poetry run pytest -vv

# Run a single test file
cd api && poetry run pytest -vv tests/test_cache.py

# Run tests with coverage + lint
cd api && poetry run pytest -vv --cov --flake8

# Format code
cd api && poetry run black .

# Docker (recommended for full stack)
./scripts/bootstrap_coins_cache.sh  # one-time bootstrap
docker compose build
docker compose up -d
```

## Environment Setup

Copy and configure `api/.env` with:
- `API_PORT`, `API_HOST`, `API_USER`, `API_PASS`
- `NODE_TYPE`: `'dev'` (API + processing), `'serve'` (API only), `'process'` (processing only)
- `LOCAL_MM2_DB_PATH_7777` / `LOCAL_MM2_DB_PATH_8762` / `LOCAL_MM2_DB_PATH_6133` — paths to SQLite MM2 databases
- `LOCAL_MM2_DB_PATH_SEED` / `LOCAL_MM2_DB_PATH_SEED_6133` — paths to active MM2.db on host (from running containers)
- `DEXAPI_7777_HOST` / `DEXAPI_8762_HOST` / `DEXAPI_6133_HOST` and corresponding `_PORT` vars — Komodo DeFi RPC endpoints
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DATABASE`, `POSTGRES_PASSWORD`
- `FIXER_API_KEY` — for FX rates
- `COINS_CONFIG_URL`, `COINS_URL` — KomodoPlatform coins repo URLs

## Architecture

### Data Flow

```
MM2 Nodes (SQLite DBs, RPC ports 7877/7862/7783)
    ↓
lib/dex_api.py  (HTTP JSON-RPC)
    ↓
lib/cache_calc.py  (aggregation/transformation)
    ↓
Memcached + JSON files (api/cache/*/) + PostgreSQL
    ↓
FastAPI routes (api/routes/*)  →  REST API at /api/v3/*
```

### Key Concepts

- **Pairs** are stored as `{COIN-PROTOCOL}_{COIN-PROTOCOL}` in the DB (e.g., `KMD-UTXO_LTC-segwit`) and exposed as `{TICKER}_{TICKER}` (e.g., `KMD_LTC`).
- **Pair ordering** follows market cap: higher mcap coin = quote.
- **Trade types**: BUY, SELL, ALL — from the maker's perspective.
- **Pair inversion**: any pair can be requested as `ABC_XYZ` or `XYZ_ABC`; the API handles both.
- **NetIDs**: 7777 (legacy), 8762, 6133 (primary); separate MM2 instances and SQLite DBs for each.

### Background Cache Loops

`routes/cache_loop.py` uses `@repeat_every()` to refresh all cache items every 300–900 seconds. Cache items include: orderbooks, 24hr/14d/alltime volumes, prices, CoinGecko/CMC-compatible data. The startup event initializes all caches.

### Route Modules (`api/routes/`)

| Module | Prefix | Purpose |
|--------|--------|---------|
| `gecko.py` | `/api/v3/gecko/` | CoinGecko-compatible endpoints |
| `cmc.py` | `/api/v3/cmc/` | CoinMarketCap-compatible endpoints |
| `markets.py` | `/api/v3/markets/` | Legacy markets.atomicdex.io |
| `stats_api.py` | `/api/v3/stats-api/` | Legacy stats-api.atomicdex.io |
| `prices.py` | `/api/v3/prices/` | Price/ticker data |
| `pairs.py` | `/api/v3/pairs/` | Pair metadata |
| `swaps.py` | `/api/v3/swaps/` | Swap history |
| `cache_loop.py` | — | Background cache refresh tasks |

### Important Modules

- `api/const.py` — All env vars loaded as module-level constants; controls feature flags like `NODE_TYPE`, `MEMCACHE_LIMIT`, DB paths.
- `api/lib/pair.py` — `Pair` class: historical trades, volume calculations, inversion logic.
- `api/lib/cache.py` + `lib/cache_calc.py` — Pre-compute aggregated data; feeds memcached and JSON cache files.
- `api/util/transform.py` (62KB) — Pair normalization, sorting, inversion, format conversions.
- `api/util/memcache.py` — Memcached client wrapper with connection pooling.
- `api/db/sqlitedb.py` — SQLite queries against local MM2.db files.
- `api/db/sqldb.py` — PostgreSQL/MySQL connector.
- `api/db/schema.py` — SQLModel ORM schemas (`DefiSwap`, etc.).

## Testing Notes

- Tests live in `api/tests/`; fixtures in `api/tests/fixtures/`.
- `IS_TESTING=True` is set automatically via `api/setup.cfg` pytest env.
- Memcache is flushed after each test session (`api/conftest.py`).
- Linting (flake8) is integrated into pytest runs.
- Max line length: 99 chars; max docstring length: 74 chars.
- Coverage omits: `const.py`, `mm2/*`, `deprecated/*`, `DB/*`, `logger.py`, `main.py`.

## Database

- **SQLite (MM2.db)**: Source of swap history from AtomicDEX seed nodes. Synced via `./scripts/import_dbs.sh`. Files live in `api/db/local/`, `api/db/master/`, `api/db/source/`.
- **PostgreSQL**: Long-term storage. Initialized via `api/docker-entrypoint-initdb.d/`. Backup: `./scripts/pg_backup.sh`; restore: `./scripts/pg_restore.sh`.
- **Memcached**: Port 11211, 500MB limit, 100MB max item size.

## Docker Services

| Service | Purpose | Port |
|---------|---------|------|
| `defi_stats` | FastAPI app | 7068 |
| `komodefi_8762` | MM2 node (netid 8762) | 7862 |
| `komodefi_6133` | MM2 node (netid 6133) | 7783 |
| `memcached` | Response cache | 11211 |
| `pgsqldb` | PostgreSQL 12.17 | 5432 |
