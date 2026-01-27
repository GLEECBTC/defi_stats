#!/usr/bin/env python3
import os
import sys
from decimal import Decimal
from starlette.datastructures import UploadFile as StarletteUploadFile
from dotenv import load_dotenv

load_dotenv()

# https://lightrun.com/solutions/troubleshooting-tiangolo-fastapi/
# keep the SpooledTemporaryFile in-memory
StarletteUploadFile.spool_max_size = 0

# [NODE_TYPE]
# Options:
# - dev: runs both api endpoints and database sourcing / processing
# - serve: runs only the api endpoints.
# - process: runs only the database sourcing / processing

# Database Creds
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_USERNAME = os.getenv("POSTGRES_USERNAME")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
POSTGRES_PORT = os.getenv("POSTGRES_PORT")
POSTGRES_DATABASE = os.getenv("POSTGRES_DATABASE")

MYSQL_HOSTNAME = os.getenv("MYSQL_HOST")
MYSQL_USERNAME = os.getenv("MYSQL_USERNAME")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD")
MYSQL_PORT = 3306
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE")


NODE_TYPE = os.getenv("NODE_TYPE") or "dev"
RESET_TABLE = os.getenv("RESET_TABLE") == "True"
DEVMODE = os.getenv("DEVMODE") == "True"


IN_DOCKER = os.getenv("IN_DOCKER")
if IN_DOCKER == "True":
    IN_DOCKER = True
else:
    IN_DOCKER = False


if IN_DOCKER:
    DEXAPI_7777_HOST = os.getenv("DEXAPI_7777_HOST")
    DEXAPI_8762_HOST = os.getenv("DEXAPI_8762_HOST")
else:
    DEXAPI_7777_HOST = "http://127.0.0.1"
    DEXAPI_8762_HOST = "http://127.0.0.1"
    POSTGRES_HOST = "127.0.0.1"


DEXAPI_7777_PORT = os.getenv("DEXAPI_7777_PORT")
DEXAPI_8762_PORT = os.getenv("DEXAPI_8762_PORT")

# Project path URLs
API_ROOT_PATH = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# FastAPI configuration
API_HOST = os.getenv("API_HOST") or "0.0.0.0"
API_PORT = int(os.getenv("API_PORT")) or 7068
API_USER = os.getenv("API_USER")  # For HTTPBasicAuth
API_PASS = os.getenv("API_PASS")  # For HTTPBasicAuth

# API Keys for 3rd Party Services
FIXER_API_KEY = os.getenv("FIXER_API_KEY") or ""
if not FIXER_API_KEY:
    print(
        "FIXER_API_KEY is not set in .env file. Without this, '/api/v3/rates/fixer_io' will fail."
    )

# Path of active MM2.db database for NetId 7777 running
# in this repos docker container [if NODE_TYPE is not 'process']
LOCAL_MM2_DB_PATH_7777 = os.getenv("LOCAL_MM2_DB_PATH_7777")
if LOCAL_MM2_DB_PATH_7777 is None and NODE_TYPE != "process":
    print("You need to set 'LOCAL_MM2_DB_PATH_7777' in api/.env")
    sys.exit()

# Path of active MM2.db database for NetId 8762 running
# in this repos docker container [if NODE_TYPE is not 'process']
LOCAL_MM2_DB_PATH_8762 = os.getenv("LOCAL_MM2_DB_PATH_8762")
if LOCAL_MM2_DB_PATH_8762 is None and NODE_TYPE != "process":
    print("You need to set 'LOCAL_MM2_DB_PATH_8762' in api/.env")
    sys.exit()

# Paths for backups of mm2 instances running in local docker container
DB_SOURCE_PATH = f"{PROJECT_ROOT_PATH}/api/db/source"
DB_CLEAN_PATH = f"{PROJECT_ROOT_PATH}/api/db/cleaned"
DB_MASTER_PATH = f"{PROJECT_ROOT_PATH}/api/db/master"
DB_LOCAL_PATH = f"{PROJECT_ROOT_PATH}/api/db/local"
LOCAL_MM2_DB_BACKUP_7777 = f"{DB_SOURCE_PATH}/local_MM2_7777.db"
LOCAL_MM2_DB_BACKUP_8762 = f"{DB_SOURCE_PATH}/local_MM2_8762.db"

