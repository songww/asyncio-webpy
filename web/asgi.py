"""
ASGI Utilities
(from asyncio-webpy)
"""

import os, sys

from . import http
from . import webapi as web
from .utils import listget, intget
from .net import validaddr, validip
from . import httpserver


def runasgi(func):
    """
    Runs a WSGI-compatible `func` using FCGI, SCGI, or a simple web server,
    as appropriate based on context and `sys.argv`.
    """

    server_addr = validip(listget(sys.argv, 1, ""))
    if "PORT" in os.environ:  # e.g. Heroku
        server_addr = ("0.0.0.0", intget(os.environ["PORT"]))

    return httpserver.runsimple(func, server_addr)


def _is_dev_mode():
    # Some embedded python interpreters won't have sys.arv
    # For details, see https://github.com/webpy/webpy/issues/87
    argv = getattr(sys, "argv", [])

    # quick hack to check if the program is running in dev mode.
    if (
        "SERVER_SOFTWARE" in os.environ
        or "PHP_FCGI_CHILDREN" in os.environ
        or "fcgi" in argv
        or "fastcgi" in argv
        or "mod_wsgi" in argv
    ):
        return False
    return True


# When running the builtin-server, enable debug mode if not already set.
web.config.setdefault("debug", _is_dev_mode())
