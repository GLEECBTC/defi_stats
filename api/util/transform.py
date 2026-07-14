from decimal import Decimal, InvalidOperation
from typing import Any, List, Dict

from util.logger import logger, timed
from util.cron import cron
import util.defaults as default

import util.memcache as memcache


# TODO: Create Subclasses for transform / strip / aggregate / cast


class Clean:
    def __init__(self):
        pass

    @timed
    def decimal_dict_lists(self, data, to_string=False, rounding=8):
        """
        Works for a list of dicts with no nesting
        (e.g. summary_cache.json)
        """
        try:
            for i in data:
                for j in i:
                    if isinstance(i[j], Decimal):
                        if to_string:
                            i[j] = convert.round_to_str(i[j], rounding)
                        else:
                            i[j] = round(float(i[j]), rounding)
            return data
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")

    @timed
    def decimal_dicts(
        self, data, to_string=False, rounding=10, exclude_keys: List = list()
    ):
        """
        Works for a simple dict with no nesting
        (e.g. summary_cache.json)
        """
        try:
            for i in data:
                if i not in exclude_keys:
                    if isinstance(data[i], Decimal):
                        if to_string:
                            data[i] = convert.round_to_str(data[i], rounding)
                        else:
                            data[i] = float(data[i])
            return data
        except Exception as e:  # pragma: no cover
            logger.warning(data)
            return default.result(msg=e, loglevel="warning")

    @timed
    def orderbook_data(self, data):
        try:
            for i in ["bids", "asks"]:
                for j in data[i]:
                    for k in ["price", "volume"]:
                        j[k] = convert.format_10f(Decimal(j[k]))
            for i in [
                "total_asks_base_vol",
                "total_bids_base_vol",
                "total_asks_quote_vol",
                "total_bids_quote_vol",
                "total_asks_base_usd",
                "total_bids_quote_usd",
                "liquidity_usd",
                "base_liquidity_coins",
                "base_liquidity_usd",
                "quote_liquidity_coins",
                "quote_liquidity_usd",
                "highest_bid",
                "lowest_ask",
            ]:
                if i in data:
                    data[i] = convert.format_10f(Decimal(data[i]))
                else:  # pragma: no cover
                    logger.warning(f"{i} not in data!")
            return data
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")


class Convert:
    def __init__(self):
        self._coins_config = None

    @property
    def coins_config(self):
        if self._coins_config is None:
            self._coins_config = memcache.get_coins_config()
        return self._coins_config

    @timed
    def format_10f(self, number: float | Decimal) -> str:
        """
        Format a float to 10 decimal places.
        """
        if isinstance(number, str):
            number = Decimal(number)
        return f"{number:.10f}"

    @timed
    def round_to_str(self, value: Any, rounding=8):
        try:
            if isinstance(value, (str, int, float)):
                value = Decimal(value)
            if isinstance(value, Decimal):
                value = value.quantize(Decimal(f'1.{"0" * rounding}'))
            else:
                raise TypeError(f"Invalid type: {type(value)}")
        except (ValueError, TypeError, InvalidOperation) as e:  # pragma: no cover
            logger.muted(f"{type(e)} Error rounding {value}: {e}")
            value = 0
        except Exception as e:  # pragma: no cover
            logger.error(e)
            value = 0
        return f"{value:.{rounding}f}"

    @timed
    def book_to_stats_api_ticker(self, book_item):
        return {
            book_item["pair"]: {
                "last_swap_price": book_item["newest_price"],
                "quote_volume": book_item["quote_liquidity_coins"],
                "base_volume": book_item["base_liquidity_coins"],
                "isFrozen": "0",
            }
        }

    # DEAD CODE: this method has no callers anywhere in the codebase.
    # Known bugs in the `reverse` branch (same class of bug fixed in
    # orderbook_to_gecko): bids/asks are dicts from invert.ask_bid()
    # instead of [[price, volume], ...] lists, the key is "ticker_id"
    # instead of "pair", and total_asks_base_vol /
    # total_bids_quote_vol are missing. Fix these before reusing.
    @timed
    def orderbook_to_stats_api(self, data, depth=100, reverse=False):
        if reverse:
            return {
                "ticker_id": invert.pair(data["pair"]),
                "timestamp": int(cron.now_utc()),
                "variants": derive.pair_variants(pair_str=invert.pair(data["pair"])),
                "asks": [invert.ask_bid(i) for i in data["bids"]][:depth],
                "bids": [invert.ask_bid(i) for i in data["asks"]][:depth],
            }
        else:
            return {
                "pair": data["pair"],
                "timestamp": int(cron.now_utc()),
                "variants": derive.pair_variants(pair_str=data["pair"]),
                "bids": [
                    [convert.format_10f(i["price"]), convert.format_10f(i["volume"])]
                    for i in data["bids"]
                ][:depth],
                "asks": [
                    [convert.format_10f(i["price"]), convert.format_10f(i["volume"])]
                    for i in data["asks"]
                ][:depth],
                "total_asks_base_vol": data["base_liquidity_coins"],
                "total_bids_quote_vol": data["quote_liquidity_coins"],
            }

    @timed
    def orderbook_to_gecko(self, data, depth=100, reverse=False):
        if reverse:
            return {
                "ticker_id": invert.pair(data["pair"]),
                "timestamp": int(cron.now_utc()),
                "variants": derive.pair_variants(pair_str=invert.pair(data["pair"])),
                "asks": [
                    [i["price"], i["volume"]]
                    for i in (invert.ask_bid(x) for x in data["bids"])
                ][:depth],
                "bids": [
                    [i["price"], i["volume"]]
                    for i in (invert.ask_bid(x) for x in data["asks"])
                ][:depth],
            }
        else:
            return {
                "ticker_id": data["pair"],
                "timestamp": int(cron.now_utc()),
                "variants": derive.pair_variants(pair_str=data["pair"]),
                "bids": [
                    [convert.format_10f(i["price"]), convert.format_10f(i["volume"])]
                    for i in data["bids"]
                ][:depth],
                "asks": [
                    [convert.format_10f(i["price"]), convert.format_10f(i["volume"])]
                    for i in data["asks"]
                ][:depth],
            }

    def pair_orderbook_extras_to_gecko_tickers(self, book, vols, prices):
        return {
            "ticker_id": book["pair"],
            "pool_id": book["pair"],
            "base_currency": book["base"],
            "target_currency": book["quote"],
            "base_volume": convert.format_10f(vols["base_volume"]),
            "target_volume": convert.format_10f(vols["quote_volume"]),
            "bid": convert.format_10f(book["highest_bid"]),
            "ask": convert.format_10f(book["lowest_ask"]),
            "high": convert.format_10f(prices["highest_price_24hr"]),
            "low": convert.format_10f(prices["lowest_price_24hr"]),
            "trades_24hr": vols["trades_24hr"],
            "last_price": convert.format_10f(prices["newest_price_24hr"]),
            "last_swap_uuid": prices["last_swap_uuid"],
            "last_trade": prices["newest_price_time"],
            "volume_usd_24hr": convert.format_10f(vols["trade_volume_usd"]),
            "liquidity_usd": convert.format_10f(book["liquidity_usd"]),
            "variants": derive.pair_variants(book["pair"]),
        }

    def ticker_to_gecko_pair(self, pair_data):
        return {
            "ticker_id": pair_data["ticker_id"],
            "pool_id": pair_data["ticker_id"],
            "base": pair_data["base_currency"],
            "target": pair_data["quote_currency"],
            "variants": pair_data["variants"],
        }

    def ticker_to_gecko_ticker(self, ticker_data):
        return {
            "ticker_id": ticker_data["ticker_id"],
            "pool_id": ticker_data["ticker_id"],
            "base_currency": ticker_data["base_currency"],
            "target_currency": ticker_data["quote_currency"],
            "base_volume": ticker_data["base_volume"],
            "target_volume": ticker_data["quote_volume"],
            "bid": ticker_data["highest_bid"],
            "ask": ticker_data["lowest_ask"],
            "high": ticker_data["highest_price_24hr"],
            "low": ticker_data["lowest_price_24hr"],
            "trades_24hr": ticker_data["trades_24hr"],
            "last_price": ticker_data["last_swap_price"],
            "last_trade": ticker_data["last_swap_time"],
            "last_swap_uuid": ticker_data["last_swap_uuid"],
            "volume_usd_24hr": ticker_data["combined_volume_usd"],
            "liquidity_usd": ticker_data["liquidity_usd"],
            "variants": ticker_data["variants"],
        }

    def historical_trades_to_gecko(self, i):
        return {
            "trade_id": i["trade_id"],
            "base": i["base_coin"],
            "target": i["quote_coin"],
            "price": i["price"],
            "base_volume": i["base_volume"],
            "target_volume": i["quote_volume"],
            "timestamp": i["timestamp"],
            "type": i["type"],
        }

    def historical_trades_to_stats_api(self, i):
        return {
            "pair": i["pair"],
            "trade_id": i["trade_id"],
            "price": i["price"],
            "base_volume": i["base_volume"],
            "target_volume": i["quote_volume"],
            "timestamp": i["timestamp"],
            "type": i["type"],
        }

    def historical_trades_to_cmc(self, i):
        return {
            "pair": i["pair"],
            "trade_id": i["trade_id"],
            "price": i["price"],
            "base_volume": i["base_volume"],
            "quote_volume": i["quote_volume"],
            "timestamp": i["timestamp"] * 1000,
            "type": i["type"],
        }

    @timed
    def label_bids_asks(self, orderbook_data):
        try:
            for i in ["asks", "bids"]:
                if len(orderbook_data[i]) > 0:
                    if "quote_volume" not in orderbook_data[i][0]:
                        orderbook_data[i] = [
                            {
                                "price": convert.format_10f(
                                    Decimal(j["price"]["decimal"])
                                ),
                                "volume": j["base_max_volume"]["decimal"],
                                "quote_volume": j["rel_max_volume"]["decimal"],
                            }
                            for j in orderbook_data[i]
                        ]
            return orderbook_data
        except Exception as e:
            logger.warning(e)


