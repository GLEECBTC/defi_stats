#!/usr/bin/env python3
from const import MM2_RPC_PORTS, MM2_NETID
from util.logger import timed
import util.defaults as default
from util.transform import template


@timed
def get_mm2_rpc_port(netid=MM2_NETID):
    try:
        return MM2_RPC_PORTS[str(netid)]
    except Exception as e:  # pragma: no cover
        return default.result(msg=e, loglevel="warning")


def get_netid(filename):
    if "7777" in filename:
        return "7777"
    if "6133" in filename:
        return "6133"
    if filename.startswith("seed"):
        return "7777"
    else:
        return "8762"


@timed
def get_netid_filename(filename, netid):
    try:
        parts = filename.split(".")
        return f"{'.'.join(parts[:-1])}_{netid}.{parts[-1]}"
    except Exception as e:  # pragma: no cover
        return default.result(msg=e, loglevel="warning")


@timed
def get_chunks(data, chunk_length):
    try:
        for i in range(0, len(data), chunk_length):
            yield data[i: i + chunk_length]
    except Exception as e:  # pragma: no cover
        return default.result(msg=e, loglevel="warning")


@timed
def get_pairs_info(pair_list: str, priced: bool = False) -> list:
    try:
        return [template.pair_info(i, priced) for i in pair_list]
    except Exception as e:  # pragma: no cover
        return default.result(msg=e, loglevel="warning")


@timed
def get_pair_info_sorted(pair_list: str, priced: bool = False) -> dict:
    try:
        return sorted(
            get_pairs_info(pair_list, priced),
            key=lambda d: d["ticker_id"],
        )
    except Exception as e:  # pragma: no cover
        return default.result(msg=e, loglevel="warning")
