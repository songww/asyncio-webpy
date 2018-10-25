"""
Web application
(from web.py)
"""
from __future__ import print_function

import logging
import os
import sys
import traceback
from importlib import reload
from inspect import isawaitable, isclass, iscoroutine, iscoroutinefunction
from urllib.parse import splitquery, unquote, urlencode

from . import browser, httpserver, utils
from . import webapi as web
from . import wsgi
from .debugerror import debugerror
from .py3helpers import is_iter, string_types
from .utils import safebytes

__all__ = [
    "application",
    "auto_application",
    "subdir_application",
    "subdomain_application",
    "loadhook",
    "unloadhook",
    "autodelegate",
]

logger = logging.getLogger("web")


class application:
    """
    Application to delegate requests based on path.

        >>> urls = ("/hello", "hello")
        >>> app = application(urls, globals())
        >>> class hello:
        ...     def GET(self): return "hello"
        >>>
        >>> app.request("/hello").data
        b'hello'
    """

    def __init__(self, mapping=(), fvars={}, autoreload=None):
        if autoreload is None:
            autoreload = web.config.get("debug", False)
        self.init_mapping(mapping)
        self.fvars = fvars
        self.processors = []

        self.add_processor(loadhook(self._load))
        self.add_processor(unloadhook(self._unload))

        if autoreload:

            def main_module_name():
                mod = sys.modules["__main__"]
                file = getattr(mod, "__file__", None)  # make sure this works even from python interpreter
                return file and os.path.splitext(os.path.basename(file))[0]

            def modname(fvars):
                """find name of the module name from fvars."""
                file, name = fvars.get("__file__"), fvars.get("__name__")
                if file is None or name is None:
                    return None

                if name == "__main__":
                    # Since the __main__ module can't be reloaded, the module has
                    # to be imported using its file name.
                    name = main_module_name()
                return name

            mapping_name = utils.dictfind(fvars, mapping)
            module_name = modname(fvars)

            def reload_mapping():
                """loadhook to reload mapping and fvars."""
                mod = __import__(module_name, None, None, [""])
                mapping = getattr(mod, mapping_name, None)
                if mapping:
                    self.fvars = mod.__dict__
                    self.init_mapping(mapping)

            self.add_processor(loadhook(Reloader()))
            if mapping_name and module_name:
                self.add_processor(loadhook(reload_mapping))

            # load __main__ module usings its filename, so that it can be reloaded.
            if main_module_name() and "__main__" in sys.argv:
                try:
                    __import__(main_module_name())
                except ImportError:
                    pass

    def _load(self):
        web.ctx.app_stack.append(self)

    def _unload(self):
        web.ctx.app_stack = web.ctx.app_stack[:-1]

        if web.ctx.app_stack:
            # this is a sub-application, revert ctx to earlier state.
            oldctx = web.ctx.get("_oldctx")
            if oldctx:
                web.ctx.home = oldctx.home
                web.ctx.homepath = oldctx.homepath
                web.ctx.path = oldctx.path
                web.ctx.fullpath = oldctx.fullpath

    def _cleanup(self):
        # Threads can be recycled by WSGI servers.
        # Clearing up all thread-local state to avoid interefereing with subsequent requests.
        utils.Context.clear_all()

    def init_mapping(self, mapping):
        self.mapping = list(utils.group(mapping, 2))

    def add_mapping(self, pattern, classname):
        self.mapping.append((pattern, classname))

    def add_processor(self, processor):
        """
        Adds a processor to the application.

            >>> urls = ("/(.*)", "echo")
            >>> app = application(urls, globals())
            >>> class echo:
            ...     def GET(self, name): return name
            ...
            >>>
            >>> def hello(handler): return "hello, " +  handler()
            ...
            >>> app.add_processor(hello)
            >>> app.request("/web.py").data
            b'hello, web.py'
        """
        self.processors.append(processor)

    async def request(
        self, localpart="/", method="GET", data=None, host="0.0.0.0:8080", headers=None, https=False, **kw
    ):
        """Makes request to this application for the specified path and method.
        Response will be a storage object with data, status and headers.

            >>> urls = ("/hello", "hello")
            >>> app = application(urls, globals())
            >>> class hello:
            ...     def GET(self):
            ...         web.header('Content-Type', 'text/plain')
            ...         return "hello"
            ...
            >>> response = await app.request("/hello")
            >>> response.data
            b'hello'
            >>> response.status
            '200 OK'
            >>> response.headers['Content-Type']
            'text/plain'

        To use https, use https=True.

            >>> urls = ("/redirect", "redirect")
            >>> app = application(urls, globals())
            >>> class redirect:
            ...     def GET(self): raise web.seeother("/foo")
            ...
            >>> response = await app.request("/redirect")
            >>> response.headers['Location']
            'http://0.0.0.0:8080/foo'
            >>> response = await app.request("/redirect", https=True)
            >>> response.headers['Location']
            'https://0.0.0.0:8080/foo'

        The headers argument specifies HTTP headers as a mapping object
        such as a dict.

            >>> urls = ('/ua', 'uaprinter')
            >>> class uaprinter:
            ...     def GET(self):
            ...         return 'your user-agent is ' + web.ctx.env['HTTP_USER_AGENT']
            ...
            >>> app = application(urls, globals())
            >>> await app.request('/ua', headers = {
            ...      'User-Agent': 'a small jumping bean/1.0 (compatible)'
            ... }).data
            b'your user-agent is a small jumping bean/1.0 (compatible)'

        """
        path, maybe_query = splitquery(localpart)
        query = maybe_query or ""

        server = host.split(":")
        if len(server) == 1:
            server.append(80)
        scope = dict(
            server=server,
            method=method,
            path=path,
            query_string=safebytes(query),
            https=str(https),
            headers=[],
            scheme="http",
            http_version="1.1",
            root_path="",
        )
        if "scope" in kw:
            scope.update(kw["scope"])
        headers = headers or {}

        has_content_length = False
        for k, v in headers.items():
            bytes_key = safebytes(k.lower().replace("-", "_"))
            if bytes_key == b"content_length":
                has_content_length = True
                scope["headers"].append((bytes_key, safebytes(v)))
            elif bytes_key == b"content_type":
                scope["headers"].append((bytes_key, safebytes(v)))
            else:
                scope["headers"].append((b"http_" + bytes_key, safebytes(v)))

        q = ""

        if method not in ["HEAD", "GET"]:
            data = data or ""

            if isinstance(data, dict):
                q = urlencode(data)
            else:
                q = data

            # env["wsgi.input"] = BytesIO(q.encode("utf-8"))
            # if not env.get('CONTENT_TYPE', '').lower().startswith('multipart/') and 'CONTENT_LENGTH' not in env:
            if not has_content_length:
                scope["headers"].append((b"content_length", len(q)))

        logger.getChild("application.request").debug("scope(%s)", scope)
        response = web.storage()
        response_data = []

        async def receive():
            return {"type": "http.request", "body": q.encode("utf8"), "more_body": False}

        async def send_response(message):
            if message["type"] == "http.response.start":
                response.status = f'{message["status"]} OK'
                response.headers = dict(message["headers"])
                response.header_items = message["headers"]
            elif message["type"] == "http.response.body":
                response_data.append(safebytes(message["body"]))

        await self.asgifunc()(scope)(receive, send_response)
        print(response_data)
        response.data = b"".join(response_data)
        return response

    def browser(self):
        return browser.AppBrowser(self)

    async def handle(self):
        fn, args = self._match(self.mapping, web.ctx.path)
        logger.getChild("application.handle").debug("match result: fn(%s), args(%s)", fn, args)
        return await self._delegate(fn, self.fvars, args)

    def handle_with_processors(self):
        async def process(processors):
            try:
                if processors:
                    p, processors = processors[0], processors[1:]
                    response = await p(lambda: process(processors))
                    if isawaitable(response):
                        return await response
                    return response
                else:
                    return await self.handle()
            except web.HTTPError:
                raise
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as exc:
                logger.getChild("application.handle_with_processors").critical("", exc_info=exc)
                raise self.internalerror()

        # processors must be applied in the resvere order. (??)
        return process(self.processors)

    def asgifunc(self, *middleware):
        """Return a ASGI-compatibal function for this application."""

        def asgi(scope):
            self.load(scope)

            return self

        for m in middleware:
            asgi = m(asgi)

        return asgi

    async def __call__(self, receive, send):
        body = b""
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.request":
                body += message["body"]
                more_body = message["more_body"]

        try:
            if web.ctx.method.upper() != web.ctx.method:
                raise web.nomethod()
            result = await self.handle_with_processors()

        except web.HTTPError as e:
            result = e.data

        await send({"type": "http.response.start", "status": web.ctx.status, "headers": web.ctx.headers})
        if is_iter(result):
            for chunck in result:
                await send({"type": "http.response.body", "body": safebytes(chunck), "more_body": True})
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        else:
            await send({"type": "http.response.body", "body": safebytes(result), "more_body": False})

    def run(self, *middleware):
        """
        Starts handling requests. If called in a CGI or FastCGI context, it will follow
        that protocol. If called from the command line, it will start an HTTP
        server on the port named in the first command line argument, or, if there
        is no argument, on port 8080.

        `middleware` is a list of WSGI middleware which is applied to the resulting WSGI
        function.
        """
        return wsgi.runwsgi(self.wsgifunc(*middleware))

    def stop(self):
        """Stops the http server started by run.
        """
        if httpserver.server:
            httpserver.server.stop()
            httpserver.server = None

    def load(self, scope):
        """Initializes ctx using scope."""
        ctx = web.ctx
        ctx.clear()

        ctx.status = 200

        ctx.headers = []
        ctx.output = ""
        # ctx.environ = ctx.env = env
        ctx.scope = scope

        # ctx.host = env.get("HTTP_HOST")
        try:
            host, port = scope["server"]
        except Exception:
            host = "localhost"
            port = 80
        ctx.server = f"{host}:{port}"
        ctx.host = host
        ctx.port = port

        if scope.get("https", "").lower() in ["on", "true", "1"]:
            ctx.protocol = "https"
        else:
            ctx.protocol = scope["scheme"]
        # if env.get("wsgi.url_scheme") in ["http", "https"]:
        #     ctx.protocol = env["wsgi.url_scheme"]
        # elif env.get("HTTPS", "").lower() in ["on", "true", "1"]:
        #     ctx.protocol = "https"
        # else:
        #     ctx.protocol = "http"
        ctx.homedomain = f"{ctx.protocol}://{host}:{port}"
        ctx.homepath = scope["root_path"]
        ctx.home = ctx.homedomain + ctx.homepath
        # @@ home is changed when the request is handled to a sub-application.
        # @@ but the real home is required for doing absolute redirects.
        ctx.realhome = ctx.home
        # ctx.ip = env.get("REMOTE_ADDR")
        # ctx.method = env.get("REQUEST_METHOD")
        # ctx.path = env.get("PATH_INFO")
        try:
            remote_addr, remote_port = scope["client"]
        except Exception:
            remote_addr = ""
            # remote_port = 0
        ctx.ip = remote_addr
        ctx.method = scope["method"]
        ctx.path = unquote(scope["path"])

        # http://trac.lighttpd.net/trac/ticket/406 requires:
        # if env.get("SERVER_SOFTWARE", "").startswith("lighttpd/"):
        #     ctx.path = lstrips(env.get("REQUEST_URI").split("?")[0], ctx.homepath)
        #     # Apache and CherryPy webservers unquote the url but lighttpd doesn't.
        #     # unquote explicitly for lighttpd to make ctx.path uniform across all servers.
        #     ctx.path = unquote(ctx.path)

        # if env.get("QUERY_STRING"):
        #     ctx.query = "?" + env.get("QUERY_STRING", "")
        # else:
        #     ctx.query = ""
        ctx.query = "?" + scope["query_string"].decode("utf8")

        ctx.fullpath = ctx.path + ctx.query

        for k, v in ctx.items():
            # convert all string values to unicode values and replace
            # malformed data with a suitable replacement marker.
            if isinstance(v, bytes):
                ctx[k] = v.decode("utf-8", "replace")

        # status must always be str
        # ctx.status = "200 OK"
        ctx.status = 200

        ctx.app_stack = []

    async def _delegate(self, f, fvars, args=[]):
        async def handle_class(cls):
            meth = web.ctx.method
            if meth == "HEAD" and not hasattr(cls, meth):
                meth = "GET"
            if not hasattr(cls, meth):
                raise web.nomethod(cls)
            tocall = getattr(cls(), meth)
            if iscoroutinefunction(tocall):
                return await tocall(*args)
            return tocall(*args)

        if f is None:
            logger.getChild("application._delegate").debug("fn(%s) not found.", f)
            raise web.notfound()
        elif isinstance(f, application):
            logger.getChild("application._delegate").debug("calling handle_with_processors")
            return await f.handle_with_processors()
        elif iscoroutinefunction(f):
            logger.getChild("application._delegate").debug("awaiting coroutine function.")
            return await f()
        elif iscoroutine(f):
            logger.getChild("application._delegate").debug("awaiting coroutine.")
            return await f
        elif isclass(f):
            logger.getChild("application._delegate").debug("calling class %s.", f)
            return await handle_class(f)
        elif isinstance(f, string_types):
            if f.startswith("redirect "):
                url = f.split(" ", 1)[1]
                if web.ctx.method == "GET":
                    x = web.ctx.scope.get("query_string", "")
                    if x:
                        url += "?" + x
                logger.getChild("application._delegate").debug("%s to %s.", f, url)
                raise web.redirect(url)
            elif "." in f:
                mod, cls = f.rsplit(".", 1)
                mod = __import__(mod, None, None, [""])
                cls = getattr(mod, cls)
            else:
                cls = fvars[f]
            logger.getChild("application._delegate").debug("calling class %s", cls)
            return await handle_class(cls)
        elif callable(f):
            logger.getChild("application._delegate").debug("callable object %s", f)
            return f()
        else:
            logger.getChild("application._delegate").debug("%s not found.", f)
            return web.notfound()

    def _match(self, mapping, value):
        for pat, what in mapping:
            if isinstance(what, application):
                if value.startswith(pat):
                    return (self._delegate_sub_application(pat, what), None)
                else:
                    continue
            elif isinstance(what, string_types):
                what, result = utils.re_subm(r"^%s\Z" % (pat,), what, value)
            else:
                result = utils.re_compile(r"^%s\Z" % (pat,)).match(value)

            if result:  # it's a match
                return what, [x for x in result.groups()]
        return None, None

    def _delegate_sub_application(self, dir, app):
        """Deletes request to sub application `app` rooted at the directory `dir`.
        The home, homepath, path and fullpath values in web.ctx are updated to mimic request
        to the subapp and are restored after it is handled.

        @@Any issues with when used with yield?
        """
        web.ctx._oldctx = web.storage(web.ctx)
        web.ctx.home += dir
        web.ctx.homepath += dir
        web.ctx.path = web.ctx.path[len(dir) :]
        web.ctx.fullpath = web.ctx.fullpath[len(dir) :]
        return app.handle_with_processors()

    def get_parent_app(self):
        if self in web.ctx.app_stack:
            index = web.ctx.app_stack.index(self)
            if index > 0:
                return web.ctx.app_stack[index - 1]

    def notfound(self):
        """Returns HTTPError with '404 not found' message"""
        parent = self.get_parent_app()
        if parent:
            return parent.notfound()
        else:
            return web._NotFound()

    def internalerror(self):
        """Returns HTTPError with '500 internal error' message"""
        parent = self.get_parent_app()
        if parent:
            return parent.internalerror()
        elif web.config.get("debug"):
            return debugerror()
        else:
            return web._InternalError()


