#!/usr/bin/env python3
import os
import time
from decimal import Decimal
from datetime import date, datetime, timezone
from datetime import time as dt_time
from dotenv import load_dotenv
from itertools import chain
from sqlalchemy import Numeric, func, text
from sqlalchemy.sql.expression import bindparam
from sqlmodel import Session, SQLModel, create_engine, text, update, select, or_, and_
from typing import Dict
from const import (
    MYSQL_USERNAME,
    MYSQL_HOSTNAME,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_DATABASE,
    POSTGRES_HOST,
    POSTGRES_USERNAME,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_DATABASE,
    MM2_DB_PATH_ALL,
)
from db.schema import (
    DefiSwap,
    DefiSwapTest,
    StatsSwap,
    CipiSwap,
    CipiSwapFailed,
    Mm2StatsNodes,
)
from util.exceptions import InvalidParamCombination
from util.logger import logger, timed
from util.transform import merge, sortdata, deplatform, invert, derive, template
from util.cron import cron
from lib.external import gecko_api
import util.defaults as default
import util.memcache as memcache
import util.validate as validate

load_dotenv()


def swap_log_context(swap_data):
    """
    Identifies a source swap row in a log message, so a
    conversion failure can be traced back to its origin.
    """
    try:
        return (
            f"uuid: {swap_data.get('uuid')} | "
            f"{swap_data.get('maker_coin')}/{swap_data.get('taker_coin')} | "
            f"started_at: {swap_data.get('started_at')}"
        )
    except Exception as e:  # pragma: no cover
        return f"unloggable swap data: {e}"


class SqlDB:
    def __init__(
        self, db_type="pgsql", db_path=None, external=False, table=None
    ) -> None:
        self.table = table
        self.db_type = db_type
        self.db_path = db_path
        self.external = external
        if self.db_type == "pgsql":
            self.host = POSTGRES_HOST
            self.user = POSTGRES_USERNAME
            self.password = POSTGRES_PASSWORD
            self.port = POSTGRES_PORT
            self.database = POSTGRES_DATABASE or self.user
            # TODO: use arg/kwarg
            if self.table is None:
                if os.getenv("IS_TESTING") == "True" == "True":
                    self.table = DefiSwapTest
                else:
                    self.table = DefiSwap
            self.db_url = (
                f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}"
            )
            if self.database:
                self.db_url += f"/{self.database}"
        elif self.db_type == "sqlite":
            if self.db_path is not None:
                if self.table is None:
                    self.table = StatsSwap
                self.db_path = db_path
                self.db_url = f"sqlite:///{self.db_path}"

        elif self.db_type == "mysql":
            self.external = True
            self.table = CipiSwap
            self.host = MYSQL_HOSTNAME
            self.user = MYSQL_USERNAME
            self.password = MYSQL_PASSWORD
            self.port = MYSQL_PORT
            self.database = MYSQL_DATABASE
            self.db_url = f"mysql://{self.user}:{self.password}@{self.host}:{self.port}"
            self.db_url += f"/{self.database}"

        self.engine = create_engine(self.db_url)  # ), echo=True)
        self.sqlfilter = SqlFilter(self.table)


class SqlFilter:
    def __init__(self, table=DefiSwap) -> None:
        self.table = table

    @timed
    def coin(self, q, coin):
        if coin is not None:
            q = q.filter(
                or_(
                    coin == self.table.maker_coin,
                    coin == self.table.taker_coin,
                )
            )
        return q

    @timed
    def gui(self, q, gui):
        if gui is not None:
            q = q.filter(
                or_(
                    gui == self.table.maker_gui,
                    gui == self.table.taker_gui,
                )
            )
        return q

    @timed
    def pair(self, q, pair, reduce=True):
        if pair is not None:
            if reduce:
                pair = deplatform.pair(pair)
            q = q.filter(
                or_(
                    pair == self.table.pair_std,
                    pair == self.table.pair_std_reverse,
                )
            )
        return q

    @timed
    def pubkey(self, q, pubkey):
        if pubkey is not None:
            q = q.filter(
                or_(
                    pubkey == self.table.pubkey_gui,
                    pubkey == self.table.pubkey_gui,
                )
            )
        return q

    @timed
    def success(self, q, success_only=True, failed_only=False):
        if failed_only:
            if self.table == CipiSwap:
                return []
            elif self.table != CipiSwapFailed:
                if self.table.is_success == -1:
                    return q
                return q.filter(self.table.is_success == 0)
        if success_only:
            if self.table == CipiSwapFailed:
                return []
            elif self.table != CipiSwap:
                if self.table.is_success == -1:
                    return q
                return q.filter(self.table.is_success == 1)
        return q

    @timed
    def since(self, q, start_time):
        if self.table in [Mm2StatsNodes]:
            q = q.filter(self.table.timestamp > start_time)
        elif self.table in [CipiSwap, CipiSwapFailed]:
            q = q.filter(self.table.started_at > start_time)
        else:
            q = q.filter(self.table.finished_at > start_time)
        return q

    @timed
    def timestamps(self, q, start_time, end_time):
        if self.table in [Mm2StatsNodes]:
            q = q.filter(
                self.table.timestamp > start_time, self.table.timestamp < end_time
            )
        elif self.table in [CipiSwap, CipiSwapFailed]:
            q = q.filter(
                self.table.started_at > start_time, self.table.started_at < end_time
            )
        else:
            q = q.filter(
                self.table.finished_at > start_time, self.table.finished_at < end_time
            )
        return q

    @timed
    def version(self, q, version):
        if version is not None:
            q = q.filter(
                or_(
                    version == self.table.version_gui,
                    version == self.table.version_gui,
                )
            )
        return q

    @timed
    def uuid(self, q, uuid):
        if uuid is not None:
            q = q.filter(self.table.uuid == uuid)
        return q


class SqlUpdate(SqlDB):
    def __init__(
        self, db_type="pgsql", db_path=None, external=False, table=None, gecko_source=None
    ) -> None:
        SqlDB.__init__(
            self, db_type=db_type, db_path=db_path, external=external, table=table
        )
        self._gecko_source = gecko_source

    @property
    def gecko_source(self):
        if self._gecko_source is None:
            logger.calc("sourcing gecko")
            self._gecko_source = memcache.get_gecko_source()
        if self._gecko_source is None:
            self._gecko_source = gecko_api.get_source_data(from_file=True)
        return self._gecko_source
    
    @timed
    def drop(self, table):
        try:
            with Session(self.engine) as session:
                session.exec(text(f"DROP TABLE {get_tablename(table)};"))
                session.commit()
                logger.info(f"Dropped {get_tablename(table)}")
        except Exception as e:  # pragma: no cover
            logger.warning(e)

    @timed
    def fix_swap_pairs(self, start_time=1, end_time=0, trigger=None):
        pgdb_query = SqlQuery(db_type="pgsql", gecko_source=self.gecko_source)
        if end_time == 0:
            end_time = cron.now_utc()
        if start_time == 0:
            start_time = cron.now_utc() - 86400
        pairs = pgdb_query.get_distinct(
            column="pair",
            start_time=1,
            end_time=end_time,
            success_only=False,
            failed_only=False
        )
        x = 0
        pairs = list(set(pairs))
        pairs.sort()
        for pair in pairs:
            x += 1
            if self.fix_swap_pair(pair, pgdb_query, trigger) or x%100 == 0:
                logger.info(f"Fixing pair standard for {pair} {x}/{len(pairs)}")
            

    @timed
    def fix_swap_pair(self, pair, pgdb_query, trigger=None):
        # XEP-BEP20_XEP-segwit seems to keep being updated
        # TODO: investigate
        try:
            fixed = False
            sorted_pair = sortdata.pair_by_market_cap(pair, gecko_source=self.gecko_source)
            if pair != sorted_pair:
                logger.warning(f"{pair} in DB is non standard! Should be {sorted_pair}! Trigger: {trigger}")
                swaps = pgdb_query.swap_uuids(
                    pair=pair,
                    full_scan_pair=True
                )
                if "ALL" in swaps:
                    uuids = [i for i in swaps["ALL"]]
                else:
                    uuids = [i for i in swaps]
                
                if len(uuids) > 0:
                    logger.warning(
                        f"need to fix {len(uuids)} swaps with non standard pair {pair}"
                    )
                    updates = []
                    for uuid in uuids:
                        swap = pgdb_query.get_swap(uuid=uuid)
                        logger.calc(f"{uuid} needs update...")
                        clean_swap = validate.ensure_valid_pair(swap, gecko_source=self.gecko_source) 
                        stmt = (
                            update(DefiSwap)
                            .where(DefiSwap.uuid == clean_swap["uuid"])
                            .values(
                                pair=clean_swap["pair"],
                                pair_std=clean_swap["pair_std"],
                                pair_reverse=clean_swap["pair_reverse"],
                                pair_std_reverse=clean_swap["pair_std_reverse"],
                                maker_coin_ticker=clean_swap["maker_coin_ticker"],
                                maker_coin_platform=clean_swap["maker_coin_platform"],
                                taker_coin_ticker=clean_swap["taker_coin_ticker"],
                                taker_coin_platform=clean_swap["taker_coin_platform"],
                                trade_type=clean_swap["trade_type"],
                                price=clean_swap["price"],
                                reverse_price=clean_swap["reverse_price"],
                            )
                        )
                        with Session(self.engine) as session:
                            session.exec(stmt)
                            session.commit()
                            logger.info(f"{uuid} FIXED!")
                            fixed = True
        except Exception as e:
            logger.warning(f"error fixing swap for {pair}: {e}")
        return fixed
        