@timed
def to_summary_for_ticker_xyz_item(data):  # pragma: no cover
    return {
        "ticker_id": data["ticker_id"],
        "base_currency": data["base_currency"],
        "liquidity_usd": data["liquidity_usd"],
        "base_volume": data["base_volume"],
        "base_price_usd": data["base_price_usd"],
        "quote_currency": data["quote_currency"],
        "quote_volume": data["quote_volume"],
        "quote_price_usd": data["quote_price_usd"],
        "highest_bid": data["highest_bid"],
        "lowest_ask": data["lowest_ask"],
        "highest_price_24h": data["highest_price_24hr"],
        "lowest_price_24h": data["lowest_price_24hr"],
        "price_change_24h": data["price_change_24hr"],
        "price_change_pct_24h": data["price_change_pct_24hr"],
        "trades_24hr": data["trades_24hr"],
        "volume_usd_24h": data["combined_volume_usd"],
        "last_swap_price": data["last_swap_price"],
        "last_swap_timestamp": data["last_swap_time"],
    }


@timed
def ticker_to_xyz_summary(i):
    return {
        "trading_pair": i["pair"],
        "trades_24h": int(i["trades_24hr"]),
        "base_currency": i["base"],
        "quote_currency": i["quote"],
        "base_volume": i["base_liquidity_coins"],
        "quote_volume": i["quote_liquidity_coins"],
        "lowest_ask": i["lowest_ask"],
        "highest_bid": i["highest_bid"],
        "lowest_price_24h": i["lowest_price_24hr"],
        "highest_price_24h": i["highest_price_24hr"],
        "price_change_percent_24h": str(i["price_change_pct_24hr"]),
        "last_price": i["newest_price_24hr"],
        "last_swap_timestamp": int(i["newest_price_time"]),
    }


@timed
def ticker_to_gecko_summary(i):
    data = {
        "ticker_id": i["ticker_id"],
        "pool_id": i["ticker_id"],
        "variants": i["variants"],
        "base_currency": i["base_currency"],
        "quote_currency": i["quote_currency"],
        "highest_bid": convert.format_10f(i["highest_bid"]),
        "lowest_ask": convert.format_10f(i["lowest_ask"]),
        "highest_price_24hr": convert.format_10f(i["highest_price_24hr"]),
        "lowest_price_24hr": convert.format_10f(i["lowest_price_24hr"]),
        "base_volume": convert.format_10f(i["base_volume"]),
        "quote_volume": convert.format_10f(i["quote_volume"]),
        "last_swap_price": convert.format_10f(i["last_swap_price"]),
        "last_swap_time": int(Decimal(i["last_swap_time"])),
        "last_swap_uuid": i["last_swap_uuid"],
        "trades_24hr": int(Decimal(i["trades_24hr"])),
        "combined_volume_usd": convert.format_10f(i["combined_volume_usd"]),
        "liquidity_usd": convert.format_10f(i["liquidity_usd"]),
    }
    return data


@timed
def historical_trades_to_market_trades(i):
    return {
        "trade_id": i["trade_id"],
        "price": i["price"],
        "base_volume": i["base_volume"],
        "quote_volume": i["quote_volume"],
        "timestamp": i["timestamp"],
        "type": i["type"],
    }


class Deplatform:
    def __init__(self):
        pass

    def pair(self, pair):
        base, quote = derive.base_quote(pair)
        return f"{self.coin(base)}_{self.coin(quote)}"

    def coin(self, coin):
        if coin is None:
            return None
        return coin.split("-")[0]


