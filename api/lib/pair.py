#!/usr/bin/env python3
from collections import OrderedDict
from decimal import Decimal
from functools import cached_property
from typing import Optional, Dict, List
import db.sqldb as db
import lib.dex_api as dex
import lib.last as last_traded
import util.defaults as default
import util.memcache as memcache
from util.cron import cron
from util.logger import timed
from util.transform import (
    sortdata,
    convert,
    clean,
    deplatform,
    sumdata,
    merge,
    invert,
    filterdata,
    template,
    derive,
)
from lib.external import gecko_api
from util.logger import logger


class Pair:  # pragma: no cover
    """
    Allows for referencing pairs as a string or tuple.
    e.g. DOGE_BTC, not BTC_DOGE
    """

    def __init__(
        self,
        pair_str: str = "KMD_LTC",
        pairs_last_traded_cache: Dict | None = None,
        coins_config: Dict | None = None,
        gecko_source: Dict | None = None,
        pair_prices_24hr_cache: Dict | None = None,
    ):
        try:
            self.as_str = pair_str
            self.base, self.quote = derive.base_quote(self.as_str)
            # Lazy loading properties
            self._depair = None
            self._priced = None
            self._pg_query = None
            self._base_price_usd = None
            self._quote_price_usd = None
            self._coins_config = coins_config
            self._gecko_source = gecko_source
            self._pair_prices_24hr_cache = pair_prices_24hr_cache
            self._pairs_last_traded_cache = pairs_last_traded_cache

        except Exception as e:  # pragma: no cover
            msg = f"Init Pair for {pair_str} failed! {e}"
            return default.result(msg=msg, loglevel="warning")

    # TODO: Use the props instead of calling function where
    # possible, esp. for depair and variants.
    @property
    def priced(self):
        if self._priced is None:
            self._priced = True
            if self.quote_price_usd == 0 or self.base_price_usd == 0:
                self._priced = False
        return self._priced

    @property
    def base_price_usd(self):
        if self._base_price_usd is None:
            self._base_price_usd = derive.gecko_price(
                self.base, gecko_source=self.gecko_source
            )
        return self._base_price_usd

    @property
    def quote_price_usd(self):
        if self._quote_price_usd is None:
            self._quote_price_usd = derive.gecko_price(
                self.quote, gecko_source=self.gecko_source
            )
        return self._quote_price_usd

    @property
    def depair(self):
        if self._depair is None:
            self._depair = deplatform.pair(self.as_str)
        return self._depair

    @property
    def coins_config(self):
        if self._coins_config is None:
            self._coins_config = memcache.get_coins_config()
        return self._coins_config

    @property
    def gecko_source(self):
        if self._gecko_source is None:
            # logger.calc("sourcing gecko")
            self._gecko_source = memcache.get_gecko_source()
        if self._gecko_source is None:
            self._gecko_source = gecko_api.get_source_data(from_file=True)
        return self._gecko_source

    @property
    def pairs_last_traded_cache(self):
        if self._pairs_last_traded_cache is None:
            self._pairs_last_traded_cache = memcache.get_pairs_last_traded()
        return self._pairs_last_traded_cache

    @property
    def pair_prices_24hr_cache(self):
        if self._pair_prices_24hr_cache is None:
            self._pair_prices_24hr_cache = memcache.get_pair_prices_24hr()
        return self._pair_prices_24hr_cache

    @property
    def pg_query(self):
        if self._pg_query is None:
            self._pg_query = db.SqlQuery(gecko_source=self.gecko_source)
        return self._pg_query

    @cached_property
    def is_reversed(self):
        return self.as_str != sortdata.pair_by_market_cap(
            self.as_str, gecko_source=self.gecko_source
        )

    @cached_property
    def variants(self):
        return derive.pair_variants(self.as_str, segwit_only=False)

    @cached_property
    def segwit_variants(self):
        return derive.pair_variants(self.as_str, segwit_only=True)

    @timed
    def historical_trades(
        self,
        limit: int = 100,
        start_time: Optional[int] = 0,
        end_time: Optional[int] = 0,
    ):
        """Returns trades for this pair."""
        # TODO: Review price / reverse price logic
        try:
            if start_time == 0:
                start_time = int(cron.now_utc()) - 86400
            if end_time == 0:
                end_time = int(cron.now_utc())

            resp = {}
            swaps_for_pair = self.pg_query.get_swaps(
                start_time=start_time,
                end_time=end_time,
                pair_str=self.as_str,
            )
            for variant in swaps_for_pair:
                trades_info = []
                for swap in swaps_for_pair[variant]:
                    trade_info = OrderedDict()
                    trade_info["trade_id"] = swap["uuid"]
                    trade_info["timestamp"] = swap["finished_at"]
                    # Handle reversed pair requested.
                    # inverts base / quote and trade type
                    # so calcs after are correctly assigned
                    if self.is_reversed:
                        pair_str = invert.pair(swap["pair"])
                        price = Decimal(swap["reverse_price"])
                        trade_info["pair"] = pair_str
                        trade_info["type"] = invert.trade_type(swap["trade_type"])
                    else:
                        pair_str = swap["pair"]
                        price = Decimal(swap["price"])
                        trade_info["pair"] = pair_str
                        trade_info["type"] = swap["trade_type"]
                    base, quote = derive.base_quote(pair_str)
                    trade_info["price"] = convert.format_10f(price)
                    trade_info["base_coin"] = base
                    trade_info["quote_coin"] = quote
                    trade_info["base_coin_ticker"] = deplatform.coin(base)
                    trade_info["quote_coin_ticker"] = deplatform.coin(quote)
                    trade_info["base_coin_platform"] = derive.coin_platform(base)
                    trade_info["quote_coin_platform"] = derive.coin_platform(quote)

                    if trade_info["type"] == "buy":
                        trade_info["base_volume"] = convert.format_10f(
                            swap["maker_amount"]
                        )
                        trade_info["quote_volume"] = convert.format_10f(
                            swap["taker_amount"]
                        )
                    else:
                        trade_info["base_volume"] = convert.format_10f(
                            swap["taker_amount"]
                        )
                        trade_info["quote_volume"] = convert.format_10f(
                            swap["maker_amount"]
                        )

                    trades_info.append(trade_info)

                buys = filterdata.dict_lists(trades_info, "type", "buy")
                sells = filterdata.dict_lists(trades_info, "type", "sell")
                if len(buys) > 0:
                    buys = sortdata.dict_lists(buys, "timestamp", reverse=True)
                if len(sells) > 0:
                    sells = sortdata.dict_lists(sells, "timestamp", reverse=True)
                if variant == "ALL":
                    pair_str = deplatform.pair(self.as_str)
                else:
                    pair_str = variant
                data = {
                    "ticker_id": pair_str,
                    "start_time": str(start_time),
                    "end_time": str(end_time),
                    "limit": str(limit),
                    "trades_count": str(len(trades_info)),
                    "sum_base_volume_buys": sumdata.json_key_10f(buys, "base_volume"),
                    "sum_base_volume_sells": sumdata.json_key_10f(sells, "base_volume"),
                    "sum_quote_volume_buys": sumdata.json_key_10f(buys, "quote_volume"),
                    "sum_quote_volume_sells": sumdata.json_key_10f(
                        sells, "quote_volume"
                    ),
                    "average_price": convert.format_10f(
                        self.get_average_price(trades_info)
                    ),
                    "buy": buys,
                    "sell": sells,
                }

                resp.update({variant: data})
        except Exception as e:  # pragma: no cover
            return default.result(
                data=resp,
                msg=f"pair.historical_trades {self.as_str} failed! {e}",
                loglevel="warning",
            )
        return default.result(
            data=resp,
            msg=f"pair.historical_trades for {self.as_str} complete",
            loglevel="pair",
            ignore_until=2,
        )

    @timed
    def get_average_price(self, trades_info):
        try:
            data = 0
            if len(trades_info) > 0:
                data = sumdata.json_key(trades_info, "price") / len(trades_info)
            return default.result(
                data=data,
                msg=f"get_average_price for {self.as_str} complete",
                loglevel="pair",
                ignore_until=2,
            )
        except Exception as e:  # pragma: no cover
            msg = f"{self.as_str} get_average_price failed! {e}"
            return default.error(e, msg)

    @timed
    def get_pair_prices_info(self, days: int = 1):
        """
        Iterates over list of swaps to get prices data for a pair
        """
        try:
            key = "prices"
            ignore_until = 3
            suffix = derive.suffix(days)
            cache_name = derive.pair_cachename(key, self.as_str, suffix)
            data = memcache.get(cache_name)
            if data is not None:
                msg = f"get_pair_prices_info for {self.as_str} using cache!"
                return default.result(
                    data=data, msg=msg, loglevel="pair", ignore_until=3
                )
            data = {}
            data = clean.decimal_dicts(data)
            swaps_for_pair_combo = self.pg_query.get_swaps(
                start_time=int(cron.now_utc() - 86400 * days),
                end_time=int(cron.now_utc()),
                pair_str=self.as_str,
            )
            last_data = self.pairs_last_traded_cache
            for variant in swaps_for_pair_combo:
                last = last_traded.pair_last_trade_cache(self.as_str, last_data)
                swap_prices = self.get_swap_prices(swaps_for_pair_combo[variant])

                data[variant] = template.pair_prices_info(suffix)

                # TODO: using timestamps as an index works for now,
                # but breaks when two swaps have the same timestamp.
                if len(swap_prices) > 0:
                    swap_vals = list(swap_prices.values())
                    swap_keys = list(swap_prices.keys())
                    highest_price = max(swap_vals)
                    lowest_price = min(swap_vals)
                    newest_price = swap_prices[max(swap_prices.keys())]
                    oldest_price = swap_prices[min(swap_prices.keys())]
                    price_change = newest_price - oldest_price
                    pct_change = newest_price / oldest_price - 1

                    data[variant] = {
                        "oldest_price_time": swap_keys[swap_vals.index(oldest_price)],
                        "newest_price_time": swap_keys[swap_vals.index(newest_price)],
                        f"oldest_price_{suffix}": oldest_price,
                        f"newest_price_{suffix}": newest_price,
                        f"highest_price_{suffix}": highest_price,
                        f"lowest_price_{suffix}": lowest_price,
                        f"price_change_pct_{suffix}": pct_change,
                        f"price_change_{suffix}": price_change,
                        "base_price_usd": self.base_price_usd,
                        "quote_price_usd": self.quote_price_usd,
                        "last_swap_uuid": last["last_swap_uuid"],
                    }
                data[variant] = clean.decimal_dicts(data[variant])

            memcache.update(cache_name, data, 600)
            if abs(data["ALL"][f"price_change_{suffix}"]) > 0.02:
                ignore_until = 0
                msg = f'[{self.as_str}] 24hr price change {data["ALL"][f"price_change_{suffix}"]}%'
            msg = f"get_pair_prices_info for {self.as_str} complete!"
            return default.result(
                data=data, msg=msg, loglevel="pair", ignore_until=ignore_until
            )
        except Exception as e:  # pragma: no cover
            msg = f"get_pair_prices_info for {self.as_str} failed! {e}, returning template"
            return default.result(
                data=data, msg=msg, loglevel="warning", ignore_until=0
            )

    @timed
    def get_swap_prices(self, swaps_for_pair):
        try:
            data = {}
            [
                data.update(derive.price_at_finish(i, is_reverse=self.is_reversed))
                for i in swaps_for_pair
            ]
        except Exception as e:  # pragma: no cover
            msg = f"get_swap_prices for {self.as_str} failed! {e}"
            return default.result(data=data, msg=msg, loglevel="warning")
        msg = f"Completed get_swap_prices info for {self.as_str}"
        return default.result(data=data, msg=msg, loglevel="pair", ignore_until=2)

    @timed
    def orderbook(
        self,
        pair_str: str = "KMD_LTC",
        depth: int = 100,
        traded_pairs: List = list(),
        refresh: bool = False,
    ):
        try:
            depair = deplatform.pair(pair_str)
            if len(traded_pairs) == 0:
                ts = cron.now_utc() - 30 * 86400
                traded_pairs = derive.pairs_traded_since(
                    ts, self.pairs_last_traded_cache, reduced=False
                )
            pair_tpl = derive.base_quote(pair_str)
            if len(pair_tpl) != 2 or "error" in pair_tpl:
                msg = {"error": "Market pair should be in `KMD_BTC` format"}
                return default.result(
                    data=None, msg=msg, loglevel="error", ignore_until=0
                )
            msg = f"pair.orderbook {pair_str} (refresh {refresh})"
            loglevel = "pair"
            ignore_until = 3
            combo_orderbook = {"ALL": template.orderbook_extended(depair)}
            variants = derive.pair_variants(depair)
            for variant in variants:
                if depair in traded_pairs:
                    combo_orderbook.update(
                        {variant: template.orderbook_extended(variant)}
                    )
                    variant_cache_name = f"orderbook_{variant}"
                    cache_exists = memcache.get(variant_cache_name) is not None
                    base, quote = derive.base_quote(variant)
                    variant_orderbook = dex.get_orderbook(
                        base=base,
                        quote=quote,
                        coins_config=self.coins_config,
                        gecko_source=self.gecko_source,
                        pair_prices_24hr_cache=self.pair_prices_24hr_cache,
                        variant_cache_name=variant_cache_name,
                        depth=depth,
                        refresh=refresh,
                    )
                    if not refresh and not cache_exists:
                        dex.get_orderbook(
                            base=base,
                            quote=quote,
                            coins_config=self.coins_config,
                            gecko_source=self.gecko_source,
                            pair_prices_24hr_cache=self.pair_prices_24hr_cache,
                            variant_cache_name=variant_cache_name,
                            depth=depth,
                            refresh=True,
                        )
                    if variant_orderbook is not None:
                        combo_orderbook[variant] = variant_orderbook
                        ignore_until = 3
                        if not refresh:
                            combo_orderbook[variant]["bids"] = combo_orderbook[variant][
                                "bids"
                            ][: int(depth)][::-1]
                            combo_orderbook[variant]["asks"] = combo_orderbook[variant][
                                "asks"
                            ][::-1][: int(depth)]
                            combo_orderbook["ALL"] = merge.orderbooks(
                                existing=combo_orderbook["ALL"],
                                new=combo_orderbook[variant],
                                gecko_source=self.gecko_source,
                                trigger=variant_cache_name,
                            )
                            combo_orderbook[variant] = clean.orderbook_data(
                                combo_orderbook[variant]
                            )
            # Apply depth limit after caching so cache is complete
            # TODO: Recalc liquidity if depth is less than data.
            if not refresh:
                combo_orderbook["ALL"]["bids"] = combo_orderbook["ALL"]["bids"][
                    : int(depth)
                ][::-1]
                combo_orderbook["ALL"]["asks"] = combo_orderbook["ALL"]["asks"][::-1][
                    : int(depth)
                ]
                combo_orderbook["ALL"] = clean.orderbook_data(combo_orderbook["ALL"])
                msg = f"[{depair}] ${combo_orderbook['ALL']['liquidity_usd']} liquidity"
                if Decimal(combo_orderbook["ALL"]["liquidity_usd"]) > 10000:
                    ignore_until = 0

            return default.result(
                data=combo_orderbook,
                msg=msg,
                loglevel=loglevel,
                ignore_until=ignore_until,
            )
        except Exception as e:  # pragma: no cover
            msg = f"Pair.orderbook {pair_str} failed: {e}!"
            try:
                data = template.orderbook_extended(pair_str)
                data = dex.orderbook_extras(
                    pair_str=pair_str,
                    data=data,
                    gecko_source=self.gecko_source,
                    pair_prices_24hr_cache=self.pair_prices_24hr_cache,
                )
                msg += " Returning template!"
            except Exception as e:  # pragma: no cover
                data = {"error": f"{msg}: {e}"}
            return default.result(
                data=data, msg=msg, loglevel="warning", ignore_until=0
            )
