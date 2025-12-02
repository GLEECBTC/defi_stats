#!/usr/bin/env python3
import time
from datetime import datetime, timedelta
from fastapi import APIRouter
from fastapi_utils.tasks import repeat_every
from const import NODE_TYPE
import db.sqldb as db
import db.sqlitedb_merge as old_db_merge
import util.defaults as default
import util.memcache as memcache
from lib.cache import Cache, CacheItem, reset_cache_files
from lib.cache_calc import CacheCalc
from lib.dex_api import DexAPI
from util.cron import cron
from util.logger import logger, timed

router = APIRouter()





@router.on_event("startup")
@repeat_every(seconds=900)
@timed
def check_cache():  # pragma: no cover
    """Checks when cache items last updated"""
    try:
        cache = Cache()
        cache.healthcheck(to_console=True)
        memcache_stats = memcache.stats()
        for k, v in memcache_stats.items():
            # https://github.com/memcached/memcached/blob/master/doc/protocol.txt#L1270-L1421
            default.memcache_stat(
                msg=f"{k.decode('UTF-8'):<30}: {v}", loglevel="cached"
            )
    except Exception as e:
        return default.result(msg=e, loglevel="warning")


@router.on_event("startup")
@timed
def init_missing_cache():  # pragma: no cover
    reset_cache_files()
    msg = "init missing cache loop complete!"
    return default.result(msg=msg, loglevel="loop", ignore_until=3)


# ORDERBOOKS CACHE
@router.on_event("startup")
@repeat_every(seconds=300)
@timed
def update_pairs_orderbook_extended():
    if memcache.get("testing") is None:
        try:
            # builds from variant caches and saves to file
            CacheItem(name="pairs_orderbook_extended").save()
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        msg = "pairs_orderbook_extended refresh loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


@router.on_event("startup")
@repeat_every(seconds=360)
@timed
def refresh_pairs_orderbook_extended():
    if memcache.get("testing") is None:
        try:
            # threaded to populate variant caches
            CacheCalc().pairs_orderbook_extended(refresh=True)
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        msg = "pairs_orderbook_extended refresh loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


# PRICES CACHE
@router.on_event("startup")
@repeat_every(seconds=420)
@timed
def refresh_prices_24hr():
    if memcache.get("testing") is None:
        try:
            CacheItem(name="pair_prices_24hr").save()
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        msg = "pair_prices_24hr refresh loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


# VOLUMES CACHE
@router.on_event("startup")
@repeat_every(seconds=390)
@timed
def get_coin_volumes_24hr():
    if memcache.get("testing") is None:
        try:
            CacheItem(name="coin_volumes_24hr").save()
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        msg = "coin_volumes_24hr refresh loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


@router.on_event("startup")
@repeat_every(seconds=450)
@timed
def get_pair_volumes_24hr():
    if memcache.get("testing") is None:
        try:
            CacheItem(name="pair_volumes_24hr").save()
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        msg = "pair_volumes_24hr refresh loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


@router.on_event("startup")
@repeat_every(seconds=1200)
@timed
def get_pair_volumes_14d():
    if memcache.get("testing") is None:
        try:
            CacheItem(name="pair_volumes_14d").save()
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        msg = "pair_volumes_14d refresh loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


@router.on_event("startup")
@repeat_every(seconds=1800)
@timed
def get_pair_volumes_alltime():
    if memcache.get("testing") is None:
        try:
            CacheItem(name="pair_volumes_alltime").save()
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        msg = "pair_volumes_alltime refresh loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


# LAST TRADE
@router.on_event("startup")
@repeat_every(seconds=380)
@timed
def pairs_last_traded():
    if memcache.get("testing") is None:
        try:
            CacheItem(name="pairs_last_traded").save()
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        msg = "pairs_last_traded loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


# MARKETS CACHE
@router.on_event("startup")
@repeat_every(seconds=480)
@timed
def get_markets_summary():
    if memcache.get("testing") is None:
        try:
            CacheItem(name="markets_summary").save()
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        msg = "markets_summary loop for memcache complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


@router.on_event("startup")
@repeat_every(seconds=240)
@timed
def prices_service():  # pragma: no cover
    if memcache.get("testing") is None:
        try:
            for i in ["prices_tickers_v1", "prices_tickers_v2"]:
                CacheItem(i).save()
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        msg = "Prices update loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


# EXTERNAL SOURCES CACHE
@router.on_event("startup")
@repeat_every(seconds=14400)
@timed
def coins():  # pragma: no cover
    if memcache.get("testing") is None:
        try:
            for i in ["coins_config", "coins"]:
                CacheItem(i).save()
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        return default.result(
            msg="Coins update loop complete!", loglevel="loop", ignore_until=5
        )


# VOLUMES CACHE
@router.on_event("startup")
@repeat_every(seconds=1800)
@timed
def get_coin_volumes_alltime():
    if memcache.get("testing") is None:
        try:
            CacheItem(name="coin_volumes_alltime").save()
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        msg = "coin_volumes_alltime refresh loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