class Derive:
    def __init__(self):
        self._coins_config = None
        self._cmc_assets_source = None
        self._gecko_source = None

    @property
    def coins_config(self):
        if self._coins_config is None:
            self._coins_config = memcache.get_coins_config()
        return self._coins_config

    @property
    def cmc_assets_source(self):
        if self._cmc_assets_source is None:
            self._cmc_assets_source = memcache.get_cmc_assets_source()
        return self._cmc_assets_source

    @property
    def cmc_assets_dict(self):
        return {i["symbol"]: i for i in self.cmc_assets_source}

    def cmc_asset_info(self, coin):
        ticker = deplatform.coin(coin)
        if ticker in self.cmc_assets_dict:
            return self.cmc_assets_dict[ticker]
        return {}

    @property
    def gecko_source(self):
        if self._gecko_source is None:
            logger.calc("sourcing gecko")
            self._gecko_source = memcache.get_gecko_source()
        return self._gecko_source

    @timed
    def variant_trades(self, variant, data):
        base, quote = derive.base_quote(variant)
        return [
            k
            for k in data
            if base in [k["taker_coin"], k["maker_coin"]]
            and quote in [k["taker_coin"], k["maker_coin"]]
        ]


    @timed
    def base_quote(self, pair_str, reverse=False, reduce=False):
        # TODO: This workaround fixes the issue
        # but need to find root cause to avoid
        # unexpected related issues.
        # Might be simplest to just repair the pre-standard 
        # pair tickers in the DB.
        try:
            if reduce:
                pair_str = deplatform.pair(pair_str)
            if pair_str == "OLD_USDC-PLG20_USDC-PLG20":
                pair_str = "USDC-PLG20_USDC-PLG20_OLD"
            split_pair_str = pair_str.split("_")
            if len(split_pair_str) == 2:
                base = split_pair_str[0]
                quote = split_pair_str[1]
            elif pair_str.find("IBC_") > -1:
                if split_pair_str[0].endswith("IBC"):
                    base = f"{split_pair_str[0]}_{split_pair_str[1]}"
                    quote = split_pair_str[2]
                elif split_pair_str[1].endswith("IBC"):
                    base = split_pair_str[0]
                    quote = f"{split_pair_str[1]}_{split_pair_str[2]}"
            elif pair_str.startswith("IRIS_ATOM-IBC"):
                base = "IRIS_ATOM-IBC"
                quote = pair_str.replace(f"{base}_", "")
            elif pair_str.endswith("IRIS_ATOM-IBC"):
                quote = "IRIS_ATOM-IBC"
                base = pair_str.replace(f"_{quote}", "")

            elif pair_str.startswith("IRIS_ATOM"):
                base = "IRIS_ATOM"
                quote = pair_str.replace(f"{base}_", "")
            elif pair_str.endswith("IRIS_ATOM"):
                quote = "IRIS_ATOM"
                base = pair_str.replace(f"_{quote}", "")

            elif pair_str.startswith("ATOM-IBC_IRIS"):
                base = "ATOM-IBC_IRIS"
                quote = pair_str.replace(f"{base}_", "")
            elif pair_str.endswith("ATOM-IBC_IRIS"):
                quote = "ATOM-IBC_IRIS"
                base = pair_str.replace(f"_{quote}", "")

            elif len(split_pair_str) == 4 and "OLD" in split_pair_str:
                if split_pair_str[1] == "OLD":
                    base = f"{split_pair_str[0]}_{split_pair_str[1]}"
                if split_pair_str[3] == "OLD":
                    quote = f"{split_pair_str[2]}_{split_pair_str[3]}"
            elif len(split_pair_str) == 3 and "OLD" in split_pair_str:
                if split_pair_str[2] == "OLD":
                    base = split_pair_str[0]
                    quote = f"{split_pair_str[1]}_{split_pair_str[2]}"
                elif split_pair_str[1] == "OLD":
                    base = f"{split_pair_str[0]}_{split_pair_str[1]}"
                    quote = split_pair_str[2]
            else:
                logger.warning(f"Failed to parse {pair_str}, needs a special case")
                base = "PARSE"
                quote = "FAIL"

            if reverse:
                return quote, base
            return base, quote
        except Exception as e:  # pragma: no cover
            msg = f"failed to parse {pair_str} into base/quote! {e}"
            data = {"error": msg}
            return default.result(msg=msg, loglevel="warning", data=data)

    @timed
    def pair_cachename(self, key: str, pair_str: str, suffix: str):
        return f"{key}_{pair_str}_{suffix}"

    @timed
    def coin_platform(self, coin):
        r = coin.split("-")
        if len(r) == 2:
            return r[1]
        return ""

    def highest(self, existing, new, key):
        existing[key] = max(Decimal(existing[key]), Decimal(new[key]))
        return existing

    def lowest(self, existing, new, key):
        if Decimal(new[key]) > 0:
            if Decimal(existing[key]) > 0:
                existing[key] = min(Decimal(existing[key]), Decimal(new[key]))
            else:
                existing[key] = Decimal(new[key])
        return existing

    @timed
    def suffix(self, days: int) -> str:
        if days == 1:
            return "24hr"
        else:
            return f"{days}d"

    def gecko_price(self, ticker, gecko_source) -> float:
        try:
            if ticker in gecko_source:
                return Decimal(gecko_source[ticker]["usd_price"])
        except KeyError as e:  # pragma: no cover
            logger.warning(
                f"Failed to get usd_price and mcap for {ticker}: [KeyError] {e}"
            )
        except Exception as e:  # pragma: no cover
            logger.warning(f"Failed to get usd_price and mcap for {ticker}: {e}")
        return Decimal(0)  # pragma: no cover

    def gecko_mcap(self, ticker, gecko_source) -> float:
        # TODO: Special case, different to '-segwit'.
        # This should be handled genericaly
        # there may be other places where this is an issue
        ticker = ticker.replace("-lightning", "").replace("-segwit", "")
        if ticker in gecko_source:
            return Decimal(gecko_source[ticker]["usd_market_cap"])
        return Decimal(0)

    @timed
    def last_trade_info(self, pair_str: str, pairs_last_traded_cache: Dict):
        try:
            if pair_str in pairs_last_traded_cache:
                return pairs_last_traded_cache[pair_str]
            reverse_pair = invert.pair(pair_str, reduce=True)
            if reverse_pair in pairs_last_traded_cache:
                return pairs_last_traded_cache[reverse_pair]
        except Exception as e:  # pragma: no cover
            logger.warning(e)
        return template.last_trade_info()

    @timed
    def coin_variants(self, coin: str, segwit_only: bool = False):
        try:
            """
            If `segwit_only` is true, non-segwit coins will be
            returned on their own, otherwise the utxo legacy
            and segwit versions will be returned.
            """
            coin_parts = coin.split("-")
            if len(coin_parts) == 2 and not coin.endswith("segwit") and segwit_only:
                return [coin]
            else:
                coin = coin_parts[0]
            data = [
                i
                for i in self.coins_config
                if (i.replace(coin, "") == "" or i.replace(coin, "").startswith("-"))
            ]
            if segwit_only:
                decoin = deplatform.coin(coin)
                return [
                    i
                    for i in data
                    if i.endswith("segwit") or i.replace(decoin, "") == ""
                ]
            if len(data) == 0:
                data = [coin]
            return data
        except Exception as e:
            logger.warning(f"coin variants for {coin} failed: {e}")

    @timed
    def pair_variants(self, pair_str, segwit_only=False):
        try:
            if pair_str == "ALL":
                return ["ALL"]
            variants = []
            base, quote = derive.base_quote(pair_str)
            base_variants = self.coin_variants(base)
            quote_variants = self.coin_variants(quote)
            for i in base_variants:
                for j in quote_variants:
                    if i != j:
                        variants.append(f"{i}_{j}")
            if segwit_only:
                base_variants = []
                quote_variants = []
                segvars = []
                debase = deplatform.coin(base)
                dequote = deplatform.coin(quote)
                if base.endswith("segwit") or base == debase:
                    if debase in self.coins_config:
                        base_variants.append(debase)
                    if f"{debase}-segwit" in self.coins_config:
                        base_variants.append(f"{debase}-segwit")
                else:
                    base_variants = [base]

                if quote.endswith("segwit") or quote == dequote:
                    if dequote in self.coins_config:
                        quote_variants.append(dequote)
                    if f"{dequote}-segwit" in self.coins_config:
                        quote_variants.append(f"{dequote}-segwit")
                else:
                    quote_variants = [quote]
                for b in base_variants:
                    for q in quote_variants:
                        variant = f"{b}_{q}"
                        if b != q:
                            segvars.append(variant)
                variants = list(set(segvars))
            variants.sort()
            return variants
        except Exception as e:
            logger.warning(f"pair variants for {pair_str} failed: {e}")
            return [pair_str]

    @timed
    def pairs_traded_since(self, ts, pairs_last_traded_cache, reduced=True):
        if not reduced:
            pairs = []
            for i in pairs_last_traded_cache:
                for j in pairs_last_traded_cache[i]:
                    if pairs_last_traded_cache[i][j]["last_swap_time"] > ts:
                        if j != "ALL":
                            pairs.append(j)
            data = sorted(list(set(pairs)))
        else:
            data = sorted(list(
                set(
                    [
                        i
                        for i in pairs_last_traded_cache
                        if pairs_last_traded_cache[i]["ALL"]["last_swap_time"] > ts
                    ]
                )
            ))
        return [
            sortdata.pair_by_market_cap(
                i, gecko_source=self.gecko_source
            ) for i in data
        ]

    @timed
    def price_at_finish(self, swap, is_reverse=False):
        try:
            end_time = swap["finished_at"]
            if is_reverse:
                price = swap["reverse_price"]
            else:
                price = swap["price"]
            return {end_time: price}
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")

    # The lowest ask / highest bid needs to be inverted
    # to result in conventional vaules like seen at
    # https://api.binance.com/api/v1/ticker/24hr where
    # askPrice > bidPrice
    @timed
    def lowest_ask(self, orderbook: dict) -> str:
        """Returns lowest ask from provided orderbook"""
        try:
            if len(orderbook["asks"]) > 0:
                prices = [Decimal(i["price"]) for i in orderbook["asks"]]
                return min(prices)
        except KeyError as e:  # pragma: no cover
            logger.warning(e)
            return default.error(e, data=convert.format_10f(0))
        except Exception as e:  # pragma: no cover
            logger.warning(e)
            return default.error(e, data=convert.format_10f(0))
        return convert.format_10f(0)

    @timed
    def highest_bid(self, orderbook: list) -> str:
        """Returns highest bid from provided orderbook"""
        try:
            if len(orderbook["bids"]) > 0:
                prices = [Decimal(i["price"]) for i in orderbook["bids"]]
                return max(prices)
        except KeyError as e:  # pragma: no cover
            logger.warning(e)
            return default.error(e, data=convert.format_10f(0))
        except Exception as e:  # pragma: no cover
            logger.warning(e)
            return default.error(e, data=convert.format_10f(0))
        return convert.format_10f(0)

    def top_coin_by_volume(self, vols):
        coin_volumes = []
        for decoin in vols["volumes"]:
            if "ALL" in vols["volumes"][decoin]:
                data = vols["volumes"][decoin]["ALL"]
                coin_volumes.append({
                    "coin": decoin,
                    "maker_volume": data["maker_volume_usd"],
                    "taker_volume": data["taker_volume_usd"],
                    "volume": data["trade_volume_usd"]
                })
        return clean.decimal_dict_lists(sortdata.top_items(coin_volumes, "volume", length=25))

    def top_coin_by_swap_counts(self, vols):
        coin_swaps = []
        for decoin in vols["volumes"]:
            if "ALL" in vols["volumes"][decoin]:
                data = vols["volumes"][decoin]["ALL"]
                if data["trade_volume_usd"] > 1000:
                    coin_swaps.append({
                        "coin": decoin,
                        f"trades": data[f"total_swaps"],
                        f"maker_trades": data[f"maker_swaps"],
                        f"taker_trades": data[f"taker_swaps"]
                    })
        return clean.decimal_dict_lists(sortdata.top_items(coin_swaps, f"trades", length=25))

    def top_pairs_by_volume(self, vols):
        pair_volumes = []
        for depair in vols["volumes"]:
            if "ALL" in vols["volumes"][depair]:
                data = vols["volumes"][depair]["ALL"]
                pair_volumes.append(
                    {"pair": depair, "volume": data["trade_volume_usd"]}
                )
        return clean.decimal_dict_lists(sortdata.top_items(pair_volumes, "volume"))

    def top_pairs_by_swap_counts(self, vols, suffix):
        pair_swap_counts = []
        for depair in vols["volumes"]:
            if "ALL" in vols["volumes"][depair]:
                data = vols["volumes"][depair]["ALL"]
                # Filter out test coins
                if data["trade_volume_usd"] > 0:
                    # if suffix == "all_time":
                    #    logger.calc(data)
                    pair_swap_counts.append(
                        {"pair": depair, f"trades_{suffix}": data[f"trades_{suffix}"]}
                    )
        return clean.decimal_dict_lists(
            sortdata.top_items(pair_swap_counts, f"trades_{suffix}")
        )

    def top_pairs_by_liquidity(self, books):
        pair_liquidity = []
        for depair in books["orderbooks"]:
            if "ALL" in books["orderbooks"][depair]:
                data = books["orderbooks"][depair]["ALL"]
                pair_liquidity.append(
                    {"pair": depair, "liquidity": Decimal(data["liquidity_usd"])}
                )
        return clean.decimal_dict_lists(sortdata.top_items(pair_liquidity, "liquidity"))

    def app(self, appname):
        logger.query(f"appname: {appname}")
        gui, match = self.gui(appname)
        appname.replace(match, "")
        app_version, match = self.app_version(appname)
        appname.replace(match, "")
        defi_version, match = self.defi_version(appname)
        appname.replace(match, "")
        # check the last to avoid false positives: e.g. web / web_dex
        device, match = self.device(appname)
        appname.replace(match, "")
        derived_app = f"{gui} {app_version} {device} (sdk: {defi_version})"
        logger.info(f"derived_app: {derived_app}")
        return derived_app

    def gui(self, appname):
        for i in self.DeFiApps:
            for j in self.DeFiApps[i]:
                if j in appname.lower():
                    return i, j
        return "Unknown", ""

    def device(self, appname):
        for i in self.DeFiDevices:
            for j in self.DeFiDevices[i]:
                if j in appname.lower():
                    return i, j
        return "Unknown", ""

    def app_version(self, appname):
        parts = appname.split(" ")
        for i in parts:
            subparts = i.split("-")
            for j in subparts:
                version_parts = j.split(".")
                for k in version_parts:
                    try:
                        int(k)
                    except ValueError:
                        break
                    except Exception as e:  # pragma: no cover
                        logger.warning(e)
                        break
                    return j, j
        return "Unknown", ""

    def defi_version(self, appname):
        parts = appname.split("_")
        for i in parts:
            if len(i) > 6:
                try:
                    int(i, 16)
                    return i, i
                except ValueError:
                    pass
        return "Unknown", ""

    @property
    def DeFiApps(self):
        return {
            "Adex-CLI": ["adex-cli"],
            "AirDex": ["air_dex", "airdex"],
            "AtomicDEX": ["atomicdex"],
            "BitcoinZ Dex": ["bitcoinz dex"],
            "BumbleBee": ["bumblebee"],
            "CLI": ["cli", "atomicdex client cli"],
            "ColliderDex": ["colliderdex desktop"],
            "DexStats": ["dexstats"],
            "Docs Walkthru": [
                "docs_walkthru",
                "devdocs",
                "core_readme",
                "kmd_atomicdex_api_tutorial",
            ],
            "DogeDex": ["dogedex"],
            "Faucet": ["faucet"],
            "FiroDex": ["firodex", "firo dex"],
            "GleecDex": ["gleecdex"],
            "Komodo Wallet": ["komodo wallet"],
            "Legacy Desktop": ["atomicdex desktop"],
            "Legacy Desktop CE": ["atomicdex desktop ce"],
            "LoreDex": ["lore dex"],
            "MM2 CLI": ["mm2cli"],
            "MM2GUI": ["mm2gui"],
            "NatureDEX": ["naturedex"],
            "Other": [],
            "PirateDex": ["piratedex"],
            "PytomicDex": ["pytomicdex", "pymakerbot"],
            "QA Tools": ["history_spammer_tool", "wasmtest", "artemii_dev", "qa_cli"],
            "ShibaDex": ["shibadex"],
            "SmartDEX": ["smartdex"],
            "SqueexeDEX": ["squeexedex", "squeexe wallet"],
            "SwapCase Desktop": ["swapcase desktop"],
            "Tokel IDO": ["tokel ido"],
            "Unknown": ["unknown"],
            "WebDEX": ["web_dex", "webdex"],
            "mmtools": ["mmtools"],
            "mpm": ["mpm"],
            "NN Seed": ["nn_seed"],
            "No Gui": ["nogui"],
        }

    @property
    def DeFiVersions(self):
        return {}

    @property
    def DeFiDevices(self):
        return {
            "ios": ["iOS"],
            "web": ["Web"],
            "android": ["Android"],
            "darwin": ["Mac"],
            "linux": ["Linux"],
            "windows": ["Windows"],
        }


