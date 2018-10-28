"""
Web API (wrapper around ASGI)
(from asyncio-webpy)
"""

__all__ = [
    "config",
    "header",
    "debug",
    "input",
    "query",
    "data",
    "setcookie",
    "cookies",
    "ctx",
    "HTTPError",
    # 200, 201, 202, 204
    "OK",
    "Created",
    "Accepted",
    "NoContent",
    "ok",
    "created",
    "accepted",
    "nocontent",
    # 301, 302, 303, 304, 307
    "Redirect",
    "Found",
    "SeeOther",
    "NotModified",
    "TempRedirect",
    "redirect",
    "found",
    "seeother",
    "notmodified",
    "tempredirect",
    # 400, 401, 403, 404, 405, 406, 409, 410, 412, 415, 451
    "BadRequest",
    "Unauthorized",
    "Forbidden",
    "NotFound",
    "NoMethod",
    "NotAcceptable",
    "Conflict",
    "Gone",
    "PreconditionFailed",
    "UnsupportedMediaType",
    "UnavailableForLegalReasons",
    "badrequest",
    "unauthorized",
    "forbidden",
    "notfound",
    "nomethod",
    "notacceptable",
    "conflict",
    "gone",
    "preconditionfailed",
    "unsupportedmediatype",
    "unavailableforlegalreasons",
    # 500
    "InternalError",
    "internalerror",
]

import pprint
import sys
from http.cookies import CookieError, Morsel, SimpleCookie
from urllib.parse import parse_qsl, quote, unquote

import multipart

from . import types
from .py3helpers import urljoin
from .utils import Context, dictadd, intget, safestr, storage, storify

config = storage()
config.__doc__ = """
A configuration object for various aspects of web.py.

`debug`
   : when True, enables reloading, disabled template caching and sets internalerror to debugerror.
"""


class HTTPError(Exception):
    def __init__(self, status, headers={}, data=""):
        ctx.status = status
        for k, v in headers.items():
            header(k, v)
        self.data = data
        super().__init__(status)


def _status_code(status, data=None, classname=None, docstring=None):
    if data is None:
        data = status.split(" ", 1)[1]
    classname = status.split(" ", 1)[1].replace(" ", "")  # 304 Not Modified -> NotModified
    docstring = docstring or "`%s` status" % status

    def __init__(self, data=data, headers={}):
        super().__init__(status, headers, data)

    # trick to create class dynamically with dynamic docstring.
    return type(classname, (HTTPError, object), {"__doc__": docstring, "__init__": __init__})


ok = OK = _status_code("200 OK", data="")
created = Created = _status_code("201 Created")
accepted = Accepted = _status_code("202 Accepted")
nocontent = NoContent = _status_code("204 No Content")


class Redirect(HTTPError):
    """A `301 Moved Permanently` redirect."""

    def __init__(self, url, status="301 Moved Permanently", absolute=False):
        """
        Returns a `status` redirect to the new URL.
        `url` is joined with the base URL so that things like
        `redirect("about") will work properly.
        """
        newloc = urljoin(ctx.path, url)

        if newloc.startswith("/"):
            if absolute:
                home = ctx.realhome
            else:
                home = ctx.home
            newloc = home + newloc

        headers = {"Content-Type": "text/html", "Location": newloc}
        super().__init__(status, headers, "")


redirect = Redirect


class Found(Redirect):
    """A `302 Found` redirect."""

    def __init__(self, url, absolute=False):
        super().__init__(url, "302 Found", absolute=absolute)


found = Found


class SeeOther(Redirect):
    """A `303 See Other` redirect."""

    def __init__(self, url, absolute=False):
        super().__init__(url, "303 See Other", absolute=absolute)


seeother = SeeOther


class NotModified(HTTPError):
    """A `304 Not Modified` status."""

    def __init__(self):
        super().__init__("304 Not Modified")


notmodified = NotModified


class TempRedirect(Redirect):
    """A `307 Temporary Redirect` redirect."""

    def __init__(self, url, absolute=False):
        super().__init__(url, "307 Temporary Redirect", absolute=absolute)


tempredirect = TempRedirect