@router.on_event("startup")
@repeat_every(seconds=540)
@timed
def gecko_data():  # pragma: no cover
    if memcache.get("testing") is None:
        try:
            CacheItem("gecko_source").save()
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        msg = "Gecko source data update loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


@router.on_event("startup")
@repeat_every(seconds=1800)
@timed
def gecko_pairs():  # pragma: no cover
    if memcache.get("testing") is None:
        try:
            CacheItem("gecko_pairs").save()
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        msg = "Gecko pairs data update loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


@router.on_event("startup")
@repeat_every(seconds=370)
@timed
def stats_api_summary():  # pragma: no cover
    if memcache.get("testing") is None:
        try:
            CacheItem("stats_api_summary").save()
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        msg = "stats_api_summary data update loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


@router.on_event("startup")
@repeat_every(seconds=375)
@timed
def cmc_summary():  # pragma: no cover
    if memcache.get("testing") is None:
        try:
            CacheItem("cmc_summary").save()
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        msg = "cmc_summary data update loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


@router.on_event("startup")
@repeat_every(seconds=90)
@timed
def cmc_assets_source():  # pragma: no cover
    if memcache.get("cmc_assets_source") is None:
        try:
            CacheItem("cmc_assets_source").save()
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        msg = "cmc_assets_source data update loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


@router.on_event("startup")
@repeat_every(seconds=75)
@timed
def cmc_assets():  # pragma: no cover
    if memcache.get("cmc_assets") is None:
        try:
            CacheItem("cmc_assets").save()
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        msg = "cmc_assets data update loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


@router.on_event("startup")
@repeat_every(seconds=320)
@timed
def fixer_rates():  # pragma: no cover
    if memcache.get("testing") is None:
        try:
            CacheItem(name="fixer_rates").save()
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        msg = "Fixer rates update loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


# DATABASE SYNC
@router.on_event("startup")
@repeat_every(seconds=310)
@timed
def populate_pgsqldb_loop():
    try:
        if memcache.get("testing") is None:
            # updates last 24 hours swaps
            today = datetime.today().date()
            db.SqlSource().import_swaps_for_day(today)
            yesterday = today - timedelta(days=1)
    except Exception as e:
        return default.result(msg=e, loglevel="warning")


@router.on_event("startup")
@repeat_every(seconds=350)
@timed
def import_dbs():
    if memcache.get("testing") is None:
        if NODE_TYPE != "serve":
            try:
                merge = old_db_merge.SqliteMerge()
                merge.import_source_databases()
            except Exception as e:
                return default.result(msg=e, loglevel="warning")
            msg = "Import source databases loop complete!"
            return default.result(msg=msg, loglevel="merge")
        msg = "Import source databases skipped, NodeType is 'serve'!"
        msg += " Masters will be updated from cron."
        return default.result(msg=msg, loglevel="merge")


@router.on_event("startup")
@repeat_every(seconds=3600)
@timed
def adex_alltime():
    if memcache.get("testing") is None:
        try:
            CacheItem(name="adex_alltime").save()
        except Exception as e:
            logger.warning(default.result(msg=e, loglevel="warning"))
        msg = "Adex alltime loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)

@router.on_event("startup")
@repeat_every(seconds=600)
@timed
def adex_weekly():
    if memcache.get("testing") is None:
        try:
            CacheItem(name="adex_weekly").save()
        except Exception as e:
            logger.warning(default.result(msg=e, loglevel="warning"))
        msg = "Adex fortnight loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)

@router.on_event("startup")
@repeat_every(seconds=900)
@timed
def adex_fortnite():
    if memcache.get("testing") is None:
        try:
            CacheItem(name="adex_fortnite").save()
        except Exception as e:
            logger.warning(default.result(msg=e, loglevel="warning"))
        msg = "Adex fortnight loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


@router.on_event("startup")
@repeat_every(seconds=300)
@timed
def adex_24hr():
    if memcache.get("testing") is None:
        try:
            CacheItem(name="adex_24hr").save()
        except Exception as e:
            logger.warning(default.result(msg=e, loglevel="warning"))
        msg = "Adex 24hr loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


# TICKERS
@router.on_event("startup")
@repeat_every(seconds=210)
@timed
def pair_tickers():
    if memcache.get("testing") is None:
        try:
            CacheItem(name="tickers").save()
        except Exception as e:
            return default.result(msg=e, loglevel="warning")
        msg = "pair_tickers loop complete!"
        return default.result(msg=msg, loglevel="loop", ignore_until=0)


# fix_swap_pairs
@router.on_event("startup")
@repeat_every(seconds=75)
@timed
def fix_swap_pairs():
    reset_cache_files()
    time.sleep(10)
    db.SqlUpdate().fix_swap_pairs(trigger="cache_loop")