class Invert:
    def __init__(self):
        self._coins_config = None

    @property
    def coins_config(self):
        if self._coins_config is None:
            self._coins_config = memcache.get_coins_config()
        return self._coins_config

    def pair(self, pair_str, reduce=False):
        base, quote = derive.base_quote(pair_str, reverse=True, reduce=reduce)
        return f"{base}_{quote}"

    def trade_type(self, trade_type):
        if trade_type == "buy":
            return "sell"
        if trade_type == "sell":
            return "buy"
        raise ValueError

    def ask_bid(self, i):
        return {
            "price": convert.format_10f(
                Decimal(i["volume"]) / Decimal(i["quote_volume"])
            ),
            "volume": convert.format_10f(Decimal(i["quote_volume"])),
            "quote_volume": convert.format_10f(Decimal(i["volume"])),
        }

    def pair_orderbook(self, orderbook):
        try:
            orderbook.update(
                {
                    "pair": self.pair(orderbook["pair"]),
                    "base": orderbook["quote"],
                    "quote": orderbook["base"],
                    "base_liquidity_coins": orderbook["quote_liquidity_coins"],
                    "quote_liquidity_coins": orderbook["base_liquidity_coins"],
                    "base_liquidity_usd": orderbook["quote_liquidity_usd"],
                    "quote_liquidity_usd": orderbook["base_liquidity_usd"],
                    "base_price_usd": orderbook["quote_price_usd"],
                    "quote_price_usd": orderbook["base_price_usd"],
                    "asks": [self.ask_bid(i) for i in orderbook["bids"]],
                    "bids": [self.ask_bid(i) for i in orderbook["asks"]],
                    "total_asks_base_vol": orderbook["total_bids_quote_vol"],
                    "total_asks_quote_vol": orderbook["total_bids_base_vol"],
                    "total_asks_base_usd": orderbook["total_bids_quote_usd"],
                    "total_bids_base_vol": orderbook["total_asks_quote_vol"],
                    "total_bids_quote_vol": orderbook["total_asks_base_vol"],
                    "total_bids_quote_usd": orderbook["total_asks_base_usd"],
                }
            )
            if "variants" in orderbook:
                orderbook.update(
                    {
                        "variants": [self.pair(i) for i in orderbook["variants"]],
                    }
                )
            for i in [
                "highest_bid",
                "lowest_ask",
                "oldest_price_24hr",
                "newest_price_24hr",
                "highest_price_24hr",
                "lowest_price_24hr",
            ]:
                if Decimal(orderbook[i]) != 0:
                    orderbook[i] = 1 / Decimal(orderbook[i])

            orderbook.update(
                {
                    "price_change_24hr": convert.format_10f(
                        Decimal(orderbook["newest_price_24hr"])
                        - Decimal(orderbook["oldest_price_24hr"])
                    )
                }
            )
            if Decimal(orderbook["oldest_price_24hr"]) > 0:
                orderbook["price_change_pct_24hr"] = convert.format_10f(
                    Decimal(orderbook["newest_price_24hr"])
                    / Decimal(orderbook["oldest_price_24hr"])
                    - 1
                )
            else:
                orderbook["price_change_pct_24hr"] = convert.format_10f(0)
            return orderbook
        except Exception as e:  # pragma: no cover
            logger.warning(e)
        return orderbook

    def orderbook_fixture(self, orderbook):
        try:
            if "rel" in orderbook:
                quote = orderbook["rel"]
                total_asks_quote_vol = orderbook["total_asks_rel_vol"]["decimal"]
                total_bids_quote_vol = orderbook["total_bids_rel_vol"]["decimal"]
                total_asks_base_vol = orderbook["total_asks_base_vol"]["decimal"]
                total_bids_base_vol = orderbook["total_bids_base_vol"]["decimal"]
            if "quote" in orderbook:
                quote = orderbook["quote"]
                total_asks_quote_vol = orderbook["total_asks_quote_vol"]
                total_bids_quote_vol = orderbook["total_bids_quote_vol"]
                total_asks_base_vol = orderbook["total_asks_base_vol"]
                total_bids_base_vol = orderbook["total_bids_base_vol"]
            inverted = {
                "pair": f'{quote}_{orderbook["base"]}',
                "base": quote,
                "quote": orderbook["base"],
                "num_asks": len(orderbook["bids"]),
                "num_bids": len(orderbook["asks"]),
                "total_asks_base_vol": {"decimal": total_asks_quote_vol},
                "total_asks_rel_vol": {"decimal": total_asks_base_vol},
                "total_bids_base_vol": {"decimal": total_bids_quote_vol},
                "total_bids_rel_vol": {"decimal": total_bids_base_vol},
                "asks": [],
                "bids": [],
            }

            for i in orderbook["asks"]:
                inverted["bids"].append(
                    {
                        "coin": orderbook["rel"],
                        "price": {
                            "decimal": convert.format_10f(
                                1 / Decimal(i["price"]["decimal"])
                            )
                        },
                        "base_max_volume": {"decimal": i["rel_max_volume"]["decimal"]},
                        "rel_max_volume": {"decimal": i["base_max_volume"]["decimal"]},
                    }
                )
            for i in orderbook["bids"]:
                inverted["asks"].append(
                    {
                        "coin": orderbook["base"],
                        "price": {
                            "decimal": convert.format_10f(
                                1 / Decimal(i["price"]["decimal"])
                            )
                        },
                        "base_max_volume": {"decimal": i["rel_max_volume"]["decimal"]},
                        "rel_max_volume": {"decimal": i["base_max_volume"]["decimal"]},
                    }
                )
        except Exception as e:  # pragma: no cover
            logger.warning(e)
        return inverted


