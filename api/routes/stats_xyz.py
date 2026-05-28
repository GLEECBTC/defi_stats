#!/usr/bin/env python3
from datetime import datetime, timedelta
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from typing import Dict, List
from lib.pair import Pair
from lib.cache_calc import CacheCalc
from models.generic import ErrorMessage
from models.stats_xyz import (
    StatsXyzOrderbookItem,
    StatsXyzTickerItem,
    StatsXyzSwaps24,
    StatsXyzTrades,
    StatsXyzTickerSummary,
    StatsXyzUsdVolume,
    StatsXyzAtomicdexIo,
    StatsXyzLiquidity,
    StatsXyzSummary,
)
from routes.metadata import stats_xyz_desc
from util.cron import cron
from util.enums import TradeType
from util.logger import logger
from util.exceptions import BadPairFormatError
from util.transform import sortdata, deplatform, invert
import db.sqldb as db
import util.memcache as memcache
import util.transform as transform
import util.validate as validate


router = APIRouter()


# TODO: Move to new DB
@router.get(
    "/atomicdexio",
    description=stats_xyz_desc.atomicdexio,
    response_model=StatsXyzAtomicdexIo,
    responses={406: {"model": ErrorMessage}},
    status_code=200,
)
def atomicdex_info_api():
    # TODO: Use new DB
    query = db.SqlQuery()
    return query.swap_counts()


# New endpoint
@router.get(
    "/current_liquidity",
    description=stats_xyz_desc.current_liquidity,
    response_model=StatsXyzLiquidity,
    responses={406: {"model": ErrorMessage}},
    status_code=200,
)
def current_liquidity():
    try:
        data = memcache.get_tickers()
        return {"current_liquidity": data["combined_liquidity_usd"]}

    except Exception as e:  # pragma: no cover
        logger.warning(f"{type(e)} Error in [/api/v3/markets/current_liquidity]: {e}")
        return {"error": f"{type(e)} Error in [/api/v3/markets/current_liquidity]: {e}"}


@router.get(
    "/fiat_rates",
    description=stats_xyz_desc.fiat_rates,
    responses={406: {"model": ErrorMessage}},
    status_code=200,
)
def fiat_rates():
    return memcache.get_gecko_source()


@router.get(
    "/orderbook/{pair_str}",
    description=stats_xyz_desc.orderbook,
    responses={406: {"model": ErrorMessage}},
    response_model=Dict[str, StatsXyzOrderbookItem],
    status_code=200,
)
def orderbook(pair_str: str = "KMD_LTC", depth: int = 100):
    try:
        gecko_source = memcache.get_gecko_source()
        # Where a non standard pair is requested
        # we need to invert some values.
        is_reversed = pair_str != sortdata.pair_by_market_cap(
            pair_str, gecko_source=gecko_source
        )
        if is_reversed:
            pair = Pair(pair_str=invert.pair(pair_str))
            data = pair.orderbook(
                pair_str=invert.pair(pair_str)
            )
        else:
            pair = Pair(pair_str=pair_str)
            data = pair.orderbook(
                pair_str=pair_str, depth=depth
            )

        resp = data["ALL"]
        if is_reversed:
            resp = invert.pair_orderbook(resp)
        resp["newest_price"] = resp["newest_price_24hr"]
        resp["volume_usd_24hr"] = resp["trade_volume_usd"]
        resp["oldest_price"] = resp["oldest_price_24hr"]
        resp["variants"] = sorted(list(set(data.keys())))
        return {pair_str: resp}
    except Exception as e:  # pragma: no cover
        err = {"error": f"{e}"}
        logger.warning(err)
        return JSONResponse(status_code=400, content=err)