class SqlQuery(SqlDB):
    def __init__(
        self,
        db_type="pgsql",
        db_path=None,
        external=False,
        gecko_source=None,
        table=None,
    ) -> None:
        SqlDB.__init__(
            self, db_type=db_type, db_path=db_path, external=external, table=table
        )
        self._gecko_source = gecko_source

    @property
    def gecko_source(self):
        if self._gecko_source is None:
            logger.calc("sourcing gecko")
            self._gecko_source = memcache.get_gecko_source()
        if self._gecko_source is None:
            self._gecko_source = gecko_api.get_source_data(from_file=True)
        return self._gecko_source

    # TODO: Subclass 'volumes'
    @timed
    def coin_trade_volumes(
        self,
        start_time: int = 0,
        end_time: int = 0,
        pubkey: str | None = None,
        gui: str | None = None,
        version: str | None = None,
    ) -> list:
        """
        Returns volume traded of coin between two timestamps.
        If no timestamp is given, returns data for last 24 hrs.
        """
        try:
            if start_time == 0:
                start_time = int(cron.now_utc()) - 86400
            if end_time == 0:
                end_time = int(cron.now_utc())

            resp = {
                "start_time": start_time,
                "end_time": end_time,
                "range_days": (end_time - start_time) / 86400,
                "total_swaps": 0,
                "maker_volume_usd": 0,
                "taker_volume_usd": 0,
                "trade_volume_usd": 0,
                "volumes": {},
            }
            total_maker_swaps = 0
            total_taker_swaps = 0

            with Session(self.engine) as session:
                q = session.query(
                    func.sum(func.cast(self.table.maker_amount, Numeric)).label(
                        "maker_volume"
                    ),
                    self.table.maker_coin.label("coin"),
                    self.table.maker_coin_ticker.label("ticker"),
                    func.count(self.table.maker_coin).label("num_swaps"),
                )

                q = self.sqlfilter.success(q)
                q = self.sqlfilter.timestamps(q, start_time, end_time)
                q = self.sqlfilter.gui(q, gui)
                q = self.sqlfilter.version(q, version)
                q = self.sqlfilter.pubkey(q, pubkey)
                q = q.group_by(self.table.maker_coin, self.table.maker_coin_ticker)
                q = q.order_by(
                    self.table.maker_coin, self.table.maker_coin_ticker.desc()
                )
                data = [dict(i) for i in q.all()]

            for i in data:
                # logger.calc(i)
                ticker = i["ticker"]
                variant = i["coin"]
                num_swaps = int(i["num_swaps"])
                maker_vol = Decimal(i["maker_volume"])

                if ticker not in resp["volumes"]:
                    resp["volumes"].update(
                        {ticker: {"ALL": template.coin_trade_vol_item()}}
                    )

                if variant not in resp["volumes"][ticker]:
                    resp["volumes"][ticker].update(
                        {variant: template.coin_trade_vol_item()}
                    )

                total_maker_swaps += num_swaps
                resp["volumes"][ticker][variant]["maker_swaps"] += num_swaps
                resp["volumes"][ticker][variant]["maker_volume"] += maker_vol
                resp["volumes"][ticker][variant]["total_swaps"] += num_swaps
                resp["volumes"][ticker][variant]["total_volume"] += maker_vol

                resp["volumes"][ticker]["ALL"]["maker_swaps"] += num_swaps
                resp["volumes"][ticker]["ALL"]["maker_volume"] += maker_vol
                resp["volumes"][ticker]["ALL"]["total_volume"] += maker_vol
                resp["volumes"][ticker]["ALL"]["total_swaps"] += num_swaps
                resp["total_swaps"] += num_swaps

            with Session(self.engine) as session:
                q = session.query(
                    func.sum(func.cast(self.table.taker_amount, Numeric)).label(
                        "taker_volume"
                    ),
                    self.table.taker_coin.label("coin"),
                    self.table.taker_coin_ticker.label("ticker"),
                    func.count(self.table.taker_coin).label("num_swaps"),
                )

                q = self.sqlfilter.success(q)
                q = self.sqlfilter.timestamps(q, start_time, end_time)
                q = self.sqlfilter.gui(q, gui)
                q = self.sqlfilter.version(q, version)
                q = self.sqlfilter.pubkey(q, pubkey)
                q = q.group_by(self.table.taker_coin, self.table.taker_coin_ticker)
                q = q.order_by(
                    self.table.taker_coin, self.table.taker_coin_ticker.desc()
                )
                data = [dict(i) for i in q.all()]

            for i in data:
                ticker = i["ticker"]
                variant = i["coin"]
                num_swaps = int(i["num_swaps"])
                taker_vol = Decimal(i["taker_volume"])

                if ticker not in resp["volumes"]:
                    resp["volumes"].update(
                        {ticker: {"ALL": template.coin_trade_vol_item()}}
                    )

                if variant not in resp["volumes"][ticker]:
                    resp["volumes"][ticker].update(
                        {variant: template.coin_trade_vol_item()}
                    )

                total_taker_swaps += num_swaps
                resp["volumes"][ticker][variant]["taker_volume"] += taker_vol
                resp["volumes"][ticker][variant]["total_volume"] += taker_vol
                resp["volumes"][ticker][variant]["taker_swaps"] += num_swaps
                resp["volumes"][ticker][variant]["total_swaps"] += num_swaps

                resp["volumes"][ticker]["ALL"]["taker_swaps"] += num_swaps
                resp["volumes"][ticker]["ALL"]["taker_volume"] += taker_vol
                resp["volumes"][ticker]["ALL"]["total_swaps"] += num_swaps
                resp["volumes"][ticker]["ALL"]["total_volume"] += taker_vol

                resp["total_swaps"] += num_swaps

            # Swap counts halved, avoid double counts from coins in pair
            resp.update(
                {"total_swaps": int((total_maker_swaps + total_taker_swaps) / 2)}
            )
            logger.info("coin_trade_volumes: {resp}")
            return default.result(
                data=resp, msg="coin_trade_volumes complete", loglevel="debug"
            )
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="error")

    @timed
    def coin_trade_vols_usd(self, volumes: Dict) -> list:
        """
        Returns volume traded of coin between two timestamps.
        If no timestamp is given, returns volume for last 24hrs.
        Price is based on current price, so less accurate for
        longer timespans
        """
        try:
            for coin in volumes["volumes"]:
                usd_price = derive.gecko_price(coin, self.gecko_source)
                for variant in volumes["volumes"][coin]:
                    maker_vol = volumes["volumes"][coin][variant]["maker_volume"]
                    taker_vol = volumes["volumes"][coin][variant]["taker_volume"]
                    variant_vol = volumes["volumes"][coin][variant]["total_volume"]
                    volumes["volumes"][coin][variant].update(
                        {
                            "taker_volume_usd": taker_vol * usd_price,
                            "maker_volume_usd": maker_vol * usd_price,
                            "trade_volume_usd": variant_vol * usd_price,
                        }
                    )
                maker_vol = volumes["volumes"][coin]["ALL"]["maker_volume_usd"]
                taker_vol = volumes["volumes"][coin]["ALL"]["taker_volume_usd"]
                total_vol = volumes["volumes"][coin]["ALL"]["trade_volume_usd"]
                volumes["maker_volume_usd"] += maker_vol
                volumes["taker_volume_usd"] += taker_vol
                volumes["trade_volume_usd"] += total_vol

            return default.result(
                data=volumes,
                msg=f"coin_trade_vols_usd complete [US${volumes['trade_volume_usd']}]",
                loglevel="query",
                ignore_until=0,
            )

        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")

    @timed
    def pair_trade_volumes(
        self,
        start_time: int = 0,
        end_time: int = 0,
        pubkey: str | None = None,
        gui: str | None = None,
        coin: str | None = None,
        version: str | None = None,
    ) -> list:
        """
        Returns volume traded of pairs between two timestamps.
        If no timestamp is given, returns data for last 24 hrs.
        """
        try:
            if start_time == 0:
                start_time = int(cron.now_utc()) - 86400
            if end_time == 0:
                end_time = int(cron.now_utc())

            resp = {
                "start_time": start_time,
                "end_time": end_time,
                "range_days": int((end_time - start_time) / 86400),
                "total_swaps": 0,
                "base_volume_usd": 0,
                "quote_volume_usd": 0,
                "trade_volume_usd": 0,
                "volumes": {},
            }
            if start_time == 1:
                suffix = "all_time"
            else:
                suffix = derive.suffix(resp["range_days"])
            
            with Session(self.engine) as session:
                q = session.query(
                    self.table.pair_std,
                    self.table.trade_type,
                    func.sum(func.cast(self.table.maker_amount, Numeric)).label(
                        "maker_volume"
                    ),
                    func.sum(func.cast(self.table.taker_amount, Numeric)).label(
                        "taker_volume"
                    ),
                    func.count(self.table.maker_amount).label("num_swaps"),
                )

                q = self.sqlfilter.success(q)
                q = self.sqlfilter.timestamps(q, start_time, end_time)
                q = self.sqlfilter.gui(q, gui)
                q = self.sqlfilter.version(q, version)
                q = self.sqlfilter.pubkey(q, pubkey)
                q = self.sqlfilter.coin(q, coin)
                q = q.group_by(self.table.pair_std, self.table.trade_type)
                q = q.order_by(self.table.pair_std.asc())
                data = [dict(i) for i in q.all()]

            for i in data:
                variant = i["pair_std"]
                depair = deplatform.pair(variant)
                if depair not in resp["volumes"]:
                    resp["volumes"].update(
                        {depair: {"ALL": template.pair_volume_item(suffix=suffix)}}
                    )
                if variant not in resp["volumes"][depair]:
                    resp["volumes"][depair].update(
                        {variant: template.pair_volume_item(suffix=suffix)}
                    )

                num_swaps = int(i["num_swaps"])
                if i["trade_type"] == "buy":
                    base_vol = Decimal(i["maker_volume"])
                    quote_vol = Decimal(i["taker_volume"])

                elif i["trade_type"] == "sell":
                    base_vol = Decimal(i["taker_volume"])
                    quote_vol = Decimal(i["maker_volume"])
                resp["volumes"][depair]["ALL"][f"trades_{suffix}"] += num_swaps
                resp["volumes"][depair]["ALL"]["base_volume"] += base_vol
                resp["volumes"][depair]["ALL"]["quote_volume"] += quote_vol
                resp["volumes"][depair][variant][f"trades_{suffix}"] += num_swaps
                resp["volumes"][depair][variant]["base_volume"] += base_vol
                resp["volumes"][depair][variant]["quote_volume"] += quote_vol
                resp["total_swaps"] += num_swaps

            return default.result(
                data=resp,
                msg="pair_trade_volumes complete",
                loglevel="query",
                ignore_until=5,
            )
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")

    @timed
    def pair_trade_vols_usd(self, volumes: Dict) -> list:
        """
        Returns volume traded of a pair between two timestamps.
        If no timestamp is given, returns volume for last 24hrs.
        Price is based on current price, so less accurate for
        longer timespans
        """
        try:
            total_base_vol_usd = 0
            total_quote_vol_usd = 0
            total_trade_vol_usd = 0
            for depair in volumes["volumes"]:
                base, quote = derive.base_quote(depair)
                base_price_usd = derive.gecko_price(base, self.gecko_source)
                quote_price_usd = derive.gecko_price(quote, self.gecko_source)

                for variant in volumes["volumes"][depair]:
                    base_vol = volumes["volumes"][depair][variant]["base_volume"]
                    quote_vol = volumes["volumes"][depair][variant]["quote_volume"]
                    base_vol_usd = Decimal(base_vol * base_price_usd)
                    quote_vol_usd = Decimal(quote_vol * quote_price_usd)
                    trade_vol_usd = Decimal(base_vol_usd + quote_vol_usd)
                    volumes["volumes"][depair][variant].update(
                        {
                            "base_volume": base_vol,
                            "quote_volume": quote_vol,
                            "base_volume_usd": base_vol_usd,
                            "quote_volume_usd": quote_vol_usd,
                            "trade_volume_usd": trade_vol_usd,
                            "dex_price": quote_vol / base_vol,
                        }
                    )
                    if variant == "ALL":
                        total_base_vol_usd += base_vol_usd
                        total_quote_vol_usd += quote_vol_usd
                        total_trade_vol_usd += trade_vol_usd

            volumes.update(
                {
                    "base_volume_usd": total_base_vol_usd,
                    "quote_volume_usd": total_quote_vol_usd,
                    "trade_volume_usd": total_trade_vol_usd,
                }
            )
            return default.result(
                data=volumes,
                msg=f"pair_trade_vols_usd complete [US${total_trade_vol_usd}]",
                loglevel="query",
                ignore_until=0,
            )

        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")

    # TODO: Pair swap duration stats.
    # Fastest, slowest, average, [x,y] for graph
    # TODO: Subclass 'last trade'
    @timed
    def last_trade(
        self, group_by_cols, is_success: bool = True, since=0, is_pairs=False
    ):
        try:
            with Session(self.engine) as session:
                resp = {}
                # 1st query for most recent swap info for category
                category = list(
                    chain.from_iterable((text(obj), "-") for obj in group_by_cols[:-1])
                ) + [group_by_cols[-1]]
                cols = [
                    self.table.uuid.label("last_swap_uuid"),
                    self.table.finished_at.label("last_swap_time"),
                    self.table.price.label("last_swap_price"),
                    self.table.maker_amount.label("last_maker_amount"),
                    self.table.taker_amount.label("last_taker_amount"),
                    self.table.trade_type.label("last_trade_type"),
                    func.concat(*category).label("category"),
                ]
                q = session.query(*cols)
                q = self.sqlfilter.since(q, since)
                q = self.sqlfilter.success(q, is_success)
                q = q.distinct(*category)
                q = q.order_by(*category, self.table.finished_at.desc())
                last_data = [dict(i) for i in q.all()]

                last_data_dict = {}
                for i in last_data:
                    if i["category"] not in last_data_dict:
                        last_data_dict.update({i["category"]: i})
                    else:
                        logger.query(f"INVERSE DATA EXISTS for {i['category']}!")
                for cat in last_data_dict:
                    if cat not in resp:
                        resp.update({cat: {}})
                    for k, v in last_data_dict[cat].items():
                        if k != "category":
                            resp[cat].update({k: v})

                # TODO: use separate cache for the below

                # 2nd query for swap first swap info for category
                cols = [
                    self.table.uuid.label("first_swap_uuid"),
                    self.table.finished_at.label("first_swap_time"),
                    self.table.price.label("first_swap_price"),
                    self.table.maker_amount.label("first_maker_amount"),
                    self.table.taker_amount.label("first_taker_amount"),
                    self.table.trade_type.label("first_trade_type"),
                    func.concat(*category).label("category"),
                ]
                q = session.query(*cols)
                q = self.sqlfilter.since(q, since)
                q = self.sqlfilter.success(q, is_success)
                q = q.distinct(*group_by_cols)
                q = q.order_by(*group_by_cols, self.table.finished_at.asc())
                first_data = [dict(i) for i in q.all()]

                first_data_dict = {}
                for i in first_data:
                    if i["category"] not in first_data_dict:
                        first_data_dict.update({i["category"]: i})
                    else:
                        logger.warning(f"INVERSE DATA EXISTS for {i['category']}!")
                for cat in first_data_dict:
                    if cat not in resp:
                        resp.update({cat: {}})
                    for k, v in first_data_dict[cat].items():
                        if k != "category":
                            resp[cat].update({k: v})

                return default.result(
                    data=resp,
                    msg="last_traded complete",
                    loglevel="query",
                    ignore_until=5,
                )
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")

    @timed
    def pair_last_trade(self, is_success: bool = True, since=0):
        try:
            group_by_cols = [self.table.pair_std]
            results = self.last_trade(
                is_success=is_success,
                group_by_cols=group_by_cols,
                since=since,
                is_pairs=True,
            )
            return default.result(
                data=results,
                msg="pair_last_trade complete",
                loglevel="query",
                ignore_until=5,
            )
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")

    @timed
    def coin_last_traded(self, is_success: bool = True, trade_side: str = "maker"):
        try:
            if trade_side == "maker":
                group_by_cols = [self.table.maker_coin]
            elif trade_side == "taker":
                group_by_cols = [self.table.taker_coin]
            elif trade_side == "all":
                group_by_cols = [self.table.maker_coin, self.table.taker_coin]
            results = self.last_trade(
                is_success=is_success, group_by_cols=group_by_cols
            )
            return default.result(
                data=results,
                msg="coin_last_traded complete",
                loglevel="query",
                ignore_until=5,
            )
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")

    @timed
    def pubkey_last_traded(self, is_success: bool = True, trade_side: str = "maker"):
        try:
            if trade_side == "maker":
                group_by_cols = [self.table.maker_pubkey]
            elif trade_side == "taker":
                group_by_cols = [self.table.taker_pubkey]
            elif trade_side == "all":
                group_by_cols = [self.table.maker_pubkey, self.table.taker_pubkey]
            results = self.last_trade(
                is_success=is_success, group_by_cols=group_by_cols
            )
            return default.result(
                data=results, msg="pubkey_last_traded complete", loglevel="query"
            )
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")

    @timed
    def version_last_traded(self, is_success: bool = True, trade_side: str = "maker"):
        try:
            if trade_side == "maker":
                group_by_cols = [self.table.maker_version]
            elif trade_side == "taker":
                group_by_cols = [self.table.taker_version]
            elif trade_side == "all":
                group_by_cols = [self.table.maker_version, self.table.taker_version]
            results = self.last_trade(
                is_success=is_success, group_by_cols=group_by_cols
            )
            return default.result(
                data=results, msg="version_last_traded complete", loglevel="query"
            )
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")

    @timed
    def gui_last_traded(self, is_success: bool = True, trade_side: str = "maker"):
        try:
            data = {}
            group_by_cols = [self.table.maker_gui]
            maker_data = self.last_trade(
                is_success=is_success, group_by_cols=group_by_cols
            )
            for i in maker_data:
                k = derive.app(i)
                if k not in data:
                    data.update({k: template.last_traded_item()})
                data[k].update(
                    {
                        # "maker_num_swaps": maker_data[i]["num_swaps"],
                        "maker_last_swap_uuid": maker_data[i]["last_swap_uuid"],
                        "maker_last_swap_time": maker_data[i]["last_swap_time"],
                        "maker_first_swap_uuid": maker_data[i]["first_swap_uuid"],
                        "maker_first_swap_time": maker_data[i]["first_swap_time"],
                        "raw_category": i,
                    }
                )

            group_by_cols = [self.table.taker_gui]
            taker_data = self.last_trade(
                is_success=is_success, group_by_cols=group_by_cols
            )
            for i in taker_data:
                k = derive.app(i)
                if k not in data:
                    data.update({k: template.last_traded_item()})
                data[k].update(
                    {
                        # "taker_num_swaps": taker_data[i]["num_swaps"],
                        "taker_last_swap_uuid": taker_data[i]["last_swap_uuid"],
                        "taker_last_swap_time": taker_data[i]["last_swap_time"],
                        "taker_first_swap_uuid": taker_data[i]["first_swap_uuid"],
                        "taker_first_swap_time": taker_data[i]["first_swap_time"],
                        "raw_category": i,
                    }
                )

            return default.result(
                data=data, msg="gui_last_traded complete", loglevel="query"
            )
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")

    # TODO: Returning errors, debug later
    @timed
    def platform_last_traded(self, is_success: bool = True, trade_side: str = "maker"):
        try:
            if trade_side == "maker":
                group_by_cols = [self.table.maker_coin_platform]
            elif trade_side == "taker":
                group_by_cols = [self.table.taker_coin_platform]
            elif trade_side == "all":
                group_by_cols = [
                    self.table.maker_coin_platform,
                    self.table.taker_coin_platform,
                ]
            results = self.last_trade(
                is_success=is_success, group_by_cols=group_by_cols
            )
            return default.result(
                data=results, msg="platform_last_traded complete", loglevel="query"
            )
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")

    @timed
    def ticker_last_traded(self, is_success: bool = True, trade_side: str = "maker"):
        try:
            if trade_side == "maker":
                group_by_cols = [self.table.maker_coin_ticker]
            elif trade_side == "taker":
                group_by_cols = [self.table.taker_coin_ticker]
            elif trade_side == "all":
                group_by_cols = [
                    self.table.maker_coin_ticker,
                    self.table.taker_coin_ticker,
                ]
            results = self.last_trade(
                is_success=is_success, group_by_cols=group_by_cols
            )
            return default.result(
                data=results, msg="ticker_last_traded complete", loglevel="query"
            )
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")

    # TODO: Subclass 'swaps'
    @timed
    def get_swaps(
        self,
        start_time: int = 0,
        end_time: int = 0,
        coin: str | None = None,
        pair_str: str | None = None,
        pubkey: str | None = None,
        gui: str | None = None,
        version: str | None = None,
        success_only: bool = True,
        failed_only: bool = False,
        limit: int = 100,
        trade_type: int | None = None,
        uuid: str | None = None,
    ):
        """
        Returns swaps matching filter from any of the SQL databases.
        For MM2 and Cipi's databases, some fields are derived or set
        to default as they are not present in the source. The Pgsql
        'defi_stats' database contains data imported from the above,
        using the higher value for any numeric fields, and with defaults
        reconciled (if available in either of the MM2/Cipi databases).

        For `pair_str` or `coin`, it will return all
        variants to be combined (or further filtered) later.
        """
        try:
            # TODO: Implement limit and trade_type
            if uuid is None:
                if start_time == 0:
                    start_time = int(cron.now_utc()) - 86400
                if end_time == 0:
                    end_time = int(cron.now_utc())
            else:
                start_time = 1
                end_time = int(cron.now_utc())
            if end_time == 1741176652:
                logger.info(f"Getting swaps for {start_time} to {end_time} | {coin} | {pair_str} |")
            if self.table.__tablename__ in ["swaps", "swaps_failed"]:
                start_time = datetime.fromtimestamp(start_time, timezone.utc)
                end_time = datetime.fromtimestamp(end_time, timezone.utc)
            
            with Session(self.engine) as session:
                q = select(self.table)
                q = self.sqlfilter.timestamps(q, start_time, end_time)
                if gui is not None:
                    q = self.sqlfilter.gui(q, gui)
                if uuid is not None:
                    q = self.sqlfilter.uuid(q, uuid)
                if gui is not None:
                    q = self.sqlfilter.version(q, version)
                if version is not None:
                    q = self.sqlfilter.pubkey(q, pubkey)
                if end_time != 1741176652:
                    q = self.sqlfilter.success(q, success_only, failed_only)
                if self.table in [CipiSwap, CipiSwapFailed]:
                    q = q.order_by(self.table.started_at)
                else:
                    q = q.order_by(self.table.finished_at)

                r = session.exec(q)
                data = [dict(i) for i in r]
                if end_time == 1741176652:
                    logger.info(f"Got {len(data)} swaps for {start_time} to {end_time} | {coin} | {pair_str} |")
                if coin is not None:
                    variants = derive.coin_variants(coin)
                    resp = {
                        i: [j for j in data if i in [j["taker_coin"], j["maker_coin"]]]
                        for i in variants
                    }
                    all = []
                    for i in resp:
                        all += resp[i]
                    resp.update({"ALL": all})
                elif pair_str is not None:
                    resp = {}
                    variants = derive.pair_variants(pair_str)
                    for variant in variants:
                        if validate.is_bridge_swap_duplicate(pair_str, self.gecko_source):
                            logger.warning(f"Skipping bridge_swap_duplicate {pair_str}")
                            continue
                        resp.update({
                            variant: derive.variant_trades(variant, data)
                        })
                    all = []
                    for i in resp:
                        all += resp[i]
                    sortdata.dict_lists(data=all, key="finished_at", reverse=True)
                    resp.update({"ALL": all})

                else:
                    resp = data
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")
        msg = f"Got {len(data)} swaps from {self.table.__tablename__}"
        msg += f" between {start_time} and {end_time}"
        return default.result(data=resp, msg=msg, loglevel="muted")

    @timed
    def get_swap(self, uuid: str = ""):
        try:
            with Session(self.engine) as session:
                q = select(self.table).where(self.table.uuid == uuid)
                data = [dict(i) for i in session.exec(q)]
                if len(data) == 0:
                    return {"error": f"swap uuid {uuid} not found"}
                else:
                    return data[0]
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")

    @timed
    def get_timespan_swaps(self, start_time: int = 0, end_time: int = 0) -> list:
        """
        Returns a list of swaps between two timestamps
        """
        try:
            return self.get_swaps(start_time=start_time, end_time=end_time)
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")

    @timed
    def get_swaps_for_coin(
        self,
        coin: str,
        merge_segwit: bool = False,
        all_variants: bool = False,
        **kwargs,
    ):
        """
        Returns swaps for a variant of a coin only.
        Optionally, segwit coins can be merged
        """
        swaps = self.get_swaps(coin=coin, **kwargs)
        if all_variants:
            return swaps["ALL"]
        if merge_segwit:
            variants = derive.coin_variants(coin, segwit_only=True)
            return merge.swaps(variants, swaps)
        return swaps[coin]

    @timed
    def get_swaps_for_pair(
        self,
        base: str,
        quote: str,
        merge_segwit: bool = True,
        start_time: int = 0,
        end_time: int = 0,
        limit: int = 100,
        trade_type: int | None = None,
        pubkey: str | None = None,
        gui: str | None = None,
        version: str | None = None,
        success_only: bool = True,
        failed_only: bool = False,
        all_variants: bool = False,
        full_scan: bool = False,
    ):
        """
        Returns swaps for a variant of a pair only.
        Optionally, pairs with segwit coins can be merged
        """
        try:
            pair_str = f"{base}_{quote}"
            if full_scan:
                swaps = []
                with Session(self.engine) as session:
                    q = select(self.table).filter(
                        or_(
                            pair_str == self.table.pair,
                            pair_str == self.table.pair_reverse,
                        )
                    ).order_by(self.table.finished_at)
                r = session.exec(q)
                resp = [dict(i) for i in r]
            else:
                swaps = self.get_swaps(
                    pair_str=pair_str,
                    start_time=start_time,
                    end_time=end_time,
                    limit=limit,
                    trade_type=trade_type,
                    pubkey=pubkey,
                    gui=gui,
                    version=version,
                    success_only=success_only,
                    failed_only=failed_only,
                )
                # TODO: This should return all variants
                # and be merged as req later
                if all_variants:
                    resp = swaps["ALL"]
                elif merge_segwit:
                    segwit_variants = derive.pair_variants(pair_str, segwit_only=True)
                    resp = merge.swaps(segwit_variants, swaps)
                elif pair_str in swaps:
                    resp = swaps[pair_str]
                elif invert.pair(pair_str) in swaps:
                    resp = swaps[invert.pair(pair_str)]
                else:
                    return []
            if len(resp) > 0:
                resp = sortdata.dict_lists(data=resp, key="finished_at", reverse=True)
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")
        msg = f"Got {len(resp)} swaps from {self.table.__tablename__}"
        msg += f" between {start_time} and {end_time}"
        return default.result(data=resp, msg=msg, loglevel="muted")

    @timed
    def swap_uuids(
        self,
        start_time: int = 0,
        end_time: int = 0,
        coin=None,
        pair=None,
        pubkey: str | None = None,
        gui: str | None = None,
        version: str | None = None,
        success_only: bool = True,
        failed_only: bool = False,
        full_scan_pair: bool = False,
    ):
        try:
            if full_scan_pair:
                base, quote = derive.base_quote(pair)
                swaps = self.get_swaps_for_pair(full_scan=True, base=base, quote=quote)
            else:
                if start_time == 0:
                    start_time = int(cron.now_utc()) - 86400
                if end_time == 0:
                    end_time = int(cron.now_utc())
                swaps = self.get_swaps(
                    start_time=start_time,
                    end_time=end_time,
                    coin=coin,
                    pair_str=pair,
                    pubkey=pubkey,
                    gui=gui,
                    version=version,
                    success_only=success_only,
                    failed_only=failed_only,
                )
            if len(swaps) > 0:
                if "uuid" in swaps[0]:
                    return [i["uuid"] for i in swaps]
                elif "ALL" in swaps[0]:
                    resp = {}
                    for variant in swaps:
                        resp.update({variant: [i["uuid"] for i in swaps[variant]]})
                    return resp
                else:
                    logger.warning(swaps[0])
            
        except Exception as e:
            logger.loop(e)
        return []

    @timed
    def get_pairs(self, days: int = 7) -> list:
        """
        Returns an alphabetically sorted list of pair strings
        with at least one successful swap in the last 'x' days.
        Results sorted by market cap to conform to CEX standards.
        """
        # TODO: Function underutilised. Refactor.
        try:
            
            start_time = int(cron.now_utc() - 86400 * days)
            end_time = int(cron.now_utc())
            pairs = self.get_distinct(
                column="pair", start_time=start_time, end_time=end_time
            )

            # Sort pair by ticker mcap to expose duplicates
            sorted_pairs = list(
                set(
                    [
                        sortdata.pair_by_market_cap(i, gecko_source=self.gecko_source)
                        for i in pairs
                    ]
                )
            )
            if len(sorted_pairs) < len(pairs):
                logger.warning(f"{len(pairs) - len(sorted_pairs)} pairs have non standard entries!")
                bad_pairs = pairs - sorted_pairs
                logger.warning(bad_pairs)
                pgdb = SqlUpdate(db_type="pgsql")    
                # TODO: Thread this
                # for pair in bad_pairs:
                    # pgdb.fix_swap_pair(pair, self)
            return default.result(
                data=sorted_pairs,
                msg="Got generic pairs from db",
                loglevel="query",
                ignore_until=0,
            )
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")

    @timed
    def get_distinct(
        self,
        start_time: int = 0,
        end_time: int = 0,
        column: str | None = None,
        coin: str | None = None,
        pair: str | None = None,
        pubkey: str | None = None,
        gui: str | None = None,
        version: str | None = None,
        success_only: bool = True,
        failed_only: bool = False,
    ):
        if end_time == 0:
            end_time = int(cron.now_utc())
        with Session(self.engine) as session:
            if coin is not None:
                q = session.query(self.table.maker_coin, self.table.taker_coin)
            elif pair is not None:
                q = session.query(self.table.pair)
            elif column is not None:
                try:
                    col = getattr(self.table, column)
                    q = session.query(col)
                except AttributeError as e:  # pragma: no cover
                    logger.warning(type(e))
                    logger.warning(e)
                    msg = f"'{column}' does not exist in {self.table.__tablename__}!"
                    msg += f" Options are {get_columns(self.table)}"
                    raise InvalidParamCombination(msg=msg)
                except Exception as e:  # pragma: no cover
                    logger.warning(type(e))
                    logger.warning(e)
                    msg = f"'{column}' does not exist in {self.table.__tablename__}!"
                    msg += f" Options are {get_columns(self.table)}"
                    raise InvalidParamCombination(msg=msg)
            else:  # pragma: no cover
                raise InvalidParamCombination(
                    "Unless 'pair' or 'coin' param is set, you must set the 'column' param."
                )

            q = self.sqlfilter.gui(q, gui)
            q = self.sqlfilter.coin(q, coin)
            q = self.sqlfilter.pair(q, pair)
            q = self.sqlfilter.pubkey(q, pubkey)
            q = self.sqlfilter.version(q, version)
            q = self.sqlfilter.timestamps(q, start_time, end_time)
            q = self.sqlfilter.success(q, success_only, failed_only)
            q = q.distinct()
            data = [list(dict(i).values())[0] for i in q.all()]
        return data

    @timed
    def get_count(
        self,
        start_time: int = 0,
        end_time: int = 0,
        coin: str | None = None,
        pair: str | None = None,
        pubkey: str | None = None,
        gui: str | None = None,
        version: str | None = None,
        success_only: bool = True,
        failed_only: bool = False,
    ):
        if start_time == 0:
            start_time = int(cron.now_utc()) - 86400
        if end_time == 0:
            end_time = int(cron.now_utc())

        with Session(self.engine) as session:
            q = session.query(func.count(self.table.uuid).label("swaps_count"))
            q = self.sqlfilter.gui(q, gui=gui)
            q = self.sqlfilter.coin(q, coin=coin)
            q = self.sqlfilter.pair(q, pair=pair)
            q = self.sqlfilter.pubkey(q, pubkey=pubkey)
            q = self.sqlfilter.version(q, version=version)
            q = self.sqlfilter.timestamps(q, start_time=start_time, end_time=end_time)
            q = self.sqlfilter.success(
                q, success_only=success_only, failed_only=failed_only
            )
            r = q.all()
            return r[0][0]

    @timed
    def get_last(self, table: str, limit: int = 3):
        try:
            with Session(self.engine) as session:
                r = (
                    session.query(table)
                    .where(table.is_success == 1)
                    .order_by(table.finished_at.desc())
                    .limit(limit)
                    .all()
                )
                return [dict(i) for i in r]
        except Exception as e:  # pragma: no cover
            logger.error(e)

    @timed
    def get_first(self, table: str, limit: int = 3):
        try:
            with Session(self.engine) as session:
                r = (
                    session.query(table)
                    .where(table.is_success == 1)
                    .order_by(table.finished_at.asc())
                    .limit(limit)
                    .all()
                )
                return [dict(i) for i in r]
        except Exception as e:  # pragma: no cover
            logger.error(e)

    @timed
    def describe(self, table):
        with Session(self.engine) as session:
            stmt = text(f"DESCRIBE {get_tablename(table)};")
            r = session.exec(stmt)
            for i in r:
                logger.merge(i)

    @timed
    def swap_counts(self):  # pragma: no cover
        month_ago = int(cron.now_utc()) - 86400 * 30
        fortnight_ago = int(cron.now_utc()) - 86400 * 14
        week_ago = int(cron.now_utc()) - 86400 * 7
        day_ago = int(cron.now_utc()) - 86400
        return {
            "swaps_all_time": self.get_count(start_time=1),
            "swaps_30d": self.get_count(start_time=month_ago),
            "swaps_14d": self.get_count(start_time=fortnight_ago),
            "swaps_7d": self.get_count(start_time=week_ago),
            "swaps_24hr": self.get_count(start_time=day_ago),
        }