class FilterData:
    def __init__(self):
        pass

    @timed
    def dict_lists(self, data: dict, key: str, filter_value: str) -> Decimal:
        """
        list of key values from dicts.
        """
        return [i for i in data if i[key] == filter_value]


class Merge:
    def __init__(self):
        pass

    def swaps(self, variants, swaps):
        resp = []
        for i in variants:
            resp = resp + swaps[i]
        return sortdata.dict_lists(resp, "finished_at", reverse=True)

    def orderbooks(self, existing, new, gecko_source, trigger):
        try:
            existing.update(
                {
                    i: sumdata.dict_lists(existing[i], new[i], sort_key="price")
                    for i in ["asks", "bids"]
                }
            )

            numerics = [
                "liquidity_usd",
                "total_asks_base_vol",
                "total_bids_base_vol",
                "total_asks_quote_vol",
                "total_bids_quote_vol",
                "total_asks_base_usd",
                "total_bids_quote_usd",
                "base_liquidity_coins",
                "base_liquidity_usd",
                "quote_liquidity_coins",
                "quote_liquidity_usd",
                "trade_volume_usd",
            ]
            existing.update(
                {i: sumdata.decimals(existing[i], new[i]) for i in numerics}
            )
            existing["trades_24hr"] = sumdata.ints(
                existing["trades_24hr"], new["trades_24hr"]
            )
            existing = derive.lowest(existing, new, key="lowest_ask")
            existing = derive.lowest(existing, new, key="lowest_price_24hr")
            existing = derive.highest(existing, new, key="highest_bid")
            existing = derive.highest(existing, new, key="highest_price_24hr")
            existing = merge.newest_price(existing, new, "newest_price_24hr")
            existing = merge.oldest_price(existing, new, "oldest_price_24hr")

            existing["price_change_24hr"] = convert.format_10f(
                Decimal(existing["newest_price_24hr"])
                - Decimal(existing["oldest_price_24hr"])
            )
            if Decimal(existing["oldest_price_24hr"]) > 0:
                existing["price_change_pct_24hr"] = convert.format_10f(
                    Decimal(existing["newest_price_24hr"])
                    / Decimal(existing["oldest_price_24hr"])
                    - 1
                )
            else:
                existing["price_change_pct_24hr"] = convert.format_10f(0)
            existing.update(
                {
                    "base_price_usd": derive.gecko_price(
                        existing["base"], gecko_source=gecko_source
                    ),
                    "quote_price_usd": derive.gecko_price(
                        existing["quote"], gecko_source=gecko_source
                    ),
                }
            )
            return existing
        except Exception as e:  # pragma: no cover
            logger.error(existing)
            logger.warning(new)
            err = {"error": f"merge.orderbooks: {e}"}
            logger.warning(err)
        return existing

    def first_last_traded(self, all, variant, is_reversed=False):
        if variant["last_swap_time"] > all["last_swap_time"]:
            all["last_swap_time"] = variant["last_swap_time"]
            all["last_swap_price"] = variant["last_swap_price"]
            all["last_swap_uuid"] = variant["last_swap_uuid"]
            all["last_maker_amount"] = variant["last_maker_amount"]
            all["last_taker_amount"] = variant["last_taker_amount"]
            all["last_trade_type"] = variant["last_trade_type"]
            all["priced"] = variant["priced"]
            if is_reversed and all["last_swap_price"] != 0:
                all["last_swap_price"] = 1 / all["last_swap_price"]

        if (
            variant["first_swap_time"] < all["first_swap_time"]
            or all["first_swap_time"] == 0
        ):
            all["first_swap_time"] = variant["first_swap_time"]
            all["first_swap_price"] = variant["first_swap_price"]
            all["first_swap_uuid"] = variant["first_swap_uuid"]
            all["first_maker_amount"] = variant["first_maker_amount"]
            all["first_taker_amount"] = variant["first_taker_amount"]
            all["first_trade_type"] = variant["first_trade_type"]
            if is_reversed and all["first_swap_price"] != 0:
                all["first_swap_price"] = 1 / all["first_swap_price"]

        return all

    def trades(self, all, variant):
        all += variant["buy"]
        all += variant["sell"]
        return all

    def market_summary(self, existing, new):
        try:
            existing.update(
                {
                    "base_volume": sumdata.decimals(
                        existing["base_volume"], new["base_volume"]
                    ),
                    "quote_volume": sumdata.decimals(
                        existing["quote_volume"], new["quote_volume"]
                    ),
                    "trades_24hr": sumdata.ints(
                        existing["trades_24hr"], new["trades_24hr"]
                    ),
                    "variants": sumdata.lists(existing["variants"], new["variants"]),
                    "volume_usd_24hr": sumdata.decimals(
                        existing["volume_usd_24hr"], new["volume_usd_24hr"]
                    ),
                    "base_price_usd": new["base_price_usd"],
                    "quote_price_usd": new["quote_price_usd"],
                    "liquidity_usd": new["liquidity_usd"],
                }
            )
            existing["variants"] = sorted(list(set(existing["variants"])))
            if int(existing["last_swap"]) < int(new["last_swap"]):
                existing.update(
                    {
                        "last_price": new["last_price"],
                        "last_swap": new["last_swap"],
                        "last_swap_uuid": new["last_swap_uuid"],
                    }
                )
            existing = derive.lowest(existing, new, key="lowest_ask")
            existing = derive.lowest(existing, new, key="lowest_price_24hr")
            existing = derive.highest(existing, new, key="highest_bid")
            existing = derive.highest(existing, new, key="highest_price_24hr")
            existing = merge.newest_price(existing, new, key="newest_price_24hr")
            existing = merge.oldest_price(existing, new, key="oldest_price_24hr")

            existing["price_change_24hr"] = Decimal(new["newest_price_24hr"]) - Decimal(
                new["oldest_price_24hr"]
            )
            if Decimal(existing["oldest_price_24hr"]) != 0:
                existing["price_change_pct_24hr"] = convert.format_10f(
                    Decimal(existing["newest_price_24hr"])
                    / Decimal(existing["oldest_price_24hr"])
                    - 1
                )
            return existing
        except Exception as e:
            logger.warning(e)

    def orderbook_prices_data(self, prices_data: List, suffix="24hr") -> dict:
        existing = template.pair_prices_info(suffix=suffix)
        for new in prices_data:
            existing[f"trades_{suffix}"] = sumdata.ints(
                existing[f"trades_{suffix}"], new[f"trades_{suffix}"]
            )
            existing["trade_volume_usd"] = sumdata.decimals(
                existing["trade_volume_usd"], new["trade_volume_usd"]
            )
            existing = derive.lowest(existing, new, key=f"lowest_price_{suffix}")
            existing = derive.highest(existing, new, key=f"highest_price_{suffix}")
            existing = self.newest_price(existing, new, key=f"newest_price_{suffix}")
            existing = self.oldest_price(existing, new, key=f"oldest_price_{suffix}")

        existing[f"price_change_{suffix}"] = Decimal(
            existing[f"newest_price_{suffix}"]
        ) - Decimal(existing[f"oldest_price_{suffix}"])

        if Decimal(existing[f"oldest_price_{suffix}"]) > 0:
            existing[f"price_change_pct_{suffix}"] = convert.format_10f(
                Decimal(existing[f"newest_price_{suffix}"])
                / Decimal(existing[f"oldest_price_{suffix}"])
                - 1
            )
        else:
            existing[f"price_change_pct_{suffix}"] = convert.format_10f(0)
        return existing

    def newest_price(self, existing, new, key="newest_price"):
        """Updates to new values if more recent timestamp"""
        if (
            int(existing["newest_price_time"]) < int(new["newest_price_time"])
            or existing["newest_price_time"] == 0
        ):
            existing["newest_price_time"] = new["newest_price_time"]
            existing[key] = new[key]
        return existing

    def oldest_price(self, existing, new, key="oldest_price"):
        """Updates to new values if older timestamp"""
        if (
            int(existing["oldest_price_time"]) > int(new["oldest_price_time"])
            or existing["oldest_price_time"] == 0
        ):
            existing["oldest_price_time"] = new["oldest_price_time"]
            existing[key] = new[key]
        return existing


