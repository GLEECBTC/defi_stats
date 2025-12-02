#!/usr/bin/env python3
import time
from decimal import Decimal
from lib.coins import Coins
from lib.cmc import CmcAPI
from lib.pair import Pair
from util.cron import cron
from util.logger import logger, timed
from util.transform import (
    clean,
    derive,
    merge,
    template,
    convert,
    deplatform,
    sortdata,
    invert,
)
import db.sqldb as db
import lib.prices
import util.defaults as default
import util.memcache as memcache
from lib.external import gecko_api
from const import (
    ORDERBOOK_FETCH_BATCH_SIZE,
    ORDERBOOK_FETCH_LOOP_SLEEP,
)


ORDERBOOK_QUEUE_POINTER_KEY = "orderbook_fetch_queue_idx"
ORDERBOOK_BATCH_LOCK_KEY = "orderbook_fetch_in_progress"
ORDERBOOK_BATCH_LOCK_TTL = 300


class CacheCalc:
    def __init__(
        self,
        coins_config=None,
        gecko_source=None,
        pairs_last_traded_cache=None,
        pair_prices_24hr_cache=None,
        pairs_orderbook_extended_cache=None,
        pair_volumes_24hr_cache=None,
        coin_volumes_alltime_cache=None
    ) -> None:
        self._priced_coins = None
        self._coins_obj = None
        self._coins_config = coins_config
        self._gecko_source = gecko_source
        self._pairs_last_traded_cache = pairs_last_traded_cache
        self._pairs_orderbook_extended_cache = pairs_orderbook_extended_cache
        self._pair_prices_24hr_cache = pair_prices_24hr_cache
        self._pair_volumes_24hr_cache = pair_volumes_24hr_cache
        self._coin_volumes_alltime_cache = coin_volumes_alltime_cache

    @property
    def pg_query(self):
        return db.SqlQuery(gecko_source=self.gecko_source)

    @property
    def coins_obj(self):
        if self._coins_obj is None:
            return Coins(coins_config=self.coins_config, gecko_source=self.gecko_source)
        return self._coins_obj

    @property
    def priced_coins(self):
        if self._priced_coins is None:
            self._priced_coins = self.coins_obj.with_price
        return self._priced_coins

    @property
    def coins_config(self):
        if self._coins_config is None:
            self._coins_config = memcache.get_coins_config()
        return self._coins_config

    @property
    def gecko_source(self):
        if self._gecko_source is None:
            self._gecko_source = memcache.get_gecko_source()
        if self._gecko_source is None:
            logger.calc("sourcing gecko from upstream API")
            self._gecko_source = gecko_api.get_source_data(from_file=True)
        return self._gecko_source

    @property
    def coin_volumes_24hr_cache(self):
        if self._coin_volumes_24hr_cache is None:
            # logger.info("Getting _coin_volumes_24hr_cache")
            self._coin_volumes_24hr_cache = memcache.get_coin_volumes_24hr()
        return self._coin_volumes_24hr_cache

    @timed
    def coin_volumes_24hr(self):
        try:
            vols = self.pg_query.coin_trade_volumes()
            vols_usd = self.pg_query.coin_trade_vols_usd(vols)
            for coin in vols_usd["volumes"]:
                for variant in vols_usd["volumes"][coin]:
                    vols_usd["volumes"][coin][variant] = clean.decimal_dicts(
                        vols_usd["volumes"][coin][variant]
                    )
            vols_usd = clean.decimal_dicts(vols_usd)
            msg = "coin_volumes_24hr complete!"
            return default.result(vols_usd, msg, loglevel="loop", ignore_until=3)
        except Exception as e:  # pragma: no cover
            msg = f"coin_volumes_24hr failed! {e}"
            logger.warning(msg)

    @property
    def coin_volumes_alltime_cache(self):
        if self._coin_volumes_alltime_cache is None:
            # logger.info("Getting _coin_volumes_alltime")
            self._coin_volumes_alltime_cache = memcache.get_coin_volumes_alltime()
        return self._coin_volumes_alltime_cache

    @timed
    def coin_volumes_alltime(self):
        try:
            now = cron.now_utc()
            logger.info(now)
            vols = self.pg_query.coin_trade_volumes(
                start_time=1,
                end_time=now,
            )
            logger.info(len(vols))
            vols_usd = self.pg_query.coin_trade_vols_usd(vols)
            logger.info(len(vols_usd))
            for coin in vols_usd["volumes"]:
                for variant in vols_usd["volumes"][coin]:
                    vols_usd["volumes"][coin][variant] = clean.decimal_dicts(
                        vols_usd["volumes"][coin][variant]
                    )
            vols_usd = clean.decimal_dicts(vols_usd)
            msg = "coin_volumes_alltime complete!"
            return default.result(vols_usd, msg, loglevel="loop", ignore_until=3)
        except Exception as e:  # pragma: no cover
            msg = f"coin_volumes_alltime failed! {e}"
            logger.warning(msg)

    @property
    def pairs_last_traded_cache(self):
        if self._pairs_last_traded_cache is None:
            self._pairs_last_traded_cache = memcache.get_pairs_last_traded()
        return self._pairs_last_traded_cache

    @timed
    def pairs_last_traded(self, since=0):
        try:
            data = self.pg_query.pair_last_trade(since=since)
            for i in data:
                data[i] = clean.decimal_dicts(data[i])
                data[i].update({"priced": i in self.coins_obj.with_price})
            resp = {}
            for variant in data:
                depair = deplatform.pair(variant)
                if depair not in resp:
                    resp.update({depair: {"ALL": template.first_last_traded()}})
                resp[depair].update({variant: data[variant]})
                all = resp[depair]["ALL"]
                x = resp[depair][variant]
                all = merge.first_last_traded(all, x)
            msg = "pairs_last_traded complete!"
            return default.result(resp, msg, loglevel="loop", ignore_until=3)
        except Exception as e:  # pragma: no cover
            msg = f"pairs_last_traded failed! {e}"
            logger.warning(msg)

    @property
    def pair_prices_24hr_cache(self):
        if self._pair_prices_24hr_cache is None:
            # logger.loop("sourcing pair_prices_24hr_cache")
            self._pair_prices_24hr_cache = memcache.get_pair_prices_24hr()
        return self._pair_prices_24hr_cache

    @timed
    # TODO: Expand to 7d, 14d, 30d etc
    def pair_prices_24hr(self, days=1, from_memcache: bool = False):
        return lib.prices.pair_prices(days=days, from_memcache=from_memcache)

    @property
    def pairs_orderbook_extended_cache(self):
        if self._pairs_orderbook_extended_cache is None:
            # logger.loop("sourcing pairs_orderbook_extended_cache")
            self._pairs_orderbook_extended_cache = (
                memcache.get_pairs_orderbook_extended()
            )
        return self._pairs_orderbook_extended_cache

    @timed
    def pairs_orderbook_extended(self, pairs_days: int = 21, refresh: bool = False):
        try:
            if not self._acquire_batch_lock():
                logger.loop("[orderbook-batch] skipped: batch already running")
                return default.result(
                    {
                        "pairs_count": 0,
                        "swaps_24hr": 0,
                        "volume_usd_24hr": 0,
                        "combined_liquidity_usd": 0,
                        "orderbooks": {},
                        "pointer_start": None,
                        "pointer_next": None,
                        "pairs": [],
                    },
                    msg="Batch in progress, skipping duplicate run",
                    loglevel="loop",
                    ignore_until=0,
                )
            # Filter out pairs older than requested time
            ts = cron.now_utc() - pairs_days * 86400
            depairs = derive.pairs_traded_since(ts, self.pairs_last_traded_cache)
            traded_pairs = derive.pairs_traded_since(
                ts, self.pairs_last_traded_cache, reduced=False
            )
            volumes_cache = self.pair_volumes_24hr_cache or {}
            volumes_map = volumes_cache.get("volumes") or {}

            eligible_pairs = self._build_sorted_eligible_pairs(depairs, volumes_map)

            if len(eligible_pairs) == 0:
                msg = (
                    "pairs_orderbook_extended skipped: no pairs traded "
                    f"in the last {pairs_days} days"
                )
                return default.result(
                    {
                        "pairs_count": 0,
                        "swaps_24hr": 0,
                        "volume_usd_24hr": 0,
                        "combined_liquidity_usd": 0,
                        "orderbooks": {},
                    },
                    msg=msg,
                    loglevel="loop",
                    ignore_until=0,
                )

            total_pairs = len(eligible_pairs)
            batch_pairs, pointer_idx = self._select_pair_batch(eligible_pairs)
            logger.loop(
                f"[orderbook-batch-pointer] start_idx={pointer_idx['start']} next_idx={pointer_idx['next']}"
            )
            logger.loop(f"[orderbook-batch-detail] pairs={batch_pairs}")
            from lib import dex_api  # local import to avoid circular dependency

            with dex_api._ORDERBOOK_CACHE_STATS_LOCK:  # pylint: disable=protected-access
                dex_api._ORDERBOOK_CACHE_STATS["processed"] = 0
                dex_api._ORDERBOOK_CACHE_STATS["skipped"] = 0
                dex_api._ORDERBOOK_CACHE_STATS["total"] = max(total_pairs, 1)
                dex_api._ORDERBOOK_CACHE_STATS["pointer"] = pointer_idx["start"]
            if len(batch_pairs) == 0:
                msg = "pairs_orderbook_extended skipped: batch selection returned zero pairs"
                return default.result(
                    {
                        "pairs_count": 0,
                        "swaps_24hr": 0,
                        "volume_usd_24hr": 0,
                        "combined_liquidity_usd": 0,
                        "orderbooks": {},
                    },
                    msg=msg,
                    loglevel="loop",
                    ignore_until=0,
                )

            data = []
            processed = 0
            batch_start = time.perf_counter()
            for depair in batch_pairs:
                x = Pair(
                    pair_str=depair,
                    coins_config=self.coins_config,
                    gecko_source=self.gecko_source,
                    pair_prices_24hr_cache=self.pair_prices_24hr_cache,
                ).orderbook(
                    depair, depth=100, traded_pairs=batch_pairs, refresh=refresh
                )
                data.append(x)
                processed += 1
                if ORDERBOOK_FETCH_LOOP_SLEEP > 0:
                    time.sleep(ORDERBOOK_FETCH_LOOP_SLEEP)
            batch_duration = time.perf_counter() - batch_start
            orderbook_data = {}
            liquidity_usd = 0
            for book in data:
                depair = deplatform.pair(book["ALL"]["pair"])
                # Exclude if no activity
                if depair not in orderbook_data:
                    if (
                        Decimal(book["ALL"]["liquidity_usd"]) > 0
                        or Decimal(book["ALL"]["trade_volume_usd"]) > 0
                    ):
                        orderbook_data.update({depair: {}})
                    else:
                        continue
                for variant in book:
                    if book[variant] is not None:
                        # Exclude if no activity
                        if (
                            Decimal(book[variant]["liquidity_usd"]) > 0
                            or Decimal(book[variant]["trade_volume_usd"]) > 0
                        ):
                            orderbook_data[depair].update(
                                {variant: clean.decimal_dicts(book[variant])}
                            )
                liquidity_usd += Decimal(book["ALL"]["liquidity_usd"])

            vols_24hr = self.pair_volumes_24hr()
            if vols_24hr is not None:
                swaps_24hr = vols_24hr["total_swaps"]
                volume_usd_24hr = vols_24hr["trade_volume_usd"]

            resp = clean.decimal_dicts(
                {
                    "pairs_count": len(data),
                    "swaps_24hr": swaps_24hr,
                    "volume_usd_24hr": volume_usd_24hr,
                    "combined_liquidity_usd": liquidity_usd,
                    "orderbooks": orderbook_data,
                }
            )

            msg = (
                f"pairs_orderbook_extended processed {processed}/{len(eligible_pairs)} "
                f"eligible pairs (from {len(traded_pairs)} traded in last {pairs_days}d) "
                f"in {batch_duration:.2f}s"
            )
            avg_time = batch_duration / processed if processed else 0
            logger.loop(
                f"[orderbook-batch] size={processed} duration={batch_duration:.2f}s "
                f"avg_per_pair={avg_time:.2f}s"
            )
            return default.result(resp, msg, loglevel="calc", ignore_until=3)
        except Exception as e:  # pragma: no cover
            msg = "pairs_orderbook_extended failed!"
            return default.error(e, msg)
        finally:
            # Some time to let KDF breathe before the next batch
            time.sleep(5)
            self._release_batch_lock()

    @property
    def pair_volumes_24hr_cache(self):
        if self._pair_volumes_24hr_cache is None:
            # logger.loop("sourcing pair_volumes_24hr_cache")
            self._pair_volumes_24hr_cache = memcache.get_pair_volumes_24hr()
        return self._pair_volumes_24hr_cache

    @timed
    def pair_volumes_24hr(self):
        try:
            vols = self.pg_query.pair_trade_volumes()
            vols_usd = self.pg_query.pair_trade_vols_usd(vols)
            for pair_str in vols_usd["volumes"]:
                for variant in vols_usd["volumes"][pair_str]:
                    vols_usd["volumes"][pair_str][variant] = clean.decimal_dicts(
                        vols_usd["volumes"][pair_str][variant]
                    )
            vols_usd = clean.decimal_dicts(vols_usd)
            msg = "pair_volumes_24hr complete!"
            return default.result(vols_usd, msg, loglevel="loop", ignore_until=3)
        except Exception as e:  # pragma: no cover
            msg = f"pair_volumes_24hr failed! {e}"
            logger.warning(msg)

    @timed
    def pair_volumes_timespan(self, start_time=None, end_time=None):
        try:
            # Defaults to 14 days
            if start_time is None:
                start_time = int(cron.now_utc()) - 86400 * 14
            if end_time is None:
                end_time = int(cron.now_utc())
            vols = self.pg_query.pair_trade_volumes(
                start_time=start_time, end_time=end_time
            )
            vols_usd = self.pg_query.pair_trade_vols_usd(vols)
            for pair_str in vols_usd["volumes"]:
                for variant in vols_usd["volumes"][pair_str]:
                    vols_usd["volumes"][pair_str][variant] = clean.decimal_dicts(
                        vols_usd["volumes"][pair_str][variant]
                    )
            vols_usd = clean.decimal_dicts(vols_usd)
            msg = "pair_volumes_timespan complete!"
            return default.result(vols_usd, msg, loglevel="loop", ignore_until=3)
        except Exception as e:  # pragma: no cover
            msg = f"pair_volumes_timespan failed! {e}"
            logger.warning(msg)

    # TODO: Add props for the below

    def _pair_activity_score(self, depair: str, volumes_map) -> Decimal:
        if not volumes_map:
            return Decimal("0")
        pair_data = volumes_map.get(depair) or volumes_map.get(invert.pair(depair))
        if not pair_data:
            return Decimal("0")
        best = Decimal("0")
        for variant in pair_data.values():
            try:
                trade_usd = Decimal(str(variant.get("trade_volume_usd", 0) or 0))
            except Exception:
                trade_usd = Decimal(0)
            if trade_usd > best:
                best = trade_usd
        return best

    def _build_sorted_eligible_pairs(self, depairs, volumes_map):
        ranked = []
        for depair in depairs:
            sorted_pair = sortdata.pair_by_market_cap(
                depair, gecko_source=self.gecko_source
            )
            score = self._pair_activity_score(sorted_pair, volumes_map)
            ranked.append((sorted_pair, score))
        ranked.sort(key=lambda item: item[1], reverse=True)
        return [pair for pair, _ in ranked]

    def _select_pair_batch(self, pairs):
        if not pairs:
            return ([], {"start": 0, "next": 0})
        pointer = memcache.get(ORDERBOOK_QUEUE_POINTER_KEY)
        try:
            pointer = int(pointer)
        except (TypeError, ValueError):
            pointer = 0
        pointer = pointer % len(pairs)
        batch = []
        idx = pointer
        processed = 0
        batch_size = min(ORDERBOOK_FETCH_BATCH_SIZE, len(pairs))
        while processed < batch_size:
            batch.append(pairs[idx])
            idx = (idx + 1) % len(pairs)
            processed += 1
            if idx == pointer:
                break
        memcache.update(ORDERBOOK_QUEUE_POINTER_KEY, idx, 3600)
        return batch, {"start": pointer, "next": idx}

    def _acquire_batch_lock(self):
        try:
            return memcache.MEMCACHE.add(
                ORDERBOOK_BATCH_LOCK_KEY, True, ORDERBOOK_BATCH_LOCK_TTL
            )
        except Exception:
            return False

    def _release_batch_lock(self):
        try:
            memcache.MEMCACHE.delete(ORDERBOOK_BATCH_LOCK_KEY)
        except Exception:
            pass

    @timed
    def markets_summary(self):
        try:
            resp = []
            data = {}
            book = self.pairs_orderbook_extended_cache
            vols = self.pair_volumes_24hr_cache
            last = self.pairs_last_traded_cache
            prices = self.pair_prices_24hr_cache
            if None not in [self.coins_config, book, vols, last, prices]:

                for depair in book["orderbooks"]:
                    base, quote = derive.base_quote(depair)
                    for variant in book["orderbooks"][depair]:
                        segwit_variants = derive.pair_variants(
                            variant, segwit_only=True
                        )
                        variant = variant.replace("-segwit", "")
                        if variant == "ALL":
                            continue
                        else:
                            existing = template.markets_summary(pair_str=variant)
                        if variant not in data:
                            for i in segwit_variants:
                                o = template.orderbook_extended(pair_str=variant)
                                if i in book["orderbooks"][depair]:
                                    o = book["orderbooks"][depair][i]
                                v = template.pair_volume_item(suffix="24hr")
                                if depair in vols["volumes"]:
                                    if i in vols["volumes"][depair]:
                                        v = vols["volumes"][depair][i]
                                p = template.pair_prices_info(suffix="24hr")
                                if depair in prices:
                                    if i in prices[depair]:
                                        p = prices[depair][i]
                                lt = template.first_last_traded()
                                if depair in last:
                                    if i in last[depair]:
                                        lt = last[depair][i]
                                new = {
                                    "base_price_usd": p["base_price_usd"],
                                    "quote_price_usd": p["quote_price_usd"],
                                    "lowest_price_24hr": p["lowest_price_24hr"],
                                    "highest_price_24hr": p["highest_price_24hr"],
                                    "price_change_24hr": p["price_change_24hr"],
                                    "price_change_pct_24hr": p["price_change_pct_24hr"],
                                    "trades_24hr": v["trades_24hr"],
                                    "base_volume": v["base_volume"],
                                    "quote_volume": v["quote_volume"],
                                    "volume_usd_24hr": v["trade_volume_usd"],
                                    "last_price": lt["last_swap_price"],
                                    "last_swap": lt["last_swap_time"],
                                    "last_swap_uuid": lt["last_swap_uuid"],
                                    "lowest_ask": o["lowest_ask"],
                                    "highest_bid": o["highest_bid"],
                                    "liquidity_usd": o["liquidity_usd"],
                                    "newest_price_24hr": o["newest_price_24hr"],
                                    "newest_price_time": o["newest_price_time"],
                                    "oldest_price_24hr": o["oldest_price_24hr"],
                                    "oldest_price_time": o["oldest_price_time"],
                                    "variants": segwit_variants,
                                }
                                merged = merge.market_summary(existing, new)
                                existing = clean.decimal_dicts(merged)
                            # remove where no past trades detected
                            if lt["last_swap_uuid"] != "":
                                data.update({variant: existing})
                    resp = [i for i in data.values()]
            return resp
        except Exception as e:  # pragma: no cover
            logger.warning(f"{type(e)} Error in [/api/v3/market/summary]: {e}")
            return {"error": f"{type(e)} Error in [/api/v3/market/summary]: {e}"}

    @timed
    def stats_api_summary(self, refresh: bool = False):
        try:
            resp = memcache.get_stats_api_summary()
            if refresh:
                resp = []
                book = self.pairs_orderbook_extended_cache
                vols = self.pair_volumes_24hr_cache
                last = self.pairs_last_traded_cache
                prices = self.pair_prices_24hr_cache
                if None not in [book, vols, last, prices]:
                    for depair in book["orderbooks"]:
                        o = book["orderbooks"][depair]["ALL"]
                        lt = template.first_last_traded()
                        p = template.pair_prices_info(suffix="24hr")
                        v = template.pair_volume_item(suffix="24hr")

                        if depair in vols["volumes"]:
                            if "ALL" in vols["volumes"][depair]:
                                v = vols["volumes"][depair]["ALL"]
                        if depair in prices:
                            if "ALL" in prices[depair]:
                                p = prices[depair]["ALL"]
                        if depair in last:
                            if "ALL" in last[depair]:
                                lt = last[depair]["ALL"]
                        variants = derive.pair_variants(pair_str=depair)
                        data = clean.decimal_dicts(
                            {
                                "ticker_id": depair,
                                "trading_pair": depair,
                                "base_currency": o["base"],
                                "base_trade_value_usd": v["base_volume_usd"],
                                "base_liquidity_coins": o["base_liquidity_coins"],
                                "base_liquidity_usd": o["base_liquidity_usd"],
                                "base_volume": v["base_volume"],
                                "volume_usd_24h": v["trade_volume_usd"],
                                "pair_trade_value_usd": v["trade_volume_usd"],
                                "quote_currency": o["quote"],
                                "quote_trade_value_usd": v["quote_volume_usd"],
                                "quote_liquidity_coins": o["quote_liquidity_coins"],
                                "quote_liquidity_usd": o["quote_liquidity_usd"],
                                "quote_volume": v["quote_volume"],
                                "rel_currency": o["quote"],
                                "rel_trade_value_usd": v["quote_volume_usd"],
                                "rel_liquidity_coins": o["quote_liquidity_coins"],
                                "rel_liquidity_usd": o["quote_liquidity_usd"],
                                "rel_volume": v["quote_volume"],
                                "lowest_ask": o["lowest_ask"],
                                "highest_bid": o["highest_bid"],
                                "lowest_price_24h": o["lowest_price_24hr"],
                                "highest_price_24h": o["highest_price_24hr"],
                                "price_change_24h": o["price_change_24hr"],
                                "price_change_percent_24h": o["price_change_pct_24hr"],
                                "newest_price": o["newest_price_24hr"],
                                "newest_price_time": o["newest_price_time"],
                                "oldest_price": o["oldest_price_24hr"],
                                "oldest_price_time": o["oldest_price_time"],
                                "last_price": lt["last_swap_price"],
                                "last_trade": lt["last_swap_time"],
                                "last_swap_uuid": lt["last_swap_uuid"],
                                "pair_swaps_count": o["trades_24hr"],
                                "pair_liquidity_usd": o["liquidity_usd"],
                                "base_price_usd": p["base_price_usd"],
                                "quote_price_usd": p["quote_price_usd"],
                                "rel_price_usd": p["quote_price_usd"],
                                "variants": variants,
                            }
                        )
                        # remove where no past trades detected
                        if lt["last_swap_uuid"] != "":
                            resp.append(data)
            return resp
        except Exception as e:  # pragma: no cover
            logger.warning(f"{type(e)} Error in [/api/v3/stats_api/summary]: {e}")
            return {"error": f"{type(e)} Error in [/api/v3/stats_api/summary]: {e}"}

    @timed
    def gecko_pairs(self, refresh: bool = False):
        resp = memcache.get_gecko_pairs()
        if resp is None or refresh:
            cache = self.pairs_last_traded_cache
            if None not in [self.coins_config, cache]:
                ts = cron.now_utc() - 86400 * 7
                pairs = derive.pairs_traded_since(ts=ts, pairs_last_traded_cache=cache)
                resp = [template.gecko_pair_item(i) for i in pairs]
        return resp

    def adex_24hr(self, refresh=False):
        try:
            data = memcache.get_adex_24hr()
            if data is None or refresh:
                books = self.pairs_orderbook_extended_cache
                vols = self.pair_volumes_24hr_cache
                if None not in [books, vols]:
                    top_vol = derive.top_pairs_by_volume(vols)
                    top_swaps = derive.top_pairs_by_swap_counts(
                                vols, suffix="24hr"
                            )
                    top_liquidity = derive.top_pairs_by_liquidity(
                                books
                            )
                    data = {
                        "days": 1,
                        "swaps_count": vols["total_swaps"],
                        "swaps_volume": vols["trade_volume_usd"],
                        "current_liquidity": books["combined_liquidity_usd"],
                        "top_pairs": {
                            "by_volume": top_vol,
                            "by_swaps_count": top_swaps,
                            "by_current_liquidity_usd": top_liquidity,
                        },
                    }
                    data = clean.decimal_dicts(data)
            return data
        except Exception as e:  # pragma: no cover
            logger.error(f"{type(e)} Error in [StatsAPI.adex_24hr]: {e}")
            return None


    def adex_weekly(self, refresh=False):
        try:
            data = memcache.get_adex_weekly()
            if data is None or refresh:
                books = self.pairs_orderbook_extended_cache
                start_time = int(cron.now_utc()) - 86400 * 7
                end_time = int(cron.now_utc())  
                vols = self.pair_volumes_timespan(
                    start_time=start_time, end_time=end_time
                )
                if None not in [books, vols]:
                    top_vol = derive.top_pairs_by_volume(vols)
                    top_swaps = derive.top_pairs_by_swap_counts(
                                vols, suffix="7d"
                            )
                    top_liquidity = derive.top_pairs_by_liquidity(
                                books
                            )
                    data = {
                        "days": 7,
                        "swaps_count": vols["total_swaps"],
                        "swaps_volume": vols["trade_volume_usd"],
                        "current_liquidity": books["combined_liquidity_usd"],
                        "top_pairs": {
                            "by_volume": top_vol,
                            "by_swaps_count": top_swaps,
                            "by_current_liquidity_usd": top_liquidity,
                        },
                    }
                    data = clean.decimal_dicts(data)
            return data
        except Exception as e:  # pragma: no cover
            logger.error(f"{type(e)} Error in [StatsAPI.adex_weekly]: {e}")
            return None


    def adex_fortnite(self, refresh=False):
        try:
            data = memcache.get_adex_fortnite()
            if data is None or refresh:
                books = self.pairs_orderbook_extended_cache
                vols = self.pair_volumes_timespan()
                if None not in [books, vols]:
                    top_vol = derive.top_pairs_by_volume(vols)
                    top_swaps = derive.top_pairs_by_swap_counts(
                                vols, suffix="14d"
                            )
                    top_liquidity = derive.top_pairs_by_liquidity(
                                books
                            )
                    data = {
                        "days": 14,
                        "swaps_count": vols["total_swaps"],
                        "swaps_volume": vols["trade_volume_usd"],
                        "current_liquidity": books["combined_liquidity_usd"],
                        "top_pairs": {
                            "by_volume": top_vol,
                            "by_swaps_count": top_swaps,
                            "by_current_liquidity_usd": top_liquidity,
                        },
                    }
                    data = clean.decimal_dicts(data)
            return data
        except Exception as e:  # pragma: no cover
            logger.error(f"{type(e)} Error in [StatsAPI.adex_fortnite]: {e}")
            return None

    def adex_alltime(self, refresh=False):
        try:
            data = memcache.get_adex_alltime()
            if data is None or refresh:
                books = self.pairs_orderbook_extended_cache
                vols = self.pair_volumes_timespan(start_time=1)
                if None not in [books, vols]:
                    top_vol = derive.top_pairs_by_volume(vols)
                    top_liquidity = derive.top_pairs_by_liquidity(
                                books
                            )
                    top_swaps = derive.top_pairs_by_swap_counts(
                                vols, suffix="all_time"
                            )
                    data = {
                        "days": "All",
                        "swaps_count": vols["total_swaps"],
                        "swaps_volume": vols["trade_volume_usd"],
                        "current_liquidity": books["combined_liquidity_usd"],
                        "top_pairs": {
                            "by_volume": top_vol,
                            "by_swaps_count": top_swaps,
                            "by_current_liquidity_usd": top_liquidity,
                        },
                    }
                    data = clean.decimal_dicts(data)
            return data
        except Exception as e:  # pragma: no cover
            logger.error(f"{type(e)} Error in [StatsAPI.adex_alltime]: {e}")
            return None

    @timed
    def tickers_lite(self, coin=None, depaired=False):
        # TODO: confirm no reverse duplicates
        try:
            book = self.pairs_orderbook_extended_cache
            if book is None:
                return
            resp = []
            data = {}
            sorted_pairs = list(
                set(
                    [
                        sortdata.pair_by_market_cap(i, gecko_source=self.gecko_source)
                        for i in book["orderbooks"].keys()
                    ]
                )
            )
            for depair in sorted_pairs:
                base, quote = derive.base_quote(pair_str=depair)
                if deplatform.coin(coin) in [None, base, quote]:
                    if depair not in book["orderbooks"]:
                        logger.warning(f"Inverting non standard pair {depair}")
                        depair = invert.pair(depair)
                    depair_orderbook = book["orderbooks"][depair]

                    if depaired:
                        v_data = depair_orderbook["ALL"]
                        data.update(template.markets_ticker(depair, v_data))
                    else:
                        for variant in depair_orderbook:
                            if variant != "ALL":
                                v = variant.replace("-segwit", "")
                                v_data = depair_orderbook[variant]
                                if v not in data:
                                    data.update(template.markets_ticker(v, v_data))
                                else:
                                    # Cover merge of segwit variants
                                    if (
                                        v_data["newest_price_24hr"]
                                        > data[v]["last_price"]
                                    ):
                                        data[v]["last_price"] = Decimal(
                                            v_data["newest_price_24hr"]
                                        )

            for v in data:
                if data[v]["base_volume"] != 0 and data[v]["quote_volume"] != 0:
                    data[v] = clean.decimal_dicts(data=data[v], to_string=True)
                    resp.append({v: data[v]})
            return resp
        except Exception as e:  # pragma: no cover
            msg = "markets_tickers failed!"
            return default.error(e, msg)

    @timed
    def tickers(self, refresh: bool = False):
        try:
            if refresh:
                book = self.pairs_orderbook_extended_cache
                volumes = self.pair_volumes_24hr_cache
                prices = self.pair_prices_24hr_cache
                if None not in [self.coins_config, book, volumes, prices]:
                    sorted_pairs = list(
                        set(
                            [
                                sortdata.pair_by_market_cap(
                                    i, gecko_source=self.gecko_source
                                )
                                for i in book["orderbooks"].keys()
                            ]
                        )
                    )
                    resp = {
                        "last_update": int(cron.now_utc()),
                        "pairs_count": book["pairs_count"],
                        "swaps_count": volumes["total_swaps"],
                        "combined_volume_usd": volumes["trade_volume_usd"],
                        "combined_liquidity_usd": book["combined_liquidity_usd"],
                        "data": {},
                    }
                    ok = 0
                    not_ok = 0
                    for depair in sorted_pairs:
                        if depair not in book["orderbooks"]:
                            depair = invert.pair(depair)
                        if depair in book["orderbooks"]:
                            if "ALL" in book["orderbooks"][depair]:
                                v = template.pair_volume_item(suffix="24hr")
                                p = template.pair_prices_info(suffix="24hr")
                                b = book["orderbooks"][depair]["ALL"]
                                if depair in volumes["volumes"]:
                                    if "ALL" in volumes["volumes"][depair]:
                                        v = volumes["volumes"][depair]["ALL"]
                                if depair in prices:
                                    if "ALL" in prices[depair]:
                                        p = prices[depair]["ALL"]
                                resp["data"].update(
                                    {
                                        depair: convert.pair_orderbook_extras_to_gecko_tickers(
                                            b, v, p
                                        )
                                    }
                                )
                                ok += 1
                        else:
                            std = sortdata.pair_by_market_cap(depair, gecko_source=self.gecko_source)
                            logger.warning(
                                f"Ticker failed for {depair} and {invert.pair(depair)} \
                                (standard is {std})"
                            )
                            not_ok += 1
                    logger.calc(f"{ok}/{ok + not_ok} pairs added to tickers cache")
                # Not needed, done in cache.py
                # memcache.set_tickers(resp)
                msg = "Tickers cache updated"
                ignore_until = 0
            else:
                resp = memcache.get_tickers()
                msg = "Got tickers from cache"
                ignore_until = 5

        except Exception as e:  # pragma: no cover
            msg = f"tickers failed! {e}"
            ignore_until = 0
            loglevel = "warning"
            return default.error(e, msg)
        return default.result(
            data=resp, msg=msg, loglevel="cached", ignore_until=ignore_until
        )


