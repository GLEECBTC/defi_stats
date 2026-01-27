#!/usr/bin/env python3
from util.cron import cron
from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from typing import List
import db.sqldb as db
import lib.dex_api as dex
from lib.pair import Pair
from lib.cache_calc import CacheCalc
from models.generic import ErrorMessage
from models.gecko import (
    GeckoPairsItem,
    GeckoTickers,
    GeckoOrderbook,
    GeckoHistoricalTrades,
)
from util.enums import TradeType
from util.logger import logger
from util.transform import convert, deplatform, derive, invert, sortdata
import util.memcache as memcache
import util.validate as validate


router = APIRouter()


# Gecko Endpoints
@router.get(
    "/pairs",
    description="A list of CoinGecko compatible pairs traded within the last week.",
    response_model=List[GeckoPairsItem],
    responses={406: {"model": ErrorMessage}},
    status_code=200,
)
def gecko_pairs():
    try:
        return CacheCalc().gecko_pairs()
    except Exception as e:  # pragma: no cover
        logger.warning(f"{type(e)} Error in [/api/v3/gecko/pairs]: {e}")
        return {"error": f"{type(e)} Error in [/api/v3/gecko/pairs]: {e}"}


@router.get(
    "/tickers",
    description="24-hour price & volume for each CoinGecko compatible pair traded in last 7 days.",
    response_model=GeckoTickers,
    responses={406: {"model": ErrorMessage}},
    status_code=200,
)
def gecko_tickers():
    try:
        data = memcache.get_tickers()
        if not data or "data" not in data:
            logger.warning("gecko_tickers: tickers cache missing or malformed, returning empty payload")
            return {
                "last_update": int(cron.now_utc()),
                "pairs_count": data.get("pairs_count", 0) if isinstance(data, dict) else 0,
                "swaps_count": data.get("swaps_count", 0) if isinstance(data, dict) else 0,
                "combined_volume_usd": data.get("combined_volume_usd", "0") if isinstance(data, dict) else "0",
                "combined_liquidity_usd": data.get("combined_liquidity_usd", "0") if isinstance(data, dict) else "0",
                "data": [],
            }
        resp = {
            "last_update": int(cron.now_utc()),
            "pairs_count": data["pairs_count"],
            "swaps_count": data["swaps_count"],
            "combined_volume_usd": data["combined_volume_usd"],
            "combined_liquidity_usd": data["combined_liquidity_usd"],
            "data": [],
        }
        gecko_source = memcache.get_gecko_source()
        for depair in data["data"]:
            std_pair = sortdata.pair_by_market_cap(depair, gecko_source=gecko_source)
            if std_pair is None:
                std_pair = depair
            if depair == std_pair:
                resp["data"].append(data["data"][depair])
            elif std_pair in data["data"]:
                # Prefer the standardised name if present
                resp["data"].append(data["data"][std_pair])
            elif invert.pair(depair) in data["data"]:
                logger.warning(
                    f"Non standard {depair} exists in memcache.get_tickers(), should be {std_pair}. Including as-is."
                )
                resp["data"].append(data["data"][depair])
            else:
                logger.warning(
                    f"{depair} not found in memcache.get_tickers() (std {std_pair})"
                )
                # TODO: This should be threaded to avoid blocking
                # db_update.fix_swap_pair(depair, pgdb_query)
        return resp
    except Exception as e:  # pragma: no cover
        logger.warning(f"{type(e)} Error in [/api/v3/gecko/tickers]: {e}")
        return {"error": f"{type(e)} Error in [/api/v3/gecko/tickers]: {e}"}