class auto_application(application):
    """Application similar to `application` but urls are constructed
    automatically using metaclass.

        >>> app = auto_application()
        >>> class hello(app.page):
        ...     def GET(self): return "hello, world"
        ...
        >>> class foo(app.page):
        ...     path = '/foo/.*'
        ...     def GET(self): return "foo"
        >>> app.request("/hello").data
        b'hello, world'
        >>> app.request('/foo/bar').data
        b'foo'
    """

    def __init__(self):
        application.__init__(self)

        class metapage(type):
            def __init__(klass, name, bases, attrs):
                type.__init__(klass, name, bases, attrs)
                path = attrs.get("path", "/" + name)

                # path can be specified as None to ignore that class
                # typically required to create a abstract base class.
                if path is not None:
                    self.add_mapping(path, klass)

        class page(meta=metapage):
            path = None

        self.page = page


# The application class already has the required functionality of subdir_application
subdir_application = application


class subdomain_application(application):
    """
    Application to delegate requests based on the host.

        >>> urls = ("/hello", "hello")
        >>> app = application(urls, globals())
        >>> class hello:
        ...     def GET(self): return "hello"
        >>>
        >>> mapping = ("hello.example.com", app)
        >>> app2 = subdomain_application(mapping)
        >>> app2.request("/hello", host="hello.example.com").data
        b'hello'
        >>> response = app2.request("/hello", host="something.example.com")
        >>> response.status
        '404 Not Found'
        >>> response.data
        b'not found'
    """

    async def handle(self):
        host = web.ctx.host.split(":")[0]  # strip port
        logger.getChild("subdomain_application.handle").debug("host: %s", host)
        fn, args = self._match(self.mapping, host)
        logger.getChild("subdomain_application.handle").debug("fn: %s, args: %s", fn, args)
        return await self._delegate(fn, self.fvars, args)

    def _match(self, mapping, value):
        for pat, what in mapping:
            if isinstance(what, string_types):
                what, result = utils.re_subm("^" + pat + "$", what, value)
            else:
                result = utils.re_compile("^" + pat + "$").match(value)

            if result:  # it's a match
                logger.getChild("subdomain_application._match").debug("result: %s, what: %s", result, what)
                return what, [x for x in result.groups()]
        return None, None


