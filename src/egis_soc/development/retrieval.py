"""Package import for the hash-pinned W3 retrieval implementation."""

from importlib import import_module as _import_module
import sys as _sys

_sys.modules[__name__] = _import_module("egis_soc.development_retrieval")
