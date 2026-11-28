"""Security tests for the --gui local server (issue #14).

Nothing is launched: `launch` and `recent_sessions` are replaced with fakes,
the browser is never opened, and requests go to 127.0.0.1 via http.client.
"""
import http.client
import importlib.machinery
import importlib.util
import json
import re
import threading
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent.parent / "cc-session-restore"


def load_module():
    loader = importlib.machinery.SourceFileLoader("ccsr_gui_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


ccsr = load_module()
FAKE = [{"id": "sess-1", "title": "t", "cwd": "/tmp", "mtime": 0, "running": False}]


class GuiSecurityTest(unittest.TestCase):
    def setUp(self):
        self.launched = []
        self.opened = False  # set once any /api/open has succeeded
        url_seen = threading.Event()
        urls = []

        def fake_print(*args, **kw):
            m = re.search(r"http://127\.0\.0\.1:(\d+)/\?t=(\S+)", " ".join(map(str, args)))
            if m:
                urls.append(m)
                url_seen.set()

        def fake_launch(sessions, **kw):
            self.launched.extend(s["id"] for s in sessions)
            return []

        def no_browser(url):
            raise AssertionError("tests must never open a browser")

        patches = [
            mock.patch.object(ccsr, "launch", fake_launch),
            mock.patch.object(ccsr, "recent_sessions", lambda: list(FAKE)),
            mock.patch.object(ccsr, "sessions_payload", lambda n: {"count": n, "sessions": []}),
            mock.patch.object(ccsr, "open_in_browser", no_browser),
            mock.patch.object(ccsr, "print", fake_print, create=True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        self.thread = threading.Thread(
            target=ccsr.run_gui, args=(10, "tmux"), kwargs={"browser": False, "idle_timeout": 60},
            daemon=True)
        self.thread.start()
        self.assertTrue(url_seen.wait(10), "server did not start")
        self.port, url_token = int(urls[0].group(1)), urls[0].group(2)
        self.host = f"127.0.0.1:{self.port}"
        self.origin = f"http://{self.host}"
        self.addCleanup(self.stop_server)

        # First load: swap the one-time URL token for the cookie, and read the page's API token.
        status, headers, body = self.request("GET", f"/?t={url_token}")
        self.assertEqual(status, 200)
        self.cookie = headers["Set-Cookie"].split(";")[0]
        m = re.search(r'<meta name="ccsr-token" content="([^"]+)">', body)
        self.assertIsNotNone(m)
        self.token = m.group(1)
        self.assertNotEqual(self.token, "__CCSR_TOKEN__")

    def stop_server(self):
        # A valid open ends the server loop. If the test already had one succeed, the
        # server is shutting down, and another POST could hit a closing socket
        # (ConnectionResetError), so just wait for it.
        if not self.opened:
            # Nothing opened yet: this open must succeed, which also shows rejected
            # requests didn't use up the one open.
            status, _, _ = self.request("POST", "/api/open", json.dumps({"ids": []}), self.good_headers())
            self.assertEqual(status, 200)
        self.thread.join(10)
        self.assertFalse(self.thread.is_alive())

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            res = conn.getresponse()
            if method == "POST" and path == "/api/open" and res.status == 200:
                self.opened = True
            return res.status, res.headers, res.read().decode("utf-8")
        finally:
            conn.close()

    def good_headers(self, **extra):
        h = {"Cookie": self.cookie, "X-CCSR-Token": self.token, "Content-Type": "application/json"}
        h.update(extra)
        return {k: v for k, v in h.items() if v is not None}

    def open_ids(self, headers):
        return self.request("POST", "/api/open", json.dumps({"ids": ["sess-1"]}), headers)

    def test_cross_origin_post_rejected(self):
        for origin in ("http://127.0.0.1:1", "http://evil.example", "null", f"https://{self.host}"):
            status, _, _ = self.open_ids(self.good_headers(Origin=origin))
            self.assertEqual(status, 403, origin)
        self.assertEqual(self.launched, [])

    def test_cross_origin_get_rejected(self):
        status, _, _ = self.request("GET", "/api/sessions",
                                    headers=self.good_headers(Origin="http://127.0.0.1:1"))
        self.assertEqual(status, 403)

    def test_text_plain_post_rejected(self):
        for ctype in ("text/plain", "text/plain;charset=UTF-8", None):
            status, _, _ = self.open_ids(self.good_headers(**{"Content-Type": ctype}))
            self.assertEqual(status, 415, ctype)
        self.assertEqual(self.launched, [])

    def test_cookie_without_header_rejected(self):
        h = self.good_headers(**{"X-CCSR-Token": None})
        self.assertEqual(self.open_ids(h)[0], 403)
        self.assertEqual(self.request("GET", "/api/sessions", headers=h)[0], 403)
        self.assertEqual(self.launched, [])

    def test_wrong_header_rejected(self):
        for bad in ("wrong", self.token + "x", self.token[:-1]):
            h = self.good_headers(**{"X-CCSR-Token": bad})
            self.assertEqual(self.open_ids(h)[0], 403, bad)
            self.assertEqual(self.request("GET", "/api/sessions", headers=h)[0], 403, bad)
        self.assertEqual(self.launched, [])

    def test_header_without_cookie_rejected(self):
        h = self.good_headers(Cookie=None)
        self.assertEqual(self.open_ids(h)[0], 403)
        self.assertEqual(self.launched, [])

    def test_same_origin_json_post_succeeds(self):
        status, _, body = self.open_ids(self.good_headers(Origin=self.origin))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["opened"], 1)
        self.assertEqual(self.launched, ["sess-1"])

    def test_localhost_origin_succeeds(self):
        h = self.good_headers(Origin=f"http://localhost:{self.port}", Host=f"localhost:{self.port}")
        self.assertEqual(self.open_ids(h)[0], 200)
        self.assertEqual(self.launched, ["sess-1"])

    def test_originless_same_origin_succeeds(self):
        status, _, body = self.request("GET", "/api/sessions", headers=self.good_headers())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["count"], 10)
        status, _, body = self.open_ids(self.good_headers())
        self.assertEqual(status, 200)
        self.assertEqual(self.launched, ["sess-1"])

    def test_replayed_cookie_cannot_get_secret(self):
        # A hostile local server that received the cookie replays it to load the page.
        status, _, body = self.request("GET", "/", headers={"Cookie": self.cookie})
        self.assertEqual(status, 200)  # a reload in the same tab still loads the page...
        self.assertNotIn(self.token, body)  # ...but without the secret
        m = re.search(r'<meta name="ccsr-token" content="([^"]*)">', body)
        self.assertIsNotNone(m)
        stolen = m.group(1)
        self.assertEqual(stolen, "")
        h = {"Cookie": self.cookie, "X-CCSR-Token": stolen, "Content-Type": "application/json"}
        self.assertEqual(self.open_ids(h)[0], 403)
        self.assertEqual(self.request("GET", "/api/sessions", headers=h)[0], 403)
        self.assertEqual(self.launched, [])

    def test_page_js_reads_secret_from_session_storage_on_reload(self):
        self.assertIn('sessionStorage.setItem("ccsr-token", t)', ccsr.PAGE)
        self.assertIn('sessionStorage.getItem("ccsr-token")', ccsr.PAGE)

    def test_frame_headers_on_every_response(self):
        responses = [
            self.request("GET", "/", headers={"Cookie": self.cookie}),
            self.request("GET", "/"),  # 403, no cookie
            self.request("GET", "/api/sessions", headers=self.good_headers()),
            self.request("GET", "/nope", headers=self.good_headers()),
            self.open_ids(self.good_headers(Origin="http://evil.example")),
        ]
        for status, headers, _ in responses:
            self.assertEqual(headers["X-Frame-Options"], "DENY", status)
            self.assertEqual(headers["Content-Security-Policy"], "frame-ancestors 'none'", status)

    def test_non_ascii_secrets_get_403(self):
        cases = [
            ("GET", "/api/sessions", {"Cookie": "ccsr=\u00e9", "X-CCSR-Token": self.token}),
            ("GET", "/api/sessions", {"Cookie": self.cookie, "X-CCSR-Token": "\u00e9"}),
            ("POST", "/api/open", self.good_headers(Cookie="ccsr=\u00e9")),
            ("GET", "/?t=%C3%A9", {}),
            ("GET", "/", {"Cookie": "ccsr=\u00e9"}),
        ]
        for method, path, headers in cases:
            body = json.dumps({"ids": ["sess-1"]}) if method == "POST" else None
            self.assertEqual(self.request(method, path, body, headers)[0], 403, (path, headers))
        self.assertEqual(self.launched, [])

    def test_page_js_detaches_key_handler_on_result_screen(self):
        # The result screen removes the list and filter; the key handler must go with them.
        self.assertIn('document.addEventListener("keydown", onKey)', ccsr.PAGE)
        body = re.search(r"async function openIds\(ids\) \{(.*?)\n\}", ccsr.PAGE, re.S).group(1)
        self.assertLess(body.index('document.removeEventListener("keydown", onKey)'),
                        body.index("app.replaceChildren()"))

    def test_page_js_sends_token_on_every_fetch(self):
        fetches = re.findall(r"fetch\((.*?)\);", ccsr.PAGE, re.S)
        self.assertEqual(len(fetches), 2)
        for call in fetches:
            self.assertIn('"X-CCSR-Token": TOKEN', call)


if __name__ == "__main__":
    unittest.main()
