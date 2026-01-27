#!/usr/bin/env python3
import requests
import time
#import backoff
from typing import List, Dict
from const import FIXER_API_KEY
from util.files import Files
from util.helper import get_chunks
from util.logger import logger
import util.defaults as default
from util.transform import template
import util.memcache as memcache


INVALID_IDS = {"na", "test-coin", ""}

class CoinGeckoAPI:
    def __init__(self, coins_config=None, file_handler=None, **kwargs):
        self.kwargs = kwargs
        self.options = []
        self.files = file_handler or Files()
        self._coins_config = coins_config

        try:
            default.params(self, self.kwargs, self.options)
            self.coin_ids = self.get_coin_ids()
            self.template = self.build_template()
        except Exception as e:
            logger.error(f"{type(e)} Failed to init CoinGeckoAPI: {e}")

    @property
    def coins_config(self):
        if self._coins_config is None:
            self._coins_config = memcache.get_coins_config()
        return self._coins_config

    def get_coin_ids(self) -> List[str]:
        coin_ids = {
            cfg["coingecko_id"]
            for cfg in self.coins_config.values()
            if cfg["coingecko_id"] not in INVALID_IDS
        }
        return sorted(coin_ids)

    def build_template(self):
        info = {}
        for coin, cfg in self.coins_config.items():
            coin_id = cfg["coingecko_id"]
            if coin_id in INVALID_IDS:
                continue
            if coin not in info:
                info[coin] = template.gecko_info(coin_id)
                native_coin = coin.split("-")[0] if "-" in coin else coin
            if native_coin not in info:
                info[native_coin] = info[coin]
        return info

    def map_gecko_coins(self, gecko_info: Dict[str, Dict]) -> Dict[str, List[str]]:
        gecko_coins = {cid: [] for cid in self.coin_ids}
        for coin, info in gecko_info.items():
            coin_id = info.get("coingecko_id")
            if coin_id in gecko_coins:
                gecko_coins[coin_id].append(coin)
        return gecko_coins

    # @backoff.on_exception(backoff.expo, requests.exceptions.RequestException, max_tries=3)
    def fetch_price_data(self, coin_id_chunk: List[str]) -> Dict:
        params = f"ids={','.join(coin_id_chunk)}&vs_currencies=usd&include_market_cap=true"
        url = f"https://api.coingecko.com/api/v3/simple/price?{params}"
        try:
            r = requests.get(url)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"Failed to fetch from URL: {url}, error: {e}")
            return {}

    def get_source_data(self, from_file=False):
        if memcache.get("testing") is not None or from_file:
            return self.files.load_jsonfile(self.files.gecko_source)

        gecko_info = self.build_template()
        gecko_coins = self.map_gecko_coins(gecko_info)
        param_limit = 200

        for chunk in get_chunks(self.coin_ids, param_limit):
            gecko_source = self.fetch_price_data(chunk)

            for coin_id, values in gecko_source.items():
                coins = gecko_coins.get(coin_id, [])
                for coin in coins:
                    if "usd" in values:
                        gecko_info[coin]["usd_price"] = values["usd"]
                    if "usd_market_cap" in values:
                        gecko_info[coin]["usd_market_cap"] = values["usd_market_cap"]
            time.sleep(0.1)

        self.files.save_json(self.files.gecko_source, gecko_info)
        return gecko_info


class FixerAPI:  # pragma: no cover
    def __init__(self):
        self.base_url = "http://data.fixer.io/api"
        self.api_key = FIXER_API_KEY

    def latest(self):
        try:
            # TODO: move this to defi-stats.komodo.earth
            return requests.get("https://defistats.gleec.com/api/v3/markets/fiat_rates").json()
            """
            if self.api_key == "":
                raise ApiKeyNotFoundException("FIXER_API key not set!")
            url = f"{self.base_url}/latest?access_key={self.api_key}"
            r = requests.get(url)
            received_rates = r.json()
            received_rates["date"] = str(
                datetime.fromtimestamp(received_rates["timestamp"])
            )
            if "error" in received_rates:
                raise Exception(received_rates["error"])
            usd_eur_rate = received_rates["rates"]["USD"]
            for rate in received_rates["rates"]:
                received_rates["rates"][rate] /= usd_eur_rate
            received_rates["base"] = "USD"
            received_rates["rates"]["USD"] = 1.0
            received_rates["rates"].pop("BTC")
            return received_rates
            """
        except Exception as e:
            return default.result(msg=e, loglevel="warning")


class BinanceAPI:  # pragma: no cover
    def __init__(self):
        self.base_url = "https://data-api.binance.vision"

    def ticker_price(self):
        endpoint = "api/v3/ticker/price"
        r = requests.get(f"{self.base_url}/{endpoint}")
        return r.json()


gecko_api = CoinGeckoAPI(coins_config=memcache.get_coins_config())
