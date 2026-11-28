"""Exercise the real loopback HTTP server without opening browsers or terminals."""
import concurrent.futures
import contextlib
import http.client
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import queue
import socket
import threading
import unittest
from unittest import mock
from urllib.parse import urlsplit


def load_script():
    loader = importlib.machinery.SourceFileLoader(
        "restore_gui", str(Path(__file__).resolve().parents[1] / "cc-session-restore"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class GuiTests(unittest.TestCase):
    def setUp(self):
        self.app = load_script()
        self.urls = queue.Queue()
        self.errors = queue.Queue()
        self.release = threading.Event()
        self.addCleanup(self.release.set)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(self.app, "open_in_browser",
                                                  side_effect=AssertionError("browser opened")))
        self.stack.enter_context(mock.patch.object(self.app.subprocess, "Popen",
                                                  side_effect=AssertionError("process launched")))
        self.stack.enter_context(mock.patch.object(self.app, "recent_sessions", return_value=[
            {"id": "fake-session", "running": False}]))
        self.stack.enter_context(mock.patch.object(self.app, "sessions_payload", return_value={"sessions": []}))
        self.launch = self.stack.enter_context(mock.patch.object(self.app, "launch", return_value=[]))

    def start_server(self):
        def capture(*args, **kwargs):
            if args and str(args[0]).startswith("cc-session-restore: http"):
                self.urls.put(urlsplit(str(args[0]).split(" ", 1)[1]))

        def serve():
            try:
                self.app.run_gui(15, "fake", browser=False, idle_timeout=3)
            except BaseException as error:
                self.errors.put(error)

        self.stack.enter_context(mock.patch.object(self.app, "print", side_effect=capture, create=True))
        self.server = threading.Thread(target=serve, daemon=True)
        self.server.start()
        self.addCleanup(self.stop_server)
        self.url = self.urls.get(timeout=5)

    def stop_server(self):
        self.release.set()
        self.server.join(timeout=6)
        self.assertFalse(self.server.is_alive(), "GUI server failed to stop")
        if not self.errors.empty():
            raise self.errors.get()

    def request(self, path, method="GET", cookie=None, host=None, body=None):
        headers = {}
        if cookie:
            headers["Cookie"] = cookie
        if host:
            headers["Host"] = host
        conn = http.client.HTTPConnection("127.0.0.1", self.url.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def authenticate(self):
        status, headers, _ = self.request("/?" + self.url.query)
        self.assertEqual(status, 200)
        return headers["Set-Cookie"].split(";", 1)[0]

    def test_token_is_single_use_cookie_required_and_host_checked(self):
        self.start_server()
        cookie = self.authenticate()
        self.assertEqual(self.request("/?" + self.url.query)[0], 403)
        self.assertEqual(self.request("/api/sessions")[0], 403)
        self.assertEqual(self.request("/api/sessions", cookie="ccsr=wrong")[0], 403)
        self.assertEqual(self.request("/api/sessions", cookie=cookie, host="attacker.invalid")[0], 403)
        self.assertEqual(self.request("/api/open", "POST", cookie, "attacker.invalid", "{}")[0], 403)
        self.assertEqual(self.request("/api/sessions", cookie=cookie)[0], 200)
        self.assertEqual(self.request("/", cookie=cookie)[0], 200)
        self.launch.assert_not_called()

    def test_three_concurrent_opens_launch_only_once(self):
        entered = threading.Event()

        def launch(*args, **kwargs):
            entered.set()
            if not self.release.wait(5):
                raise RuntimeError("test did not release launch")
            return []

        self.launch.side_effect = launch
        self.start_server()
        cookie = self.authenticate()
        barrier = threading.Barrier(3)

        def post():
            barrier.wait(timeout=5)
            return self.request("/api/open", "POST", cookie,
                                body=json.dumps({"ids": ["fake-session", "fake-session"]}))

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(post) for _ in range(3)]
            self.assertTrue(entered.wait(5))
            # Keep the winning launch blocked until both rejected responses arrive.
            completed = []
            try:
                for future in concurrent.futures.as_completed(futures, timeout=5):
                    completed.append(future.result())
                    if len(completed) == 2:
                        break
                self.assertEqual([r[0] for r in completed], [409, 409])
            finally:
                self.release.set()
            results = [f.result(timeout=5) for f in futures]
        self.assertEqual(sorted(r[0] for r in results), [200, 409, 409])
        self.launch.assert_called_once()
        self.assertEqual(self.launch.call_args[0][0], [{"id": "fake-session", "running": False}])
        success = next(r for r in results if r[0] == 200)
        self.assertEqual(json.loads(success[2]), {"opened": 1, "errors": []})

    def test_busy_port_has_clean_cli_error(self):
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen(1)
            port = occupied.getsockname()[1]
            with self.assertRaises(SystemExit) as error:
                self.app.main(["--gui", "--no-browser", "--port", str(port)])
        self.assertIn("can't listen on port {}".format(port), str(error.exception))
        self.assertIn("--port", str(error.exception))


if __name__ == "__main__":
    unittest.main()