class SortData:
    def __init__(self):
        pass

    def dict_lists(self, data: List, key: str, reverse=False) -> dict:
        """
        Sort a list of dicts by the value of a key.
        """
        resp = sorted(data, key=lambda k: k[key], reverse=reverse)
        return resp

    def top_items(self, data: List[Dict], sort_key: str, length: int = 5):
        data.sort(key=lambda x: x[sort_key], reverse=True)
        return data[:length]

    @timed
    def pair_by_market_cap(self, pair_str: str, gecko_source) -> str:
        try:
            # TODO: If gecko source is none, compare with db pairs.
            base, quote = derive.base_quote(pair_str)
            if gecko_source is None:
                gecko_source = memcache.get_gecko_source()
            if gecko_source is None:
                # We want this to error out rather than return the alphabetic
                # ticker otherwise it may enter the DB incorrectly if the
                # gecko data is not yet available
                logger.warning(f"Unable to get mcap for {pair_str}, gecko source is None!")
                return None
            base_mc = derive.gecko_mcap(base, gecko_source)
            quote_mc = derive.gecko_mcap(quote, gecko_source)
            # Generalise the MCAP so coins very close in value
            # dont flip ticker order too often. 
            if len(str(int(base_mc))) == len(str(int(quote_mc))):
                div = len(str(int(quote_mc)))
                base_mc = int(base_mc / Decimal(10 ** (div - 2)))
                quote_mc = int(quote_mc / Decimal(10 ** (div - 2)))

            # Sort by mcap
            if int(quote_mc) < int(base_mc):
                return invert.pair(pair_str)

            # Sort alphabetically
            elif quote_mc == base_mc:
                return "_".join(sorted([base, quote]))
            # sort by mcap
            else:
                return pair_str    
            
        except Exception as e:  # pragma: no cover
            msg = f"pair_by_market_cap failed: {e}"
            logger.warning(msg)
            return None
        