class BadRequest(HTTPError):
    """`400 Bad Request` error."""

    message = "bad request"

    def __init__(self, message=None):
        status = "400 Bad Request"
        headers = {"Content-Type": "text/html"}
        super().__init__(status, headers, message or self.message)


badrequest = BadRequest


class Unauthorized(HTTPError):
    """`401 Unauthorized` error."""

    message = "unauthorized"

    def __init__(self, message=None):
        status = "401 Unauthorized"
        headers = {"Content-Type": "text/html"}
        super().__init__(status, headers, message or self.message)


unauthorized = Unauthorized


class Forbidden(HTTPError):
    """`403 Forbidden` error."""

    message = "forbidden"

    def __init__(self, message=None):
        status = "403 Forbidden"
        headers = {"Content-Type": "text/html"}
        super().__init__(status, headers, message or self.message)


forbidden = Forbidden


class _NotFound(HTTPError):
    """`404 Not Found` error."""

    message = "not found"

    def __init__(self, message=None):
        status = "404 Not Found"
        headers = {"Content-Type": "text/html"}
        super().__init__(status, headers, message or self.message)


def NotFound(message=None):
    """Returns HTTPError with '404 Not Found' error from the active application.
    """
    if message:
        return _NotFound(message)
    elif ctx.get("app_stack"):
        return ctx.app_stack[-1].notfound()
    else:
        return _NotFound()


notfound = NotFound


class NoMethod(HTTPError):
    """A `405 Method Not Allowed` error."""

    def __init__(self, cls=None):
        data = status = "405 Method Not Allowed"
        headers = {}
        headers["Content-Type"] = "text/html"

        methods = ["GET", "HEAD", "POST", "PUT", "DELETE"]
        if cls:
            methods = [method for method in methods if hasattr(cls, method)]

        headers["Allow"] = ", ".join(methods)
        super().__init__(status, headers, data)


nomethod = NoMethod


class NotAcceptable(HTTPError):
    """`406 Not Acceptable` error."""

    message = "not acceptable"

    def __init__(self, message=None):
        status = "406 Not Acceptable"
        headers = {"Content-Type": "text/html"}
        super().__init__(status, headers, message or self.message)


notacceptable = NotAcceptable


class Conflict(HTTPError):
    """`409 Conflict` error."""

    message = "conflict"

    def __init__(self, message=None):
        status = "409 Conflict"
        headers = {"Content-Type": "text/html"}
        super().__init__(status, headers, message or self.message)


conflict = Conflict


class Gone(HTTPError):
    """`410 Gone` error."""

    message = "gone"

    def __init__(self, message=None):
        status = "410 Gone"
        headers = {"Content-Type": "text/html"}
        super().__init__(status, headers, message or self.message)


gone = Gone


class PreconditionFailed(HTTPError):
    """`412 Precondition Failed` error."""

    message = "precondition failed"

    def __init__(self, message=None):
        status = "412 Precondition Failed"
        headers = {"Content-Type": "text/html"}
        super().__init__(status, headers, message or self.message)


preconditionfailed = PreconditionFailed


class UnsupportedMediaType(HTTPError):
    """`415 Unsupported Media Type` error."""

    message = "unsupported media type"

    def __init__(self, message=None):
        status = "415 Unsupported Media Type"
        headers = {"Content-Type": "text/html"}
        super().__init__(status, headers, message or self.message)


unsupportedmediatype = UnsupportedMediaType


class _UnavailableForLegalReasons(HTTPError):
    """`451 Unavailable For Legal Reasons` error."""

    message = "unavailable for legal reasons"

    def __init__(self, message=None):
        status = "451 Unavailable For Legal Reasons"
        headers = {"Content-Type": "text/html"}
        super().__init__(status, headers, message or self.message)


def UnavailableForLegalReasons(message=None):
    """Returns HTTPError with '415 Unavailable For Legal Reasons' error from the active application.
    """
    if message:
        return _UnavailableForLegalReasons(message)
    elif ctx.get("app_stack"):
        return ctx.app_stack[-1].unavailableforlegalreasons()
    else:
        return _UnavailableForLegalReasons()