@router.get(
    "/orderbook/{pair_str}",
    description="Returns live orderbook for a compatible pair (e.g. `KMD_LTC` ).",
    response_model=GeckoOrderbook,
    responses={406: {"model": ErrorMessage}},
    status_code=200,
)
def gecko_orderbook(
    response: Response,
    pair_str: str = "KMD_LTC",
    depth: int = 100,
):
    # No extras needed, but cache combines variants.
    try:
        book = memcache.get_pairs_orderbook_extended() or {}
        if "orderbooks" not in book or book.get("orderbooks") is None:
            logger.warning("gecko_orderbook: pairs_orderbook_extended cache missing; falling back to direct fetch")
            book = {"orderbooks": {}}
        depair = deplatform.pair(pair_str)
        if depair in book["orderbooks"]:
            data = book["orderbooks"][depair]["ALL"]
            return convert.orderbook_to_gecko(data, depth=depth)
        elif invert.pair(depair) in book["orderbooks"]:
            data = book["orderbooks"][invert.pair(depair)]["ALL"]
            return convert.orderbook_to_gecko(data, depth=depth, reverse=True)
        # Use direct method if no cache.
        variant_cache_name = f"orderbook_{pair_str}"
        coins_config = memcache.get_coins_config()
        gecko_source = memcache.get_gecko_source()
        base, quote = derive.base_quote(pair_str=pair_str)
        data = dex.get_orderbook(
            base=base,
            quote=quote,
            coins_config=coins_config,
            gecko_source=gecko_source,
            variant_cache_name=variant_cache_name,
            depth=depth,
        )
        resp = {
            "ticker_id": pair_str,
            "timestamp": int(cron.now_utc()),
            "variants": [pair_str],
            "bids": [
                [convert.format_10f(i["price"]), convert.format_10f(i["volume"])]
                for i in data["bids"]
            ][:depth],
            "asks": [
                [convert.format_10f(i["price"]), convert.format_10f(i["volume"])]
                for i in data["asks"]
            ][:depth],
        }
        return resp
    except Exception as e:  # pragma: no cover
        err = {"error": f"{e}"}
        logger.warning(err)
        return JSONResponse(status_code=400, content=err)


@router.get(
    "/historical_trades/{pair_str}",
    description="Trade history for CoinGecko compatible pairs. Use format `KMD_LTC`",
    response_model=GeckoHistoricalTrades,
    responses={406: {"model": ErrorMessage}},
    status_code=200,
)
def gecko_historical_trades(
    response: Response,
    trade_type: TradeType = TradeType.ALL,
    pair_str: str = "KMD_LTC",
    limit: int = 100,
    start_time: int = 0,
    end_time: int = 0,
):
    try:
        if start_time == 0:
            start_time = int(cron.now_utc() - 86400)
        if end_time == 0:
            end_time = int(cron.now_utc())
        for value, name in [
            (limit, "limit"),
            (start_time, "start_time"),
            (end_time, "end_time"),
        ]:
            validate.positive_numeric(value, name)
        if start_time > end_time:
            raise ValueError("start_time must be less than end_time")
        pair = Pair(pair_str=pair_str)
        data = pair.historical_trades(
            limit=limit,
            start_time=start_time,
            end_time=end_time,
        )["ALL"]
        base, target = derive.base_quote(pair_str=pair_str)
        resp = {
            "ticker_id": pair_str,
            "base": base,
            "target": target,
            "start_time": str(start_time),
            "end_time": str(end_time),
            "limit": str(limit),
            "trades_count": data["trades_count"],
            "sum_base_volume_buys": data["sum_base_volume_buys"],
            "sum_target_volume_buys": data["sum_quote_volume_buys"],
            "sum_base_volume_sells": data["sum_base_volume_sells"],
            "sum_target_volume_sells": data["sum_quote_volume_sells"],
            "average_price": data["average_price"],
            "buy": [convert.historical_trades_to_gecko(i) for i in data["buy"]],
            "sell": [convert.historical_trades_to_gecko(i) for i in data["sell"]],
        }
        return resp
    except Exception as e:  # pragma: no cover
        err = {"error": f"{e}"}
        logger.warning(err)
        return JSONResponse(status_code=400, content=err)
