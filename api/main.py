#!/usr/bin/env python3
from util.cron import cron
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI

"""
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
"""

from const import API_HOST, API_PORT, DEVMODE
from routes import (
    gecko,
    cmc,
    cache_loop,
    swaps,
    rates,
    coins,
    pairs,
    markets,
    prices,
    binance,
    generic,
    tickers,
    stats_api,
    new_db,
    stats_xyz,
    dex,
)
from lib.cache import Cache, CacheItem
from models.generic import ErrorMessage, HealthCheck


@asynccontextmanager
async def lifespan(app: FastAPI):
    # start up functions
    for i in ["coins", "coins_config", "gecko_source"]:
        cache_item = CacheItem(i)
        cache_item.save()
    yield
    # shut down functions


app = FastAPI(swagger_ui_parameters={"syntaxHighlight.theme": "obsidian"})

app.include_router(cache_loop.router)

app.include_router(
    binance.router,
    prefix="/api/v3/binance",
    tags=["Binance"],
    dependencies=[],
    responses={418: {"description": "I'm a teapot"}},
)


app.include_router(
    gecko.router,
    prefix="/api/v3/gecko",
    tags=["CoinGecko"],
    dependencies=[],
    responses={418: {"description": "I'm a teapot"}},
)


app.include_router(
    markets.router,
    prefix="/api/v3/markets",
    tags=["Markets"],
    dependencies=[],
    responses={418: {"description": "I'm a teapot"}},
)

app.include_router(
    rates.router,
    prefix="/api/v3/rates",
    tags=["Rates"],
    dependencies=[],
    responses={418: {"description": "I'm a teapot"}},
)

app.include_router(
    prices.router,
    prefix="/api/v3/prices",
    tags=["Prices"],
    dependencies=[],
    responses={418: {"description": "I'm a teapot"}},
)


app.include_router(
    stats_api.router,
    prefix="/api/v3/stats-api",
    tags=["Stats-API"],
    dependencies=[],
    responses={418: {"description": "I'm a teapot"}},
)


app.include_router(
    tickers.router,
    prefix="/api/v3/tickers",
    tags=["Tickers"],
    dependencies=[],
    responses={418: {"description": "I'm a teapot"}},
)


app.include_router(
    stats_xyz.router,
    prefix="/api/v3/stats_xyz",
    tags=["Stats XYZ"],
    dependencies=[],
    responses={418: {"description": "I'm a teapot"}},
)


@app.get(
    "/healthcheck",
    tags=["Status"],
    description="Simple service status check",
    responses={406: {"model": ErrorMessage}},
    response_model=HealthCheck,
    status_code=200,
)
def healthcheck():
    cache = Cache()
    return {
        "timestamp": int(cron.now_utc()),
        "status": "ok",
        "cache_age_mins": cache.healthcheck(),
    }


app.include_router(
    coins.router,
    prefix="/api/v3/coins",
    tags=["Coins"],
    dependencies=[],
    responses={418: {"description": "I'm a teapot"}},
)

app.include_router(
    pairs.router,
    prefix="/api/v3/pairs",
    tags=["Pairs"],
    dependencies=[],
    responses={418: {"description": "I'm a teapot"}},
)

app.include_router(
    swaps.router,
    prefix="/api/v3/swaps",
    tags=["Swaps"],
    dependencies=[],
    responses={418: {"description": "I'm a teapot"}},
)

app.include_router(
    cmc.router,
    prefix="/api/v3/cmc",
    tags=["Coin Market Cap"],
    dependencies=[],
    responses={418: {"description": "I'm a teapot"}},
)


app.include_router(
    dex.router,
    prefix="/api/v3",
    tags=["Dex"],
    dependencies=[],
    responses={418: {"description": "I'm a teapot"}},
)

if DEVMODE:

    app.include_router(
        new_db.router,
        prefix="/api/v3/new_db",
        tags=["New DB"],
        dependencies=[],
        responses={418: {"description": "I'm a teapot"}},
    )

    app.include_router(
        generic.router,
        prefix="/api/v3/generic",
        tags=["Generic"],
        dependencies=[],
        responses={418: {"description": "I'm a teapot"}},
    )

"""
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui-bundle.js",
        #swagger_css_url="https://defi-stats.komodo.earth/static/css/dark.css",
    )
"""

if __name__ == "__main__":  # pragma: no cover
    uvicorn.run("main:app", host=API_HOST, port=API_PORT, reload=True)