unavailableforlegalreasons = UnavailableForLegalReasons


class _InternalError(HTTPError):
    """500 Internal Server Error`."""

    message = "internal server error"

    def __init__(self, message=None):
        status = "500 Internal Server Error"
        headers = {"Content-Type": "text/html"}
        super().__init__(status, headers, message or self.message)


def InternalError(message=None):
    """Returns HTTPError with '500 internal error' error from the active application.
    """
    if message:
        return _InternalError(message)
    elif ctx.get("app_stack"):
        return ctx.app_stack[-1].internalerror()
    else:
        return _InternalError()


internalerror = InternalError


def header(hdr, value, unique=False):
    """
    Adds the header `hdr: value` with the response.

    If `unique` is True and a header with that name already exists,
    it doesn't add a new one.
    """
    hdr, value = safestr(hdr), safestr(value)
    # protection against HTTP response splitting attack
    if "\n" in hdr or "\r" in hdr or "\n" in value or "\r" in value:
        raise ValueError("invalid characters in header")
    if unique is True and hdr in ctx.headers:
        return

    ctx.headers[hdr] = value


def rawinput(method=None):
    """Returns storage object with GET or POST arguments.
    """
    method = method or "both"

    e = ctx.scope.copy()
    a = b = {}

    if method.lower() in ["both", "post", "put"]:
        if e["method"] in ["POST", "PUT"]:
            a = form()

    if method.lower() in ["both", "get"]:
        e["method"] = "GET"
        b = query()

    return storage([(k, v) for k, v in dictadd(a, b).items()])


def input(*requireds, **defaults):
    """
    Returns a `storage` object with the GET and POST arguments.
    See `storify` for how `requireds` and `defaults` work.
    """
    _method = defaults.pop("_method", "both")
    out = rawinput(_method)
    try:
        defaults.setdefault("_bytes", False)
        return storify(out, *requireds, **defaults)
    except KeyError:
        raise badrequest()


def query(**default_kwargs) -> types.QueryParams:
    """Returns the query params sent with the request."""
    params: types.QueryParams = types.ImmutableDict(parse_qsl(ctx.query.strip("?")))
    for key, value in default_kwargs.items():
        if key not in params:
            params[key] = value
    return params


def data():
    """Returns the data sent with the request."""
    if "data" not in ctx:
        cl = intget(ctx.scope["headers"].get("content_length"), 0)
        ctx.scope["input"].seek(0)
        ctx.data = ctx.scope["input"].read(cl)
    return ctx.data


def form() -> types.Form:
    """Returns the form data sent with the request."""

    formdata: types.Form = types.MutableDict()

    def on_field(field):
        formdata[field.field_name] = field.value

    def on_file(file):
        files = formdata.setdefault("file", {})
        files[safestr(file.file_name)] = file.file_object

    if ctx.scope["headers"].get("content_type", "").startswith("multipart/"):
        ctx.scope["input"].seek(0)
        multipart.parse_form(ctx.scope["headers"], ctx.scope["input"], on_field, on_file)
    elif ctx.scope["headers"].get("content_type", "") == "application/x-www-form-urlencoded":
        formdata.update(parse_qsl(data()))

    return types.ImmutableDict(formdata)


def setcookie(name, value, expires="", domain=None, secure=False, httponly=False, path=None):
    """Sets a cookie."""
    morsel = Morsel()
    name, value = safestr(name), safestr(value)
    morsel.set(name, value, quote(value))
    if isinstance(expires, int) and expires < 0:
        expires = -1_000_000_000
    morsel["expires"] = expires
    morsel["path"] = path or ctx.homepath + "/"
    if domain:
        morsel["domain"] = domain
    if secure:
        morsel["secure"] = secure
    value = morsel.OutputString()
    if httponly:
        value += "; httponly"
    header("Set-Cookie", value)


