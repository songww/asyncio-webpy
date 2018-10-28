import time
from urllib.parse import urlencode

import pytest
import asynctest

import web

pytestmark = pytest.mark.asyncio

data = """
import web

urls = ("/", "%(classname)s")
app = web.application(urls, globals(), autoreload=True)

class %(classname)s:
    def GET(self):
        return "%(output)s"

"""


def write(filename, data):
    f = open(filename, "w")
    f.write(data)
    f.close()


class ApplicationTest(asynctest.TestCase):
    async def test_reloader(self):
        write("foo.py", data % dict(classname="a", output="a"))
        import foo

        app = foo.app

        self.assertEqual((await app.request("/")).data, b"a")

        # test class change
        time.sleep(1)
        write("foo.py", data % dict(classname="a", output="b"))
        self.assertEqual((await app.request("/")).data, b"b")

        # test urls change
        time.sleep(1)
        write("foo.py", data % dict(classname="c", output="c"))
        self.assertEqual((await app.request("/")).data, b"c")

    async def testUppercaseMethods(self):
        urls = ("/", "hello")
        app = web.application(urls, locals())

        class hello:
            def GET(self):
                return "hello"

            def internal(self):
                return "secret"

        response = await app.request("/", method="internal")
        self.assertEqual(response.status, "405 Method Not Allowed")

    async def testRedirect(self):
        urls = ("/a", "redirect /hello/", "/b/(.*)", r"redirect /hello/\1", "/hello/(.*)", "hello")
        app = web.application(urls, locals())

        class hello:
            def GET(self, name):
                name = name or "world"
                return "hello " + name

        response = await app.request("/a")
        self.assertEqual(response.status, "301 Moved Permanently")
        self.assertEqual(response.headers["Location"], "http://0.0.0.0:8080/hello/")

        response = await app.request("/a?x=2")
        self.assertEqual(response.status, "301 Moved Permanently")
        self.assertEqual(response.headers["Location"], "http://0.0.0.0:8080/hello/?x=2")

        response = await app.request("/b/foo?x=2")
        self.assertEqual(response.status, "301 Moved Permanently")
        self.assertEqual(response.headers["Location"], "http://0.0.0.0:8080/hello/foo?x=2")

    async def test_routing(self):
        urls = ("/foo", "foo")

        class foo:
            def GET(self):
                return "foo"

        app = web.application(urls, {"foo": foo})

        self.assertEqual((await app.request("/foo\n")).data, b"not found")
        self.assertEqual((await app.request("/foo")).data, b"foo")

    async def test_subdirs(self):
        urls = ("/(.*)", "blog")

        class blog:
            def GET(self, path):
                return "blog " + path

        app_blog = web.application(urls, locals())

        urls = ("/blog", app_blog, "/(.*)", "index")

        class index:
            def GET(self, path):
                return "hello " + path

        app = web.application(urls, locals())

        self.assertEqual((await app.request("/blog/foo")).data, b"blog foo")
        self.assertEqual((await app.request("/foo")).data, b"hello foo")

        async def processor(handler):
            return web.ctx.path + ":" + await handler()

        app.add_processor(processor)
        self.assertEqual((await app.request("/blog/foo")).data, b"/blog/foo:blog foo")

    async def test_subdomains(self):
        def create_app(name):
            urls = ("/", "index")

            class index:
                def GET(self):
                    return name

            return web.application(urls, locals())

        urls = ("a.example.com", create_app("a"), "b.example.com", create_app("b"), ".*.example.com", create_app("*"))
        app = web.subdomain_application(urls, locals())

        async def test(host, expected_result):
            result = await app.request("/", host=host)
            self.assertEqual(result.data, expected_result)

        await test("a.example.com", b"a")
        await test("b.example.com", b"b")
        await test("c.example.com", b"*")
        await test("d.example.com", b"*")

    async def test_redirect(self):
        urls = ("/(.*)", "blog")

        class blog:
            def GET(self, path):
                if path == "foo":
                    raise web.seeother("/login", absolute=True)
                else:
                    raise web.seeother("/bar")

        app_blog = web.application(urls, locals())

        urls = ("/blog", app_blog, "/(.*)", "index")

        class index:
            def GET(self, path):
                return "hello " + path

        app = web.application(urls, locals())

        response = await app.request("/blog/foo")
        self.assertEqual(response.headers["Location"], "http://0.0.0.0:8080/login")

        response = await app.request("/blog/foo", scope={"root_path": "/x"})
        self.assertEqual(response.headers["Location"], "http://0.0.0.0:8080/x/login")

        response = await app.request("/blog/foo2")
        self.assertEqual(response.headers["Location"], "http://0.0.0.0:8080/blog/bar")

        response = await app.request("/blog/foo2", scope={"root_path": "/x"})
        self.assertEqual(response.headers["Location"], "http://0.0.0.0:8080/x/blog/bar")

    async def test_processors(self):
        urls = ("/(.*)", "blog")

        class blog:
            def GET(self, path):
                return "blog " + path

        state = web.storage(x=0, y=0)

        def f():
            state.x += 1

        app_blog = web.application(urls, locals())
        app_blog.add_processor(web.loadhook(f))

        urls = ("/blog", app_blog, "/(.*)", "index")

        class index:
            def GET(self, path):
                return "hello " + path

        app = web.application(urls, locals())

        def g():
            state.y += 1

        app.add_processor(web.loadhook(g))

        await app.request("/blog/foo")
        assert state.x == 1 and state.y == 1, repr(state)
        await app.request("/foo")
        assert state.x == 1 and state.y == 2, repr(state)

    async def testUnicodeInput(self):
        urls = ("(/.*)", "foo")

        class foo:
            def GET(self, path):
                i = web.query(name="")
                return repr(i.name)

            def POST(self, path):
                if path == "/multipart":
                    i = web.input(file={})
                    return list(i.file.keys())
                else:
                    i = web.input()
                    return repr(dict(i)).replace("u", "")

        app = web.application(urls, locals())

        async def f(name):
            path = "/?" + urlencode({"name": name.encode("utf-8")})
            self.assertEqual((await app.request(path)).data.decode("utf-8"), repr(name))

        await f("\u1234")
        await f("foo")

        response = await app.request("/", method="POST", data=dict(name="foo"))

        self.assertEqual(response.data, b"{'name': 'foo'}")

        data = "\r\n".join(
            [
                "--boundary",
                'Content-Disposition: form-data; name="x"',
                "",
                "foo",
                "--boundary",
                'Content-Disposition: form-data; name="file"; filename="a.txt"',
                "Content-Type: text/plain",
                "",
                "a",
                "--boundary--",
                "",
            ]
        )
        headers = {"Content-Type": "multipart/form-data; boundary=boundary"}
        response = await app.request("/multipart", method="POST", data=data, headers=headers)

        self.assertEqual(response.data, b"['a.txt']")

    async def testCustomNotFound(self):
        urls_a = ("/", "a")
        urls_b = ("/", "b")

        app_a = web.application(urls_a, locals())
        app_b = web.application(urls_b, locals())

        app_a.notfound = lambda: web.HTTPError("404 Not Found", {}, "not found 1")

        urls = ("/a", app_a, "/b", app_b)
        app = web.application(urls, locals())

        async def assert_notfound(path, message):
            response = await app.request(path)
            self.assertEqual(response.status.split()[0], "404")
            self.assertEqual(response.data, message)

        await assert_notfound("/b/foo", b"not found")
        await assert_notfound("/a/foo", b"not found 1")

        app.notfound = lambda: web.HTTPError("404 Not Found", {}, "not found 2")
        await assert_notfound("/a/foo", b"not found 1")
        await assert_notfound("/b/foo", b"not found 2")

    async def testIter(self):
        class do_iter:
            def GET(self):
                yield "hello, "
                yield web.input(name="world").name

            POST = GET

        urls = ("/iter", "do_iter")
        app = web.application(urls, locals())

        self.assertEqual((await app.request("/iter")).data, b"hello, world")
        self.assertEqual((await app.request("/iter?name=web")).data, b"hello, web")

        self.assertEqual((await app.request("/iter", method="POST")).data, b"hello, world")
        self.assertEqual((await app.request("/iter", method="POST", data="name=web")).data, b"hello, web")

    async def testUnload(self):
        x = web.storage(a=0)

        urls = ("/foo", "foo", "/bar", "bar")

        class foo:
            def GET(self):
                return "foo"

        class bar:
            def GET(self):
                raise web.notfound()

        app = web.application(urls, locals())

        def unload():
            x.a += 1

        app.add_processor(web.unloadhook(unload))

        await app.request("/foo")
        self.assertEqual(x.a, 1)

        await app.request("/bar")
        self.assertEqual(x.a, 2)

    async def test_changequery(self):
        urls = ("/", "index")

        class index:
            def GET(self):
                return web.changequery(x=1)

        app = web.application(urls, locals())

        async def f(path):
            return (await app.request(path)).data

        self.assertEqual(await f("/?x=2"), b"/?x=1")

        p = await f("/?y=1&y=2&x=2")
        self.assertTrue(p == b"/?y=1&y=2&x=1" or p == b"/?x=1&y=1&y=2")

    async def test_setcookie(self):
        urls = ("/", "index")

        class index:
            def GET(self):
                web.setcookie("foo", "bar")
                return "hello"

        app = web.application(urls, locals())

        async def f(script_name=""):
            response = await app.request("/", scope={"root_path": script_name})
            return response.headers["Set-Cookie"]

        self.assertEqual(await f(""), "foo=bar; Path=/")
        self.assertEqual(await f("/admin"), "foo=bar; Path=/admin/")

    # def test_stopsimpleserver(self):
    #     urls = ("/", "index")

    #     class index:
    #         def GET(self):
    #             pass

    #     # reset command-line arguments
    #     sys.argv = ["code.py"]

    #     app = web.application(urls, locals())
    #     thread = threading.Thread(target=app.run)

    #     thread.start()
    #     time.sleep(1)
    #     self.assertTrue(thread.isAlive())

    #     app.stop()
    #     thread.join(timeout=1)
    #     self.assertFalse(thread.isAlive())