class CMC:
    def init(self):
        pass

    @property
    def calc(self):
        return CacheCalc()

    @property
    def api(self):
        return CmcAPI()

    @timed
    def assets(self, refresh: bool = False):
        try:
            resp = memcache.get_cmc_assets()
            if refresh or resp is None:
                assets_source = memcache.get("cmc_assets_source")
                if assets_source is None:
                    assets_source = self.api.assets_source()
                cmc_by_ticker = self.api.get_cmc_by_ticker(assets_source)
                resp = self.api.extract_ids(cmc_by_ticker)
            return resp
        except Exception as e:  # pragma: no cover
            logger.warning(f"{type(e)} Error in [/api/v3/cmc/summary]: {e}")
            return {"error": f"{type(e)} Error in [/api/v3/cmc/summary]: {e}"}

    @timed
    def summary(self, refresh: bool = False):
        try:
            resp = memcache.get_cmc_summary()
            if refresh or resp is None:
                resp = []
                book = self.calc.pairs_orderbook_extended_cache
                vols = self.calc.pair_volumes_24hr_cache
                last = self.calc.pairs_last_traded_cache
                if None not in [book, vols, last]:
                    for depair in book["orderbooks"]:
                        o = book["orderbooks"][depair]["ALL"]
                        lt = template.first_last_traded()
                        v = template.pair_volume_item(suffix="24hr")
                        if depair in vols["volumes"]:
                            if "ALL" in vols["volumes"][depair]:
                                v = vols["volumes"][depair]["ALL"]
                        if depair in last:
                            if "ALL" in last[depair]:
                                lt = last[depair]["ALL"]
                        data = clean.decimal_dicts(
                            {
                                "trading_pair": depair,
                                "base_currency": o["base"],
                                "quote_currency": o["quote"],
                                "last_price": lt["last_swap_price"],
                                "lowest_ask": o["lowest_ask"],
                                "highest_bid": o["highest_bid"],
                                "base_volume": v["base_volume"],
                                "quote_volume": v["quote_volume"],
                                "price_change_percent_24h": o["price_change_pct_24hr"],
                                "highest_price_24h": o["highest_price_24hr"],
                                "lowest_price_24h": o["lowest_price_24hr"],
                                # Only here for the filter
                                "last_swap_uuid": lt["last_swap_uuid"],
                            }
                        )
                        # remove where no past trades detected
                        if lt["last_swap_uuid"] != "":
                            resp.append(data)
            return resp
        except Exception as e:  # pragma: no cover
            logger.warning(f"{type(e)} Error in [/api/v3/cmc/summary]: {e}")
            return {"error": f"{type(e)} Error in [/api/v3/cmc/summary]: {e}"}

    @timed
    def tickers(self):
        try:
            tickers_lite = self.calc.tickers_lite(depaired=True)
            # TODO: Derive cmc base/quote ids
            resp = []
            for i in tickers_lite:
                for k, v in i.items():
                    base, quote = derive.base_quote(k)
                    cmc_base_info = derive.cmc_asset_info(base)
                    cmc_quote_info = derive.cmc_asset_info(quote)
                    if "id" in cmc_base_info and "id" in cmc_quote_info:
                        v.update(
                            {
                                "base_id": cmc_base_info["id"],
                                "quote_id": cmc_quote_info["id"],
                            }
                        )
                        resp.append({k: v})
            return resp
        except Exception as e:  # pragma: no cover
            logger.warning(f"{type(e)} Error in [/api/v3/cmc/tickers]: {e}")
            return {"error": f"{type(e)} Error in [/api/v3/cmc/tickers]: {e}"}
