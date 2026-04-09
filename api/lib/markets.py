#!/usr/bin/env python3
from lib.pair import Pair
from lib.coins import Coins
from util.logger import timed, logger
from util.transform import sortdata, derive, invert, merge
from util.cron import cron
import util.defaults as default
import util.memcache as memcache
from lib.external import gecko_api


class Markets:
    def __init__(self, coins_config=None, gecko_source=None) -> None:
        try:
            self._coins_config = coins_config
            self._gecko_source = gecko_source
            self.netid = 6133
            self.coins = Coins()
            self.segwit_coins = self.coins.with_segwit
        except Exception as e:  # pragma: no cover
            logger.error(f"Failed to init Markets: {e}")

    @property
    def gecko_source(self):
        if self._gecko_source is None:
            logger.calc("sourcing gecko")
            self._gecko_source = memcache.get_gecko_source()
        if self._gecko_source is None:
            self._gecko_source = gecko_api.get_source_data(from_file=True)
        return self._gecko_source

    @property
    def coins_config(self):
        if self._coins_config is None:
            self._coins_config = memcache.get_coins_config()
        return self._coins_config

    # TODO: Cache this
    @timed
    def trades(self, pair_str: str, days_in_past: int = 1, all_variants: bool = False):
        try:
            start_time = int(cron.now_utc() - 86400 * days_in_past)
            end_time = int(cron.now_utc())
            data = Pair(
                pair_str=pair_str,
                coins_config=self.coins_config,
                gecko_source=self.gecko_source,
            ).historical_trades(
                start_time=start_time,
                end_time=end_time,
            )
            resp = []
            base, quote = derive.base_quote(pair_str)
            if all_variants:
                resp = merge.trades(resp, data["ALL"])
            else:
                variants = derive.pair_variants(pair_str=pair_str, segwit_only=True)
                for v in variants:
                    if v in data:
                        resp = merge.trades(resp, data[v])
                    elif invert.pair(v) in data:
                        resp = merge.trades(resp, data[invert.pair(v)])
                    else:
                        logger.warning(f"Variant {v} not found in data!")
            return sortdata.dict_lists(resp, "timestamp", reverse=True)

        except Exception as e:  # pragma: no cover
            msg = f"markets_tickers failed for netid {self.netid}!"
            return default.error(e, msg)