def decode_cookie(value):
    r"""Safely decodes a cookie value to unicode.

    Tries us-ascii, utf-8 and io8859 encodings, in that order.

    >>> decode_cookie('')
    u''
    >>> decode_cookie('asdf')
    u'asdf'
    >>> decode_cookie('foo \xC3\xA9 bar')
    u'foo \xe9 bar'
    >>> decode_cookie('foo \xE9 bar')
    u'foo \xe9 bar'
    """
    try:
        # First try plain ASCII encoding
        return str(value, "us-ascii")
    except UnicodeError:
        # Then try UTF-8, and if that fails, ISO8859
        try:
            return str(value, "utf-8")
        except UnicodeError:
            return str(value, "iso8859", "ignore")


def parse_cookies(http_cookie):
    r"""Parse a HTTP_COOKIE header and return dict of cookie names and decoded values.

    >>> sorted(parse_cookies('').items())
    []
    >>> sorted(parse_cookies('a=1').items())
    [('a', '1')]
    >>> sorted(parse_cookies('a=1%202').items())
    [('a', '1 2')]
    >>> sorted(parse_cookies('a=Z%C3%A9Z').items())
    [('a', 'Z\xc3\xa9Z')]
    >>> sorted(parse_cookies('a=1; b=2; c=3').items())
    [('a', '1'), ('b', '2'), ('c', '3')]
    >>> sorted(parse_cookies('a=1; b=w("x")|y=z; c=3').items())
    [('a', '1'), ('b', 'w('), ('c', '3')]
    >>> sorted(parse_cookies('a=1; b=w(%22x%22)|y=z; c=3').items())
    [('a', '1'), ('b', 'w("x")|y=z'), ('c', '3')]

    >>> sorted(parse_cookies('keebler=E=mc2').items())
    [('keebler', 'E=mc2')]
    >>> sorted(parse_cookies(r'keebler="E=mc2; L=\"Loves\"; fudge=\012;"').items())
    [('keebler', 'E=mc2; L="Loves"; fudge=\n;')]
    """
    # print "parse_cookies"
    if '"' in http_cookie:
        # HTTP_COOKIE has quotes in it, use slow but correct cookie parsing
        cookie = SimpleCookie()
        try:
            cookie.load(http_cookie)
        except CookieError:
            # If HTTP_COOKIE header is malformed, try at least to load the cookies we can by
            # first splitting on ';' and loading each attr=value pair separately
            cookie = SimpleCookie()
            for attr_value in http_cookie.split(";"):
                try:
                    cookie.load(attr_value)
                except CookieError:
                    pass
        cookies = dict([(k, unquote(v.value)) for k, v in cookie.iteritems()])
    else:
        # HTTP_COOKIE doesn't have quotes, use fast cookie parsing
        cookies = {}
        for key_value in http_cookie.split(";"):
            key_value = key_value.split("=", 1)
            if len(key_value) == 2:
                key, value = key_value
                cookies[key.strip()] = unquote(value.strip())
    return cookies


def cookies(*requireds, **defaults):
    r"""Returns a `storage` object with all the request cookies in it.

    See `storify` for how `requireds` and `defaults` work.

    This is forgiving on bad HTTP_COOKIE input, it tries to parse at least
    the cookies it can.

    The values are converted to unicode if _unicode=True is passed.
    """
    # If _unicode=True is specified, use decode_cookie to convert cookie value to unicode
    if defaults.get("_unicode") is True:
        defaults["_unicode"] = decode_cookie

    # parse cookie string and cache the result for next time.
    if "_parsed_cookies" not in ctx:
        http_cookie = ctx.scope.get("http_cookie", "")
        ctx._parsed_cookies = parse_cookies(http_cookie)

    try:
        return storify(ctx._parsed_cookies, *requireds, **defaults)
    except KeyError:
        badrequest()
        raise StopIteration()


def debug(*args):
    """
    Prints a prettyprinted version of `args` to stderr.
    """
    try:
        out = ctx.environ["wsgi.errors"]
    except KeyError:
        out = sys.stderr
    for arg in args:
        print(pprint.pformat(arg), file=out)
    return ""


def _debugwrite(x):
    try:
        out = ctx.environ["wsgi.errors"]
    except Exception:
        out = sys.stderr
    out.write(x)


debug.write = _debugwrite


ctx = context = Context()

if __name__ == "__main__":
    import doctest

    doctest.testmod()