class SqlSource:
    def __init__(
        self,
        gecko_source: Dict | None = None,
    ) -> None:
        self._gecko_source = gecko_source

    @property
    def gecko_source(self):
        if self._gecko_source is None:
            logger.calc("sourcing gecko")
            self._gecko_source = memcache.get_gecko_source()
        if self._gecko_source is None:
            self._gecko_source = gecko_api.get_source_data(from_file=True)
        return self._gecko_source

    @timed
    def import_cipi_swaps(
        self,
        pgdb: SqlDB,
        pgdb_query: SqlQuery,
        start_time=0,
        end_time=0,
    ):
        try:
            if start_time == 0:
                start_time = int(cron.now_utc() - 86400)
            if end_time == 0:
                end_time = int(cron.now_utc())
            # import Cipi's swap data
            ext_mysql = SqlQuery(db_type="mysql", gecko_source=self.gecko_source)
            cipi_swaps = ext_mysql.get_swaps(start_time=start_time, end_time=end_time)
            cipi_swaps = self.normalise_swap_data(cipi_swaps)
            if len(cipi_swaps) > 0:
                with Session(pgdb.engine) as session:
                    # check_column_types(session, DefiSwap)
                    count = pgdb_query.get_count(start_time=1)
                    logger.info(f"count: {count}")
                    cipi_swaps_data = {}
                    for i in cipi_swaps:
                        cipi_swaps_data.update({i["uuid"]: i})
                    overlapping_swaps = (
                        session.query(DefiSwap)
                        .filter(DefiSwap.uuid.in_(cipi_swaps_data.keys()))
                        .all()
                    )

                    updates = []
                    skipped = 0
                    for each in overlapping_swaps:
                        # logger.info(each.__dict__)

                        # Get dict row for existing swaps
                        swap = self.cipi_to_defi_swap(
                            cipi_swaps_data[each.uuid], each.__dict__
                        )
                        if not isinstance(swap, DefiSwap):
                            # A row we can not convert must never abort the
                            # batch. Drop it from the queue (it is already in
                            # the DB) and keep importing the rest.
                            skipped += 1
                            logger.warning(
                                "Skipped Cipi swap update, conversion failed! "
                                f"{swap_log_context(cipi_swaps_data[each.uuid])}"
                            )
                            cipi_swaps_data.pop(each.uuid)
                            continue
                        cipi_data = swap.__dict__
                        # create bindparam
                        cipi_data.update({"_id": each.id})
                        # remove id field to avoid contraint errors
                        if "_sa_instance_state" in cipi_data:
                            del cipi_data["_sa_instance_state"]
                        if "id" in cipi_data:
                            del cipi_data["id"]
                        # all to bulk update list
                        updates.append(cipi_data)
                        # remove from processing queue
                        cipi_swaps_data.pop(each.uuid)
                        # logger.calc(cipi_data)

                    valid_updates = [d for d in updates if "_id" in d and d["_id"]]
                    invalid_updates = [d for d in updates if "_id" not in d or not d["_id"]]
 

                    if len(valid_updates) > 0:
                        for d in valid_updates:
                            if "_id" not in d or not d["_id"]:
                                logger.warning("Missing primary key in update data:", d)
                            d = validate.ensure_valid_pair(d, gecko_source=self.gecko_source)
                        # Update existing records
                        bind_values = {
                            i: bindparam(i)
                            for i in valid_updates[0].keys()
                            if i not in ["_id"]
                        }
                        stmt = (
                            update(DefiSwap)
                            .where(DefiSwap.id == bindparam("_id"))
                            .values(bind_values)
                            .execution_options(synchronize_session=None)
                        )
                        session.connection().execute(stmt, valid_updates)

                    # Add new records left in processing queue
                    for uuid in cipi_swaps_data.keys():
                        swap = self.cipi_to_defi_swap(cipi_swaps_data[uuid])
                        if not isinstance(swap, DefiSwap):
                            # One unconvertable row used to poison the whole
                            # batch via `session.add(dict)`. Skip it instead.
                            skipped += 1
                            logger.warning(
                                "Skipped Cipi swap, conversion failed! "
                                f"{swap_log_context(cipi_swaps_data[uuid])}"
                            )
                            continue
                        if uuid not in valid_updates:
                            session.add(swap)
                    session.commit()
                    count_after = pgdb_query.get_count(start_time=1)
                    msg = f"{count_after - count} records added, "
                    msg += f"{len(valid_updates)} updated from Cipi database"
                    if skipped > 0:
                        msg += f", {skipped} skipped (conversion failed)"
            else:
                msg = "Zero Cipi swaps returned!"

        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")
        return default.result(msg=msg, loglevel="sourced")

    @timed
    def import_mm2_swaps(
        self,
        pgdb: SqlDB,
        pgdb_query: SqlQuery,
        start_time=int(cron.now_utc() - 86400),
        end_time=int(cron.now_utc()),
    ):
        try:
            # Import in Sqlite (all) database
            mm2_sqlite = SqlQuery(
                db_type="sqlite",
                db_path=MM2_DB_PATH_ALL,
                gecko_source=self.gecko_source,
            )
            mm2_swaps = mm2_sqlite.get_swaps(start_time=start_time, end_time=end_time)
            mm2_swaps = self.normalise_swap_data(mm2_swaps)
            if len(mm2_swaps) > 0:
                with Session(pgdb.engine) as session:
                    count = pgdb_query.get_count(start_time=1)
                    mm2_swaps_data = {}
                    for i in mm2_swaps:
                        mm2_swaps_data.update({i["uuid"]: i})

                    overlapping_swaps = (
                        session.query(DefiSwap)
                        .filter(DefiSwap.uuid.in_(mm2_swaps_data.keys()))
                        .all()
                    )

                    updates = []
                    skipped = 0
                    overlapping_uuids = {each.uuid for each in overlapping_swaps}
                    for each in overlapping_swaps:
                        # Get dict row for existing swaps
                        swap = self.mm2_to_defi_swap(
                            mm2_swaps_data[each.uuid], each.__dict__
                        )
                        if not isinstance(swap, DefiSwap):
                            # A row we can not convert must never abort the
                            # batch. Drop it from the queue (it is already in
                            # the DB) and keep importing the rest.
                            skipped += 1
                            logger.warning(
                                "Skipped MM2 swap update, conversion failed! "
                                f"{swap_log_context(mm2_swaps_data[each.uuid])}"
                            )
                            mm2_swaps_data.pop(each.uuid)
                            continue
                        mm2_data = swap.__dict__
                        # create bindparam
                        mm2_data.update({"_id": each.id})
                        # remove id field to avoid contraint errors
                        if "id" in mm2_data:
                            del mm2_data["id"]
                        if "_sa_instance_state" in mm2_data:
                            del mm2_data["_sa_instance_state"]
                        # all to bulk update list
                        updates.append(mm2_data)
                        # remove from processing queue
                        mm2_swaps_data.pop(each.uuid)

                    if len(updates) > 0:
                        for d in updates:
                            if "_id" not in d or not d["_id"]:
                                logger.warning("Missing primary key in update data:", d)
                            d = validate.ensure_valid_pair(d, gecko_source=self.gecko_source)
                        # Update existing records
                        bind_values = {
                            i: bindparam(i)
                            for i in updates[0].keys()
                            if i not in ["_id"]
                        }
                        stmt = (
                            update(DefiSwap)
                            .where(DefiSwap.id == bindparam("_id"))
                            .values(bind_values)
                            .execution_options(synchronize_session="none")
                        )
                        session.connection().execute(stmt, updates)

                    # Add new records left in processing queue
                    for uuid in mm2_swaps_data.keys():
                        swap = self.mm2_to_defi_swap(mm2_swaps_data[uuid])
                        if not isinstance(swap, DefiSwap):
                            # One unconvertable row used to poison the whole
                            # batch via `session.add(dict)`. Skip it instead.
                            skipped += 1
                            logger.warning(
                                "Skipped MM2 swap, conversion failed! "
                                f"{swap_log_context(mm2_swaps_data[uuid])}"
                            )
                            continue
                        if uuid not in overlapping_uuids:
                            session.add(swap)
                    session.commit()
                    count_after = pgdb_query.get_count(start_time=1)
                    msg = f"{count_after - count} records added, "
                    msg += f"{len(updates)} updated from MM2.db"
                    if skipped > 0:
                        msg += f", {skipped} skipped (conversion failed)"
            else:
                msg = "Zero MM2 swaps returned!"
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")
        return default.result(msg=msg, loglevel="sourced")

        
    @timed
    def populate_pgsqldb(
        self,
        start_time=0,
        end_time=0,
    ):
        try:
            if start_time == 0:
                start_time = int(cron.now_utc() - 86400)
            if end_time == 0:
                end_time = int(cron.now_utc())
            pgdb = SqlUpdate(db_type="pgsql")
            pgdb_query = SqlQuery(db_type="pgsql", gecko_source=self.gecko_source)
            self.import_cipi_swaps(
                pgdb, pgdb_query, start_time=start_time, end_time=end_time
            )
            self.import_mm2_swaps(
                pgdb, pgdb_query, start_time=start_time, end_time=end_time
            )
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")
        msg = f"Importing swaps from {start_time} - {end_time} complete"
        return default.result(msg=msg, loglevel="updated", ignore_until=10)

    @timed
    def reset_defi_stats_table(self):
        pgdb = SqlUpdate("pgsql")
        pgdb.drop("defi_swaps")
        SQLModel.metadata.create_all(pgdb.engine)
        logger.merge("Recreated PGSQL Table")

    @timed
    def normalise_swap_data(self, data, is_success=None):
        try:

            for i in data:
                # Standardize pair_strings
                # "pair" should always be sorted by market cap. | KMD_LTC
                i = validate.ensure_valid_pair(i, gecko_source=self.gecko_source)
                if "is_success" not in i:
                    if is_success is not None:
                        if is_success:
                            i.update({"is_success": 1})
                        else:
                            i.update({"is_success": 0})
                    else:
                        # Incoming cipi swaps dont have this, so we assume success until validated.
                        # TODO: make this less fuzzy
                        i.update({"is_success": 1})

                for k, v in i.items():
                    if k in [
                        "maker_pubkey",
                        "taker_pubkey",
                        "taker_gui",
                        "maker_gui",
                        "taker_version",
                        "maker_version",
                    ]:
                        if v in [None, ""]:
                            i.update({k: ""})
                    if k in [
                        "maker_coin_usd_price",
                        "taker_coin_usd_price",
                        "started_at",
                        "finished_at",
                    ]:
                        if v in [None, ""]:
                            i.update({k: 0})

        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")
        msg = "Data normalised"
        return default.result(msg=msg, data=data, loglevel="calc", ignore_until=10)

    @timed
    def cipi_to_defi_swap(self, cipi_data, defi_data=None):  # pragma: no cover
        """
        Compares with existing to select best value where there
        is a conflict, or returns normalised data from a source
        database with derived fields calculated or defaults applied
        """
        try:
            if defi_data is None:
                for i in ["taker_gui", "maker_gui", "taker_version", "maker_version"]:
                    if i not in cipi_data:
                        cipi_data.update({i: ""})
                cipi_data = validate.ensure_valid_pair(cipi_data, gecko_source=self.gecko_source)
                if cipi_data["pair"] != sortdata.pair_by_market_cap(
                    cipi_data["pair"], gecko_source=self.gecko_source
                ):
                    logger.warning(
                        f"cipi_data Pair is non standard! {cipi_data['pair']}"
                    )
                data = DefiSwap(
                    uuid=cipi_data["uuid"],
                    taker_amount=cipi_data["taker_amount"],
                    taker_coin=cipi_data["taker_coin"],
                    taker_gui=cipi_data["taker_gui"],
                    taker_pubkey=cipi_data["taker_pubkey"],
                    taker_version=cipi_data["taker_version"],
                    maker_amount=cipi_data["maker_amount"],
                    maker_coin=cipi_data["maker_coin"],
                    maker_gui=cipi_data["maker_gui"],
                    maker_pubkey=cipi_data["maker_pubkey"],
                    maker_version=cipi_data["maker_version"],
                    started_at=int(cipi_data["started_at"].timestamp()),
                    # Not in Cipi's DB, but better than zero.
                    finished_at=cipi_data["started_at"],
                    # Not in Cipi's DB, but able to derive.
                    price=cipi_data["price"],
                    reverse_price=cipi_data["reverse_price"],
                    is_success=cipi_data["is_success"],
                    maker_coin_platform=cipi_data["maker_coin_platform"],
                    maker_coin_ticker=cipi_data["maker_coin_ticker"],
                    taker_coin_platform=cipi_data["taker_coin_platform"],
                    taker_coin_ticker=cipi_data["taker_coin_ticker"],
                    # Extra columns
                    trade_type=cipi_data["trade_type"],
                    pair=cipi_data["pair"],
                    pair_reverse=invert.pair(cipi_data["pair"]),
                    pair_std=deplatform.pair(cipi_data["pair"]),
                    pair_std_reverse=deplatform.pair(invert.pair(cipi_data["pair"])),
                    last_updated=int(cron.now_utc()),
                )
            else:
                cipi_data = validate.ensure_valid_pair(cipi_data, gecko_source=self.gecko_source)
                defi_data = validate.ensure_valid_pair(defi_data, gecko_source=self.gecko_source)
                if cipi_data["pair"] != sortdata.pair_by_market_cap(
                    cipi_data["pair"], gecko_source=self.gecko_source
                ):
                    logger.warning(
                        f"cipi_data Pair is non standard! {cipi_data['pair']}"
                    )
                if defi_data["pair"] != sortdata.pair_by_market_cap(
                    defi_data["pair"], gecko_source=self.gecko_source
                ):
                    logger.warning(
                        f"defi_data Pair is non standard! {defi_data['pair']}"
                    )
                for i in [
                    "taker_coin",
                    "maker_coin",
                    "taker_gui",
                    "maker_gui",
                    "taker_pubkey",
                    "maker_pubkey",
                    "taker_version",
                    "maker_version",
                    "taker_coin_ticker",
                    "taker_coin_ticker",
                    "taker_coin_platform",
                    "taker_coin_platform",
                ]:
                    if cipi_data[i] != defi_data[i]:
                        if cipi_data[i] in ["", "None", "unknown", None]:
                            cipi_data[i] = defi_data[i]
                        elif defi_data[i] in ["", "None", "unknown", None]:
                            defi_data[i] = cipi_data[i]
                        elif isinstance(defi_data[i], str):
                            if len(defi_data[i]) == 0:
                                defi_data[i] = cipi_data[i]
                            pass
                        else:
                            # This shouldnt happen
                            logger.warning(
                                "Mismatch on incoming cipi data vs defi data:"
                            )
                            logger.warning(f"{cipi_data[i]} vs {defi_data[i]}")

                if cipi_data["pair"] != sortdata.pair_by_market_cap(
                    cipi_data["pair"], gecko_source=self.gecko_source
                ):
                    logger.warning(
                        f"cipi_data Pair is non standard! {cipi_data['pair']}"
                    )
                data = DefiSwap(
                    uuid=cipi_data["uuid"],
                    taker_coin=cipi_data["taker_coin"],
                    taker_gui=cipi_data["taker_gui"],
                    taker_pubkey=cipi_data["taker_pubkey"],
                    taker_version=cipi_data["taker_version"],
                    maker_coin=cipi_data["maker_coin"],
                    maker_gui=cipi_data["maker_gui"],
                    maker_pubkey=cipi_data["maker_pubkey"],
                    maker_version=cipi_data["maker_version"],
                    maker_coin_platform=cipi_data["maker_coin_platform"],
                    maker_coin_ticker=cipi_data["maker_coin_ticker"],
                    taker_coin_platform=cipi_data["taker_coin_platform"],
                    taker_coin_ticker=cipi_data["taker_coin_ticker"],
                    taker_amount=max(
                        cipi_data["taker_amount"], defi_data["taker_amount"]
                    ),
                    maker_amount=max(
                        cipi_data["maker_amount"], defi_data["maker_amount"]
                    ),
                    started_at=max(
                        int(cipi_data["started_at"].timestamp()),
                        defi_data["started_at"],
                    ),
                    finished_at=max(
                        int(cipi_data["started_at"].timestamp()),
                        defi_data["finished_at"],
                    ),
                    is_success=max(cipi_data["is_success"], defi_data["is_success"]),
                    # Not in Cipi's DB, derived from taker/maker amounts.
                    price=max(cipi_data["price"], defi_data["price"]),
                    reverse_price=max(
                        cipi_data["reverse_price"], defi_data["reverse_price"]
                    ),
                    # Not in Cipi's DB
                    maker_coin_usd_price=max(0, defi_data["maker_coin_usd_price"]),
                    taker_coin_usd_price=max(0, defi_data["taker_coin_usd_price"]),
                    # Extra columns
                    trade_type=defi_data["trade_type"],
                    pair=defi_data["pair"],
                    pair_reverse=invert.pair(defi_data["pair"]),
                    pair_std=deplatform.pair(defi_data["pair"]),
                    pair_std_reverse=deplatform.pair(invert.pair(defi_data["pair"])),
                    last_updated=int(cron.now_utc()),
                )
            if isinstance(data.finished_at, int) and isinstance(data.started_at, int):
                data.duration = data.finished_at - data.started_at
            else:
                data.duration = -1

        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")
        msg = "cipi to defi conversion complete"
        return default.result(msg=msg, data=data, loglevel="muted")


    @timed
    def mm2_to_defi_swap(self, mm2_data, defi_data=None):  # pragma: no cover
        """
        Compares to select best value where there is a conflict
        """
        try:
            if defi_data is None:
                for i in ["taker_gui", "maker_gui", "taker_version", "maker_version"]:
                    if i not in mm2_data:
                        mm2_data.update({i: ""})
                mm2_data = validate.ensure_valid_pair(mm2_data, gecko_source=self.gecko_source)
                if mm2_data["pair"] != sortdata.pair_by_market_cap(
                    mm2_data["pair"], gecko_source=self.gecko_source
                ):
                    logger.warning(f"mm2_data Pair is non standard! {mm2_data['pair']}")
                data = DefiSwap(
                    uuid=mm2_data["uuid"],
                    taker_amount=mm2_data["taker_amount"],
                    taker_coin=mm2_data["taker_coin"],
                    taker_pubkey=mm2_data["taker_pubkey"],
                    maker_amount=mm2_data["maker_amount"],
                    maker_coin=mm2_data["maker_coin"],
                    maker_pubkey=mm2_data["maker_pubkey"],
                    is_success=mm2_data["is_success"],
                    maker_coin_platform=mm2_data["maker_coin_platform"],
                    maker_coin_ticker=mm2_data["maker_coin_ticker"],
                    taker_coin_platform=mm2_data["taker_coin_platform"],
                    taker_coin_ticker=mm2_data["taker_coin_ticker"],
                    started_at=mm2_data["started_at"],
                    finished_at=mm2_data["finished_at"],
                    # Not in MM2 DB, but able to derive.
                    price=mm2_data["price"],
                    reverse_price=mm2_data["reverse_price"],
                    # Not in MM2 DB, using default.
                    taker_gui=mm2_data["taker_gui"],
                    taker_version=mm2_data["taker_version"],
                    maker_gui=mm2_data["maker_gui"],
                    maker_version=mm2_data["maker_version"],
                    # Extra columns
                    trade_type=mm2_data["trade_type"],
                    pair=mm2_data["pair"],
                    pair_reverse=invert.pair(mm2_data["pair"]),
                    pair_std=deplatform.pair(mm2_data["pair"]),
                    pair_std_reverse=deplatform.pair(invert.pair(mm2_data["pair"])),
                    last_updated=int(cron.now_utc()),
                )
            else:
                mm2_data = validate.ensure_valid_pair(mm2_data, gecko_source=self.gecko_source)
                if self.gecko_source is not None:
                    if mm2_data["pair"] != sortdata.pair_by_market_cap(
                        mm2_data["pair"], gecko_source=self.gecko_source
                    ):
                        logger.warning(
                            f"mm2_data Pair is non standard! {mm2_data['pair']}"
                        )
                    defi_data = validate.ensure_valid_pair(defi_data, gecko_source=self.gecko_source)
                    if defi_data["pair"] != sortdata.pair_by_market_cap(
                        defi_data["pair"], gecko_source=self.gecko_source
                    ):
                        logger.warning(
                            f"defi_data Pair is non standard! {defi_data['pair']}"
                        )
                for i in [
                    "taker_coin",
                    "maker_coin",
                    "taker_pubkey",
                    "maker_pubkey",
                    "taker_coin_ticker",
                    "taker_coin_ticker",
                    "taker_coin_platform",
                    "taker_coin_platform",
                ]:
                    if mm2_data[i] != defi_data[i]:
                        if mm2_data[i] in ["", "None", None, -1, "unknown"]:
                            mm2_data[i] = defi_data[i]
                        elif defi_data[i] in ["", "None", None, -1, "unknown"]:
                            pass
                        elif isinstance(mm2_data[i], str):
                            if len(mm2_data[i]) == 0:
                                mm2_data[i] = defi_data[i]
                        else:
                            # This shouldnt happen
                            logger.warning(
                                "Mismatch on incoming mm2 data vs defi data:"
                            )
                            logger.warning(f"{mm2_data[i]} vs {defi_data[i]}")
                            logger.warning(
                                f"{type(mm2_data[i])} vs {type(defi_data[i])}"
                            )

                taker_gui = defi_data["taker_gui"]
                maker_gui = defi_data["maker_gui"]
                taker_version = defi_data["taker_version"]
                maker_version = defi_data["maker_version"]
                
                if "taker_gui" in mm2_data:
                    logger.info("Using mm2 data for taker gui")
                    taker_gui = mm2_data["taker_gui"]
                if "maker_gui" in mm2_data:
                    logger.info("Using mm2 data for maker gui")
                    maker_gui = mm2_data["maker_gui"]
                if "taker_version" in mm2_data:
                    logger.info("Using mm2 data for taker version")
                    taker_version = mm2_data["taker_version"]
                if "maker_version" in mm2_data:
                    logger.info("Using mm2 data for maker version")
                    maker_version = mm2_data["maker_version"]
                
                data = DefiSwap(
                    uuid=mm2_data["uuid"],
                    taker_coin=mm2_data["taker_coin"],
                    taker_pubkey=mm2_data["taker_pubkey"],
                    maker_coin=mm2_data["maker_coin"],
                    maker_pubkey=mm2_data["maker_pubkey"],
                    maker_coin_platform=mm2_data["maker_coin_platform"],
                    maker_coin_ticker=mm2_data["maker_coin_ticker"],
                    taker_coin_platform=mm2_data["taker_coin_platform"],
                    taker_coin_ticker=mm2_data["taker_coin_ticker"],
                    taker_amount=max(
                        mm2_data["taker_amount"], defi_data["taker_amount"]
                    ),
                    maker_amount=max(
                        mm2_data["maker_amount"], defi_data["maker_amount"]
                    ),
                    started_at=max(mm2_data["started_at"], defi_data["started_at"]),
                    finished_at=max(mm2_data["finished_at"], defi_data["finished_at"]),
                    is_success=max(mm2_data["is_success"], defi_data["is_success"]),
                    maker_coin_usd_price=max(0, defi_data["maker_coin_usd_price"]),
                    taker_coin_usd_price=max(0, defi_data["taker_coin_usd_price"]),
                    # Not in MM2 DB, but derived from taker/maker amounts.
                    price=max(mm2_data["price"], defi_data["price"]),
                    reverse_price=max(
                        mm2_data["reverse_price"], defi_data["reverse_price"]
                    ),                    
                    taker_gui=taker_gui,
                    maker_gui=maker_gui,
                    taker_version=taker_version,
                    maker_version=maker_version,
                    # Extra columns
                    trade_type=defi_data["trade_type"],
                    pair=defi_data["pair"],
                    pair_reverse=invert.pair(defi_data["pair"]),
                    pair_std=deplatform.pair(defi_data["pair"]),
                    pair_std_reverse=deplatform.pair(invert.pair(defi_data["pair"])),
                    last_updated=int(cron.now_utc()),
                )
            if isinstance(data.finished_at, int) and isinstance(data.started_at, int):
                data.duration = data.finished_at - data.started_at
            else:
                data.duration = -1

        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")
        msg = "mm2 to defi conversion complete"
        return default.result(msg=msg, data=data, loglevel="muted")

    @timed
    def import_swaps_for_day(self, day):
        msg = f"Importing swaps from {day.strftime('%Y-%m-%d')} {day}"
        start_ts = datetime.combine(day, dt_time()).timestamp()
        end_ts = datetime.combine(day, dt_time()).timestamp() + 86400
        SqlSource(gecko_source=self.gecko_source).populate_pgsqldb(
            start_time=start_ts, end_time=end_ts
        )
        return default.result(msg=msg, loglevel="merge", ignore_until=0)

    @timed
    def import_swaps(
        self, start_dt: date = date(2019, 1, 1), end_dt: date = datetime.today().date()
    ):
        for day in cron.daterange(start_dt, end_dt):
            self.import_swaps_for_day(day)
            time.sleep(1)

    def import_seed_stats(self, start_time: int, end_time: int):
        # Get stats from MM2.db

        # Add stats to pgsql
        return


# Subclass 'utils' under SqlQuery
@timed
def get_tablename(table):
    if isinstance(table, str):
        return table
    else:
        return table.__tablename__


@timed
def get_columns(table: object):
    return sorted(list(table.__annotations__.keys()))



def check_column_types(session, table=DefiSwap):
    print(table)
    query = text(f"SELECT column_name, data_type FROM information_schema.columns")
    result = session.connection().execute(query)
    column_types = {row['column_name']: row['data_type'] for row in result}
    for row in result:
        print(row)
    print(f"Column types:")
    for column, data_type in column_types.items():
        print(f" - {column}: {data_type}")
    
    return column_types


if __name__ == "__main__":
    pgsql = SqlUpdate("pgsql")


# pubkey swaps [maker/taker]
# version swaps [maker/taker]
# gui swaps [maker/taker]
# pubkey versions
# gui versions
# version pubkeys
# gui pubkeys

# swap durations per pair

# fails: find patterns
# - same coin? [maker/taker]
# - same pair? [maker/taker]
# - same pubkey? [maker/taker] Derive reputation score?
# - same version? [maker/taker]
# - same gui? [maker/taker]