def loadhook(h):
    """
    Converts a load hook into an application processor.

        >>> app = auto_application()
        >>> def f(): "something done before handling request"
        ...
        >>> app.add_processor(loadhook(f))
    """

    async def processor(handler):
        if iscoroutinefunction(h):
            await h()
        else:
            h()
        if iscoroutinefunction(handler):
            return await handler()
        else:
            return handler()

    return processor


def unloadhook(h):
    """
    Converts an unload hook into an application processor.

        >>> app = auto_application()
        >>> def f(): "something done after handling request"
        ...
        >>> app.add_processor(unloadhook(f))
    """

    async def processor(handler):
        try:
            if iscoroutinefunction(handler):
                result = await handler()
            else:
                result = handler()
            is_gen = is_iter(result)
        except Exception:
            # run the hook even when handler raises some exception
            if iscoroutinefunction(h):
                await h()
            else:
                h()
            raise

        if is_gen:
            return wrap(result)
        else:
            if iscoroutinefunction(h):
                await h()
            else:
                h()
            return result

    def wrap(result):
        def next_hook():
            try:
                return next(result)
            except Exception:
                # call the hook at the and of iterator
                h()
                raise

        result = iter(result)
        while True:
            try:
                yield next_hook()
            except StopIteration:
                return

    return processor


