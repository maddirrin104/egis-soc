"""Compatibility import for :mod:`egis_soc.pds01.pds01_owner_review`."""

from importlib import import_module as _import_module
import sys as _sys

_sys.modules[__name__] = _import_module("egis_soc.pds01.pds01_owner_review")
