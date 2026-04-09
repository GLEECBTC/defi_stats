#!/usr/bin/env python3
import os
from decimal import Decimal

import sqlite3
from typing import List
from const import (
    LOCAL_MM2_DB_PATH_7777,
    LOCAL_MM2_DB_PATH_8762,
    LOCAL_MM2_DB_PATH_6133,
    LOCAL_MM2_DB_BACKUP_7777,
    LOCAL_MM2_DB_BACKUP_8762,
    LOCAL_MM2_DB_BACKUP_6133,
    MM2_DB_PATHS,
    DB_SOURCE_PATH,
    DB_CLEAN_PATH,
    DB_MASTER_PATH,
    compare_fields,
)
from db.sqlitedb import (
    get_sqlite_db,
    SqliteDB,
)
from util.cron import cron
from util.enums import NetId
from util.logger import logger, timed
import util.defaults as default
import util.helper as helper
import util.validate as validate


class SqliteMerge:
    def __init__(self):
        self.init_dbs()

    @timed
    def import_source_databases(self):  # pragma: no cover
        self.backup_local_dbs()
        self.clean_source_dbs()
        self.compare_dbs()
        self.update_temp_dbs()
        self.get_db_row_counts(temp=True)
        self.update_master_dbs()
        self.get_db_row_counts()
        msg = "Souce database import completed!"
        return default.result(msg=msg, loglevel="merge", ignore_until=10)

    def clean_source_dbs(self):  # pragma: no cover
        # Denullify source databases, move to 'clean' folder
        try:
            source_dbs = list_sqlite_dbs(DB_SOURCE_PATH)
            for fn in source_dbs:
                if validate.is_source_db(fn):
                    src_db_path = f"{DB_SOURCE_PATH}/{fn}"
                    src_db = get_sqlite_db(db_path=src_db_path)
                    src_db.update.denullify_stats_swaps()

                    dest_db_path = f"{DB_CLEAN_PATH}/{fn}"
                    dest_db = get_sqlite_db(db_path=dest_db_path)
                    dest_db.update.create_swap_stats_table()
                    self.merge_db_tables(
                        src_db=src_db,
                        dest_db=dest_db,
                        table="stats_swaps",
                        column="uuid",
                        since=0,
                    )

                    for i in [src_db, dest_db]:
                        i.close()
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")
        msg = f"{len(source_dbs)} source databases cleaned."
        return default.result(msg=msg, loglevel="merge")

    @timed
    def get_db_row_counts(self, temp=False):  # pragma: no cover
        path = MM2_DB_PATHS["temp_7777"] if temp else MM2_DB_PATHS["7777"]
        db_7777 = get_sqlite_db(db_path=path)
        path = MM2_DB_PATHS["temp_8762"] if temp else MM2_DB_PATHS["8762"]
        db_8762 = get_sqlite_db(db_path=path)
        path = MM2_DB_PATHS["temp_6133"] if temp else MM2_DB_PATHS["6133"]
        db_6133 = get_sqlite_db(db_path=path)
        path = MM2_DB_PATHS["temp_ALL"] if temp else MM2_DB_PATHS["ALL"]
        db_all = get_sqlite_db(db_path=path)

        db_8762.update.remove_overlaps(db_7777)
        rows = db_7777.query.get_row_count("stats_swaps")
        msg_7777 = f"7777: {rows}"
        rows = db_8762.query.get_row_count("stats_swaps")
        msg_8762 = f"8762: {rows}"
        rows = db_6133.query.get_row_count("stats_swaps")
        msg_6133 = f"6133: {rows}"
        rows = db_all.query.get_row_count("stats_swaps")
        msg_ALL = f"ALL: {rows}"
        msg = f"Master DB rows: [{msg_7777}] [{msg_8762}] [{msg_6133}] [{msg_ALL}]"

        for i in [db_all, db_6133, db_8762, db_7777]:
            i.close()
        if temp:
            msg = f"Temp DB rows: [{msg_7777}] [{msg_8762}] [{msg_6133}] [{msg_ALL}]"
        return default.result(msg=msg, loglevel="merge")

    @timed
    def update_master_dbs(self):  # pragma: no cover
        # Merge temp databases into master
        try:
            for i in NetId:
                i = i.value
                src_db = get_sqlite_db(db_path=MM2_DB_PATHS[f"temp_{i}"])
                dest_db = get_sqlite_db(db_path=MM2_DB_PATHS[f"{i}"])
                self.merge_db_tables(
                    src_db=src_db,
                    dest_db=dest_db,
                    table="stats_swaps",
                    column="uuid",
                    since=0,
                )
                for i in [src_db, dest_db]:
                    i.close()
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")
        msg = "Merge of source data into master databases complete!"
        return default.result(msg=msg, loglevel="merge")

    @timed
    def update_temp_dbs(self):  # pragma: no cover
        # Merge clean source databases into temp
        try:
            source_dbs = list_sqlite_dbs(DB_CLEAN_PATH)
            for fn in source_dbs:
                if not fn.startswith("temp"):
                    if validate.is_source_db(fn):
                        src_db_path = f"{DB_CLEAN_PATH}/{fn}"
                        src_db = get_sqlite_db(db_path=src_db_path)
                        netid = helper.get_netid(fn)
                        dest_db_path = f"{DB_CLEAN_PATH}/temp_MM2_{netid}.db"
                        dest_db = get_sqlite_db(db_path=dest_db_path)
                        self.merge_db_tables(
                            src_db=src_db,
                            dest_db=dest_db,
                            table="stats_swaps",
                            column="uuid",
                            since=0,
                        )
                        for i in [src_db, dest_db]:
                            i.close()

            # Merge both netids into 'ALL'

            for i in NetId:
                i = i.value
                if i != "ALL":
                    dest_db = get_sqlite_db(db_path=f"{DB_CLEAN_PATH}/temp_MM2_ALL.db")
                    src_db = get_sqlite_db(db_path=f"{DB_CLEAN_PATH}/temp_MM2_{i}.db")
                    self.merge_db_tables(
                        src_db=src_db,
                        dest_db=dest_db,
                        table="stats_swaps",
                        column="uuid",
                        since=0,
                    )
                    src_db.close()
                    dest_db.close()
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")
        msg = "Merge of source data into temp master databases complete!"
        return default.result(msg=msg, loglevel="merge")

    @timed
    def merge_db_tables(
        self, src_db, dest_db, table, column, since=None
    ):  # pragma: no cover
        if since is None:
            since = int(cron.now_utc()) - 86400 * 7
        sql = ""
        try:
            src_columns = src_db.query.get_table_columns(table)
            src_columns.pop(src_columns.index("id"))
            sql = f"ATTACH DATABASE '{src_db.db_path}' AS src_db;"
            sql += f" INSERT INTO {table} ({','.join(src_columns)})"
            sql += f" SELECT {','.join(src_columns)}"
            sql += f" FROM src_db.{table}"
            sql += " WHERE NOT EXISTS ("
            sql += f"SELECT * FROM {table}"
            sql += f" WHERE {table}.{column} = src_db.{table}.{column})"
            sql += f" AND src_db.{table}.finished_at > {since};"
            sql += " DETACH DATABASE 'src_db';"
            dest_db.sql_cursor.executescript(sql)
        except sqlite3.OperationalError as e:
            msg = f"OpErr {src_db.db_path} ==> {dest_db.db_path}"
            return default.error(e, msg=msg)
        except Exception as e:  # pragma: no cover
            msg = f"{type(e)} {src_db.db_path} ==> {dest_db.db_path} {e}"
            return default.error(e, msg=msg)
        msg = f"Importing {src_db.db_path} ==> {dest_db.db_path} complete"
        return default.result(msg=msg, loglevel="updated", ignore_until=10)

    @timed
    def compare_dbs(self):  # pragma: no cover
        # Compare clean DBs to repair mismatches
        try:
            comparisons = 0
            clean_dbs = list_sqlite_dbs(DB_CLEAN_PATH)
            for fna in clean_dbs:
                for fnb in clean_dbs:
                    if fna != fnb:
                        db1 = get_sqlite_db(db_path=f"{DB_CLEAN_PATH}/{fna}")
                        db2 = get_sqlite_db(db_path=f"{DB_CLEAN_PATH}/{fnb}")
                        uuids = self.get_mismatched_uuids(db1, db2)
                        self.repair_swaps(uuids, db1, db2)
                        comparisons += 1
                        db1.close()
                        db2.close()
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")
        msg = f"Comparison of {len(clean_dbs)} databases in {comparisons} combinations complete!"
        return default.result(msg=msg, loglevel="merge", ignore_until=10)

    @timed
    def backup_local_dbs(self):  # pragma: no cover
        # Backup the local active mm2 instance DBs
        try:
            self.backup_db(
                src_db_path=LOCAL_MM2_DB_PATH_7777,
                dest_db_path=LOCAL_MM2_DB_BACKUP_7777,
            )
            self.backup_db(
                src_db_path=LOCAL_MM2_DB_PATH_8762,
                dest_db_path=LOCAL_MM2_DB_BACKUP_8762,
            )
            self.backup_db(
                src_db_path=LOCAL_MM2_DB_PATH_6133,
                dest_db_path=LOCAL_MM2_DB_BACKUP_6133,
            )
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")
        msg = "Merge of local source data into backup databases complete!"
        return default.result(msg=msg, loglevel="merge")

    # @timed
    def get_mismatched_uuids(self, db1: SqliteDB, db2: SqliteDB):  # pragma: no cover
        try:
            uuids_a = db1.query.get_uuids(success_only=True)
            uuids_b = db2.query.get_uuids(fail_only=True)
            mismatch_uuids = list(set(uuids_a).intersection(set(uuids_b)))
            return list(set(mismatch_uuids))
        except sqlite3.OperationalError as e:
            logger.error(e)
        except Exception as e:  # pragma: no cover
            logger.error(e)

    @timed
    def repair_swaps(
        self, uuids: List, db1: SqliteDB, db2: SqliteDB
    ) -> None:  # pragma: no cover
        try:
            db_list = [db1, db2]
            loglevel = "merged"
            if len(uuids) == 0:
                msg = "UUID list is empty, no swaps to repair!"
                loglevel = "muted"
            else:
                uuids.sort()
                for uuid in list(uuids):
                    swaps = []
                    for db in db_list:
                        swap_info = db.query.get_swap(uuid)
                        if "error" in swap_info:
                            continue
                        swaps.append(swap_info)
                    for swap1 in swaps:
                        for swap2 in swaps:
                            fixed = compare_uuid_fields(swap1, swap2)
                            if (
                                len(set(compare_fields).intersection(set(fixed.keys())))
                                > 0
                            ):
                                db1.update.update_stats_swap_row(uuid, fixed)
                                db2.update.update_stats_swap_row(uuid, fixed)
                                logger.updated(f"{uuid} repaired")
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")
        msg = f"{len(uuids)} repaired in {db1.db_file},  {db2.db_file}"
        return default.result(msg=msg, loglevel=loglevel)

    @timed
    def init_dbs(self):  # pragma: no cover
        try:
            for i in MM2_DB_PATHS:
                db = get_sqlite_db(db_path=MM2_DB_PATHS[i])
                self.init_stats_swaps_db(db)
                db.close()
            for i in [
                LOCAL_MM2_DB_BACKUP_7777,
                LOCAL_MM2_DB_PATH_7777,
                LOCAL_MM2_DB_BACKUP_8762,
                LOCAL_MM2_DB_PATH_8762,
                LOCAL_MM2_DB_BACKUP_6133,
                LOCAL_MM2_DB_PATH_6133,
            ]:
                db = get_sqlite_db(db_path=i)
                self.init_stats_swaps_db(db)
        except sqlite3.OperationalError as e:
            return default.result(msg=e, loglevel="warning")
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")
        return default.result(
            msg="Database Initialisation complete!", loglevel="merge", ignore_until=10
        )

    @timed
    def setup_temp_dbs(self):  # pragma: no cover
        try:
            for netid in NetId:
                db_path = MM2_DB_PATHS[f"temp_{netid.value}"]
                db = get_sqlite_db(db_path=db_path)
                db.update.create_swap_stats_table()
                db.update.clear("stats_swaps")
                db.close()
        except sqlite3.OperationalError as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")
        msg = "Temp DBs setup complete..."
        return default.result(msg=msg, loglevel="info")

    @timed
    def backup_db(
        self, src_db_path: str, dest_db_path: str
    ) -> None:  # pragma: no cover
        try:
            src = get_sqlite_db(db_path=src_db_path)
            dest = get_sqlite_db(db_path=dest_db_path)
            src.conn.backup(dest.conn, pages=1, progress=self.progress)
            src.close()
            dest.close()
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")
        msg = f"Backup of {src.db_path} complete..."
        return default.result(msg=msg, loglevel="muted")

    def progress(status, remaining, total, show=False):  # pragma: no cover
        if show:
            logger.muted(f"Copied {total-remaining} of {total} pages...")

    @timed
    def init_stats_swaps_db(self, db):  # pragma: no cover
        try:
            db.update.create_swap_stats_table()
        except sqlite3.OperationalError as e:
            return default.result(msg=e, loglevel="warning")
        except Exception as e:  # pragma: no cover
            return default.result(msg=e, loglevel="warning")
        msg = f"Table 'stats_swaps' init for {db.db_file} complete..."
        return default.result(msg=msg, loglevel="merge", ignore_until=10)

    @timed
    def truncate_wal(self):
        source_dbs = list_sqlite_dbs(DB_SOURCE_PATH)
        for fn in source_dbs:
            src_db_path = f"{DB_SOURCE_PATH}/{fn}"
            src_db = get_sqlite_db(db_path=src_db_path)
            src_db.truncate_wal()

        master_dbs = list_sqlite_dbs(DB_MASTER_PATH)
        for fn in master_dbs:
            master_db_path = f"{DB_MASTER_PATH}/{fn}"
            master_db = get_sqlite_db(db_path=master_db_path)
            master_db.truncate_wal()
        msg = "Database wal truncation complete..."
        return default.result(msg=msg, loglevel="merge", ignore_until=10)


