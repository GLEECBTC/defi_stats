#!/usr/bin/env python3
import os
import csv
import json
import requests
from lib.coins import Coin
from util.logger import logger
import util.memcache as memcache

SCRIPT_PATH = os.path.dirname(os.path.abspath(__file__))
API_ROOT_PATH = os.path.dirname(os.path.dirname(SCRIPT_PATH))
PROJECT_ROOT_PATH = os.path.dirname(API_ROOT_PATH)

COINS_CONFIG_URL = "https://raw.githubusercontent.com/GLEECBTC/coins/master/utils/coins_config.json"


class CmcAPI:  # pragma: no cover
    def __init__(self):
        self.base_url = "https://pro-api.coinmarketcap.com"

    @property
    def coins_config(self):
        return memcache.get_coins_config()

    def assets_source(self):
        apikey = "UNIFIED-CRYPTOASSET-INDEX"
        logger.calc(apikey)
        endpoint = (
            f"v1/cryptocurrency/map?CMC_PRO_API_KEY={apikey}&listing_status=active"
        )
        logger.calc(endpoint)
        url = f"{self.base_url}/{endpoint}"
        logger.calc(url)
        r = requests.get(url)
        data = r.json()["data"]
        return data

    def get_cmc_by_ticker(self, assets_source, save=False):
        by_ticker = {}
        for i in assets_source:
            if i["symbol"] not in by_ticker.keys():
                by_ticker.update({i["symbol"]: []})
            by_ticker[i["symbol"]].append(i)
        if save:
            with open("cmc_by_ticker.json", "w+") as f:
                json.dump(by_ticker, f, indent=4)
        return by_ticker

    def extract_ids(self, cmc_by_ticker):
        common_keys = self.get_common_keys(cmc_by_ticker)
        data = {}

        # These are ignored as known to not be in coins repo
        cmc_reject = [
            "Tracer",
            "MetaTrace",
            "Evernode",
            "ENEFTIVERSE",
            "D-SHOP",
            "Betero",
            "McLaren F1 Fan Token",
            "LABS Group",
            "PUTinCoin",
            "PUTinCoin",
            "PUTinCoin",
            "PUTinCoin",
            "Solar",
            "Xave Coin",
            "Ninja Protocol",
            "Dog Wif Nunchucks",
            "Shinobi",
            "Dot Finance",
            "Drawshop Kingdom Reverse",
            "Lynex",
            "Pink",
            "Joystream",
        ]
        # These have been sighted as the same token,
        # though having a slightly different full name value
        cmc_allow = [
            "Pirate Chain",
            "KuCoin Token",
            "Jarvis Synthetic Euro",
            "Gleec Coin",
            "IRISnet",
            "BNB",
            "BUSD" "KuCoin Token",
            "Energy Web Token",
            "Injective",
            "VerusCoin",
            "KuCoin Token",
            "Loop Network",
            "GM Wagmi",
            "BIDR",
            "Energo",
            "FLOKI",
            "KuCoin Token",
            "Rootstock Smart Bitcoin",
            "CAKE",
            "GlobalBoost",
            "Hyper Pay",
        ]
        # These are for cases where there is a name match,
        # but also mismatches which have been sighted as invalid
        coin_compare = [
            [
                "Coins Repo Ticker",
                "Base Ticker",
                "CMC Name",
                "Coins Repo Name",
                "Coins Repo Fname",
            ]
        ]
        # These are false positives in bad match detection
        ignore = [
            "DOGE",
            "AUR",
            "AVN",
            "ETH",
            "FLUX",
            "GLC",
            "GRS",
            "MONA",
            "ONE",
            "HT",
            "KOIN",
            "THC",
            "VAL",
            "VIA",
            "XVG",
            "POT",
            "PPC",
        ]
        for coin in common_keys:
            needs_validation = True
            for coin_full in self.coins_config:
                if coin != coin_full.split("-")[0]:
                    continue
                for src in cmc_by_ticker[coin]:
                    if src["name"] in cmc_reject:
                        continue
                    if coin in data:
                        item = data[coin]
                    else:
                        item = {
                            "name": src["name"],
                            "unified_cryptoasset_id": src["id"],
                        }
                    try:
                        if coin_full.endswith("_OLD"):
                            # Excluding these, though there may be a CMC ticker for them
                            continue
                        # If same name and symbol, we can be confident it is valid
                        if (
                            src["name"].lower()
                            == self.coins_config[coin_full]["name"].lower()
                            or src["name"].lower()
                            == self.coins_config[coin_full]["fname"].lower()
                            or src["name"] in cmc_allow
                        ):
                            needs_validation = False
                        if src["platform"] is not None and coin not in [
                            "KCS",
                            "ONE",
                            "BNB",
                        ]:
                            C = Coin(coin=coin_full, coins_config=self.coins_config)
                            contract = C.token_contract
                            token_address = src["platform"]["token_address"]
                            if (
                                contract.lower() == token_address.lower()
                                or src["name"] in cmc_allow
                            ):
                                contract_link = C.contract_link
                                if contract_link is not None:
                                    for i in [
                                        "contractAddressUrl",
                                        "contractAddress",
                                    ]:
                                        if i not in item:
                                            item.update({i: []})

                                item["contractAddress"].append(contract)
                                item["contractAddressUrl"].append(contract_link)
                                needs_validation = False

                        if needs_validation:
                            coin_compare.append(
                                [
                                    coin_full,
                                    coin,
                                    src["name"],
                                    self.coins_config[coin_full]["name"],
                                    self.coins_config[coin_full]["fname"],
                                ]
                            )
                        elif coin not in data:
                            data.update({coin: item})
                        else:
                            data[coin].update(item)

                    except Exception as e:
                        if coin not in ["ARRR", "ATOM", "IRIS", "OSMO"]:
                            pass
                            # Uncomment here to identify coins which fail to map
                            # logger.error(f"Error getting link for {coin}: {e}")
                            # logger.merge(src)
        for coin in data:
            for i in ["contractAddressUrl", "contractAddress"]:
                if i in data[coin]:
                    data[coin][i] = ",".join(data[coin][i])
        logger.info(f"{len(data)} coins translated")

        with open("coin_compare.csv", mode="w") as cf:
            cw = csv.writer(cf, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)

            for i in coin_compare:
                if i[1] not in data:
                    cw.writerow(i)
        return data

    def get_common_keys(self, cmc_assets):
        coins_config_keys = list(
            set(
                [
                    i.split("-")[0]
                    for i in self.coins_config.keys()
                    if self.coins_config[i]["is_testnet"] is False
                ]
            )
        )
        logger.info(f"{len(coins_config_keys)} coins from coins_config.json")
        cmc_assets_keys = list(cmc_assets.keys())
        logger.info(f"{len(cmc_assets_keys)} coins from CMC")
        data = [i for i in coins_config_keys if i in cmc_assets_keys]
        data.sort()
        logger.info(f"{len(data)} common tickers")
        return data