# Paths for "master" databases, which import seed node databases
MM2_DB_PATH_ALL = f"{DB_MASTER_PATH}/MM2_all.db"
MM2_DB_PATH_7777 = f"{DB_MASTER_PATH}/MM2_7777.db"
MM2_DB_PATH_8762 = f"{DB_MASTER_PATH}/MM2_8762.db"
MM2_DB_PATH_SEED = f"{DB_LOCAL_PATH}/MM2_8762.db"
LOCAL_MM2_DB_PATH_SEED = os.getenv("LOCAL_MM2_DB_PATH_SEED")


# Database paths as a dict, for convenience
MM2_DB_PATHS = {
    "7777": MM2_DB_PATH_7777,
    "8762": MM2_DB_PATH_8762,
    "ALL": MM2_DB_PATH_ALL,
    "temp_ALL": f"{DB_CLEAN_PATH}/temp_MM2_ALL.db",
    "temp_7777": f"{DB_CLEAN_PATH}/temp_MM2_7777.db",
    "temp_8762": f"{DB_CLEAN_PATH}/temp_MM2_8762.db",
    "local_7777": LOCAL_MM2_DB_PATH_7777,
    "local_8762": LOCAL_MM2_DB_PATH_8762,
    "local_7777_backup": LOCAL_MM2_DB_BACKUP_7777,
    "local_8762_backup": LOCAL_MM2_DB_BACKUP_8762,
}

# KomodoPlatform DeFi API config.
MM2_RPC_PORTS = {
    "7777": int(DEXAPI_7777_PORT),
    "8762": int(DEXAPI_8762_PORT),
    "ALL": int(DEXAPI_8762_PORT),
}
MM2_RPC_HOSTS = {
    "7777": DEXAPI_7777_HOST,
    "8762": DEXAPI_8762_HOST,
    "ALL": DEXAPI_8762_HOST,
}
MM2_NETID = 8762  # The primary active NetId currently supported by KomodoPlatform

# Some coins may have swaps data, but are not currently in the coins repo.
CoinConfigNotFoundCoins = ["XEP", "MORTY", "RICK", "SMTF-v2"]

compare_fields = [
    "is_success",
    "started_at",
    "finished_at",
    "maker_coin_usd_price",
    "taker_coin_usd_price",
]

MARKETS_PAIRS_DAYS = 30
GENERIC_PAIRS_DAYS = 30

MEMCACHE_LIMIT = 500 * 1024 * 1024  # 500 MB
DEXAPI_USERPASS = os.getenv("DEXAPI_USERPASS")

ORDERBOOK_CACHE_MIN_TRADES = int(os.getenv("ORDERBOOK_CACHE_MIN_TRADES", "1"))
ORDERBOOK_CACHE_LOCK_TTL = int(os.getenv("ORDERBOOK_CACHE_LOCK_TTL", "30"))
ORDERBOOK_CACHE_WAIT_ATTEMPTS = int(os.getenv("ORDERBOOK_CACHE_WAIT_ATTEMPTS", "5"))
ORDERBOOK_CACHE_WAIT_INTERVAL = float(os.getenv("ORDERBOOK_CACHE_WAIT_INTERVAL", "0.2"))

ORDERBOOK_FETCH_BATCH_SIZE = int(os.getenv("ORDERBOOK_FETCH_BATCH_SIZE", "100"))
ORDERBOOK_FETCH_LOOP_SLEEP = float(os.getenv("ORDERBOOK_FETCH_LOOP_SLEEP", "0.5"))
ORDERBOOK_FETCH_PRIORITY_SIZE = int(os.getenv("ORDERBOOK_FETCH_PRIORITY_SIZE", "50"))
ORDERBOOK_FETCH_SWAP_WEIGHT = float(os.getenv("ORDERBOOK_FETCH_SWAP_WEIGHT", "1"))