def autodelegate(prefix=""):
    """
    Returns a method that takes one argument and calls the method named prefix+arg,
    calling `notfound()` if there isn't one. Example:

        urls = ('/prefs/(.*)', 'prefs')

        class prefs:
            GET = autodelegate('GET_')
            def GET_password(self): pass
            def GET_privacy(self): pass

    `GET_password` would get called for `/prefs/password` while `GET_privacy` for
    `GET_privacy` gets called for `/prefs/privacy`.

    If a user visits `/prefs/password/change` then `GET_password(self, '/change')`
    is called.
    """

    def internal(self, arg):
        if "/" in arg:
            first, rest = arg.split("/", 1)
            func = prefix + first
            args = ["/" + rest]
        else:
            func = prefix + arg
            args = []

        if hasattr(self, func):
            try:
                return getattr(self, func)(*args)
            except TypeError:
                raise web.notfound()
        else:
            raise web.notfound()

    return internal


class Reloader:
    """Checks to see if any loaded modules have changed on disk and,
    if so, reloads them.
    """

    """File suffix of compiled modules."""
    if sys.platform.startswith("java"):
        SUFFIX = "$py.class"
    else:
        SUFFIX = ".pyc"

    def __init__(self):
        self.mtimes = {}

    def __call__(self):
        for mod in sys.modules.values():
            self.check(mod)

    def check(self, mod):
        # jython registers java packages as modules but they either
        # don't have a __file__ attribute or its value is None
        if not (mod and hasattr(mod, "__file__") and mod.__file__):
            return

        try:
            mtime = os.stat(mod.__file__).st_mtime
        except (OSError, IOError):
            return
        if mod.__file__.endswith(self.__class__.SUFFIX) and os.path.exists(mod.__file__[:-1]):
            mtime = max(os.stat(mod.__file__[:-1]).st_mtime, mtime)

        if mod not in self.mtimes:
            self.mtimes[mod] = mtime
        elif self.mtimes[mod] < mtime:
            try:
                reload(mod)
                self.mtimes[mod] = mtime
            except ImportError:
                pass


if __name__ == "__main__":
    import doctest

    doctest.testmod()
