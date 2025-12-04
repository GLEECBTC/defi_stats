#!/usr/bin/env python3
import time
from util.cron import cron
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from util.logger import logger
from models.generic import ErrorMessage
from lib.cache import Cache

router = APIRouter()
cache = Cache()

# Data comes via prices.komodian.info


@router.get(
    "/tickers_v1",
    description="Returns data cached from https://prices.gleec.com/api/v1/tickers",
    responses={406: {"model": ErrorMessage}},
    status_code=200,
)
def get_v1_tickers(expire_at: int = 900):
    # r.GET("/api/v1/tickers", TickerAllInfos)
    try:
        data = {}
        cache = Cache(netid="ALL")
        resp = cache.get_item(name="prices_tickers_v1").data
        for i in resp:
            if resp[i]["last_updated_timestamp"] > int(cron.now_utc()) - int(expire_at):
                data.update({i: resp[i]})
        return data
    except Exception as e:  # pragma: no cover
        err = {"error": f"Error in [/api/v3/prices/tickers_v1]: {e}"}
        logger.warning(err)
        return JSONResponse(status_code=400, content=err)


@router.get(
    "/tickers_v2",
    description="Returns data cached from https://prices.gleec.com/api/v2/tickers",
    responses={406: {"model": ErrorMessage}},
    status_code=200,
)
def get_v2_tickers(expire_at: int = 900):
    # r.GET("/api/v2/tickers", TickerAllInfosV2)
    try:
        data = {}
        cache = Cache()
        resp = cache.get_item(name="prices_tickers_v2").data
        for i in resp:
            if resp[i]["last_updated_timestamp"] > int(cron.now_utc()) - int(expire_at):
                data.update({i: resp[i]})
        return data
    except Exception as e:  # pragma: no cover
        err = {"error": f"Error in [/api/v3/prices/tickers_v2]: {e}"}
        logger.warning(err)
        return JSONResponse(status_code=400, content=err)


# Unsure of these params, cant get a response:
# r.POST("/api/v1/ticker_infos", TickerInfos)
# r.POST("/api/v1/cex_rates", CexRates)
# r.POST("/api/v1/volume24hr", Volume24h)

# No need to mirror these
# r.GET("/api/v1/ping", Ping)