def compare_uuid_fields(swap1, swap2):
    uuid = swap1["uuid"]
    # logger.muted(f"Repairing swap {uuid}")
    try:
        fixed = {}
        for k, v in swap1.items():
            if k in compare_fields:
                if v != swap2[k]:
                    # use higher value for below fields
                    try:
                        if k in [
                            "maker_coin_usd_price",
                            "taker_coin_usd_price",
                        ]:
                            if Decimal(v) == Decimal(0):
                                fixed.update({k: swap2[k]})
                            else:
                                fixed.update({k: v})
                        else:
                            fixed.update({k: str(max([Decimal(v), Decimal(swap2[k])]))})
                    except sqlite3.OperationalError as e:  # pragma: no cover
                        msg = f"{uuid} | {v} vs {swap2[k]} | {type(v)} vs {type(swap2[k])}"
                        return default.error(e, msg)
                else:
                    fixed.update({k: v})
        return fixed
    except Exception as e:  # pragma: no cover
        return default.result(msg=e, loglevel="warning")


def list_sqlite_dbs(folder):
    db_list = [i for i in os.listdir(folder) if i.endswith(".db")]
    db_list.sort()
    return db_list


if __name__ == "__main__":  # pragma: no cover
    merge = SqliteMerge()
    merge.init_dbs()
    merge.import_source_databases()
