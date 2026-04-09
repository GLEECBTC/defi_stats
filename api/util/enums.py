from enum import Enum


class GroupBy(str, Enum):
    gui = "gui"
    coin = "coin"
    pair = "pair"
    pubkey = "pubkey"
    ticker = "ticker"
    platform = "platform"
    version = "version"


class TradeSide(str, Enum):
    MAKER = "maker"
    TAKER = "taker"


class TradeType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    ALL = "all"


class NetId(str, Enum):
    NETID_7777 = "7777"
    NETID_8762 = "8762"
    NETID_6133 = "6133"
    ALL = "ALL"


class TablesEnum(str, Enum):
    stats_swaps = "stats_swaps"


class ColumnsEnum(str, Enum):
    maker_coin_usd_price = "maker_coin_usd_price"
    taker_coin_usd_price = "taker_coin_usd_price"
    maker_pubkey = "maker_pubkey"
    taker_pubkey = "taker_pubkey"
    is_success = "is_success"
    uuid = "uuid"
    started_at = "started_at"
    finished_at = "finished_at"
    taker_coin = "taker_coin"
    maker_coin = "maker_coin"
    taker_amount = "taker_amount"
    maker_amount = "maker_amount"
    taker_coin_platform = "taker_coin_platform"
    maker_coin_platform = "maker_coin_platform"