# Migrated from https://stats.testchain.xyz/api/v1/summary
@router.get(
    "/summary",
    description=stats_xyz_desc.summary,
    responses={406: {"model": ErrorMessage}},
    response_model=List[StatsXyzSummary],
    status_code=200,
)
def summary():
    try:
        data = memcache.get_pairs_orderbook_extended()
        resp = []
        for depair in data["orderbooks"]:
            if "ALL" not in data["orderbooks"][depair]:
                continue
            resp.append(
                transform.ticker_to_xyz_summary(data["orderbooks"][depair]["ALL"])
            )
        return resp
    except Exception as e:  # pragma: no cover
        logger.warning(f"{type(e)} Error in [/api/v3/stats_xyz/tickers]: {e}")
        return {"error": f"{type(e)} Error in [/api/v3/stats_xyz/tickers]: {e}"}


# Migrated from https://stats.testchain.xyz/api/v1/summary_for_ticker/KMD
@router.get(
    "/summary_for_ticker/{coin}",
    description=stats_xyz_desc.summary_for_ticker,
    responses={406: {"model": ErrorMessage}},
    response_model=List[StatsXyzSummary],
    status_code=200,
)
def summary_for_ticker(coin: str = "KMD"):
    # TODO: Segwit not merged in this endpoint yet
    try:
        data = memcache.get_pairs_orderbook_extended()
        resp = []
        decoin = deplatform.coin(coin)
        for depair in data["orderbooks"]:
            if "ALL" not in data["orderbooks"][depair]:
                continue
            item = data["orderbooks"][depair]["ALL"]
            if decoin in [item["base"], item["quote"]]:
                resp.append(transform.ticker_to_xyz_summary(item))
        return resp
    except Exception as e:  # pragma: no cover
        logger.warning(
            f"{type(e)} Error in [/api/v3/stats_xyz/summary_for_ticker]: {e}"
        )
        return {
            "error": f"{type(e)} Error in [/api/v3/stats_xyz/summary_for_ticker]: {e}"
        }


@router.get(
    "/swaps24/{coin}",
    description=stats_xyz_desc.swaps24,
    responses={406: {"model": ErrorMessage}},
    response_model=StatsXyzSwaps24,
    status_code=200,
)
def swaps24(coin: str = "KMD") -> dict:
    # TODO: Lower than xyz source. Is it combined?
    try:
        data = memcache.get_coin_volumes_24hr()
        decoin = deplatform.coin(coin)
        if decoin in data["volumes"]:
            item = data["volumes"][decoin]["ALL"]
            return {
                "ticker": coin,
                "swaps_amount_24h": item["total_swaps"],
                "volume": item["total_volume"],
                "volume_usd": item["trade_volume_usd"],
            }
        return {
            "ticker": coin,
            "swaps_amount_24h": 0,
            "volume": 0,
            "volume_usd": 0,
        }
    except Exception as e:  # pragma: no cover
        logger.warning(f"{type(e)} Error in [/api/v3/stats_xyz/swaps24]: {e}")
        return {"error": f"{type(e)} Error in [/api/v3/stats_xyz/swaps24]: {e}"}


@router.get(
    "/ticker",
    description=stats_xyz_desc.ticker,
    response_model=List[Dict[str, StatsXyzTickerItem]],
    status_code=200,
)
def ticker():
    try:
        c = CacheCalc()
        return c.tickers_lite(depaired=True)
    except Exception as e:  # pragma: no cover
        logger.warning(f"{type(e)} Error in [/api/v3/stats_xyz/ticker]: {e}")
        return {"error": f"{type(e)} Error in [/api/v3/stats_xyz/ticker]: {e}"}


@router.get(
    "/ticker_for_ticker",
    description=stats_xyz_desc.ticker_for_ticker,
    response_model=List[Dict[str, StatsXyzTickerItem]],
    status_code=200,
)
def ticker_for_ticker(ticker):
    try:
        c = CacheCalc()
        return c.tickers_lite(coin=ticker, depaired=True)

    except Exception as e:  # pragma: no cover
        logger.warning(f"{type(e)} Error in [/api/v3/stats_xyz/ticker_for_ticker]: {e}")
        return {
            "error": f"{type(e)} Error in [/api/v3/stats_xyz/ticker_for_ticker]: {e}"
        }


