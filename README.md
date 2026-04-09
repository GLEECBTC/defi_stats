## A Simple API for AtomicDEX network statistics

**Currrent production URL:** https://defi-stats.komodo.earth/docs#/

The goal of this project is to provide all required data from the Komodo DeFi DEX network to match the required formats for a variety of target consumers:
- [CoinGecko](https://docs.google.com/document/d/1v27QFoQq1SKT3Priq3aqPgB70Xd_PnDzbOCiuoCyixw/edit?usp=sharing)
- [CMC](https://docs.google.com/document/d/1S4urpzUnO2t7DmS_1dc4EL4tgnnbTObPYXvDeBnukCg/edit#)
- https://markets.atomicdex.io/

Data is sourced from the [Komodo DeFi API's SQLite database](https://developers.komodoplatform.com/basic-docs/atomicdex/atomicdex-tutorials/query-the-mm2-database.html#my-swaps). It is calculated and then stored in json files in the `cache/`folder every 5 minutes (or less). API endpoints then serve the data from these files (to reduce API endpoint response times).

![image](https://github.com/KomodoPlatform/defi_stats/assets/35845239/106973e9-72ca-4486-9fc5-ce7e7e1bfe57)

Data is also imported into more robust databases (mySQL, postgresSQL/Timescale & dGraph) for future reference and to alow more complex queries over a longer timeframe.


### Install requirements

Run the `setup.sh` script to install python3.10, docker, docker-compose, and poetry. The steps to do this manually are below for reference, but if the script returns no errors, you can skip ahead to the `Database setup` section.


#### Apt dependencies

    sudo apt update
    sudo apt install postgresql postgresql-contrib build-essential python3-dev python3-psycopg2 libpq-dev libmysqlclient-dev default-libmysqlclient-dev pkg-config python-dev-is-python3 libffi-dev
    # On Ubuntu 24.04+, python-dev was replaced by python-dev-is-python3.
    # libffi-dev is required to build cffi (_cffi_backend) for packages such as cryptography/secretstorage.

#### Install python3.10

    If not already available https://rayflare.readthedocs.io/en/stable/Installation/python_install.html
    `sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1`
    `sudo update-alternatives --config python3`
    Confirm with `which python3` or `python3 -V`
    Install pip `curl -sS https://bootstrap.pypa.io/get-pip.py | python3`
    Install pipx with `python3 -m pip install --user pipx && python3 -m pipx ensurepath`
    Install [poetry](https://python-poetry.org/docs/) with `pipx install poetry`
    Add `~/.local/bin` to your PATH so poetry and other tools are available:
    `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc`
    Poetry tries to talk to the system keyring by default. On minimal servers without SecretStorage support, disable it with `poetry config keyring.enabled false`.


#### Install Docker

Refer to https://www.digitalocean.com/community/tutorials/how-to-install-and-use-docker-on-ubuntu-20-04 to install docker
Refer to https://docs.docker.com/compose/install/linux/#install-using-the-repository to install docker compose


#### Setup mm2

- Create `mm2/.env`, `mm2_8762/.env` and `mm2_6133/.env` with the following inside (change the userpass; `mm2_6133` is the primary node)
```
MM_CONF_PATH=/home/komodian/mm2/MM2.json
MM_COINS_PATH=/home/komodian/mm2/coins
MM_LOG=/home/komodian/mm2/mm2.log
USERPASS=RPC_CONTRoL_USERP@SSW0RD
USER_ID=1000
GROUP_ID=1000
```
- Next, create `mm2/MM2.json`, `mm2_8762/MM2.json` and `mm2_6133/MM2.json`. Use the templates in each folder - `cp mm2/MM2.template.json mm2/MM2.json`. Change the passphrases.

- Get the latest coins file for each mm2 folder with `wget https://raw.githubusercontent.com/GLEECBTC/coins/master/coins`

#### Bootstrap cache files

The files inside `api/cache/coins/` are `.gitignore`'d. On a new server run `./scripts/bootstrap_coins_cache.sh` (pass `--force` to refresh) to download `coins.json` and `coins_config.json` before invoking `run_mm2.sh` or `docker compose`. The script respects the `COINS_CACHE_URL` and `COINS_CONFIG_URL` env vars if you need to point at a different data source.

#### Database setup

    sudo systemctl stop postgresql.service  # this will run in docker, so we disable on host to avoid port conflicts

    # Optionally, to run on host:
    # https://www.digitalocean.com/community/tutorials/how-to-install-and-use-postgresql-on-ubuntu-18-04
    # sudo -u postgres createuser --interactive
    # sudo -u postgres createdb stats_swaps
    # sudo -u postgres psql
    # ALTER USER postgres PASSWORD 'myPassword';
    # Update .env with creds (see readme after TODO: update)


    cd ~/defi_stats/api
    git stash
    git pull
    poetry install

- Then execute `./run_mm2.sh` to initialise the mm2 databases. You will need to find the path to the MM2.db file in each folder to input below. This script will tail the logs, but you can `ctl-c` to exit without stopping the service.

- Create `api/.env` file containing the following variables:

```
# DEPENDENCY VERSIONS
POETRY_VERSION='1.7.1'

# Use `serve` for front end. Any other value will do database merge and processing.
NODE_TYPE='serve'

# FastAPI
API_PORT=7068
API_HOST='0.0.0.0'
API_USER="komodian"
API_PASS="api_password"


# API KEYS
FIXER_API_KEY=your_key

# DATABASES

## External MySQL source DB
mysql_hostname="db_IP"
mysql_username="db_username"
mysql_password="db_password"
MYSQL_DATABASE="db_name"

## Postgres/TimescaleDB
POSTGRES_HOST=pgsqldb
POSTGRES_PORT=5432
POSTGRES_DATABASE=db_name
PGDATA=/var/lib/postgresql/data
MYSQL_USERNAME=db_user
POSTGRES_PASSWORD=db_pass

## Sqlite
LOCAL_MM2_DB_PATH_7777="/home/komodian/api/db/local/MM2_7777.db"
LOCAL_MM2_DB_PATH_8762="/home/komodian/api/db/local/MM2_8762.db"
LOCAL_MM2_DB_PATH_6133="/home/komodian/api/db/local/MM2_6133.db"
HOST_LOCAL_MM2_DB_PATH_7777="/home/hound/defi_stats/api/db/local/MM2_7777.db"
HOST_LOCAL_MM2_DB_PATH_8762="/home/hound/defi_stats/api/db/local/MM2_8762.db"
HOST_LOCAL_MM2_DB_PATH_6133="/home/hound/defi_stats/api/db/local/MM2_6133.db"
LOCAL_MM2_DB_PATH_SEED="/home/komodian/mm2/DB/43ec929fe30ee72be42c9162c56dde910a05e50d/MM2.db"
LOCAL_MM2_DB_PATH_SEED_6133="/home/komodian/mm2_6133/DB/43ec929fe30ee72be42c9162c56dde910a05e50d/MM2.db"

# Komodo DeFi (hosts below are docker services, set to 127.0.0.1 if not using docker)
DEXAPI_7777_HOST="http://komodefi"
DEXAPI_8762_HOST="http://komodefi_8762"
DEXAPI_6133_HOST="http://komodefi_6133"
DEXAPI_7777_PORT="7877"
DEXAPI_8762_PORT="7862"
DEXAPI_6133_PORT="7783"


# AtomicDEX API
COINS_CONFIG_URL='https://raw.githubusercontent.com/GLEECBTC/coins/master/utils/coins_config.json'
COINS_URL='https://raw.githubusercontent.com/GLEECBTC/coins/master/coins'

```

Edit the values for your paths and passwords etc. Some of these are not curently in us in main branch, but will be used later.

Finally, we can build the containers.

    docker compose build
    docker compose up

## Postgres backups and restores

- Make sure the stack is up (`docker compose up -d`) so the `pgsqldb` service is running.
- Create a dump that contains every table in the configured database:

        ./scripts/pg_backup.sh

  A timestamped `.dump` file is written to `backups/postgres/`. Use `-o` to change the output directory, `-e` to point at a different `.env`, or `-c` if you renamed the database service.

- Transfer the dump to the target host (for example with `scp`) and run the restore once the new stack is up:

        ./scripts/pg_restore.sh -f /path/to/backup.dump

  The script loads credentials from `api/.env`, pipes the dump into `pg_restore`, and replaces the existing schema (`--clean --if-exists`). Use `-p` to run the docker compose command from another directory, or `-c` to target a different service name.


# Sourcing data

- To ensure data integrity, past swaps are sourced from several long running Seed Nodes. This is periodically sourced via rsync with `./import_dbs.sh` (assuming ssh key access). This script should be added to cron to check for updates every minute. E.g. `* * * * * /home/USERNAME/defi_stats/api/db/source/import_dbs.sh`


### Running the API
From the project root folder, execute `./run_api.sh`.
Optionally, use the `defi-stats.service` file as a template to let systemd to manage the defi stats service.

## Testing

You may need to install pytest: `sudo apt install python-pytest`

From the `api` folder:
- To test everything: `poetry run pytest -vv`
- To test a specific file: `poetry run pytest -vv tests/test_file.py`



## Warning
Some data is cached with memcache. if the size of this data grows too large, it might fail to enter the cache. It should be split into smaller parts. See https://github.com/memcached/memcached/wiki/ConfiguringServer for configuration.


## Known Issues
To speed up the orderbook request loop, the requests are sent in separate threads which update the memcache. As a result, the first request for an orderbook may return a template rather than actual result. 

To mitigate this there are a few options:
- send a second request after a 3 second delay (kind of makes the threading speed up pointless, though waiting for one item could also give others later in the loop time to populate)
- Increase the orderbook loop frequency (this will reduce returned template chance, but can still happen for first request after cache expiry)
- Use a `no_cache` param for `run_every` functions so that background processing never uses existing cache. Alongside a loop frequency less than expiry time, this should ensure a persistantly populated cache at the expense of additional processing.
- Use a `no_thread` param for endpoint functions to avoid consumers receving a template where data should exist. This will be slightly less responsive when cache is empty, but will return valid data. This will update the cache along the way, but cant be relied on to keep the cache updated as consumer initiated requests is unpredictable.


## Endpoints

All endpoints for this update will have a `api/v3/` prefix. Swagger docs are available at https://192.168.0.1:7766/docs#/ (replace with domain/IP address when deployed).

For [CoinGecko](https://www.coingecko.com/) endpoints, we are using the prefix `api/v3/gecko/`
Endpoints previously at http://stats.testchain.xyz/ have been migrated to the prefix `api/v3/markets/`
Endpoints previously at https://stats-api.atomicdex.io/ have been migrated to the prefix `api/v3/stats-api/`

## Data completeness
Add `* * * * * /home/USERNAME/defi_stats/update_MM2_db.sh > /home/atomic/logs/db_update.log` to the crontab of the server you are running this api on to collect a variety of MM2.db files on varying netids, and to cover any missing data from swaps completed during server downtime. SSH key access is required.

This will place the external MM2.db copies into the `defi_stats/DB` folder, which is then periodically scanned, with all data merged into `defi_stats/DB/{netid}_MM2.db` for each netid, and `defi_stats/DB/all_MM2.db` for the complete picture.


## TODOs:

- Create table for liquidity to track it over time. Should be updated every hour, with any rows older than 1 day reduced into a single row of average values for the day.
| id | pair | base_amount | quote_amount | base_price_usd | quote_price_usd | base_liquidity_usd | quote_liquidity_usd | combined_liquidity | timestamp | updated_at |

- Equivalent view for volumes can be derived from the `defi_swaps` table

- Migrate gui/version/pubkey related views/queries from kmd.stats.io

- Additional endpoints for use in apps:
    - Dex Resilience alerts for newsfeed.
    - "Trending pairs" and similar network context stats
    - Automated "Latest release" link / hash for all apps.

### On Update:
- Run `poetry install` in the `api/` folder to update any deps.
- If changes to DB, edit `.env` to uncomment `# RESET_TABLE=True` then launch. After launch, disable this again and restart. It will clear the db data and reload the table with new schema.



### TODOs:

#### Supplemental data sources:
 - https://data.chain.link/feed
 - this is how the eth_call looks like: https://github.com/cipig/mmtools/blob/master/mpm/mpm#L337 
 - the price is in sats and is a hex, so need to be "converted" before use: https://github.com/cipig/mmtools/blob/master/mpm/mpm#L2372-L2374

#### Poetry version install

curl -sSL https://install.python-poetry.org | POETRY_VERSION=1.7.1 python3 -
