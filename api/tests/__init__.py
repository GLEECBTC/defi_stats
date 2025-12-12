import os
import sys

API_ROOT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(API_ROOT_PATH)

from lib.coins import Coins
from lib.cache import reset_cache_files
import util.memcache as memcache

try:  # pragma: no cover - compatibility shim
    import importlib_metadata
except ImportError:  # pragma: no cover
    import importlib.metadata as importlib_metadata


def _ensure_entrypoints_get():
    entry_points_cls = getattr(importlib_metadata, "EntryPoints", None)
    if entry_points_cls is not None and not hasattr(entry_points_cls, "get"):
        def _get(self, group, default=None):
            try:
                return self.select(group=group)
            except AttributeError:
                return default if default is not None else ()

        setattr(entry_points_cls, "get", _get)


_ensure_entrypoints_get()

os.environ["IS_TESTING"] = "True"
reset_cache_files()