@router.get(
    "/tickers_summary",
    description=stats_xyz_desc.tickers_summary,
    response_model=Dict[str, StatsXyzTickerSummary],
    status_code=200,
)
def tickers_summary():
    try:
        data = memcache.get_coin_volumes_24hr()
        resp = {}
        for depair in data["volumes"]:
            item = data["volumes"][depair]["ALL"]
            resp.update(
                {
                    depair: {
                        "trades_24h": item["total_swaps"],
                        "volume_24h": item["total_volume"],
                    }
                }
            )
        return resp
    except Exception as e:  # pragma: no cover
        logger.warning(f"{type(e)} Error in [/api/v3/stats_xyz/tickers_summary]: {e}")
        return {"error": f"{type(e)} Error in [/api/v3/stats_xyz/tickers_summary]: {e}"}


@router.get(
    "/trades/{pair_str}/{days_in_past}",
    description=stats_xyz_desc.trades,
    response_model=List[StatsXyzTrades],
    status_code=200,
)
def trades(pair_str: str = "KMD_LTC", days_in_past: int | None = None):
    try:
        for value, name in [(days_in_past, "days_in_past")]:
            validate.positive_numeric(value, name)
        if days_in_past > 90:
            return {"error": "Maximum value for 'days_in_past' is '90'. Try again."}
        start_time = int(cron.now_utc() - 86400 * days_in_past)
        end_time = int(cron.now_utc())

        pair = Pair(pair_str=pair_str)
        data = pair.historical_trades(
            start_time=start_time,
            end_time=end_time,
        )["ALL"]
        resp = data["buy"] + data["sell"]
        resp = sortdata.dict_lists(resp, "timestamp", True)
        return resp
    except BadPairFormatError as e:
        err = f"{type(e)} Error in [/api/v3/stats_xyz/trades]: {e.msg}"
        logger.warning(err)
    except Exception as e:
        err = f"{type(e)} Error in [/api/v3/stats_xyz/trades]: {e}"
        logger.warning(err)
    return JSONResponse(status_code=400, content=err)


# Migrated from https://stats.testchain.xyz/api/v1/usd_volume_24h
@router.get(
    "/usd_volume_24hr",
    description=stats_xyz_desc.usd_volume_24hr,
    responses={406: {"model": ErrorMessage}},
    response_model=StatsXyzUsdVolume,
    status_code=200,
)
def usd_volume_24h():
    try:
        data = memcache.get_pair_volumes_24hr()
        return {"usd_volume_24h": data["trade_volume_usd"]}
    except Exception as e:  # pragma: no cover
        logger.warning(f"{type(e)} Error in [/api/v3/markets/usd_volume_24h]: {e}")
        return {"error": f"{type(e)} Error in [/api/v3/markets/usd_volume_24h]: {e}"}


@router.get(
    "/volumes_ticker/{coin}/{days_in_past}",
    description=stats_xyz_desc.trades,
    response_model=Dict[str, float],
    status_code=200,
)
def volumes_ticker(coin="KMD", days_in_past=1, trade_type: TradeType = TradeType.ALL):
    # TODO: Use new DB
    volumes_dict = {}
    query = db.SqlQuery()
    # Individual tickers only, no merge except segwit
    decoin = deplatform.coin(coin)
    for i in range(0, int(days_in_past)):
        d = datetime.today() - timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        day_ts = int(int(d.strftime("%s")) / 86400) * 86400
        start_time = int(day_ts)
        end_time = int(day_ts) + 86400
        volumes = query.coin_trade_volumes(start_time=start_time, end_time=end_time)
        data = query.coin_trade_vols_usd(volumes)
        volumes_dict[d_str] = 0
        if decoin in data["volumes"]:
            volumes_dict[d_str] = data["volumes"][decoin]["ALL"]["total_volume"]
    return volumes_dict