class SumData:
    def __init__(self):
        pass

    def decimals(self, x, y):
        try:
            return Decimal(x) + Decimal(y)
        except Exception as e:  # pragma: no cover
            logger.warning(f"{type(e)}: {e}")
            logger.warning(f"x: {x} ({type(x)})")
            logger.warning(f"y: {y} ({type(y)})")
            raise ValueError

    def numeric_str(self, x, y):
        return convert.format_10f(self.decimals(x, y))

    def lists(self, x, y):
        try:
            data = x + y
            if True in [isinstance(i, dict) for i in data]:
                return data
            return sorted(list(set(data)))
        except Exception as e:  # pragma: no cover
            logger.warning(f"{type(e)}: {e}")
            logger.warning(f"x: {x} ({type(x)})")
            logger.warning(f"y: {y} ({type(y)})")
            raise ValueError

    def dict_lists(self, x, y, sort_key=None):
        try:
            if sort_key:
                merged_list = self.lists(x, y)
                if True in [sort_key in i for i in merged_list]:
                    return sortdata.dict_lists(merged_list, sort_key)
                return merged_list
            return self.lists(x, y)
        except Exception as e:  # pragma: no cover
            logger.warning(f"{type(e)}: {e}")
            logger.warning(f"x: {x} ({type(x)})")
            logger.warning(f"y: {y} ({type(y)})")
            raise ValueError

    def ints(self, x, y):
        try:
            return int(Decimal(x)) + int(Decimal(y))
        except Exception as e:  # pragma: no cover
            logger.warning(f"{type(e)}: {e}")
            logger.warning(f"x: {x} ({type(x)})")
            logger.warning(f"y: {y} ({type(y)})")
            raise ValueError

    def json_key(self, data: dict, key: str) -> Decimal:
        """
        Sum a key from a list of dicts.
        """
        return sum(Decimal(d[key]) for d in data)

    def json_key_10f(self, data: dict, key: str) -> str:
        """
        Sum a key from a list of dicts and format to 10 decimal places.
        """
        return convert.format_10f(self.json_key(data, key))


