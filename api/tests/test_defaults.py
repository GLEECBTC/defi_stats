#!/usr/bin/env python3
from util.cron import cron
import util.defaults as default
from const import DEXAPI_8762_HOST, DEXAPI_6133_HOST


def test_arg_defaults():
    class Test:
        def __init__(self, **kwargs) -> None:
            self.options = []
            for i in default.arg_defaults().values():
                self.options += i
            default.params(self, kwargs, self.options)

    test = Test(order_by_mcap=False, source_url="https://dex.gleec.com/")
    assert not test.reverse
    assert test.wal
    assert not test.order_by_mcap
    assert test.db_path is None
    assert test.source_url == "https://dex.gleec.com/"
    assert test.end > int(cron.now_utc()) - 10
    assert test.mm2_host == DEXAPI_6133_HOST
    assert test.trigger == 0
    assert test.coin == "KMD"
    assert test.loglevel == "debug"
