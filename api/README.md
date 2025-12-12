## A Simple API for AtomicDEX network statistics

**Currrent production URL:** https://defi-stats.komodo.earth/docs#/

The goal of this project is to provide all required data from the Komodo DeFi DEX network to match the required formats for [CoinGecko](https://docs.google.com/document/d/1v27QFoQq1SKT3Priq3aqPgB70Xd_PnDzbOCiuoCyixw/edit?usp=sharing)

Data is sourced from the [Komodo DeFi API's SQLite database](https://developers.komodoplatform.com/basic-docs/atomicdex/atomicdex-tutorials/query-the-mm2-database.html#my-swaps). It is calculated and then stored in json files in the `cache/`folder every 5 minutes (or less). API endpoints then serve the data from these files (to reduce API endpoint response times).

![image](https://user-images.githubusercontent.com/24797699/109954887-7030db00-7d14-11eb-9b4d-b384082c0705.png)


### Setup and requirements

- Run `./setup.sh` to generate `mm2/.env`, and install poetry dependencies
- Create `api/.env` file containing the following variables:

```
# FastAPI
API_PORT=8088
API_HOST='0.0.0.0'

# AtomicDEX API
API_PORT=7068
API_HOST='127.0.0.1'
POETRY_VERSION='1.6.1'

# GitHub Releases (required for /api/v3/dex_version)
GH_USER='your_github_username'
GH_TOKEN='github_pat_or_token_with_repo_scope'
```
- A maintained MM2.db file, ideally sourced from a long running AtomicDEX-API seed node to ensure all data is included. This is periodically sourced via rsync with `./update_MM2.db` (assuming ssh key access). This should be added to cron to check for updates every minute. E.g. `* * * * * /home/admin/defi_stats/update_MM2_db.sh`


### Running the API
From the project root folder, execute `./run.sh`.
Optionally, use the `defi-stats.service` file as a template to let systemd to manage the defi stats service.

## Testing
From the `api` folder:
- To test everything: `pytest -vv`
- To test a specific file: `pytest -vv tests/test_file.py`

## Endpoints

All endpoints for this update will have a `api/v3/` prefix. Swagger docs are available at https://192.168.0.1:7766/docs#/ (replace with domain/IP address when deployed).

For gecko endpoints, we are using the prefix `api/v3/gecko/`

## Repository Branch Structure

To reduce the load of data sourcing and processing, two main branches will be maintained: `main-processing` and `main-serve`, with the associated development branches `dev-processing` and `dev-serve`.

These should be deployed on separate servers


## Deprecating API domains
The following APIs domains have been merged into this repo. They will be (or already have been) deprecated soon. Until then, the data returned from these domains is a mirror of the data in thi repository.
- https://stats-api.atomicdex.io/docs
- https://nomics.komodo.earth:8080/api/v1/info
- https://stats.testchain.xyz:8080/api/v1/summary

These should be consolidated in this repo at some point. They are based on branches of https://github.com/KomodoPlatform/dexstats_sqlite_py

## Dashboards using this API
- https://coinpaprika.com/exchanges/atomicdex/
- https://www.coingecko.com/en/exchanges/komodo-wallet
- https://markets.atomicdex.io/


## Notes
- Pairs are expressed as a string delimited by `_`, and ordered by market cap (or alphabetically where neither coin has a mcap value). To handle potential maker/taker inversion for the pair, an extra field in db was added to assign trade type as "buy" or "sell".
- Coin tickers are expressed as `COIN-PROTOCOL`. In some cases, the "protocol" field is `segwit`. This suffix should be removed and data merged (e.g. LTC & LTC-segwit == LTC) before responding to endpoint requests.
- Some consumers want no protocol suffix, and to have all tokens data merged. To facilitate this, any aggregate data from the DB should be categorised as below:
    {
        "coin": "USDC",
        "start_time": 1705238147,
        "end_time": 1705324547,
        "range_days": 1,
        "trade_type": "all",
        "data": {
            "USDC-AVX20": 0,
            "USDC-AVX20_OLD": 0,
            "USDC-ERC20": 0,
            "USDC-BEP20": 12.356005570915247,
            "USDC-FTM20": 0,
            "USDC-HCO20": 0,
            "USDC-KRC20": 0,
            "USDC-MVR20": 0,
            "USDC-PLG20": 207.8573098306688,
            "USDC-PLG20_OLD": 0,
            "USDC-ALL": 220.21331540158405
        }
    },
    {
        "coin": "LTC",
        "start_time": 1705238147,
        "end_time": 1705324547,
        "range_days": 1,
        "trade_type": "all",
        "data": {
            "LTC": 0.016497480406290333,
            "LTC-segwit": 1.010765441602137,
            "LTC-ALL": 1.0272629220084273
        }
    }
- The `-ALL` suffix is used for the combined sum of all variants.


- Given a pair XXX_YYY, we assume XXX is base and YYY is quote with higher marketcap. The pair value in DB is mcap sorted, so XXX_YYY is the `standard pair`.
- If maker is XXX and taker is YYY, its a BUY
- If maker is YYY and taker is XXX, its a SELL
- XXX is the BASE, and YYY is the QUOTE (or rel/target)
- Price should always be expressed as BASE volume / QUOTE volume

For the inverted pair `YYY_XXX`, an inversion of the data above is returned, after a transformation where:
- BUY becomes SELL and vice versa.
- BASE becomes QUOTE (or rel/target) and vice versa.
- Price becomes 1/price


## Diverting heavy use endpoints to upstream cache

A flood of calls to specific endpoints e.g. `api/v3/prices/tickers_v2` can result in server being unresponsive for other endpoints.
To mitigate this the domain `cache.defi-stats.komodo.earth` was created to offload these requests. To activate it, the following needs to be added to nginx server block on `defi-stats.komodo.earth`:

```
upstream cache_servers {
    server cache.defi-stats.komodo.earth;
}

server {
    ...
    location /api/v3/prices/tickers_v2 {
        proxy_pass http://cache_servers/api/v3/prices/tickers_v2.json;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

The same process can be repeated for any other offending endpoints. In the case of `tickers_v2` it is hardcoded into the api and the legacy desktop codebase, so usage increases in proportion to active users. Additional cache servers can be added to the upstream block as required to scale this to requirements. (e.g. `cache2.defi-stats.komodo.earth` etc.)

To populate these cache servers, add an rsync to crontab like `* * * * * /usr/bin/rsync username@defi-stats.komodo.earth:/home/username/defi_stats/api/cache/prices/tickers_v2_cache.json /var/www/cache.defi-stats.komodo.earth/api/v3/prices/tickers_v2.json`

Then create the following nginx serverblock on the `cache.defi-stats.komodo.earth` server:

```
server {
    listen 80;
    listen [::]:80;
    server_name cache.defi-stats.komodo.earth;
    return 301 https://cache.defi-stats.komodo.earth$request_uri;
}

server {
    listen [::]:443 ssl; # managed by Certbot
    listen 443 ssl; # managed by Certbot
    root /var/www/cache.defi-stats.komodian.info;
    index index.html;
    server_name cache.defi-stats.komodo.earth;
    ssl_certificate /etc/letsencrypt/live/cache.defi-stats.komodo.earth/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/cache.defi-stats.komodo.earth/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot

    location /api/v3/prices/tickers_v2/ {
         alias /var/www/cache.defi-stats.komodo.earth/api/v3/prices/tickers_v2.json;
    }

    location / {
        autoindex on;

        alias /var/www/cache.defi-stats.komodo.earth/;

        if ($request_method = 'OPTIONS') {
            add_header 'Access-Control-Allow-Origin' '*';
            add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS';
            #
            # Custom headers and headers various browsers *should* be OK with but aren't
            #
            add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range';
            #
            # Tell client that this pre-flight info is valid for 20 days
            #
            add_header 'Access-Control-Max-Age' 1728000;
            add_header 'Content-Type' 'text/plain; charset=utf-8';
            add_header 'Content-Length' 0;
            return 204;
        }

        if ($request_method = 'POST') {
            add_header 'Access-Control-Allow-Origin' '*';
            add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS';
            add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range';
            add_header 'Access-Control-Expose-Headers' 'Content-Length,Content-Range';
        }

        if ($request_method = 'GET') {
            add_header 'Access-Control-Allow-Origin' '*';
            add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS';
            add_header 'Access-Control-Allow-Headers' 'DNT,User-Agent,X-Requested-With,If-Modified-Since,Cache-Control,Content-Type,Range';
            add_header 'Access-Control-Expose-Headers' 'Content-Length,Content-Range';
        }
    }
}

```

# Update db and generalisation progress
- [] generic pairs => [markets, gecko, xyz]