class Templates:  # pragma: no cover
    def __init__(self) -> None:
        self._coins_config = None

    @property
    def coins_config(self):
        if self._coins_config is None:
            self._coins_config = memcache.get_coins_config()
        return self._coins_config

    def gecko_orderbook(self, pair_str: str) -> dict:
        base, quote = derive.base_quote(pair_str=pair_str)
        return {
            "ticker_id": pair_str,
            "timestamp": int(cron.now_utc()),
            "bids": [],
            "asks": [],
            "variants": [pair_str],
        }

    def gecko_pair_item(self, pair_str: str) -> dict:
        base, quote = derive.base_quote(pair_str=pair_str)
        return {
            "ticker_id": pair_str,
            "pool_id": pair_str,
            "base": base,
            "target": quote,
            "variants": derive.pair_variants(pair_str=pair_str),
        }

    def pair_info(self, pair_str: str, priced: bool = False) -> dict:
        base, quote = derive.base_quote(pair_str)
        return {
            "ticker_id": pair_str,
            "base": base,
            "target": quote,
            "last_swap_time": 0,
            "last_swap_price": 0,
            "last_swap_uuid": "",
            "priced": priced,
        }

    def orderbook_rpc_resp(self, base, quote):
        return {
            "base": base,
            "rel": quote,
            "num_asks": 0,
            "num_bids": 0,
            "total_asks_base_vol": {"decimal": "0"},
            "total_asks_rel_vol": {"decimal": "0"},
            "total_bids_base_vol": {"decimal": "0"},
            "total_bids_rel_vol": {"decimal": "0"},
            "asks": [],
            "bids": [],
            "net_id": 6133,
            "timestamp": 1694183345,
        }

    def orderbook_extended(self, pair_str):
        base, quote = derive.base_quote(pair_str)
        data = {
            "pair": f"{base}_{quote}",
            "base": base,
            "base_price_usd": 0,
            "quote": quote,
            "quote_price_usd": 0,
            "liquidity_usd": 0,
            "highest_bid": 0,
            "lowest_ask": 0,
            "liquidity_usd": 0,
            "total_asks_base_vol": 0,
            "total_bids_base_vol": 0,
            "total_asks_quote_vol": 0,
            "total_bids_quote_vol": 0,
            "total_asks_base_usd": 0,
            "total_bids_quote_usd": 0,
            "base_liquidity_coins": 0,
            "base_liquidity_usd": 0,
            "quote_liquidity_coins": 0,
            "quote_liquidity_usd": 0,
            "oldest_price_24hr": 0,
            "oldest_price_time": 0,
            "newest_price_24hr": 0,
            "newest_price_time": 0,
            "highest_price_24hr": 0,
            "lowest_price_24hr": 0,
            "price_change_pct_24hr": 0,
            "price_change_24hr": 0,
            "trades_24hr": 0,
            "trade_volume_usd": 0,
            "asks": [],
            "bids": [],
            "timestamp": f"{int(cron.now_utc())}",
        }
        return data

    def timespan_stats(self):
        return {
            "volume_usd_24hr": 0,
            "trades_24hr": 0,
            "price_change_pct_24hr": 0,
            "price_change_24hr": 0,
            "highest_price_24hr": 0,
            "lowest_price_24hr": 0,
            "volume_usd_7d": 0,
            "trades_7d": 0,
            "price_change_pct_7d": 0,
            "price_change_7d": 0,
            "highest_price_7d": 0,
            "lowest_price_7d": 0,
            "volume_usd_14d": 0,
            "trades_14d": 0,
            "price_change_pct_14d": 0,
            "price_change_14d": 0,
            "highest_price_14d": 0,
            "lowest_price_14d": 0,
            "volume_usd_30d": 0,
            "trades_30d": 0,
            "price_change_pct_30d": 0,
            "price_change_30d": 0,
            "highest_price_30d": 0,
            "lowest_price_30d": 0,
        }

    def gecko_info(self, coin_id):
        return {"usd_market_cap": 0, "usd_price": 0, "coingecko_id": coin_id}

    def pair_prices_info(self, suffix):
        return {
            f"oldest_price_{suffix}": 0,
            "oldest_price_time": 0,
            f"newest_price_{suffix}": 0,
            "newest_price_time": 0,
            f"highest_price_{suffix}": 0,
            f"lowest_price_{suffix}": 0,
            f"price_change_pct_{suffix}": 0,
            f"price_change_{suffix}": 0,
            "base_price_usd": 0,
            "quote_price_usd": 0,
            f"trades_{suffix}": 0,
            "trade_volume_usd": 0,
            "last_swap_uuid": "",
        }

    def volumes_ticker(self):
        return {
            "taker_swaps": 0,
            "maker_swaps": 0,
            "total_swaps": 0,
            "taker_volume": 0,
            "maker_volume": 0,
            "total_volume": 0,
            "taker_volume_usd": 0,
            "maker_volume_usd": 0,
            "trade_volume_usd": 0,
        }

    def ticker_info(self, suffix, base, quote):
        return {
            "ticker_id": f"{base}_{quote}",
            "base_currency": base,
            "base_liquidity_coins": 0,
            "base_liquidity_usd": 0,
            "base_price_usd": 0,
            "quote_currency": quote,
            "quote_liquidity_coins": 0,
            "quote_liquidity_usd": 0,
            "quote_price_usd": 0,
            "liquidity_usd": 0,
            "last_swap_price": 0,
            "last_swap_uuid": "",
            "last_swap_time": 0,
            "oldest_price": 0,
            "oldest_price_time": 0,
            "newest_price": 0,
            "newest_price_time": 0,
            f"highest_price_{suffix}": 0,
            f"lowest_price_{suffix}": 0,
            f"price_change_pct_{suffix}": 0,
            f"price_change_{suffix}": 0,
            "highest_bid": 0,
            "lowest_ask": 0,
            "priced": False,
        }

    def coin_trade_vol_item(self):
        return {
            "taker_swaps": 0,
            "maker_swaps": 0,
            "total_swaps": 0,
            "taker_volume": 0,
            "maker_volume": 0,
            "total_volume": 0,
            "taker_volume_usd": 0,
            "maker_volume_usd": 0,
            "trade_volume_usd": 0,
        }

    def first_last_traded(self):
        return {
            "first_swap_time": 0,
            "first_swap_price": 0,
            "first_swap_uuid": "",
            "first_maker_amount": 0,
            "first_taker_amount": 0,
            "first_trade_type": "",
            "last_swap_time": 0,
            "last_swap_price": 0,
            "last_swap_uuid": "",
            "last_maker_amount": 0,
            "last_taker_amount": 0,
            "last_trade_type": "",
            "priced": None,
        }

    def pair_volume_item(self, suffix="24hr"):
        return {
            "base_volume": 0,
            "quote_volume": 0,
            f"trades_{suffix}": 0,
            "base_volume_usd": 0,
            "quote_volume_usd": 0,
            "trade_volume_usd": 0,
            "dex_price": 0,
        }

    def last_trade_info(self):
        return {
            "swap_count": 0,
            "sum_taker_traded": 0,
            "sum_maker_traded": 0,
            "last_swap": 0,
            "last_swap_price": 0,
            "last_swap_uuid": "",
            "last_taker_amount": 0,
            "last_maker_amount": 0,
        }

    def last_traded_item(self):
        return {
            "total_num_swaps": 0,
            "maker_num_swaps": 0,
            "taker_num_swaps": 0,
            "maker_last_swap_uuid": 0,
            "maker_last_swap_time": 0,
            "taker_last_swap_uuid": 0,
            "taker_last_swap_time": 0,
        }

    def markets_summary(self, pair_str):
        base, quote = derive.base_quote(pair_str=pair_str)
        return {
            "pair": pair_str,
            "base_currency": base,
            "quote_currency": quote,
            "base_volume": 0,
            "quote_volume": 0,
            "lowest_ask": 0,
            "highest_bid": 0,
            "lowest_price_24hr": 0,
            "highest_price_24hr": 0,
            "price_change_pct_24hr": 0,
            "oldest_price_24hr": 0,
            "oldest_price_time": 0,
            "newest_price_24hr": 0,
            "newest_price_time": 0,
            "last_price": 0,
            "last_swap": 0,
            "last_swap_uuid": "",
            "variants": [],
            "trades_24hr": 0,
            "base_price_usd": 0,
            "quote_price_usd": 0,
            "liquidity_usd": 0,
            "volume_usd_24hr": 0,
            "price_change_24hr": 0,
        }

    def markets_ticker(self, variant, variant_data):
        return {
            variant: {
                "last_price": Decimal(variant_data["newest_price_24hr"]),
                "last_price_time": Decimal(variant_data["newest_price_time"]),
                "quote_volume": Decimal(variant_data["quote_liquidity_coins"]),
                "base_volume": Decimal(variant_data["base_liquidity_coins"]),
                "isFrozen": "0",
            }
        }


template = Templates()
clean = Clean()
convert = Convert()
deplatform = Deplatform()
derive = Derive()
filterdata = FilterData()
invert = Invert()
merge = Merge()
sortdata = SortData()
sumdata = SumData()
